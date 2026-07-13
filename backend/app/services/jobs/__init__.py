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
from datetime import UTC, datetime, timedelta
from typing import Any

from redis import Redis
from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import get_correlation_id
from app.models.audit_log import AuditLog
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


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
    audit_window_start = now - timedelta(hours=24)
    total_events = int(
        db.scalar(select(func.count(JobLifecycleEvent.id)).where(JobLifecycleEvent.relay_stream_name == stream_name)) or 0
    )
    last_event_created_at = db.scalar(
        select(func.max(JobLifecycleEvent.created_at)).where(JobLifecycleEvent.relay_stream_name == stream_name)
    )

    recent_recovery_rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action.in_(["jobs.event_consumer_recovery.preview", "jobs.event_consumer_recovery.execute"]))
            .where(AuditLog.created_at >= audit_window_start)
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        ).all()
    )
    recent_autoremediation_rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "jobs.event_consumer_recovery.auto")
            .where(AuditLog.created_at >= audit_window_start)
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        ).all()
    )
    recovery_agg: dict[str, dict[str, object]] = {
        name: {
            "preview_24h": 0,
            "execute_24h": 0,
            "autoremediation_24h": 0,
            "governance_compliant_execute_24h": 0,
            "governance_missing_execute_24h": 0,
            "last_execute_at": None,
            "last_execute_actor_email": None,
        }
        for name in consumer_names
    }
    recent_recovery_actions: list[dict[str, object]] = []
    recent_autoremediation_actions: list[dict[str, object]] = []
    for row in recent_recovery_rows:
        metadata = _deserialize(row.metadata_json) if row.metadata_json else {}
        if not isinstance(metadata, dict):
            metadata = {}
        consumer = str(metadata.get("consumer_name") or "")
        if consumer not in recovery_agg:
            continue
        if row.action.endswith(".preview"):
            recovery_agg[consumer]["preview_24h"] = int(recovery_agg[consumer]["preview_24h"] or 0) + 1
        if row.action.endswith(".execute"):
            recovery_agg[consumer]["execute_24h"] = int(recovery_agg[consumer]["execute_24h"] or 0) + 1
            governance_compliant = bool(metadata.get("reason_code")) and bool(metadata.get("change_ticket_ref"))
            if governance_compliant:
                recovery_agg[consumer]["governance_compliant_execute_24h"] = (
                    int(recovery_agg[consumer]["governance_compliant_execute_24h"] or 0) + 1
                )
            else:
                recovery_agg[consumer]["governance_missing_execute_24h"] = (
                    int(recovery_agg[consumer]["governance_missing_execute_24h"] or 0) + 1
                )
            if recovery_agg[consumer]["last_execute_at"] is None:
                recovery_agg[consumer]["last_execute_at"] = _as_utc(row.created_at)
                recovery_agg[consumer]["last_execute_actor_email"] = row.actor_email
        if len(recent_recovery_actions) < 12:
            recent_recovery_actions.append(
                {
                    "action": row.action,
                    "consumer_name": consumer,
                    "actor_email": row.actor_email,
                    "created_at": _as_utc(row.created_at),
                    "dry_run": bool(metadata.get("dry_run", False)),
                    "selected": int(metadata.get("selected", 0) or 0),
                    "requeued": int(metadata.get("requeued", 0) or 0),
                    "reason_code": str(metadata.get("reason_code") or ""),
                    "change_ticket_ref": str(metadata.get("change_ticket_ref") or ""),
                    "approved_by_email": str(metadata.get("approved_by_email") or ""),
                    "governance_compliant": bool(metadata.get("reason_code")) and bool(metadata.get("change_ticket_ref")),
                }
            )

    for row in recent_autoremediation_rows:
        metadata = _deserialize(row.metadata_json) if row.metadata_json else {}
        if not isinstance(metadata, dict):
            metadata = {}
        consumer = str(metadata.get("consumer_name") or "")
        if consumer in recovery_agg:
            recovery_agg[consumer]["autoremediation_24h"] = int(recovery_agg[consumer]["autoremediation_24h"] or 0) + 1
        if len(recent_autoremediation_actions) < 12:
            recent_autoremediation_actions.append(
                {
                    "action": row.action,
                    "consumer_name": consumer,
                    "actor_email": row.actor_email,
                    "created_at": _as_utc(row.created_at),
                    "selected": int(metadata.get("selected", 0) or 0),
                    "requeued": int(metadata.get("requeued", 0) or 0),
                    "auto_remediation": True,
                }
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
        oldest_undelivered_utc = _as_utc(oldest_undelivered)
        oldest_undelivered_age_seconds = (
            int((now - oldest_undelivered_utc).total_seconds()) if oldest_undelivered_utc is not None else 0
        )

        offset = db.scalar(
            select(JobEventConsumerOffset).where(
                JobEventConsumerOffset.consumer_name == consumer_name,
                JobEventConsumerOffset.stream_name == stream_name,
            )
        )
        offset_updated_at = _as_utc(offset.updated_at) if offset is not None else None
        last_event_created_at_utc = _as_utc(last_event_created_at)
        stale_offset = False
        if offset_updated_at is not None and last_event_created_at_utc is not None:
            stale_offset = (
                (now - offset_updated_at).total_seconds() >= stale_offset_seconds
                and offset_updated_at < last_event_created_at_utc
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

        recovery_data = recovery_agg.get(consumer_name, {})
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
                "recovery_preview_24h": int(recovery_data.get("preview_24h", 0) or 0),
                "recovery_execute_24h": int(recovery_data.get("execute_24h", 0) or 0),
                "autoremediation_24h": int(recovery_data.get("autoremediation_24h", 0) or 0),
                "governance_compliant_execute_24h": int(recovery_data.get("governance_compliant_execute_24h", 0) or 0),
                "governance_missing_execute_24h": int(recovery_data.get("governance_missing_execute_24h", 0) or 0),
                "last_recovery_execute_at": recovery_data.get("last_execute_at"),
                "last_recovery_execute_actor_email": recovery_data.get("last_execute_actor_email"),
                "status": status,
                "recommended_actions": recommended_actions,
            }
        )

    overall_status = "healthy"
    if any(item["status"] == "critical" for item in consumers):
        overall_status = "critical"
    elif any(item["status"] == "warning" for item in consumers):
        overall_status = "warning"

    governance_execute_actions_24h = sum(int(item.get("execute_24h", 0) or 0) for item in recovery_agg.values())
    governance_compliant_actions_24h = sum(
        int(item.get("governance_compliant_execute_24h", 0) or 0) for item in recovery_agg.values()
    )
    governance_compliance_rate_pct = (
        round((governance_compliant_actions_24h / governance_execute_actions_24h) * 100, 2)
        if governance_execute_actions_24h
        else 100.0
    )

    return {
        "stream_name": stream_name,
        "total_events": total_events,
        "consumer_count": len(consumers),
        "overall_status": overall_status,
        "recovery_actions_24h": len(recent_recovery_rows),
        "autoremediation_actions_24h": len(recent_autoremediation_rows),
        "governance_execute_actions_24h": governance_execute_actions_24h,
        "governance_compliant_actions_24h": governance_compliant_actions_24h,
        "governance_compliance_rate_pct": governance_compliance_rate_pct,
        "recent_recovery_actions": recent_recovery_actions,
        "recent_autoremediation_actions": recent_autoremediation_actions,
        "consumers": consumers,
    }


