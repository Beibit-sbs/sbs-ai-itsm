from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.models.job_event_consumer_delivery import JobEventConsumerDelivery
from app.models.job_lifecycle_event import JobLifecycleEvent
from app.models.notification import Notification
from app.models.audit_log import AuditLog
from app.services.jobs import create_job_run
from app.workers import jobs_worker
from app.workers.jobs_worker import (
    _consume_event_stream_batch,
    _drain_scheduled_jobs,
    _relay_job_events_batch,
    _run_auto_remediation_cycle,
    _retry_failed_event_consumers_batch,
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
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.set_keys: dict[str, str] = {}
        self.fail_xadd_once = False

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

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.set_keys:
            return False
        self.set_keys[key] = value
        return True

    def delete(self, key: str) -> int:
        if key in self.set_keys:
            del self.set_keys[key]
            return 1
        return 0

    def xadd(self, stream_name: str, payload: dict[str, str]) -> str:
        if self.fail_xadd_once:
            self.fail_xadd_once = False
            raise RuntimeError("simulated stream failure")
        bucket = self.streams.setdefault(stream_name, [])
        stream_id = f"{len(bucket) + 1}-0"
        bucket.append((stream_id, payload))
        return stream_id

    def xread(self, streams: dict[str, str], *, count: int = 100, block: int | None = None):
        del block
        result = []
        for stream_name, last_stream_id in streams.items():
            bucket = self.streams.get(stream_name, [])
            items = [(sid, payload) for sid, payload in bucket if self._stream_id_gt(sid, last_stream_id)]
            if items:
                result.append((stream_name, items[:count]))
        return result

    @staticmethod
    def _stream_id_gt(left: str, right: str) -> bool:
        left_main, left_seq = left.split("-", 1)
        right_main, right_seq = right.split("-", 1)
        if int(left_main) != int(right_main):
            return int(left_main) > int(right_main)
        return int(left_seq) > int(right_seq)


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


def test_relay_job_events_batch_publishes_pending_events(app, monkeypatch) -> None:
    from app.db.session import SessionLocal

    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)
    redis = FakeRedis()

    with TestClient(app):
        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"relay": "ok"})
            db.commit()

        relayed = _relay_job_events_batch(redis, batch_size=100)

        with SessionLocal() as db:
            events = (
                db.query(JobLifecycleEvent)
                .filter(JobLifecycleEvent.job_id == job.id)
                .order_by(JobLifecycleEvent.created_at.asc())
                .all()
            )

    assert relayed == 1
    assert "jobs:lifecycle" in redis.streams
    assert redis.streams["jobs:lifecycle"][0][1]["event_type"] == "queued"
    assert events[0].relay_published_at is not None
    assert events[0].relay_failed_attempts == 0


def test_relay_job_events_batch_retries_after_stream_failure(app, monkeypatch) -> None:
    from app.db.session import SessionLocal

    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)
    redis = FakeRedis()
    redis.fail_xadd_once = True

    with TestClient(app):
        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"relay": "retry"})
            db.commit()

        first_relay = _relay_job_events_batch(redis, batch_size=100)
        second_relay = _relay_job_events_batch(redis, batch_size=100)

        with SessionLocal() as db:
            event = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == job.id).one()

    assert first_relay == 0
    assert second_relay == 1
    assert event.relay_published_at is not None
    assert event.relay_failed_attempts == 1
    assert "jobs:lifecycle" in redis.streams


def test_relay_job_events_batch_marks_event_published_when_dedup_key_exists(app, monkeypatch) -> None:
    from app.db.session import SessionLocal

    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)
    redis = FakeRedis()

    with TestClient(app):
        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"relay": "dedup"})
            db.commit()
            event = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == job.id).one()

        redis.set(f"jobs:event-relay:{event.id}", event.id, nx=True, ex=60)
        relayed = _relay_job_events_batch(redis, batch_size=100)

        with SessionLocal() as db:
            refreshed = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.id == event.id).one()

    assert relayed == 1
    assert redis.streams == {}
    assert refreshed.relay_published_at is not None
    assert refreshed.relay_last_error == "relay_dedup_skip_already_published"


