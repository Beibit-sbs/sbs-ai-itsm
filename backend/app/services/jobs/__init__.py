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
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.context import get_correlation_id
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
    return job


async def execute_job(db: Session, job: JobRun) -> JobRun:
    """Execute the task associated with a queued job row and persist status."""

    task = registered_task(job.task_name)
    if task is None:
        job.status = "failed"
        job.error_message = f"Task '{job.task_name}' is not registered"
        job.finished_at = _now()
        job.attempts = max(job.attempts, 1)
        db.flush()
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

    job.status = "running"
    job.started_at = _now()
    job.attempts += 1
    db.flush()

    start = time.monotonic()
    try:
        result = await task(ctx, payload)
    except Exception as exc:  # pragma: no cover - actual failure path tested separately
        logger.exception(
            "job_failed",
            extra={"job_id": job.id, "task_name": job.task_name, "correlation_id": job.correlation_id},
        )
        job.status = "failed"
        job.error_message = f"{exc.__class__.__name__}: {exc}"[:2000]
        job.finished_at = _now()
        job.duration_ms = int((time.monotonic() - start) * 1000)
        db.flush()
        return job

    job.status = "success"
    job.result_json = _serialize(result if isinstance(result, (dict, list)) else {"value": result})
    job.finished_at = _now()
    job.duration_ms = int((time.monotonic() - start) * 1000)
    db.flush()
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


def _enqueue_job_id(*, redis_url: str, queue_name: str, job_id: str) -> None:
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        client.lpush(queue_name, job_id)
    finally:
        client.close()


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
    """Create a queued job and push its id to Redis for worker pickup."""

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
        _enqueue_job_id(redis_url=redis_url, queue_name=queue_name, job_id=job.id)
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
    "enqueue_task",
    "execute_job",
    "get_job",
    "job_summary",
    "list_jobs",
    "register_task",
    "registered_task",
    "registered_task_names",
    "run_task",
]