def job_event_consumer_autoremediation_safety_state(
    db: Session,
    *,
    consumer_name: str,
    cooldown_seconds: int,
    max_per_hour: int,
) -> dict[str, object]:
    now = _now()
    window_start = now - timedelta(hours=1)
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "jobs.event_consumer_recovery.auto")
            .where(AuditLog.created_at >= window_start)
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        ).all()
    )
    consumer_rows: list[AuditLog] = []
    for row in rows:
        metadata = _deserialize(row.metadata_json) if row.metadata_json else {}
        if isinstance(metadata, dict) and str(metadata.get("consumer_name") or "") == consumer_name:
            consumer_rows.append(row)

    executed_last_hour = len(consumer_rows)
    last_executed_at = _as_utc(consumer_rows[0].created_at) if consumer_rows else None
    cooldown_active = False
    retry_after_seconds = 0
    if cooldown_seconds > 0 and last_executed_at is not None:
        elapsed = int((now - last_executed_at).total_seconds())
        remaining = cooldown_seconds - elapsed
        if remaining > 0:
            cooldown_active = True
            retry_after_seconds = remaining
    rate_limit_exceeded = max_per_hour > 0 and executed_last_hour >= max_per_hour
    return {
        "consumer_name": consumer_name,
        "executed_last_hour": executed_last_hour,
        "max_per_hour": max_per_hour,
        "rate_limit_exceeded": rate_limit_exceeded,
        "cooldown_seconds": cooldown_seconds,
        "cooldown_active": cooldown_active,
        "retry_after_seconds": retry_after_seconds,
        "last_executed_at": last_executed_at,
    }


def _parse_window(value: str) -> tuple[int, int] | None:
    raw = value.strip()
    if not raw or "-" not in raw:
        return None
    start_raw, end_raw = [part.strip() for part in raw.split("-", 1)]

    def _to_minutes(token: str) -> int | None:
        parts = token.split(":")
        if len(parts) != 2:
            return None
        if not parts[0].isdigit() or not parts[1].isdigit():
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return hour * 60 + minute

    start = _to_minutes(start_raw)
    end = _to_minutes(end_raw)
    if start is None or end is None:
        return None
    return (start, end)