def test_consume_event_stream_batch_creates_notifications(app, monkeypatch) -> None:
    from app.db.session import SessionLocal

    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)
    redis = FakeRedis()

    with TestClient(app):
        with SessionLocal() as db:
            baseline = int(db.query(Notification).filter(Notification.event_type.in_(["jobs.failed", "jobs.dead_letter"])).count())
            job = create_job_run(db, task_name="system.fail", payload={"reason": "boom"}, max_attempts=1)
            db.commit()

        _run_single_job(job.id, redis_client=redis, queue_name="jobs:queue")
        _relay_job_events_batch(redis, batch_size=100)
        consumed = _consume_event_stream_batch(redis, batch_size=100)

        with SessionLocal() as db:
            delivered = (
                db.query(JobEventConsumerDelivery)
                .filter(JobEventConsumerDelivery.status == "delivered")
                .count()
            )
            current = int(db.query(Notification).filter(Notification.event_type.in_(["jobs.failed", "jobs.dead_letter"])).count())

    assert consumed >= 4
    assert delivered >= 4
    assert current >= baseline + 2


def test_retry_failed_event_consumers_batch_recovers_deliveries(app, monkeypatch) -> None:
    from app.db.session import SessionLocal

    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)
    redis = FakeRedis()

    with TestClient(app):
        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"k": "v"}, max_attempts=1)
            db.commit()

        _relay_job_events_batch(redis, batch_size=100)

        original = jobs_worker._create_notification_for_event

        def failing_create_notification(db, event):
            raise RuntimeError("simulated consumer failure")

        monkeypatch.setattr(jobs_worker, "_create_notification_for_event", failing_create_notification)
        _consume_event_stream_batch(redis, batch_size=100)

        with SessionLocal() as db:
            failed_before = (
                db.query(JobEventConsumerDelivery)
                .filter(JobEventConsumerDelivery.status == "failed")
                .count()
            )
        assert failed_before >= 1

        monkeypatch.setattr(jobs_worker, "_create_notification_for_event", original)
        retried = _retry_failed_event_consumers_batch(batch_size=100)

        with SessionLocal() as db:
            failed_after = (
                db.query(JobEventConsumerDelivery)
                .filter(JobEventConsumerDelivery.status == "failed")
                .count()
            )

    assert retried >= 1
    assert failed_after == 0


def test_dual_consumers_process_same_event_stream_independently(app, monkeypatch) -> None:
    from app.db.session import SessionLocal

    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)
    redis = FakeRedis()

    calls: list[str] = []

    def fake_trigger_automation_event(db, *, tenant_id, trigger_type, context, actor_email):
        del db, tenant_id, context, actor_email
        calls.append(trigger_type)
        return []

    monkeypatch.setattr(jobs_worker, "trigger_automation_event", fake_trigger_automation_event)

    with TestClient(app):
        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"dual": True}, max_attempts=1)
            db.commit()

        _relay_job_events_batch(redis, batch_size=100)
        notif_count = _consume_event_stream_batch(redis, consumer_name="notifications-consumer", batch_size=100)
        auto_count = _consume_event_stream_batch(
            redis,
            consumer_name="automation-consumer",
            handler=jobs_worker._process_automation_consumer,
            batch_size=100,
        )

        with SessionLocal() as db:
            notif_deliveries = (
                db.query(JobEventConsumerDelivery)
                .filter(JobEventConsumerDelivery.consumer_name == "notifications-consumer")
                .count()
            )
            auto_deliveries = (
                db.query(JobEventConsumerDelivery)
                .filter(JobEventConsumerDelivery.consumer_name == "automation-consumer")
                .count()
            )

    assert notif_count >= 1
    assert auto_count >= 1
    assert notif_deliveries >= 1
    assert auto_deliveries >= 1
    assert all(item.startswith("job_lifecycle.") for item in calls)


