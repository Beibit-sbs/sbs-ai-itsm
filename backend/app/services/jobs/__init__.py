"""Job orchestration foundation.

This module provides the observable primitive used by asynchronous work in the
system. Jobs are always persisted to `job_runs` and can be executed in two
modes:
- inline execution in the request process;
- queued execution through Redis for an out-of-process worker.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from redis import Redis
from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import get_correlation_id
from app.models.job_queue_outbox import JobQueueOutbox
from app.models.job_lifecycle_event import JobLifecycleEvent
from app.models.job_event_consumer_delivery import JobEventConsumerDelivery
from app.models.job_event_consumer_offset import JobEventConsumerOffset
from app.models.job_run import JobRun

logger = logging.getLogger("app.jobs")


JobContext = Mapping[str, Any]
TaskCallable = Callable[[JobContext, dict[str, Any]], Awaitable[dict[str, Any] | None]]


_TASK_REGISTRY: dict[str, TaskCallable] = {}


class UnknownTaskError(ValueError):
    """Raised when a task name is not registered."""


class JobExecutionError(RuntimeError):
    """Raised when a task raises during execution."""


class JobQueueUnavailableError(RuntimeError):
    """Raised when queue-backed enqueue fails."""


def register_task(name: str, func: TaskCallable) -> None:
    """Register a task under a stable, dotted name."""

    _TASK_REGISTRY[name] = func


def registered_task(name: str) -> TaskCallable | None:
    return _TASK_REGISTRY.get(name)


def registered_task_names() -> list[str]:
    return sorted(_TASK_REGISTRY.keys())


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _serialize(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return json.dumps({"repr": repr(value)}, ensure_ascii=False)


def _deserialize(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def create_job_lifecycle_event(
    db: Session,
    *,
    job: JobRun,
    event_type: str,
    previous_status: str | None,
    current_status: str,
    payload: dict[str, Any] | None = None,
) -> JobLifecycleEvent:
    settings = get_settings()
    event = JobLifecycleEvent(
        id=_uuid(),
        job_id=job.id,
        event_type=event_type,
        task_name=job.task_name,
        tenant_id=job.tenant_id,
        actor_user_id=job.actor_user_id,
        correlation_id=job.correlation_id,
        previous_status=previous_status,
        current_status=current_status,
        payload_json=_serialize(payload or {}),
        relay_stream_name=settings.jobs_event_stream_name,
        relay_published_at=None,
        relay_publish_attempted_at=None,
        relay_failed_attempts=0,
        relay_last_error=None,
        relay_lock_owner=None,
        relay_lock_expires_at=None,
    )
    db.add(event)
    db.flush()
    return event


def list_job_events(db: Session, job_id: str) -> list[JobLifecycleEvent]:
    stmt = select(JobLifecycleEvent).where(JobLifecycleEvent.job_id == job_id).order_by(JobLifecycleEvent.created_at.asc())
    return list(db.scalars(stmt).all())


def job_event_bus_summary(db: Session, stream_name: str | None = None) -> dict[str, int | float | str]:
    now = _now()
    stmt = select(
        func.count(JobLifecycleEvent.id),
        func.sum(case((JobLifecycleEvent.relay_published_at.is_(None), 1), else_=0)),
        func.sum(case((JobLifecycleEvent.relay_published_at.is_not(None), 1), else_=0)),
        func.sum(case((JobLifecycleEvent.relay_failed_attempts > 0, 1), else_=0)),
        func.sum(
            case(
                (
                    (JobLifecycleEvent.relay_published_at.is_(None))
                    & (JobLifecycleEvent.relay_lock_owner.is_not(None))
                    & (JobLifecycleEvent.relay_lock_expires_at.is_not(None))
                    & (JobLifecycleEvent.relay_lock_expires_at >= now),
                    1,
                ),
                else_=0,
            )
        ),
        func.sum(
            case(
                (
                    (JobLifecycleEvent.relay_published_at.is_(None))
                    & (JobLifecycleEvent.relay_lock_owner.is_not(None))
                    & (JobLifecycleEvent.relay_lock_expires_at.is_not(None))
                    & (JobLifecycleEvent.relay_lock_expires_at < now),
                    1,
                ),
                else_=0,
            )
        ),
    )
    if stream_name:
        stmt = stmt.where(JobLifecycleEvent.relay_stream_name == stream_name)
    total, pending, published, failures, locked, stale_locks = db.execute(stmt).one()
    total_value = int(total or 0)
    failure_rate = round((int(failures or 0) / total_value) * 100, 2) if total_value else 0.0
    return {
        "stream_name": stream_name or "*",
        "total": total_value,
        "pending": int(pending or 0),
        "published": int(published or 0),
        "with_failures": int(failures or 0),
        "locked": int(locked or 0),
        "stale_locks": int(stale_locks or 0),
        "failure_rate_pct": failure_rate,
    }


def job_event_consumer_summary(db: Session, *, consumer_name: str, stream_name: str) -> dict[str, int | str]:
    stmt = select(
        func.count(JobEventConsumerDelivery.id),
        func.sum(case((JobEventConsumerDelivery.status == "pending", 1), else_=0)),
        func.sum(case((JobEventConsumerDelivery.status == "delivered", 1), else_=0)),
        func.sum(case((JobEventConsumerDelivery.status == "failed", 1), else_=0)),
    ).where(
        JobEventConsumerDelivery.consumer_name == consumer_name,
        JobEventConsumerDelivery.stream_name == stream_name,
    )
    total, pending, delivered, failed = db.execute(stmt).one()
    return {
        "consumer_name": consumer_name,
        "stream_name": stream_name,
        "total": int(total or 0),
        "pending": int(pending or 0),
        "delivered": int(delivered or 0),
        "failed": int(failed or 0),
    }


def job_event_consumers_diagnostics(
    db: Session,
    *,
    stream_name: str,
    consumer_names: list[str],
    max_attempts: int,
    lag_alert_threshold: int,
    stale_offset_seconds: int,
) -> dict[str, object]:
    now = _now()
    total_events = int(
        db.scalar(select(func.count(JobLifecycleEvent.id)).where(JobLifecycleEvent.relay_stream_name == stream_name)) or 0
    )
    last_event_created_at = db.scalar(
        select(func.max(JobLifecycleEvent.created_at)).where(JobLifecycleEvent.relay_stream_name == stream_name)
    )

    consumers: list[dict[str, object]] = []
    for consumer_name in consumer_names:
        count_stmt = select(
            func.count(JobEventConsumerDelivery.id),
            func.sum(case((JobEventConsumerDelivery.status == "pending", 1), else_=0)),
            func.sum(case((JobEventConsumerDelivery.status == "delivered", 1), else_=0)),
            func.sum(case((JobEventConsumerDelivery.status == "failed", 1), else_=0)),
            func.sum(
                case(
                    (
                        (JobEventConsumerDelivery.status == "failed")
                        & (JobEventConsumerDelivery.attempts < max_attempts),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        (JobEventConsumerDelivery.status == "failed")
                        & (JobEventConsumerDelivery.attempts >= max_attempts),
                        1,
                    ),
                    else_=0,
                )
            ),
        ).where(
            JobEventConsumerDelivery.consumer_name == consumer_name,
            JobEventConsumerDelivery.stream_name == stream_name,
        )
        total_rows, pending, delivered, failed, retryable_failed, exhausted_failed = db.execute(count_stmt).one()
        total_rows = int(total_rows or 0)
        pending = int(pending or 0)
        delivered = int(delivered or 0)
        failed = int(failed or 0)
        retryable_failed = int(retryable_failed or 0)
        exhausted_failed = int(exhausted_failed or 0)

        oldest_undelivered = db.scalar(
            select(func.min(JobEventConsumerDelivery.created_at)).where(
                JobEventConsumerDelivery.consumer_name == consumer_name,
                JobEventConsumerDelivery.stream_name == stream_name,
                JobEventConsumerDelivery.status != "delivered",
            )
        )
        oldest_undelivered_age_seconds = (
            int((now - oldest_undelivered).total_seconds()) if oldest_undelivered is not None else 0
        )

        offset = db.scalar(
            select(JobEventConsumerOffset).where(
                JobEventConsumerOffset.consumer_name == consumer_name,
                JobEventConsumerOffset.stream_name == stream_name,
            )
        )
        offset_updated_at = offset.updated_at if offset is not None else None
        stale_offset = False
        if offset_updated_at is not None and last_event_created_at is not None:
            stale_offset = (
                (now - offset_updated_at).total_seconds() >= stale_offset_seconds
                and offset_updated_at < last_event_created_at
            )

        unseen_events = max(0, total_events - total_rows)
        lag_events = max(0, total_events - delivered)
        failure_rate_pct = round((failed / total_rows) * 100, 2) if total_rows else 0.0

        recommended_actions: list[str] = []
        if exhausted_failed > 0:
            recommended_actions.append("Inspect failed deliveries at max attempts and replay affected events manually")
        if retryable_failed > 0:
            recommended_actions.append("Keep worker running and monitor retry queue until failed deliveries recover")
        if stale_offset:
            recommended_actions.append("Consumer offset is stale against stream activity; verify worker health and DB writes")
        if lag_events >= lag_alert_threshold:
            recommended_actions.append("Consumer lag exceeded threshold; consider scaling workers or reducing downstream latency")
        if not recommended_actions and lag_events > 0:
            recommended_actions.append("Lag is present but within threshold; continue monitoring")
        if not recommended_actions:
            recommended_actions.append("Healthy")

        status = "healthy"
        if exhausted_failed > 0 or stale_offset:
            status = "critical"
        elif failed > 0 or lag_events > 0:
            status = "warning"

        consumers.append(
            {
                "consumer_name": consumer_name,
                "stream_name": stream_name,
                "total_events": total_events,
                "delivery_rows": total_rows,
                "delivered": delivered,
                "pending": pending,
                "failed": failed,
                "retryable_failed": retryable_failed,
                "exhausted_failed": exhausted_failed,
                "unseen_events": unseen_events,
                "lag_events": lag_events,
                "failure_rate_pct": failure_rate_pct,
                "oldest_undelivered_age_seconds": oldest_undelivered_age_seconds,
                "offset_updated_at": offset_updated_at,
                "stale_offset": stale_offset,
                "status": status,
                "recommended_actions": recommended_actions,
            }
        )

    overall_status = "healthy"
    if any(item["status"] == "critical" for item in consumers):
        overall_status = "critical"
    elif any(item["status"] == "warning" for item in consumers):
        overall_status = "warning"

    return {
        "stream_name": stream_name,
        "total_events": total_events,
        "consumer_count": len(consumers),
        "overall_status": overall_status,
        "consumers": consumers,
    }


def create_job_run(
    db: Session,
    *,
    task_name: str,
    payload: dict[str, Any] | None = None,
    tenant_id: str | None = None,
    actor_user_id: str | None = None,
    correlation_id: str | None = None,
    max_attempts: int = 1,
) -> JobRun:
    """Persist a `queued` job row without executing it yet.

    Use this when a background worker is expected to pick the row up. In this
    stage callers usually go through `run_task` which combines create+execute
    in one call, but the separation makes migration to an out-of-process
    worker trivial later.
    """

    if registered_task(task_name) is None:
        raise UnknownTaskError(f"Task '{task_name}' is not registered")

    resolved_correlation = correlation_id or get_correlation_id()
    now = _now()
    job = JobRun(
        id=_uuid(),
        task_name=task_name,
        status="queued",
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        correlation_id=resolved_correlation,
        payload_json=_serialize(payload or {}),
        attempts=0,
        max_attempts=max(1, max_attempts),
        queued_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    create_job_lifecycle_event(
        db,
        job=job,
        event_type="queued",
        previous_status=None,
        current_status=job.status,
        payload={"max_attempts": job.max_attempts},
    )
    return job


async def execute_job(db: Session, job: JobRun) -> JobRun:
    """Execute the task associated with a queued job row and persist status."""

    task = registered_task(job.task_name)
    if task is None:
        previous_status = job.status
        job.status = "failed"
        job.error_message = f"Task '{job.task_name}' is not registered"
        job.finished_at = _now()
        job.attempts = max(job.attempts, 1)
        db.flush()
        create_job_lifecycle_event(
            db,
            job=job,
            event_type="failed",
            previous_status=previous_status,
            current_status=job.status,
            payload={"reason": "task_not_registered"},
        )
        return job

    payload = _deserialize(job.payload_json) or {}
    if not isinstance(payload, dict):
        payload = {"value": payload}

    ctx: dict[str, Any] = {
        "job_id": job.id,
        "task_name": job.task_name,
        "tenant_id": job.tenant_id,
        "actor_user_id": job.actor_user_id,
        "correlation_id": job.correlation_id,
        "attempt": job.attempts + 1,
    }

    previous_status = job.status
    job.status = "running"
    job.started_at = _now()
    job.attempts += 1
    db.flush()
    create_job_lifecycle_event(
        db,
        job=job,
        event_type="running",
        previous_status=previous_status,
        current_status=job.status,
        payload={"attempt": job.attempts},
    )

    start = time.monotonic()
    try:
        result = await task(ctx, payload)
    except Exception as exc:  # pragma: no cover - actual failure path tested separately
        logger.exception(
            "job_failed",
            extra={"job_id": job.id, "task_name": job.task_name, "correlation_id": job.correlation_id},
        )
        previous_status = job.status
        job.status = "failed"
        job.error_message = f"{exc.__class__.__name__}: {exc}"[:2000]
        job.finished_at = _now()
        job.duration_ms = int((time.monotonic() - start) * 1000)
        db.flush()
        create_job_lifecycle_event(
            db,
            job=job,
            event_type="failed",
            previous_status=previous_status,
            current_status=job.status,
            payload={"attempt": job.attempts, "error": job.error_message},
        )
        return job

    previous_status = job.status
    job.status = "success"
    job.result_json = _serialize(result if isinstance(result, (dict, list)) else {"value": result})
    job.finished_at = _now()
    job.duration_ms = int((time.monotonic() - start) * 1000)
    db.flush()
    create_job_lifecycle_event(
        db,
        job=job,
        event_type="success",
        previous_status=previous_status,
        current_status=job.status,
        payload={"attempt": job.attempts},
    )
    return job


async def run_task(
    db: Session,
    task_name: str,
    payload: dict[str, Any] | None = None,
    *,
    tenant_id: str | None = None,
    actor_user_id: str | None = None,
    correlation_id: str | None = None,
    max_attempts: int = 1,
) -> JobRun:
    """Create + execute a job in the current process.

    The DB row exists before execution starts, so failures are still observable
    via `GET /api/v1/jobs`. This is the safe default for the current stage.
    """

    job = create_job_run(
        db,
        task_name=task_name,
        payload=payload,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
        max_attempts=max_attempts,
    )
    return await execute_job(db, job)


def enqueue_job_id(*, redis_url: str, queue_name: str, job_id: str) -> None:
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        client.lpush(queue_name, job_id)
    finally:
        client.close()


# Backward-compatible alias used by existing tests/stubs.
def _enqueue_job_id(*, redis_url: str, queue_name: str, job_id: str) -> None:
    enqueue_job_id(redis_url=redis_url, queue_name=queue_name, job_id=job_id)


def create_outbox_entry(db: Session, *, job_id: str, queue_name: str) -> JobQueueOutbox:
    dedup_key = f"{queue_name}:{job_id}"
    existing = db.scalar(select(JobQueueOutbox).where(JobQueueOutbox.dedup_key == dedup_key))
    if existing is not None:
        return existing

    entry = JobQueueOutbox(
        id=_uuid(),
        job_id=job_id,
        queue_name=queue_name,
        dedup_key=dedup_key,
        published_at=None,
        publish_attempted_at=None,
        lock_owner=None,
        lock_expires_at=None,
        failed_attempts=0,
        last_error=None,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(entry)
    db.flush()
    return entry


def outbox_summary(db: Session, queue_name: str | None = None) -> dict[str, int]:
    stmt = select(
        func.count(JobQueueOutbox.id),
        func.sum(case((JobQueueOutbox.published_at.is_(None), 1), else_=0)),
        func.sum(case((JobQueueOutbox.published_at.is_not(None), 1), else_=0)),
        func.sum(case((JobQueueOutbox.failed_attempts > 0, 1), else_=0)),
    )
    if queue_name:
        stmt = stmt.where(JobQueueOutbox.queue_name == queue_name)
    total, pending, published, failed = db.execute(stmt).one()
    return {
        "total": int(total or 0),
        "pending": int(pending or 0),
        "published": int(published or 0),
        "with_failures": int(failed or 0),
    }


def outbox_diagnostics(db: Session, queue_name: str | None = None) -> dict[str, int | float | str | list[str]]:
    now = _now()
    pending_threshold = 5
    failure_threshold = 2
    stale_lock_threshold = 1
    dedup_skip_threshold = 1

    stmt = select(
        func.count(JobQueueOutbox.id),
        func.sum(case((JobQueueOutbox.published_at.is_(None), 1), else_=0)),
        func.sum(case((JobQueueOutbox.published_at.is_not(None), 1), else_=0)),
        func.sum(case((JobQueueOutbox.failed_attempts > 0, 1), else_=0)),
        func.sum(
            case(
                (
                    (JobQueueOutbox.published_at.is_(None))
                    & (JobQueueOutbox.lock_owner.is_not(None))
                    & (JobQueueOutbox.lock_expires_at.is_not(None))
                    & (JobQueueOutbox.lock_expires_at >= now),
                    1,
                ),
                else_=0,
            )
        ),
        func.sum(
            case(
                (
                    (JobQueueOutbox.published_at.is_(None))
                    & (JobQueueOutbox.lock_owner.is_not(None))
                    & (JobQueueOutbox.lock_expires_at.is_not(None))
                    & (JobQueueOutbox.lock_expires_at < now),
                    1,
                ),
                else_=0,
            )
        ),
        func.sum(case((JobQueueOutbox.last_error == "dedup_skip_already_published", 1), else_=0)),
    )
    if queue_name:
        stmt = stmt.where(JobQueueOutbox.queue_name == queue_name)
    total, pending, published, failed, locked, stale_locks, dedup_skips = db.execute(stmt).one()

    total_value = int(total or 0)
    pending_value = int(pending or 0)
    published_value = int(published or 0)
    failed_value = int(failed or 0)
    locked_value = int(locked or 0)
    stale_locks_value = int(stale_locks or 0)
    dedup_skips_value = int(dedup_skips or 0)
    publish_failure_rate_pct = round((failed_value / total_value) * 100, 2) if total_value else 0.0

    recommended_actions: list[str] = []
    status = "ok"
    if pending_value >= pending_threshold:
        status = "warn"
        recommended_actions.append("Inspect worker throughput and Redis queue drain rate.")
    if failed_value >= failure_threshold or stale_locks_value >= stale_lock_threshold:
        status = "critical"
        recommended_actions.append("Inspect worker logs and clear blocked outbox rows after root-cause analysis.")
    if dedup_skips_value >= dedup_skip_threshold:
        status = "critical" if status == "critical" else "warn"
        recommended_actions.append("Review duplicate publish attempts across workers and confirm dedup keys are stable.")
    if not recommended_actions:
        recommended_actions.append("No immediate action required.")

    return {
        "total": total_value,
        "pending": pending_value,
        "published": published_value,
        "with_failures": failed_value,
        "locked": locked_value,
        "stale_locks": stale_locks_value,
        "dedup_skips": dedup_skips_value,
        "publish_failure_rate_pct": publish_failure_rate_pct,
        "pending_alert_threshold": pending_threshold,
        "failure_alert_threshold": failure_threshold,
        "stale_lock_alert_threshold": stale_lock_threshold,
        "status": status,
        "recommended_actions": recommended_actions,
    }


def enqueue_task(
    db: Session,
    task_name: str,
    payload: dict[str, Any] | None = None,
    *,
    redis_url: str,
    queue_name: str,
    tenant_id: str | None = None,
    actor_user_id: str | None = None,
    correlation_id: str | None = None,
    max_attempts: int = 1,
) -> JobRun:
    """Create a queued job and transactional outbox entry for worker publish."""

    job = create_job_run(
        db,
        task_name=task_name,
        payload=payload,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
        max_attempts=max_attempts,
    )
    try:
        create_outbox_entry(db, job_id=job.id, queue_name=queue_name)
    except Exception as exc:
        logger.exception(
            "job_enqueue_failed",
            extra={"job_id": job.id, "task_name": task_name, "correlation_id": job.correlation_id},
        )
        raise JobQueueUnavailableError("Unable to enqueue job to redis queue") from exc
    return job


def _apply_filters(
    stmt: Select[tuple[JobRun]],
    *,
    task_name: str | None,
    status: str | None,
    tenant_id: str | None,
) -> Select[tuple[JobRun]]:
    if task_name:
        stmt = stmt.where(JobRun.task_name == task_name)
    if status:
        stmt = stmt.where(JobRun.status == status)
    if tenant_id:
        stmt = stmt.where(JobRun.tenant_id == tenant_id)
    return stmt


def list_jobs(
    db: Session,
    *,
    limit: int = 50,
    task_name: str | None = None,
    status: str | None = None,
    tenant_id: str | None = None,
) -> list[JobRun]:
    limit = max(1, min(200, limit))
    stmt = select(JobRun).order_by(JobRun.queued_at.desc()).limit(limit)
    stmt = _apply_filters(stmt, task_name=task_name, status=status, tenant_id=tenant_id)
    return list(db.scalars(stmt).all())


def get_job(db: Session, job_id: str) -> JobRun | None:
    return db.scalar(select(JobRun).where(JobRun.id == job_id))


def job_summary(db: Session, tenant_id: str | None = None) -> dict[str, int]:
    """Return a small counter map for admin dashboards."""

    from sqlalchemy import func

    stmt = select(JobRun.status, func.count(JobRun.id)).group_by(JobRun.status)
    if tenant_id:
        stmt = stmt.where(JobRun.tenant_id == tenant_id)
    result = {"total": 0, "queued": 0, "running": 0, "success": 0, "failed": 0, "dead_letter": 0}
    for status_value, count in db.execute(stmt).all():
        key = str(status_value)
        result["total"] += int(count)
        if key in result:
            result[key] = int(count)
    return result


__all__ = [
    "JobContext",
    "JobExecutionError",
    "JobQueueUnavailableError",
    "UnknownTaskError",
    "create_job_run",
    "create_job_lifecycle_event",
    "create_outbox_entry",
    "enqueue_job_id",
    "enqueue_task",
    "execute_job",
    "get_job",
    "job_summary",
    "list_jobs",
    "job_event_bus_summary",
    "job_event_consumer_summary",
    "job_event_consumers_diagnostics",
    "list_job_events",
    "outbox_diagnostics",
    "outbox_summary",
    "register_task",
    "registered_task",
    "registered_task_names",
    "run_task",
]