def is_autoremediation_suppressed_now(*, now: datetime, windows_utc: list[str]) -> bool:
    minute_of_day = now.hour * 60 + now.minute
    for item in windows_utc:
        parsed = _parse_window(str(item))
        if parsed is None:
            continue
        start, end = parsed
        if start <= end:
            if start <= minute_of_day <= end:
                return True
            continue
        # Wrap-over window, e.g. 23:00-02:00
        if minute_of_day >= start or minute_of_day <= end:
            return True
    return False


def job_event_consumer_autoremediation_preview(
    db: Session,
    *,
    consumer_name: str,
    stream_name: str,
    max_attempts: int,
    min_failed_age_seconds: int,
    allowed_event_types: list[str],
    error_denylist: list[str],
    limit: int,
) -> dict[str, object]:
    effective_limit = max(1, min(200, int(limit)))
    cutoff = _now() - timedelta(seconds=max(0, int(min_failed_age_seconds)))
    event_types = [item.strip() for item in allowed_event_types if item and item.strip()]
    denylist = [item.strip().lower() for item in error_denylist if item and item.strip()]

    stmt = (
        select(JobEventConsumerDelivery, JobLifecycleEvent.event_type)
        .join(JobLifecycleEvent, JobLifecycleEvent.id == JobEventConsumerDelivery.event_id)
        .where(JobEventConsumerDelivery.consumer_name == consumer_name)
        .where(JobEventConsumerDelivery.stream_name == stream_name)
        .where(JobEventConsumerDelivery.status == "failed")
        .where(JobEventConsumerDelivery.attempts >= max_attempts)
        .where(JobEventConsumerDelivery.updated_at <= cutoff)
        .order_by(JobEventConsumerDelivery.updated_at.asc())
        .limit(effective_limit)
    )
    if event_types:
        stmt = stmt.where(JobLifecycleEvent.event_type.in_(event_types))

    rows = list(db.execute(stmt).all())
    items: list[dict[str, object]] = []
    selected = 0
    skipped_by_denylist = 0
    for delivery, event_type in rows:
        last_error = str(delivery.last_error or "")
        lowered = last_error.lower()
        denied = any(fragment in lowered for fragment in denylist)
        if denied:
            skipped_by_denylist += 1
            continue
        selected += 1
        items.append(
            {
                "delivery_id": delivery.id,
                "event_id": delivery.event_id,
                "event_type": str(event_type),
                "attempts": int(delivery.attempts or 0),
                "last_error": last_error,
            }
        )

    return {
        "consumer_name": consumer_name,
        "stream_name": stream_name,
        "requested_limit": effective_limit,
        "raw_candidates": len(rows),
        "selected": selected,
        "skipped_by_denylist": skipped_by_denylist,
        "items": items[:20],
    }


def job_event_consumer_autoremediate(
    db: Session,
    *,
    consumer_name: str,
    stream_name: str,
    max_attempts: int,
    min_failed_age_seconds: int,
    allowed_event_types: list[str],
    error_denylist: list[str],
    limit: int,
) -> dict[str, object]:
    effective_limit = max(1, min(200, int(limit)))
    cutoff = _now() - timedelta(seconds=max(0, int(min_failed_age_seconds)))
    event_types = [item.strip() for item in allowed_event_types if item and item.strip()]
    denylist = [item.strip().lower() for item in error_denylist if item and item.strip()]

    stmt = (
        select(JobEventConsumerDelivery, JobLifecycleEvent.event_type)
        .join(JobLifecycleEvent, JobLifecycleEvent.id == JobEventConsumerDelivery.event_id)
        .where(JobEventConsumerDelivery.consumer_name == consumer_name)
        .where(JobEventConsumerDelivery.stream_name == stream_name)
        .where(JobEventConsumerDelivery.status == "failed")
        .where(JobEventConsumerDelivery.attempts >= max_attempts)
        .where(JobEventConsumerDelivery.updated_at <= cutoff)
        .order_by(JobEventConsumerDelivery.updated_at.asc())
        .limit(effective_limit)
    )
    if event_types:
        stmt = stmt.where(JobLifecycleEvent.event_type.in_(event_types))

    rows = list(db.execute(stmt).all())
    requeued = 0
    items: list[dict[str, object]] = []
    now = _now()
    for delivery, event_type in rows:
        last_error = str(delivery.last_error or "")
        lowered = last_error.lower()
        if any(fragment in lowered for fragment in denylist):
            continue
        items.append(
            {
                "delivery_id": delivery.id,
                "event_id": delivery.event_id,
                "event_type": str(event_type),
                "attempts_before": int(delivery.attempts or 0),
                "status_before": delivery.status,
                "last_error": last_error,
            }
        )
        delivery.status = "failed"
        delivery.attempts = 0
        delivery.last_error = "auto_remediation_requeued_by_policy"
        delivery.delivered_at = None
        delivery.updated_at = now
        requeued += 1

    if rows:
        db.flush()

    return {
        "consumer_name": consumer_name,
        "stream_name": stream_name,
        "selected": len(rows),
        "requeued": requeued,
        "items": items,
    }


