"""Operator-only production-like queue, retry, DLQ and replay exercise."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid

from redis import Redis
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.job_lifecycle_event import JobLifecycleEvent
from app.models.job_queue_outbox import JobQueueOutbox
from app.models.job_run import JobRun
from app.services.jobs import enqueue_task, prepare_dead_letter_replay
from app.services.jobs import tasks as _job_tasks  # noqa: F401 - registers smoke tasks


def _enqueue(*, task_name: str, payload: dict[str, object], max_attempts: int, correlation_id: str) -> str:
    settings = get_settings()
    with SessionLocal() as db:
        job = enqueue_task(
            db,
            task_name,
            payload,
            redis_url=settings.redis_url,
            queue_name=settings.jobs_queue_name,
            correlation_id=correlation_id,
            max_attempts=max_attempts,
        )
        db.commit()
        return job.id


def _snapshot(job_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        job = db.get(JobRun, job_id)
        if job is None:
            raise RuntimeError(f"Runtime exercise job disappeared: {job_id}")
        events = list(
            db.scalars(
                select(JobLifecycleEvent)
                .where(JobLifecycleEvent.job_id == job_id)
                .order_by(JobLifecycleEvent.sequence.asc())
            ).all()
        )
        outbox_rows = list(
            db.scalars(
                select(JobQueueOutbox)
                .where(JobQueueOutbox.job_id == job_id)
                .order_by(JobQueueOutbox.created_at.asc(), JobQueueOutbox.id.asc())
            ).all()
        )
        return {
            "status": job.status,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "event_types": [event.event_type for event in events],
            "event_sequences": [event.sequence for event in events],
            "outbox_total": len(outbox_rows),
            "outbox_published": sum(row.published_at is not None for row in outbox_rows),
            "outbox_unique_keys": len({row.dedup_key for row in outbox_rows}),
        }


def _wait_for(job_id: str, predicate, *, timeout_seconds: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last = _snapshot(job_id)
    while time.monotonic() < deadline:
        if predicate(last):
            return last
        time.sleep(0.25)
        last = _snapshot(job_id)
    raise RuntimeError(f"Timed out waiting for job {job_id}; last state={last}")


def _prepare_replay(job_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        job = db.get(JobRun, job_id)
        if job is None:
            raise RuntimeError("Dead-letter job not found before replay")
        prepare_dead_letter_replay(db, job=job, queue_name=settings.jobs_queue_name)
        db.commit()


def run(*, timeout_seconds: float) -> dict[str, object]:
    settings = get_settings()
    if settings.app_env != "production":
        raise RuntimeError("Runtime queue exercise requires APP_ENV=production")
    if settings.jobs_executor_mode != "redis":
        raise RuntimeError("Runtime queue exercise requires JOBS_EXECUTOR_MODE=redis")

    run_id = uuid.uuid4().hex[:12]
    prefix = f"rehearsal-runtime-{run_id}"
    echo_id = _enqueue(
        task_name="system.echo",
        payload={"exercise": "queue_success", "run_id": run_id},
        max_attempts=1,
        correlation_id=f"{prefix}-echo",
    )
    flaky_id = _enqueue(
        task_name="system.flaky",
        payload={"fail_until_attempt": 1, "run_id": run_id},
        max_attempts=3,
        correlation_id=f"{prefix}-flaky",
    )
    failing_id = _enqueue(
        task_name="system.fail",
        payload={"reason": "intentional rehearsal DLQ exercise", "run_id": run_id},
        max_attempts=2,
        correlation_id=f"{prefix}-fail",
    )

    echo = _wait_for(echo_id, lambda item: item["status"] == "success", timeout_seconds=timeout_seconds)
    flaky = _wait_for(
        flaky_id,
        lambda item: item["status"] == "success" and item["attempts"] == 2,
        timeout_seconds=timeout_seconds,
    )
    failing_initial = _wait_for(
        failing_id,
        lambda item: item["status"] == "dead_letter" and item["attempts"] == 2,
        timeout_seconds=timeout_seconds,
    )

    _prepare_replay(failing_id)
    failing_replayed = _wait_for(
        failing_id,
        lambda item: (
            item["status"] == "dead_letter"
            and item["attempts"] == 2
            and item["event_types"].count("dead_letter") == 2
            and item["event_types"].count("replayed") == 1
            and item["outbox_total"] == 2
            and item["outbox_published"] == 2
            and item["outbox_unique_keys"] == 2
        ),
        timeout_seconds=timeout_seconds,
    )

    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        dead_letter_occurrences = redis_client.lrange(settings.jobs_dead_letter_queue_name, 0, -1).count(failing_id)
        queue_depth = int(redis_client.llen(settings.jobs_queue_name))
        scheduled_depth = int(redis_client.zcard(f"{settings.jobs_queue_name}:scheduled"))
    finally:
        redis_client.close()

    with SessionLocal() as db:
        run_job_count = int(
            db.scalar(select(func.count(JobRun.id)).where(JobRun.correlation_id.like(f"{prefix}%"))) or 0
        )
        run_outbox_total = int(
            db.scalar(
                select(func.count(JobQueueOutbox.id))
                .join(JobRun, JobRun.id == JobQueueOutbox.job_id)
                .where(JobRun.correlation_id.like(f"{prefix}%"))
            )
            or 0
        )

    if dead_letter_occurrences < 2:
        raise RuntimeError("DLQ did not record both the initial and replayed intentional failures")
    if queue_depth != 0 or scheduled_depth != 0:
        raise RuntimeError("Exercise queues did not drain to zero")
    if run_job_count != 3 or run_outbox_total != 4:
        raise RuntimeError("Unexpected exercise job/outbox cardinality")

    return {
        "schema_version": 1,
        "status": "PASS",
        "run_id": run_id,
        "jobs": {
            "echo": {"id": echo_id, **echo},
            "flaky": {"id": flaky_id, **flaky},
            "intentional_failure_before_replay": failing_initial,
            "intentional_failure_after_replay": {"id": failing_id, **failing_replayed},
        },
        "invariants": {
            "job_rows": run_job_count,
            "outbox_rows": run_outbox_total,
            "outbox_all_published": True,
            "replay_distinct_dedup_keys": True,
            "dead_letter_occurrences": dead_letter_occurrences,
            "main_queue_depth": queue_depth,
            "scheduled_queue_depth": scheduled_depth,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-rehearsal", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if not args.confirm_rehearsal or os.environ.get("REHEARSAL_RUNTIME_EXERCISE_ENABLED", "").lower() != "true":
        print("Runtime queue exercise is disabled; require env opt-in and --confirm-rehearsal")
        return 2
    try:
        result = run(timeout_seconds=max(5.0, min(args.timeout_seconds, 180.0)))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error_type": exc.__class__.__name__, "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
