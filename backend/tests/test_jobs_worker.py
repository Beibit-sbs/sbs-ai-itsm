from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.models.job_lifecycle_event import JobLifecycleEvent
from app.services.jobs import create_job_run
from app.workers import jobs_worker
from app.workers.jobs_worker import (
    _drain_scheduled_jobs,
    _retry_delay_seconds,
    _run_single_job,
    _schedule_retry,
    _scheduled_queue_name,
)


class FakeRedis:
    def __init__(self) -> None:
        self.left: list[tuple[str, str]] = []
        self.right: list[tuple[str, str]] = []
        self.zset: dict[str, dict[str, float]] = {}

    def lpush(self, key: str, value: str) -> None:
        self.left.append((key, value))

    def rpush(self, key: str, value: str) -> None:
        self.right.append((key, value))

    def incr(self, key: str) -> int:  # pragma: no cover - simple stub compatibility
        return 1

    def expire(self, key: str, seconds: int) -> None:  # pragma: no cover - simple stub compatibility
        return None

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        bucket = self.zset.setdefault(key, {})
        for member, score in mapping.items():
            bucket[member] = float(score)

    def zrangebyscore(self, key: str, min_score: str, max_score: float, *, start: int = 0, num: int = 100) -> list[str]:
        bucket = self.zset.get(key, {})
        eligible = sorted([member for member, score in bucket.items() if score <= float(max_score)])
        return eligible[start : start + num]

    def zrem(self, key: str, member: str) -> int:
        bucket = self.zset.get(key, {})
        if member in bucket:
            del bucket[member]
            return 1
        return 0


def test_retry_delay_seconds_is_exponential_with_cap() -> None:
    assert _retry_delay_seconds(1, base_seconds=0.5, max_seconds=15.0) == 0.5
    assert _retry_delay_seconds(2, base_seconds=0.5, max_seconds=15.0) == 1.0
    assert _retry_delay_seconds(3, base_seconds=0.5, max_seconds=15.0) == 2.0
    assert _retry_delay_seconds(20, base_seconds=0.5, max_seconds=15.0) == 15.0


def test_schedule_retry_stores_job_in_scheduled_sorted_set() -> None:
    redis = FakeRedis()
    _schedule_retry(redis, "jobs:queue", "job-1", delay_seconds=1.2)
    scheduled_key = _scheduled_queue_name("jobs:queue")
    assert scheduled_key in redis.zset
    assert "job-1" in redis.zset[scheduled_key]


def test_drain_scheduled_jobs_moves_due_jobs_to_main_queue() -> None:
    redis = FakeRedis()
    queue_name = "jobs:queue"
    scheduled_key = _scheduled_queue_name(queue_name)
    now = time.time()
    redis.zadd(scheduled_key, {"due-1": now - 1, "due-2": now - 0.5, "future": now + 10})

    moved = _drain_scheduled_jobs(redis, queue_name, batch_size=10)

    assert moved == 2
    assert (queue_name, "due-1") in redis.right
    assert (queue_name, "due-2") in redis.right
    assert redis.zset[scheduled_key].get("future") is not None


def test_run_single_job_emits_retry_scheduled_event(app, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.db.session import SessionLocal

    settings = get_settings()
    settings.jobs_retry_base_seconds = 0.5
    settings.jobs_retry_max_seconds = 15.0
    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)

    redis = FakeRedis()
    with TestClient(app):
        with SessionLocal() as db:
            job = create_job_run(
                db,
                task_name="system.flaky",
                payload={"fail_until_attempt": 1},
                max_attempts=2,
            )
            db.commit()

        _run_single_job(job.id, redis_client=redis, queue_name="jobs:queue")

        with SessionLocal() as db:
            event_types = [
                event.event_type
                for event in db.query(JobLifecycleEvent)
                .filter(JobLifecycleEvent.job_id == job.id)
                .order_by(JobLifecycleEvent.created_at.asc())
                .all()
            ]

    assert event_types == ["queued", "running", "failed", "retry_scheduled"]
    assert _scheduled_queue_name("jobs:queue") in redis.zset


def test_run_single_job_emits_dead_letter_event(app, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.db.session import SessionLocal

    settings = get_settings()
    settings.jobs_dead_letter_queue_name = "jobs:dead-letter"
    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)

    redis = FakeRedis()
    with TestClient(app):
        with SessionLocal() as db:
            job = create_job_run(
                db,
                task_name="system.fail",
                payload={"reason": "boom"},
                max_attempts=1,
            )
            db.commit()

        _run_single_job(job.id, redis_client=redis, queue_name="jobs:queue")

        with SessionLocal() as db:
            event_types = [
                event.event_type
                for event in db.query(JobLifecycleEvent)
                .filter(JobLifecycleEvent.job_id == job.id)
                .order_by(JobLifecycleEvent.created_at.asc())
                .all()
            ]

    assert event_types == ["queued", "running", "failed", "dead_letter"]
    assert ("jobs:dead-letter", job.id) in redis.left

