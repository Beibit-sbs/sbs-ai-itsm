from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

from redis import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.job_lifecycle_event import JobLifecycleEvent
from app.models.job_queue_outbox import JobQueueOutbox
from app.services.jobs import create_job_lifecycle_event, execute_job, get_job
from app.services.jobs import tasks as _job_tasks  # noqa: F401 - registers built-in tasks

logger = logging.getLogger("app.jobs.worker")


def _event_stream_payload(event: JobLifecycleEvent) -> dict[str, str]:
    return {
        "event_id": event.id,
        "job_id": event.job_id,
        "event_type": event.event_type,
        "task_name": event.task_name,
        "tenant_id": event.tenant_id or "",
        "actor_user_id": event.actor_user_id or "",
        "correlation_id": event.correlation_id or "",
        "previous_status": event.previous_status or "",
        "current_status": event.current_status,
        "payload_json": event.payload_json or "{}",
        "created_at": event.created_at.isoformat(),
        "source": "job_lifecycle_events",
    }


def _relay_job_events_batch(redis_client: Redis, *, batch_size: int = 100) -> int:
    worker_id = f"event-relay-{uuid.uuid4()}"
    now = datetime.now(UTC)
    lock_ttl_seconds = 30
    db = SessionLocal()
    relayed = 0
    try:
        stmt = (
            select(JobLifecycleEvent)
            .where(JobLifecycleEvent.relay_published_at.is_(None))
            .where(
                (JobLifecycleEvent.relay_lock_expires_at.is_(None))
                | (JobLifecycleEvent.relay_lock_expires_at < now)
            )
            .order_by(JobLifecycleEvent.created_at.asc())
            .limit(batch_size)
        )
        rows = list(db.scalars(stmt).all())
        for row in rows:
            row.relay_lock_owner = worker_id
            row.relay_lock_expires_at = datetime.fromtimestamp(time.time() + lock_ttl_seconds, tz=UTC)
            row.relay_publish_attempted_at = now
        db.flush()

        for row in rows:
            relay_key = f"jobs:event-relay:{row.id}"
            is_first_publish = False
            try:
                is_first_publish = redis_client.set(relay_key, row.id, nx=True, ex=7 * 24 * 3600)
                if is_first_publish:
                    redis_client.xadd(row.relay_stream_name, _event_stream_payload(row))
                row.relay_published_at = datetime.now(UTC)
                row.relay_last_error = None if is_first_publish else "relay_dedup_skip_already_published"
                row.relay_lock_owner = None
                row.relay_lock_expires_at = None
                relayed += 1
            except Exception as exc:  # pragma: no cover - external redis/network path
                if is_first_publish:
                    try:
                        redis_client.delete(relay_key)
                    except Exception:  # pragma: no cover - best-effort cleanup path
                        logger.exception("job_event_bus_relay_dedup_cleanup_failed", extra={"event_id": row.id})
                row.relay_failed_attempts += 1
                row.relay_last_error = f"{exc.__class__.__name__}: {exc}"[:2000]
                row.relay_lock_owner = None
                row.relay_lock_expires_at = None
        db.commit()
        return relayed
    except Exception:
        db.rollback()
        logger.exception("job_event_bus_relay_failed")
        return relayed
    finally:
        db.close()


def _retry_delay_seconds(attempts: int, *, base_seconds: float, max_seconds: float) -> float:
    """Exponential backoff based on already-used attempts."""

    exponent = max(0, attempts - 1)
    delay = base_seconds * (2**exponent)
    return min(max_seconds, delay)


def _scheduled_queue_name(queue_name: str) -> str:
    return f"{queue_name}:scheduled"


def _schedule_retry(redis_client: Redis, queue_name: str, job_id: str, delay_seconds: float) -> None:
    scheduled_key = _scheduled_queue_name(queue_name)
    due_at = time.time() + max(0.0, delay_seconds)
    redis_client.zadd(scheduled_key, {job_id: due_at})


def _drain_scheduled_jobs(redis_client: Redis, queue_name: str, *, batch_size: int = 100) -> int:
    scheduled_key = _scheduled_queue_name(queue_name)
    now = time.time()
    moved = 0
    while True:
        due_job_ids = redis_client.zrangebyscore(scheduled_key, "-inf", now, start=0, num=batch_size)
        if not due_job_ids:
            break
        for due_job_id in due_job_ids:
            removed = redis_client.zrem(scheduled_key, due_job_id)
            if removed:
                redis_client.rpush(queue_name, due_job_id)
                moved += 1
        if len(due_job_ids) < batch_size:
            break
    return moved