def job_event_consumer_recovery_safety_state(
    db: Session,
    *,
    consumer_name: str,
    cooldown_seconds: int,
    max_exec_per_hour: int,
) -> dict[str, object]:
    now = _now()
    window_start = now - timedelta(hours=1)
    execute_rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "jobs.event_consumer_recovery.execute")
            .where(AuditLog.created_at >= window_start)
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        ).all()
    )
    consumer_exec_rows: list[AuditLog] = []
    for row in execute_rows:
        metadata = _deserialize(row.metadata_json) if row.metadata_json else {}
        if isinstance(metadata, dict) and str(metadata.get("consumer_name") or "") == consumer_name:
            consumer_exec_rows.append(row)

    executed_last_hour = len(consumer_exec_rows)
    last_executed_at = _as_utc(consumer_exec_rows[0].created_at) if consumer_exec_rows else None
    cooldown_active = False
    retry_after_seconds = 0
    if cooldown_seconds > 0 and last_executed_at is not None:
        elapsed = int((now - last_executed_at).total_seconds())
        remaining = cooldown_seconds - elapsed
        if remaining > 0:
            cooldown_active = True
            retry_after_seconds = remaining

    rate_limit_exceeded = max_exec_per_hour > 0 and executed_last_hour >= max_exec_per_hour
    return {
        "consumer_name": consumer_name,
        "executed_last_hour": executed_last_hour,
        "max_exec_per_hour": max_exec_per_hour,
        "rate_limit_exceeded": rate_limit_exceeded,
        "cooldown_seconds": cooldown_seconds,
        "cooldown_active": cooldown_active,
        "retry_after_seconds": retry_after_seconds,
        "last_executed_at": last_executed_at,
    }


def recover_job_event_consumer_deliveries(
    db: Session,
    *,
    consumer_name: str,
    stream_name: str,
    statuses: list[str],
    event_types: list[str] | None,
    limit: int,
    dry_run: bool,
) -> dict[str, object]:
    normalized_statuses = [item.strip().lower() for item in statuses if item and item.strip()]
    normalized_event_types = [item.strip() for item in (event_types or []) if item and item.strip()]
    effective_limit = max(1, min(200, int(limit)))

    stmt = (
        select(JobEventConsumerDelivery, JobLifecycleEvent.event_type)
        .join(JobLifecycleEvent, JobLifecycleEvent.id == JobEventConsumerDelivery.event_id)
        .where(JobEventConsumerDelivery.consumer_name == consumer_name)
        .where(JobEventConsumerDelivery.stream_name == stream_name)
        .where(JobEventConsumerDelivery.status.in_(normalized_statuses))
        .order_by(JobEventConsumerDelivery.updated_at.asc())
        .limit(effective_limit)
    )
    if normalized_event_types:
        stmt = stmt.where(JobLifecycleEvent.event_type.in_(normalized_event_types))

    rows = list(db.execute(stmt).all())
    items: list[dict[str, object]] = []
    requeued = 0
    now = _now()
    for delivery, event_type in rows:
        items.append(
            {
                "delivery_id": delivery.id,
                "event_id": delivery.event_id,
                "event_type": str(event_type),
                "status_before": delivery.status,
                "attempts_before": int(delivery.attempts or 0),
                "stream_entry_id": delivery.stream_entry_id,
            }
        )
        if dry_run:
            continue
        # Recovery path only re-queues selected consumer deliveries; event source rows are untouched.
        delivery.status = "failed"
        delivery.attempts = 0
        delivery.last_error = "recovery_requeued_by_operator"
        delivery.delivered_at = None
        delivery.updated_at = now
        requeued += 1

    if not dry_run:
        db.flush()

    return {
        "consumer_name": consumer_name,
        "stream_name": stream_name,
        "dry_run": dry_run,
        "requested_limit": effective_limit,
        "selected": len(rows),
        "requeued": requeued,
        "items": items,
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
    "job_event_consumer_recovery_safety_state",
    "job_event_consumer_autoremediation_safety_state",
    "job_event_consumer_autoremediation_preview",
    "is_autoremediation_suppressed_now",
    "job_event_consumer_autoremediate",
    "recover_job_event_consumer_deliveries",
    "list_job_events",
    "outbox_diagnostics",
    "outbox_summary",
    "register_task",
    "registered_task",
    "registered_task_names",
    "run_task",
]