def test_auto_remediation_requeues_exhausted_failed_deliveries(app, monkeypatch) -> None:
    from app.db.session import SessionLocal
    from app.core.config import get_settings

    settings = get_settings()
    settings.jobs_event_consumer_name = "notifications-consumer"
    settings.jobs_event_autoremediation_enabled = True
    settings.jobs_event_autoremediation_consumers = ["notifications-consumer"]
    settings.jobs_event_autoremediation_allowed_event_types = ["failed", "dead_letter"]
    settings.jobs_event_consumer_max_attempts = 3
    settings.jobs_event_autoremediation_min_failed_age_seconds = 0
    settings.jobs_event_autoremediation_max_requeued_per_cycle = 10
    settings.jobs_event_autoremediation_cooldown_seconds = 0
    settings.jobs_event_autoremediation_max_per_hour = 100

    called: list[str] = []

    def _fake_safety(*args, **kwargs):
        return {
            "consumer_name": kwargs["consumer_name"],
            "executed_last_hour": 0,
            "max_per_hour": 100,
            "rate_limit_exceeded": False,
            "cooldown_seconds": 0,
            "cooldown_active": False,
            "retry_after_seconds": 0,
            "last_executed_at": None,
        }

    def _fake_autoremediate(db, **kwargs):
        called.append(str(kwargs["consumer_name"]))
        return {
            "consumer_name": kwargs["consumer_name"],
            "stream_name": kwargs["stream_name"],
            "selected": 1,
            "requeued": 1,
            "items": [
                {
                    "delivery_id": "auto-remediate-delivery",
                    "event_id": "event-1",
                    "event_type": "failed",
                    "attempts_before": 3,
                    "status_before": "failed",
                }
            ],
        }

    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)
    monkeypatch.setattr(jobs_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(jobs_worker, "job_event_consumer_autoremediation_safety_state", _fake_safety)
    monkeypatch.setattr(jobs_worker, "job_event_consumer_autoremediate", _fake_autoremediate)

    with TestClient(app):
        requeued = _run_auto_remediation_cycle(max_per_consumer=10)

        with SessionLocal() as db:
            audit_rows = db.query(AuditLog).filter(AuditLog.action == "jobs.event_consumer_recovery.auto").all()

    assert requeued == 1
    assert called == ["notifications-consumer"]
    assert len(audit_rows) >= 1


def test_auto_remediation_respects_cooldown_guard(app, monkeypatch) -> None:
    from app.db.session import SessionLocal
    from app.core.config import get_settings
    from app.services.audit import log_audit

    settings = get_settings()
    settings.jobs_event_consumer_name = "notifications-consumer"
    settings.jobs_event_autoremediation_enabled = True
    settings.jobs_event_autoremediation_consumers = ["notifications-consumer"]
    settings.jobs_event_autoremediation_allowed_event_types = ["failed"]
    settings.jobs_event_consumer_max_attempts = 3
    settings.jobs_event_autoremediation_min_failed_age_seconds = 0
    settings.jobs_event_autoremediation_max_requeued_per_cycle = 10
    settings.jobs_event_autoremediation_cooldown_seconds = 3600
    settings.jobs_event_autoremediation_max_per_hour = 100

    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)
    monkeypatch.setattr(jobs_worker, "get_settings", lambda: settings)

    with TestClient(app):
        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"auto": "cooldown"}, max_attempts=1)
            db.commit()
            event = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == job.id).one()
            db.add(
                JobEventConsumerDelivery(
                    id="auto-remediate-cooldown",
                    consumer_name="notifications-consumer",
                    event_id=event.id,
                        stream_name=settings.jobs_event_stream_name,
                    stream_entry_id="14-0",
                    status="failed",
                    attempts=3,
                    last_error="exhausted",
                    delivered_at=None,
                )
            )
            log_audit(
                db,
                action="jobs.event_consumer_recovery.auto",
                entity_type="job_event_consumer_delivery",
                entity_id="notifications-consumer",
                actor_email="jobs-worker@sbs.local",
                metadata={"consumer_name": "notifications-consumer", "requeued": 1},
            )
            db.commit()

        requeued = _run_auto_remediation_cycle(max_per_consumer=10)

        with SessionLocal() as db:
            delivery = db.get(JobEventConsumerDelivery, "auto-remediate-cooldown")

    assert requeued == 0
    assert delivery is not None
    assert delivery.attempts == 3