def _publish_outbox_batch(redis_client: Redis, *, batch_size: int = 100) -> int:
    worker_id = f"worker-{uuid.uuid4()}"
    now = datetime.now(UTC)
    lock_ttl_seconds = 30
    db = SessionLocal()
    published = 0
    try:
        stmt = (
            select(JobQueueOutbox)
            .where(JobQueueOutbox.published_at.is_(None))
            .where((JobQueueOutbox.lock_expires_at.is_(None)) | (JobQueueOutbox.lock_expires_at < now))
            .order_by(JobQueueOutbox.created_at.asc())
            .limit(batch_size)
        )
        rows = list(db.scalars(stmt).all())
        for row in rows:
            row.lock_owner = worker_id
            row.lock_expires_at = datetime.fromtimestamp(time.time() + lock_ttl_seconds, tz=UTC)
            row.publish_attempted_at = now
        db.flush()

        for row in rows:
            try:
                publish_key = f"jobs:publish-dedup:{row.dedup_key}"
                is_first_publish = redis_client.set(publish_key, row.id, nx=True, ex=7 * 24 * 3600)
                if is_first_publish:
                    redis_client.lpush(row.queue_name, row.job_id)
                row.published_at = datetime.now(UTC)
                row.last_error = None if is_first_publish else "dedup_skip_already_published"
                row.lock_owner = None
                row.lock_expires_at = None
                published += 1
            except Exception as exc:  # pragma: no cover - external redis/network path
                row.failed_attempts += 1
                row.last_error = f"{exc.__class__.__name__}: {exc}"[:2000]
                row.lock_owner = None
                row.lock_expires_at = None
        db.commit()
        return published
    except Exception:
        db.rollback()
        logger.exception("job_outbox_publish_failed")
        return published
    finally:
        db.close()


def _requeue_missing_job(redis_client: Redis, queue_name: str, job_id: str) -> None:
    attempts_key = f"jobs:missing-retry:{job_id}"
    attempts = int(redis_client.incr(attempts_key))
    redis_client.expire(attempts_key, 60)
    if attempts <= 5:
        redis_client.rpush(queue_name, job_id)
        logger.warning("job_not_found_requeued", extra={"job_id": job_id, "attempt": attempts})
        return
    logger.error("job_not_found_dropped", extra={"job_id": job_id, "attempt": attempts})


def _run_single_job(job_id: str, *, redis_client: Redis, queue_name: str) -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        job = get_job(db, job_id)
        if job is None:
            _requeue_missing_job(redis_client, queue_name, job_id)
            return
        if job.status != "queued":
            logger.info("job_skip_non_queued", extra={"job_id": job_id, "status": job.status})
            return
        asyncio.run(execute_job(db, job))
        if job.status == "failed" and job.attempts < job.max_attempts:
            delay = _retry_delay_seconds(
                job.attempts,
                base_seconds=settings.jobs_retry_base_seconds,
                max_seconds=settings.jobs_retry_max_seconds,
            )
            previous_status = job.status
            job.status = "queued"
            job.started_at = None
            job.finished_at = None
            job.duration_ms = None
            create_job_lifecycle_event(
                db,
                job=job,
                event_type="retry_scheduled",
                previous_status=previous_status,
                current_status=job.status,
                payload={"attempt": job.attempts, "delay_seconds": delay},
            )
            db.commit()
            _schedule_retry(redis_client, queue_name, job.id, delay)
            logger.warning(
                "job_requeued_after_failure",
                extra={
                    "job_id": job.id,
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                    "delay_seconds": delay,
                },
            )
            return
        if job.status == "failed" and job.attempts >= job.max_attempts:
            previous_status = job.status
            job.status = "dead_letter"
            create_job_lifecycle_event(
                db,
                job=job,
                event_type="dead_letter",
                previous_status=previous_status,
                current_status=job.status,
                payload={"attempt": job.attempts, "max_attempts": job.max_attempts},
            )
            db.commit()
            redis_client.lpush(settings.jobs_dead_letter_queue_name, job.id)
            logger.error(
                "job_moved_to_dead_letter",
                extra={"job_id": job.id, "attempts": job.attempts, "max_attempts": job.max_attempts},
            )
            return
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("job_worker_processing_failed", extra={"job_id": job_id})
    finally:
        db.close()


def run_worker_forever() -> None:
    settings = get_settings()
    redis_client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=30,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
    logger.info(
        "jobs_worker_started",
        extra={
            "queue": settings.jobs_queue_name,
            "dead_letter_queue": settings.jobs_dead_letter_queue_name,
            "redis_url": settings.redis_url,
            "executor": settings.jobs_executor_mode,
        },
    )
    try:
        while True:
            _relay_job_events_batch(redis_client)
            _publish_outbox_batch(redis_client)
            _drain_scheduled_jobs(redis_client, settings.jobs_queue_name)
            try:
                item = redis_client.brpop(settings.jobs_queue_name, timeout=5)
            except RedisTimeoutError:
                # BRPOP can exceed socket read timeout in some environments;
                # keep the worker alive and continue polling.
                continue
            if item is None:
                continue
            _, job_id = item
            _run_single_job(str(job_id), redis_client=redis_client, queue_name=settings.jobs_queue_name)
    except KeyboardInterrupt:
        logger.info("jobs_worker_stopped")
    finally:
        redis_client.close()


if __name__ == "__main__":
    run_worker_forever()
