from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Callable

from redis import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.job_event_consumer_delivery import JobEventConsumerDelivery
from app.models.job_event_consumer_offset import JobEventConsumerOffset
from app.models.job_lifecycle_event import JobLifecycleEvent
from app.models.job_queue_outbox import JobQueueOutbox
from app.models.user import User
from app.services.automation import trigger_automation_event
from app.services.audit import log_audit
from app.services.notifications import create_domain_event_notification
from app.services.jobs import (
    create_job_lifecycle_event,
    execute_job,
    get_job,
    job_event_consumer_autoremediate,
    job_event_consumer_autoremediation_safety_state,
    is_autoremediation_suppressed_now,
)
from app.services.jobs import tasks as _job_tasks  # noqa: F401 - registers built-in tasks

logger = logging.getLogger("app.jobs.worker")


def _uuid() -> str:
    return str(uuid.uuid4())


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


def _get_or_create_consumer_offset(db, *, consumer_name: str, stream_name: str) -> JobEventConsumerOffset:
    row = db.scalar(
        select(JobEventConsumerOffset).where(
            JobEventConsumerOffset.consumer_name == consumer_name,
            JobEventConsumerOffset.stream_name == stream_name,
        )
    )
    if row is not None:
        return row
    row = JobEventConsumerOffset(
        id=_uuid(),
        consumer_name=consumer_name,
        stream_name=stream_name,
        last_stream_id="0-0",
        updated_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


def _should_create_notification(event_type: str) -> bool:
    return event_type in {"failed", "dead_letter"}


def _create_notification_for_event(db, event: JobLifecycleEvent) -> None:
    if not _should_create_notification(event.event_type):
        return
    root_user = db.scalar(select(User).where(User.is_root.is_(True)).order_by(User.created_at.asc()).limit(1))
    if root_user is None:
        return

    severity = "critical" if event.event_type == "dead_letter" else "warning"
    title = "Job moved to dead letter" if event.event_type == "dead_letter" else "Job execution failed"
    message = (
        f"Task {event.task_name} for job {event.job_id} ended with event {event.event_type}."
        " Review job details and retry/replay if needed."
    )
    create_domain_event_notification(
        db,
        tenant_id=event.tenant_id,
        event_type=f"jobs.{event.event_type}",
        title=title,
        message=message,
        recipient_name=root_user.full_name,
        recipient_email=root_user.email,
        recipient_user_id=root_user.id,
        channel="in_app",
        severity=severity,
        entity_type="job",
        entity_id=event.job_id,
        action_url=f"/admin/system?job_id={event.job_id}",
        metadata={
            "event_id": event.id,
            "correlation_id": event.correlation_id,
            "event_type": event.event_type,
            "task_name": event.task_name,
        },
    )


def _process_notifications_consumer(db, event: JobLifecycleEvent) -> None:
    _create_notification_for_event(db, event)


def _parse_event_payload(event: JobLifecycleEvent) -> dict[str, str | dict | list | int | float | bool | None]:
    payload: dict[str, str | dict | list | int | float | bool | None] = {}
    if event.payload_json:
        try:
            raw = json.loads(event.payload_json)
            if isinstance(raw, dict):
                payload = raw
        except (TypeError, ValueError):
            payload = {}
    return payload


def _process_automation_consumer(db, event: JobLifecycleEvent) -> None:
    payload = _parse_event_payload(event)
    context = {
        "event": {
            "id": event.id,
            "event_type": event.event_type,
            "previous_status": event.previous_status,
            "current_status": event.current_status,
            "created_at": event.created_at.isoformat(),
            "payload": payload,
        },
        "job": {
            "id": event.job_id,
            "task_name": event.task_name,
            "tenant_id": event.tenant_id,
            "actor_user_id": event.actor_user_id,
            "correlation_id": event.correlation_id,
        },
        "entity_type": "job",
        "entity_id": event.job_id,
    }
    trigger_automation_event(
        db,
        tenant_id=event.tenant_id,
        trigger_type=f"job_lifecycle.{event.event_type}",
        context=context,
        actor_email=None,
    )


def _consume_event_stream_batch(
    redis_client: Redis,
    *,
    consumer_name: str | None = None,
    handler: Callable | None = None,
    batch_size: int = 100,
) -> int:
    settings = get_settings()
    db = SessionLocal()
    processed = 0
    now = datetime.now(UTC)
    effective_consumer_name = consumer_name or settings.jobs_event_consumer_name
    effective_handler = handler or _process_notifications_consumer
    try:
        offset = _get_or_create_consumer_offset(
            db,
            consumer_name=effective_consumer_name,
            stream_name=settings.jobs_event_stream_name,
        )
        rows = redis_client.xread({settings.jobs_event_stream_name: offset.last_stream_id}, count=batch_size)
        if not rows:
            db.commit()
            return 0

        _, stream_rows = rows[0]
        for stream_entry_id, payload in stream_rows:
            event_id = str(payload.get("event_id") or "")
            if not event_id:
                offset.last_stream_id = stream_entry_id
                offset.updated_at = now
                continue

            event = db.get(JobLifecycleEvent, event_id)
            if event is None:
                offset.last_stream_id = stream_entry_id
                offset.updated_at = now
                continue

            delivery = db.scalar(
                select(JobEventConsumerDelivery).where(
                    JobEventConsumerDelivery.consumer_name == effective_consumer_name,
                    JobEventConsumerDelivery.event_id == event_id,
                )
            )
            if delivery is None:
                delivery = JobEventConsumerDelivery(
                    id=_uuid(),
                    consumer_name=effective_consumer_name,
                    event_id=event_id,
                    stream_name=settings.jobs_event_stream_name,
                    stream_entry_id=stream_entry_id,
                    status="pending",
                    attempts=0,
                    last_error=None,
                    delivered_at=None,
                )
                db.add(delivery)
                db.flush()

            if delivery.status != "delivered":
                try:
                    effective_handler(db, event)
                    delivery.attempts += 1
                    delivery.status = "delivered"
                    delivery.delivered_at = now
                    delivery.last_error = None
                except Exception as exc:
                    delivery.attempts += 1
                    delivery.status = "failed"
                    delivery.last_error = f"{exc.__class__.__name__}: {exc}"[:2000]

            offset.last_stream_id = stream_entry_id
            offset.updated_at = now
            processed += 1

        db.commit()
        return processed
    except Exception:
        db.rollback()
        logger.exception("job_event_consumer_batch_failed")
        return processed
    finally:
        db.close()


def _retry_failed_event_consumers_batch(
    *,
    consumer_name: str | None = None,
    handler: Callable | None = None,
    batch_size: int = 50,
) -> int:
    settings = get_settings()
    db = SessionLocal()
    retried = 0
    now = datetime.now(UTC)
    effective_consumer_name = consumer_name or settings.jobs_event_consumer_name
    effective_handler = handler or _process_notifications_consumer
    try:
        stmt = (
            select(JobEventConsumerDelivery)
            .where(JobEventConsumerDelivery.consumer_name == effective_consumer_name)
            .where(JobEventConsumerDelivery.status == "failed")
            .where(JobEventConsumerDelivery.attempts < settings.jobs_event_consumer_max_attempts)
            .order_by(JobEventConsumerDelivery.updated_at.asc())
            .limit(batch_size)
        )
        deliveries = list(db.scalars(stmt).all())
        for delivery in deliveries:
            event = db.get(JobLifecycleEvent, delivery.event_id)
            if event is None:
                delivery.status = "delivered"
                delivery.last_error = "event_not_found_skipped"
                delivery.delivered_at = now
                retried += 1
                continue
            try:
                effective_handler(db, event)
                delivery.attempts += 1
                delivery.status = "delivered"
                delivery.delivered_at = now
                delivery.last_error = None
                retried += 1
            except Exception as exc:
                delivery.attempts += 1
                delivery.status = "failed"
                delivery.last_error = f"{exc.__class__.__name__}: {exc}"[:2000]
        db.commit()
        return retried
    except Exception:
        db.rollback()
        logger.exception("job_event_consumer_retry_failed")
        return retried
    finally:
        db.close()


def _run_auto_remediation_cycle(*, max_per_consumer: int | None = None) -> int:
    settings = get_settings()
    if not settings.jobs_event_autoremediation_enabled:
        return 0

    allowed = {
        settings.jobs_event_consumer_name,
        settings.jobs_event_automation_consumer_name,
    }
    configured_consumers = [item for item in settings.jobs_event_autoremediation_consumers if item in allowed]
    if not configured_consumers:
        return 0

    profile_map = (
        settings.jobs_event_autoremediation_policy_profiles
        if isinstance(settings.jobs_event_autoremediation_policy_profiles, dict)
        else {}
    )
    suppression_windows_utc = [str(item) for item in settings.jobs_event_autoremediation_suppression_windows_utc if item]
    if is_autoremediation_suppressed_now(now=datetime.now(UTC), windows_utc=suppression_windows_utc):
        return 0

    global_allowed_event_types = [item for item in settings.jobs_event_autoremediation_allowed_event_types if item]
    error_denylist = [item for item in settings.jobs_event_autoremediation_error_denylist if item]
    requeued_total = 0
    for consumer_name in configured_consumers:
        db = SessionLocal()
        try:
            profile_raw = profile_map.get(consumer_name, {})
            profile = profile_raw if isinstance(profile_raw, dict) else {}
            if not bool(profile.get("enabled", True)):
                db.rollback()
                continue

            policy_min_failed_age_seconds = int(
                profile.get("min_failed_age_seconds", settings.jobs_event_autoremediation_min_failed_age_seconds)
            )
            policy_max_per_hour = int(profile.get("max_per_hour", settings.jobs_event_autoremediation_max_per_hour))
            policy_cooldown_seconds = int(profile.get("cooldown_seconds", settings.jobs_event_autoremediation_cooldown_seconds))
            policy_max_requeued_per_cycle = int(
                profile.get("max_requeued_per_cycle", settings.jobs_event_autoremediation_max_requeued_per_cycle)
            )
            policy_canary_mode = bool(profile.get("canary_mode", settings.jobs_event_autoremediation_canary_mode))
            policy_canary_limit = int(
                profile.get("canary_limit_per_cycle", settings.jobs_event_autoremediation_canary_limit_per_cycle)
            )
            profile_event_types = profile.get("allowed_event_types", global_allowed_event_types)
            allowed_event_types = (
                [str(item) for item in profile_event_types if str(item).strip()]
                if isinstance(profile_event_types, list)
                else global_allowed_event_types
            )

            safety = job_event_consumer_autoremediation_safety_state(
                db,
                consumer_name=consumer_name,
                cooldown_seconds=max(0, policy_cooldown_seconds),
                max_per_hour=max(0, policy_max_per_hour),
            )
            if bool(safety.get("cooldown_active")) or bool(safety.get("rate_limit_exceeded")):
                db.rollback()
                continue

            effective_limit = max_per_consumer or policy_max_requeued_per_cycle
            if policy_canary_mode:
                effective_limit = min(max(1, effective_limit), max(1, policy_canary_limit))
            result = job_event_consumer_autoremediate(
                db,
                consumer_name=consumer_name,
                stream_name=settings.jobs_event_stream_name,
                max_attempts=settings.jobs_event_consumer_max_attempts,
                min_failed_age_seconds=max(0, policy_min_failed_age_seconds),
                allowed_event_types=allowed_event_types,
                error_denylist=error_denylist,
                limit=effective_limit,
            )
            if int(result.get("requeued", 0) or 0) > 0:
                log_audit(
                    db,
                    action="jobs.event_consumer_recovery.auto",
                    entity_type="job_event_consumer_delivery",
                    entity_id=consumer_name,
                    actor_email="jobs-worker@sbs.local",
                    metadata={
                        "consumer_name": consumer_name,
                        "selected": int(result.get("selected", 0) or 0),
                        "requeued": int(result.get("requeued", 0) or 0),
                        "event_types": allowed_event_types,
                        "canary_mode": policy_canary_mode,
                        "effective_limit": effective_limit,
                        "auto_remediation": True,
                    },
                )
            db.commit()
            requeued_total += int(result.get("requeued", 0) or 0)
        except Exception:
            db.rollback()
            logger.exception("job_event_consumer_autoremediation_failed", extra={"consumer_name": consumer_name})
        finally:
            db.close()
    return requeued_total


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
            _consume_event_stream_batch(
                redis_client,
                consumer_name=settings.jobs_event_consumer_name,
                handler=_process_notifications_consumer,
            )
            _retry_failed_event_consumers_batch(
                consumer_name=settings.jobs_event_consumer_name,
                handler=_process_notifications_consumer,
            )
            _consume_event_stream_batch(
                redis_client,
                consumer_name=settings.jobs_event_automation_consumer_name,
                handler=_process_automation_consumer,
            )
            _retry_failed_event_consumers_batch(
                consumer_name=settings.jobs_event_automation_consumer_name,
                handler=_process_automation_consumer,
            )
            _run_auto_remediation_cycle()
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