def test_auto_remediation_skips_when_suppression_window_active(app, monkeypatch) -> None:
    from app.db.session import SessionLocal
    from app.core.config import get_settings

    settings = get_settings()
    settings.jobs_event_consumer_name = "notifications-consumer"
    settings.jobs_event_autoremediation_enabled = True
    settings.jobs_event_autoremediation_consumers = ["notifications-consumer"]
    settings.jobs_event_autoremediation_suppression_windows_utc = ["00:00-23:59"]

    called = {"autoremediate": 0}

    def _fake_autoremediate(db, **kwargs):
        del db, kwargs
        called["autoremediate"] += 1
        return {"requeued": 1, "selected": 1, "items": []}

    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)
    monkeypatch.setattr(jobs_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(jobs_worker, "job_event_consumer_autoremediate", _fake_autoremediate)

    with TestClient(app):
        requeued = _run_auto_remediation_cycle(max_per_consumer=10)

    assert requeued == 0
    assert called["autoremediate"] == 0


def test_auto_remediation_uses_policy_profile_overrides(app, monkeypatch) -> None:
    from app.db.session import SessionLocal
    from app.core.config import get_settings

    settings = get_settings()
    settings.jobs_event_consumer_name = "notifications-consumer"
    settings.jobs_event_autoremediation_enabled = True
    settings.jobs_event_autoremediation_consumers = ["notifications-consumer"]
    settings.jobs_event_autoremediation_policy_profiles = {
        "notifications-consumer": {
            "enabled": True,
            "allowed_event_types": ["dead_letter"],
            "min_failed_age_seconds": 999,
            "max_requeued_per_cycle": 2,
            "cooldown_seconds": 7,
            "max_per_hour": 11,
        }
    }

    captured: dict[str, object] = {}

    def _fake_safety(db, **kwargs):
        del db
        captured["cooldown_seconds"] = kwargs["cooldown_seconds"]
        captured["max_per_hour"] = kwargs["max_per_hour"]
        return {
            "consumer_name": kwargs["consumer_name"],
            "executed_last_hour": 0,
            "max_per_hour": kwargs["max_per_hour"],
            "rate_limit_exceeded": False,
            "cooldown_seconds": kwargs["cooldown_seconds"],
            "cooldown_active": False,
            "retry_after_seconds": 0,
            "last_executed_at": None,
        }

    def _fake_autoremediate(db, **kwargs):
        del db
        captured["allowed_event_types"] = kwargs["allowed_event_types"]
        captured["min_failed_age_seconds"] = kwargs["min_failed_age_seconds"]
        captured["limit"] = kwargs["limit"]
        return {
            "consumer_name": kwargs["consumer_name"],
            "stream_name": kwargs["stream_name"],
            "selected": 1,
            "requeued": 1,
            "items": [],
        }

    monkeypatch.setattr(jobs_worker, "SessionLocal", SessionLocal)
    monkeypatch.setattr(jobs_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(jobs_worker, "job_event_consumer_autoremediation_safety_state", _fake_safety)
    monkeypatch.setattr(jobs_worker, "job_event_consumer_autoremediate", _fake_autoremediate)

    with TestClient(app):
        requeued = _run_auto_remediation_cycle(max_per_consumer=None)

    assert requeued == 1
    assert captured["cooldown_seconds"] == 7
    assert captured["max_per_hour"] == 11
    assert captured["allowed_event_types"] == ["dead_letter"]
    assert captured["min_failed_age_seconds"] == 999
    assert captured["limit"] == 2

