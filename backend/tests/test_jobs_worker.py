from __future__ import annotations

import time

from app.workers.jobs_worker import _drain_scheduled_jobs, _retry_delay_seconds, _schedule_retry, _scheduled_queue_name


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
