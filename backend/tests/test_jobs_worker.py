from __future__ import annotations

from types import SimpleNamespace

from app.workers.jobs_worker import _retry_delay_seconds


class FakeRedis:
    def __init__(self) -> None:
        self.left: list[tuple[str, str]] = []
        self.right: list[tuple[str, str]] = []

    def lpush(self, key: str, value: str) -> None:
        self.left.append((key, value))

    def rpush(self, key: str, value: str) -> None:
        self.right.append((key, value))

    def incr(self, key: str) -> int:  # pragma: no cover - simple stub compatibility
        return 1

    def expire(self, key: str, seconds: int) -> None:  # pragma: no cover - simple stub compatibility
        return None


def test_retry_delay_seconds_is_exponential_with_cap() -> None:
    assert _retry_delay_seconds(1, base_seconds=0.5, max_seconds=15.0) == 0.5
    assert _retry_delay_seconds(2, base_seconds=0.5, max_seconds=15.0) == 1.0
    assert _retry_delay_seconds(3, base_seconds=0.5, max_seconds=15.0) == 2.0
    assert _retry_delay_seconds(20, base_seconds=0.5, max_seconds=15.0) == 15.0
