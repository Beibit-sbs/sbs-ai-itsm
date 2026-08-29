from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.models.job_event_consumer_delivery import JobEventConsumerDelivery
from app.models.job_lifecycle_event import JobLifecycleEvent
from app.models.job_queue_outbox import JobQueueOutbox
from app.models.job_run import JobRun
from app.services.jobs import create_job_run


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth_headers(token: str, correlation_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if correlation_id is not None:
        headers["X-Request-ID"] = correlation_id
    return headers


def test_correlation_id_middleware_generates_header(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_correlation_id_middleware_echoes_incoming_header(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"X-Request-ID": "smoke-1234"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "smoke-1234"


def test_unsafe_correlation_id_is_replaced(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"X-Request-ID": "x" * 500})
    request_id = response.headers["X-Request-ID"]
    assert request_id != "x" * 500
    assert len(request_id) == 36


def test_jobs_list_requires_authentication(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/jobs")
    assert response.status_code == 401


def test_jobs_list_denies_requester(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "requester@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/jobs", headers=_auth_headers(token))
    assert response.status_code == 403


def test_jobs_task_registry_exposes_builtins(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get("/api/v1/jobs/tasks", headers=_auth_headers(token))
    assert response.status_code == 200
    names = response.json()
    assert "system.echo" in names
    assert "system.sleep" in names
    assert "system.fail" in names
    assert "system.flaky" in names


def test_jobs_runtime_reports_inline_mode_by_default(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get("/api/v1/jobs/runtime", headers=_auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["executor_mode"] == "inline"
    assert body["worker_required"] is False
    assert body["queue_name"]
    assert body["dead_letter_queue_name"]
    assert body["event_stream_name"]
    assert body["retry_base_seconds"] > 0
    assert body["retry_max_seconds"] > 0


def test_enqueue_success_records_result_and_correlation(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token, correlation_id="test-corr-1"),
            json={"task_name": "system.echo", "payload": {"hello": "world"}},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["task_name"] == "system.echo"
    assert body["status"] == "success"
    assert body["result"] == {"echoed": {"hello": "world"}, "task_name": "system.echo", "attempt": 1}
    assert body["correlation_id"] == "test-corr-1"
    assert body["attempts"] == 1
    assert body["duration_ms"] is not None


def test_enqueue_failure_records_error_message(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.fail", "payload": {"reason": "boom"}},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"] is not None
    assert "boom" in body["error_message"]


def test_enqueue_redis_mode_creates_queued_job_without_inline_execution(app, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.db.session import SessionLocal

    settings = get_settings()
    settings.jobs_executor_mode = "redis"
    settings.jobs_queue_name = "jobs:test"

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.echo", "payload": {"hello": "queue"}},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["attempts"] == 0
    assert body["max_attempts"] == 1
    assert body["result"] is None
    with SessionLocal() as db:
        outbox_rows = db.query(JobQueueOutbox).filter(JobQueueOutbox.job_id == body["id"]).all()
    assert len(outbox_rows) == 1
    assert outbox_rows[0].queue_name == "jobs:test"
    assert outbox_rows[0].published_at is None


def test_enqueue_allows_custom_max_attempts(app, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.db.session import SessionLocal

    settings = get_settings()
    settings.jobs_executor_mode = "redis"
    settings.jobs_queue_name = "jobs:test"

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.flaky", "payload": {"fail_until_attempt": 1}, "max_attempts": 3},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["max_attempts"] == 3
    with SessionLocal() as db:
        outbox_rows = db.query(JobQueueOutbox).filter(JobQueueOutbox.job_id == body["id"]).all()
    assert len(outbox_rows) == 1


def test_enqueue_unknown_task_returns_400(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "does.not.exist"},
        )
    assert response.status_code == 400


def test_non_root_cannot_enqueue(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.echo"},
        )
    assert response.status_code == 403


def test_admin_can_read_jobs(app) -> None:
    with TestClient(app) as client:
        root_token = _login(client, "root@sbs.local", "Root!2026")
        client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(root_token),
            json={"task_name": "system.echo", "payload": {}},
        )
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/jobs?limit=5", headers=_auth_headers(admin_token))
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert all("task_name" in item and "status" in item for item in payload)


def test_job_summary_shape(app) -> None:
    with TestClient(app) as client:
        root_token = _login(client, "root@sbs.local", "Root!2026")
        client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(root_token),
            json={"task_name": "system.echo", "payload": {"a": 1}},
        )
        response = client.get("/api/v1/jobs/summary", headers=_auth_headers(root_token))
    assert response.status_code == 200
    data = response.json()
    for key in ("total", "queued", "running", "success", "failed", "dead_letter"):
        assert key in data
    assert data["total"] >= 1
    assert data["success"] >= 1


def test_dead_letter_acknowledgement_preserves_history_and_clears_all_occurrences(
    app,
    monkeypatch,
) -> None:
    from app.services import jobs as jobs_service
    from app.db.session import SessionLocal
    from app.models.audit_log import AuditLog

    class FakeRedis:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, str]] = []
            self.closed = False

        def lrem(self, queue_name: str, count: int, job_id: str) -> int:
            self.calls.append((queue_name, count, job_id))
            return 2

        def close(self) -> None:
            self.closed = True

    fake_redis = FakeRedis()
    monkeypatch.setattr(
        jobs_service.Redis,
        "from_url",
        lambda *_args, **_kwargs: fake_redis,
    )

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        with SessionLocal() as db:
            job = create_job_run(
                db,
                task_name="system.fail",
                payload={"reason": "acceptance"},
            )
            job.status = "dead_letter"
            db.commit()
            job_id = job.id
        response = client.post(
            f"/api/v1/jobs/{job_id}/dead-letter/acknowledge",
            headers=_auth_headers(token),
            json={
                "resolution_code": "acceptance_test",
                "reason": "Expected failure-path acceptance evidence",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "job_id": job_id,
        "status": "dead_letter",
        "removed_occurrences": 2,
    }
    assert fake_redis.calls == [("jobs:dead-letter", 0, job_id)]
    assert fake_redis.closed is True
    with SessionLocal() as db:
        preserved = db.get(JobRun, job_id)
        audit = db.query(AuditLog).filter(
            AuditLog.action == "job.dead_letter_acknowledged",
            AuditLog.entity_id == job_id,
        ).one()
    assert preserved is not None and preserved.status == "dead_letter"
    assert audit.actor_email == "root@sbs.local"


def test_jobs_outbox_summary_shape(app) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    settings.jobs_executor_mode = "redis"

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.echo", "payload": {"x": 1}},
        )
        response = client.get("/api/v1/jobs/outbox-summary", headers=_auth_headers(token))

    assert response.status_code == 200
    data = response.json()
    for key in ("total", "pending", "published", "with_failures"):
        assert key in data


def test_jobs_outbox_diagnostics_shape(app) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    settings.jobs_executor_mode = "redis"

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.echo", "payload": {"x": 1}},
        )
        response = client.get("/api/v1/jobs/outbox-diagnostics", headers=_auth_headers(token))

    assert response.status_code == 200
    data = response.json()
    for key in (
        "total",
        "pending",
        "published",
        "with_failures",
        "locked",
        "stale_locks",
        "dedup_skips",
        "publish_failure_rate_pct",
        "pending_alert_threshold",
        "failure_alert_threshold",
        "stale_lock_alert_threshold",
        "status",
        "recommended_actions",
    ):
        assert key in data


def test_jobs_outbox_diagnostics_reports_threshold_breaches(app) -> None:
    from app.core.config import get_settings
    from app.db.session import SessionLocal

    settings = get_settings()
    settings.jobs_executor_mode = "redis"
    settings.jobs_queue_name = "jobs:test"

    now = datetime.now(UTC)

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")

        with SessionLocal() as db:
            rows = []
            for index in range(5):
                rows.append(
                    JobQueueOutbox(
                        id=f"outbox-{index}",
                        job_id=f"job-{index}",
                        queue_name="jobs:test",
                        dedup_key=f"jobs:test:job-{index}",
                        published_at=None,
                        publish_attempted_at=now,
                        lock_owner="worker-1" if index == 0 else None,
                        lock_expires_at=now - timedelta(minutes=1) if index == 0 else None,
                        failed_attempts=1 if index in (0, 1) else 0,
                        last_error="dedup_skip_already_published" if index == 2 else None,
                    )
                )
            db.add_all(rows)
            db.commit()

        response = client.get("/api/v1/jobs/outbox-diagnostics", headers=_auth_headers(token))

    assert response.status_code == 200
    data = response.json()
    assert data["pending"] == 5
    assert data["with_failures"] == 2
    assert data["stale_locks"] == 1
    assert data["dedup_skips"] == 1
    assert data["status"] == "critical"
    assert data["publish_failure_rate_pct"] == 40.0
    assert data["recommended_actions"]


def test_job_event_bus_summary_shape(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.echo", "payload": {"x": 1}},
        )
        response = client.get("/api/v1/jobs/event-bus-summary", headers=_auth_headers(token))

    assert response.status_code == 200
    data = response.json()
    for key in ("stream_name", "total", "pending", "published", "with_failures", "locked", "stale_locks", "failure_rate_pct"):
        assert key in data


def test_job_event_consumer_summary_shape(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get("/api/v1/jobs/event-consumer-summary", headers=_auth_headers(token))

    assert response.status_code == 200
    data = response.json()
    for key in ("consumer_name", "stream_name", "total", "pending", "delivered", "failed"):
        assert key in data


def test_job_event_consumer_summary_supports_automation_consumer(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get(
            "/api/v1/jobs/event-consumer-summary?consumer_name=automation-consumer",
            headers=_auth_headers(token),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["consumer_name"] == "automation-consumer"


def test_job_event_consumer_summary_rejects_unknown_consumer(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get(
            "/api/v1/jobs/event-consumer-summary?consumer_name=unknown-consumer",
            headers=_auth_headers(token),
        )

    assert response.status_code == 400


def test_job_event_consumers_diagnostics_shape(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get("/api/v1/jobs/event-consumers-diagnostics", headers=_auth_headers(token))

    assert response.status_code == 200
    data = response.json()
    for key in (
        "stream_name",
        "total_events",
        "consumer_count",
        "overall_status",
        "recovery_actions_24h",
        "autoremediation_actions_24h",
        "governance_execute_actions_24h",
        "governance_compliant_actions_24h",
        "governance_compliance_rate_pct",
        "policy_version",
        "policy_rollouts_24h",
        "emergency_brake_consumers",
        "runbook_executions_24h",
        "runbook_failures_24h",
        "runbook_governance_compliant_actions_24h",
        "runbook_governance_denied_actions_24h",
        "runbook_policy_version",
        "runbook_policy_hash",
        "runbook_policy_rollouts_24h",
        "recent_runbook_executions",
        "recent_runbook_denied_actions",
        "recent_runbook_policy_rollouts",
        "recent_policy_rollouts",
        "recent_recovery_actions",
        "recent_autoremediation_actions",
        "consumers",
    ):
        assert key in data
    assert isinstance(data["consumers"], list)
    assert len(data["consumers"]) == 2
    first = data["consumers"][0]
    for key in (
        "consumer_name",
        "stream_name",
        "total_events",
        "delivery_rows",
        "delivered",
        "pending",
        "failed",
        "retryable_failed",
        "exhausted_failed",
        "unseen_events",
        "lag_events",
        "failure_rate_pct",
        "oldest_undelivered_age_seconds",
        "offset_updated_at",
        "stale_offset",
        "recovery_preview_24h",
        "recovery_execute_24h",
        "autoremediation_24h",
        "governance_compliant_execute_24h",
        "governance_missing_execute_24h",
        "last_recovery_execute_at",
        "last_recovery_execute_actor_email",
        "effective_policy_hash",
        "policy_version",
        "policy_canary_mode",
        "rate_budget_10m_used",
        "rate_budget_10m_limit",
        "rate_budget_1h_used",
        "rate_budget_1h_limit",
        "emergency_brake_active",
        "emergency_brake_reason",
        "runbook_executions_24h",
        "runbook_governance_compliant_24h",
        "runbook_governance_denied_24h",
        "last_runbook_execution_at",
        "last_policy_change_at",
        "last_policy_change_actor_email",
        "status",
        "recommended_actions",
    ):
        assert key in first


def test_job_event_consumer_autoremediation_preview_shape(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get(
            "/api/v1/jobs/event-consumer-autoremediation-preview",
            headers=_auth_headers(token),
        )

    assert response.status_code == 200
    data = response.json()
    for key in (
        "consumer_name",
        "stream_name",
        "requested_limit",
        "suppression_active",
        "suppression_windows_utc",
        "raw_candidates",
        "selected",
        "skipped_by_denylist",
        "effective_policy",
        "items",
    ):
        assert key in data


def test_job_event_consumer_autoremediation_preview_applies_denylist(app) -> None:
    from app.core.config import get_settings
    from app.db.session import SessionLocal

    settings = get_settings()
    settings.jobs_event_consumer_name = "notifications-consumer"
    settings.jobs_event_autoremediation_error_denylist = ["permanent"]
    settings.jobs_event_autoremediation_policy_profiles = {
        "notifications-consumer": {
            "enabled": True,
            "allowed_event_types": ["failed"],
            "min_failed_age_seconds": 0,
            "max_requeued_per_cycle": 20,
            "cooldown_seconds": 0,
            "max_per_hour": 100,
        }
    }

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")

        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"preview": True}, max_attempts=1)
            db.commit()
            event = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == job.id).one()
            event.event_type = "failed"
            event.current_status = "failed"
            db.add(
                JobEventConsumerDelivery(
                    id="preview-denylist-delivery",
                    consumer_name="notifications-consumer",
                    event_id=event.id,
                    stream_name=settings.jobs_event_stream_name,
                    stream_entry_id="15-0",
                    status="failed",
                    attempts=3,
                    last_error="permanent_dependency_failure",
                    delivered_at=None,
                )
            )
            db.commit()

        response = client.get(
            "/api/v1/jobs/event-consumer-autoremediation-preview?consumer_name=notifications-consumer&limit=20",
            headers=_auth_headers(token),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["raw_candidates"] >= 1
    assert data["skipped_by_denylist"] >= 1
    assert data["selected"] == 0


def test_job_event_consumer_autoremediation_policy_runbook_update(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")

        current = client.get(
            "/api/v1/jobs/event-consumer-autoremediation-policy?consumer_name=notifications-consumer",
            headers=_auth_headers(token),
        )
        assert current.status_code == 200, current.text
        current_payload = current.json()

        update = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": current_payload["policy_version"],
                "enabled": True,
                "allowed_event_types": ["failed"],
                "min_failed_age_seconds": 5,
                "max_requeued_per_cycle": 3,
                "cooldown_seconds": 30,
                "max_per_hour": 12,
                "burst_limit_per_10m": 2,
                "canary_mode": True,
                "canary_limit_per_cycle": 1,
                "suppression_windows_utc": ["01:00-02:00"],
                "error_denylist": ["permanent"],
            },
        )
        assert update.status_code == 200, update.text
        updated = update.json()
        assert updated["consumer_name"] == "notifications-consumer"
        assert updated["effective_policy"]["canary_mode"] is True
        assert updated["effective_policy"]["canary_limit_per_cycle"] == 1
        assert updated["suppression_windows_utc"] == ["01:00-02:00"]
        assert updated["error_denylist"] == ["permanent"]
        assert isinstance(updated["emergency_brake_consumers"], list)
        assert updated["policy_version"] == current_payload["policy_version"] + 1
        assert updated["effective_policy_hash"]

        read_back = client.get(
            "/api/v1/jobs/event-consumer-autoremediation-policy?consumer_name=notifications-consumer",
            headers=_auth_headers(token),
        )
        assert read_back.status_code == 200, read_back.text
        payload = read_back.json()
        assert payload["effective_policy"]["canary_mode"] is True
        assert payload["effective_policy"]["burst_limit_per_10m"] == 2
        assert payload["policy_version"] == updated["policy_version"]
        assert payload["effective_policy_hash"]


def test_job_event_consumer_autoremediation_policy_rejects_stale_version(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        current = client.get(
            "/api/v1/jobs/event-consumer-autoremediation-policy?consumer_name=notifications-consumer",
            headers=_auth_headers(token),
        )
        assert current.status_code == 200, current.text
        version = int(current.json()["policy_version"])

        first = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": version,
                "enabled": True,
            },
        )
        assert first.status_code == 200, first.text

        stale = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": version,
                "enabled": False,
            },
        )
        assert stale.status_code == 409, stale.text


def test_job_event_consumer_runbook_policy_update_and_rejects_stale_version(app) -> None:
    from app.core.config import get_settings

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")

        current = client.get(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
        )
        assert current.status_code == 200, current.text
        current_payload = current.json()
        version = int(current_payload["policy_version"])

        update = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": version,
                "allowed_codes": ["jobs.consumer.repeated_failures_requeue"],
                "denied_codes": ["jobs.consumer.lag_spike_triage"],
                "high_impact_codes": ["jobs.consumer.repeated_failures_requeue"],
                "cooldown_seconds_map": {"jobs.consumer.repeated_failures_requeue": 300},
                "require_change_ticket": True,
                "dual_control_required": True,
            },
        )
        assert update.status_code == 200, update.text
        updated = update.json()
        assert updated["policy_version"] == version + 1
        assert updated["policy_hash"]
        assert updated["denied_codes"] == ["jobs.consumer.lag_spike_triage"]
        assert updated["cooldown_seconds_map"]["jobs.consumer.repeated_failures_requeue"] == 300
        assert updated["dual_control_required"] is True

        # Ensure runtime read path reloads from persisted state and not from ad-hoc in-memory changes.
        settings = get_settings()
        settings.jobs_event_runbook_denied_codes = []

        read_back = client.get(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
        )
        assert read_back.status_code == 200, read_back.text
        persisted = read_back.json()
        assert persisted["denied_codes"] == ["jobs.consumer.lag_spike_triage"]
        assert persisted["policy_version"] == updated["policy_version"]

        stale = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": version,
                "allowed_codes": ["jobs.consumer.stale_offset_triage"],
            },
        )
        assert stale.status_code == 409, stale.text


def test_job_event_consumer_autoremediation_brake_reset(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        current = client.get(
            "/api/v1/jobs/event-consumer-autoremediation-policy?consumer_name=notifications-consumer",
            headers=_auth_headers(token),
        )
        assert current.status_code == 200, current.text
        current_payload = current.json()

        set_brake = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": current_payload["policy_version"],
                "enabled": True,
            },
        )
        assert set_brake.status_code == 200, set_brake.text
        policy_after = client.get(
            "/api/v1/jobs/event-consumer-autoremediation-policy?consumer_name=notifications-consumer",
            headers=_auth_headers(token),
        ).json()

        # Simulate active brake by writing it through policy update payload path.
        with_version = int(policy_after["policy_version"])
        force_brake = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": with_version,
                "enabled": True,
            },
        )
        assert force_brake.status_code == 200, force_brake.text
        latest = client.get(
            "/api/v1/jobs/event-consumer-autoremediation-policy?consumer_name=notifications-consumer",
            headers=_auth_headers(token),
        ).json()

        reset = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-brake-reset",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": latest["policy_version"],
            },
        )
        assert reset.status_code == 200, reset.text
        reset_payload = reset.json()
        assert "notifications-consumer" not in reset_payload["emergency_brake_consumers"]


def test_job_event_consumer_runbook_repeated_failures_dry_run_and_execute(app) -> None:
    from app.db.session import SessionLocal
    from app.core.config import get_settings

    settings = get_settings()

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        current_policy = client.get("/api/v1/jobs/event-consumer-runbook-policy", headers=_auth_headers(token))
        assert current_policy.status_code == 200, current_policy.text
        current_version = int(current_policy.json()["policy_version"])
        configured_policy = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": current_version,
                "high_impact_codes": ["jobs.consumer.repeated_failures_requeue"],
                "require_change_ticket": True,
                "dual_control_required": False,
                "allowed_codes": [],
                "denied_codes": [],
                "cooldown_seconds_map": {},
            },
        )
        assert configured_policy.status_code == 200, configured_policy.text

        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"runbook": True}, max_attempts=1)
            db.commit()
            event = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == job.id).one()
            db.add(
                JobEventConsumerDelivery(
                    id="runbook-failure-delivery",
                    consumer_name="notifications-consumer",
                    event_id=event.id,
                    stream_name=settings.jobs_event_stream_name,
                    stream_entry_id="16-0",
                    status="failed",
                    attempts=2,
                    last_error="boom",
                    delivered_at=None,
                )
            )
            db.commit()

        dry_run = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.repeated_failures_requeue",
                "dry_run": True,
                "limit": 10,
            },
        )
        assert dry_run.status_code == 200, dry_run.text
        dry_payload = dry_run.json()
        assert dry_payload["status"] == "dry_run"
        assert dry_payload["result"]["selected"] >= 1

        denied = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.repeated_failures_requeue",
                "dry_run": False,
                "limit": 10,
            },
        )
        assert denied.status_code == 400

        execute = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers={**_auth_headers(token), "X-Runbook-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.repeated_failures_requeue",
                "dry_run": False,
                "limit": 10,
                "reason_code": "manual_operator_intervention",
                "change_ticket_ref": "CHG-RUNBOOK-1001",
            },
        )
        assert execute.status_code == 200, execute.text
        payload = execute.json()
        assert payload["status"] == "success"
        assert payload["result"]["requeued"] >= 1

        diag = client.get("/api/v1/jobs/event-consumers-diagnostics", headers=_auth_headers(token))
        assert diag.status_code == 200, diag.text
        diag_payload = diag.json()
        assert diag_payload["runbook_executions_24h"] >= 2
        assert diag_payload["runbook_governance_compliant_actions_24h"] >= 1


def test_job_event_consumer_runbook_governance_validation_and_denied_feed(app) -> None:
    from app.db.session import SessionLocal
    from app.core.config import get_settings

    settings = get_settings()

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        current_policy = client.get("/api/v1/jobs/event-consumer-runbook-policy", headers=_auth_headers(token))
        assert current_policy.status_code == 200, current_policy.text
        current_version = int(current_policy.json()["policy_version"])
        configured_policy = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": current_version,
                "high_impact_codes": ["jobs.consumer.repeated_failures_requeue"],
                "require_change_ticket": True,
                "dual_control_required": True,
                "allowed_codes": [],
                "denied_codes": [],
                "cooldown_seconds_map": {},
            },
        )
        assert configured_policy.status_code == 200, configured_policy.text

        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"runbook-governance": True}, max_attempts=1)
            db.commit()
            event = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == job.id).one()
            db.add(
                JobEventConsumerDelivery(
                    id="runbook-governance-failure-delivery",
                    consumer_name="notifications-consumer",
                    event_id=event.id,
                    stream_name=settings.jobs_event_stream_name,
                    stream_entry_id="18-0",
                    status="failed",
                    attempts=2,
                    last_error="boom",
                    delivered_at=None,
                )
            )
            db.commit()

        missing_reason = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers={**_auth_headers(token), "X-Runbook-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.repeated_failures_requeue",
                "dry_run": False,
                "limit": 10,
                "change_ticket_ref": "CHG-RUNBOOK-2001",
            },
        )
        assert missing_reason.status_code == 400, missing_reason.text

        missing_approver = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers={**_auth_headers(token), "X-Runbook-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.repeated_failures_requeue",
                "dry_run": False,
                "limit": 10,
                "reason_code": "bugfix_rollout",
                "change_ticket_ref": "CHG-RUNBOOK-2002",
            },
        )
        assert missing_approver.status_code == 400, missing_approver.text

        same_actor_approver = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers={**_auth_headers(token), "X-Runbook-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.repeated_failures_requeue",
                "dry_run": False,
                "limit": 10,
                "reason_code": "bugfix_rollout",
                "change_ticket_ref": "CHG-RUNBOOK-2003",
                "approved_by_email": "root@sbs.local",
            },
        )
        assert same_actor_approver.status_code == 400, same_actor_approver.text

        execute = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers={**_auth_headers(token), "X-Runbook-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.repeated_failures_requeue",
                "dry_run": False,
                "limit": 10,
                "reason_code": "bugfix_rollout",
                "change_ticket_ref": "CHG-RUNBOOK-2004",
                "approved_by_email": "approver@sbs.local",
            },
        )
        assert execute.status_code == 200, execute.text

        diag = client.get("/api/v1/jobs/event-consumers-diagnostics", headers=_auth_headers(token))
        assert diag.status_code == 200, diag.text
        diag_payload = diag.json()
        assert diag_payload["runbook_governance_compliant_actions_24h"] >= 1
        assert diag_payload["runbook_governance_denied_actions_24h"] >= 3
        assert len(diag_payload["recent_runbook_denied_actions"]) >= 1


def test_job_event_consumer_runbook_policy_deny_and_cooldown(app) -> None:
    from app.db.session import SessionLocal
    from app.core.config import get_settings

    settings = get_settings()

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        current_policy = client.get("/api/v1/jobs/event-consumer-runbook-policy", headers=_auth_headers(token))
        assert current_policy.status_code == 200, current_policy.text
        current_version = int(current_policy.json()["policy_version"])
        configured_policy = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": current_version,
                "high_impact_codes": ["jobs.consumer.repeated_failures_requeue"],
                "require_change_ticket": True,
                "dual_control_required": False,
                "allowed_codes": ["jobs.consumer.repeated_failures_requeue"],
                "denied_codes": ["jobs.consumer.lag_spike_triage"],
                "cooldown_seconds_map": {"jobs.consumer.repeated_failures_requeue": 3600},
            },
        )
        assert configured_policy.status_code == 200, configured_policy.text

        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"runbook-cooldown": True}, max_attempts=1)
            db.commit()
            event = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == job.id).one()
            db.add(
                JobEventConsumerDelivery(
                    id="runbook-policy-failure-delivery",
                    consumer_name="notifications-consumer",
                    event_id=event.id,
                    stream_name=settings.jobs_event_stream_name,
                    stream_entry_id="19-0",
                    status="failed",
                    attempts=2,
                    last_error="boom",
                    delivered_at=None,
                )
            )
            db.commit()

        deny_by_policy = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.lag_spike_triage",
                "dry_run": True,
            },
        )
        assert deny_by_policy.status_code == 403, deny_by_policy.text

        first_execute = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers={**_auth_headers(token), "X-Runbook-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.repeated_failures_requeue",
                "dry_run": False,
                "limit": 10,
                "reason_code": "manual_operator_intervention",
                "change_ticket_ref": "CHG-RUNBOOK-3001",
            },
        )
        assert first_execute.status_code == 200, first_execute.text

        cooldown_blocked = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers={**_auth_headers(token), "X-Runbook-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.repeated_failures_requeue",
                "dry_run": False,
                "limit": 10,
                "reason_code": "manual_operator_intervention",
                "change_ticket_ref": "CHG-RUNBOOK-3002",
            },
        )
        assert cooldown_blocked.status_code == 429, cooldown_blocked.text


def test_job_event_consumer_runbook_policy_validate_only_does_not_persist(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        current_policy = client.get("/api/v1/jobs/event-consumer-runbook-policy", headers=_auth_headers(token))
        assert current_policy.status_code == 200, current_policy.text
        current_version = int(current_policy.json()["policy_version"])
        current_hash = current_policy.json()["policy_hash"]

        validate = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": current_version,
                "allowed_codes": ["jobs.consumer.emergency_brake_reset"],
                "validate_only": True,
            },
        )
        assert validate.status_code == 200, validate.text
        result = validate.json()
        assert result["validation_result"] is not None
        assert result["validation_result"]["valid"] is True
        assert result["validation_result"]["message"]
        assert result["policy_version"] == current_version
        assert result["policy_hash"] == current_hash

        check_still_old = client.get(
            "/api/v1/jobs/event-consumer-runbook-policy", headers=_auth_headers(token)
        )
        assert check_still_old.status_code == 200, check_still_old.text
        assert check_still_old.json()["policy_version"] == current_version
        assert check_still_old.json()["policy_hash"] == current_hash


def test_job_event_consumer_runbook_policy_rollback_restores_previous_version(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")

        current = client.get(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
        )
        assert current.status_code == 200, current.text
        v1_policy = current.json()
        v1_version = v1_policy["policy_version"]

        update1 = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": v1_version,
                "allowed_codes": ["jobs.consumer.repeated_failures_requeue"],
                "denied_codes": ["jobs.consumer.lag_spike_triage"],
            },
        )
        assert update1.status_code == 200, update1.text
        v2_policy = update1.json()
        v2_version = v2_policy["policy_version"]
        assert v2_version == v1_version + 1

        update2 = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": v2_version,
                "allowed_codes": ["jobs.consumer.stale_offset_triage"],
                "denied_codes": [],
            },
        )
        assert update2.status_code == 200, update2.text
        v3_policy = update2.json()
        v3_version = v3_policy["policy_version"]
        assert v3_version == v2_version + 1

        rollback = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy/rollback",
            headers=_auth_headers(token),
            json={"previous_version": v1_version},
        )
        assert rollback.status_code == 200, rollback.text
        rollback_result = rollback.json()
        assert rollback_result["rolled_back_from_version"] == v3_version
        assert rollback_result["rolled_back_to_version"] == v1_version
        assert rollback_result["policy_version"] == v3_version + 1

        verify = client.get(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
        )
        assert verify.status_code == 200, verify.text
        restored = verify.json()
        assert restored["policy_version"] == v3_version + 1
        assert restored["allowed_codes"] == v1_policy["allowed_codes"]
        assert restored["denied_codes"] == v1_policy["denied_codes"]


def test_job_event_consumer_runbook_policy_rollback_rejects_invalid_version(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")

        current = client.get(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
        )
        assert current.status_code == 200, current.text
        current_version = int(current.json()["policy_version"])

        update_v2 = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": current_version,
                "allowed_codes": ["jobs.consumer.repeated_failures_requeue"],
            },
        )
        assert update_v2.status_code == 200, update_v2.text
        v2_version = int(update_v2.json()["policy_version"])

        update_v3 = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": v2_version,
                "allowed_codes": ["jobs.consumer.lag_spike_triage"],
            },
        )
        assert update_v3.status_code == 200, update_v3.text
        v3_version = int(update_v3.json()["policy_version"])

        future_version = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy/rollback",
            headers=_auth_headers(token),
            json={"previous_version": v3_version + 100},
        )
        assert future_version.status_code == 400, future_version.text


def test_job_event_consumers_diagnostics_includes_runbook_policy_decision_trace(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")

        set_policy = client.post(
            "/api/v1/jobs/event-consumer-runbook-policy",
            headers=_auth_headers(token),
            json={
                "expected_version": 1,
                "allowed_codes": ["jobs.consumer.repeated_failures_requeue"],
                "high_impact_codes": ["jobs.consumer.repeated_failures_requeue"],
                "require_change_ticket": True,
                "dual_control_required": True,
            },
        )
        assert set_policy.status_code == 200, set_policy.text

        diag = client.get(
            "/api/v1/jobs/event-consumers-diagnostics",
            headers=_auth_headers(token),
        )
        assert diag.status_code == 200, diag.text
        data = diag.json()

        consumer_diagnostics = [c for c in data["consumers"] if c["consumer_name"] == "notifications-consumer"]
        assert len(consumer_diagnostics) > 0
        consumer = consumer_diagnostics[0]
        assert consumer.get("runbook_policy_decision_trace") is not None
        trace = consumer["runbook_policy_decision_trace"]
        assert "allowlist" in trace
        assert "jobs.consumer.repeated_failures_requeue" in trace
        assert "high-impact" in trace
        assert "require-change-ticket" in trace
        assert "require-dual-control" in trace


def test_job_event_consumer_runbook_guardrail_blocked_when_no_lag(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/jobs/event-consumer-runbook",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "runbook_code": "jobs.consumer.lag_spike_triage",
                "dry_run": True,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["guardrail_blocked"] is True
    assert payload["status"] == "guardrail_blocked"


def test_event_consumer_recovery_dry_run_and_confirmed_execute(app) -> None:
    from app.db.session import SessionLocal
    from app.core.config import get_settings

    settings = get_settings()
    settings.jobs_event_recovery_cooldown_seconds = 0
    settings.jobs_event_recovery_max_exec_per_hour = 100

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"recover": True}, max_attempts=1)
            db.commit()
            event = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == job.id).one()
            delivery_notifications = JobEventConsumerDelivery(
                id="recovery-delivery-notif",
                consumer_name="notifications-consumer",
                event_id=event.id,
                stream_name="jobs:lifecycle",
                stream_entry_id="10-0",
                status="failed",
                attempts=3,
                last_error="boom",
                delivered_at=None,
            )
            delivery_automation = JobEventConsumerDelivery(
                id="recovery-delivery-auto",
                consumer_name="automation-consumer",
                event_id=event.id,
                stream_name="jobs:lifecycle",
                stream_entry_id="10-0",
                status="failed",
                attempts=2,
                last_error="auto-boom",
                delivered_at=None,
            )
            db.add(delivery_notifications)
            db.add(delivery_automation)
            db.commit()

        dry_run = client.post(
            "/api/v1/jobs/event-consumer-recovery",
            headers=_auth_headers(token),
            json={"consumer_name": "notifications-consumer", "dry_run": True, "limit": 10},
        )
        assert dry_run.status_code == 200, dry_run.text
        dry_payload = dry_run.json()
        assert dry_payload["selected"] >= 1
        assert dry_payload["requeued"] == 0

        denied = client.post(
            "/api/v1/jobs/event-consumer-recovery",
            headers=_auth_headers(token),
            json={"consumer_name": "notifications-consumer", "dry_run": False, "limit": 10},
        )
        assert denied.status_code == 400

        execute = client.post(
            "/api/v1/jobs/event-consumer-recovery",
            headers={**_auth_headers(token), "X-Recovery-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "dry_run": False,
                "limit": 10,
                "reason_code": "manual_operator_intervention",
                "change_ticket_ref": "CHG-1001",
            },
        )
        assert execute.status_code == 200, execute.text
        payload = execute.json()
        assert payload["requeued"] >= 1

        execute_repeat = client.post(
            "/api/v1/jobs/event-consumer-recovery",
            headers={**_auth_headers(token), "X-Recovery-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "dry_run": False,
                "limit": 10,
                "reason_code": "manual_operator_intervention",
                "change_ticket_ref": "CHG-1002",
            },
        )
        assert execute_repeat.status_code == 200, execute_repeat.text

        diag = client.get("/api/v1/jobs/event-consumers-diagnostics", headers=_auth_headers(token))
        assert diag.status_code == 200, diag.text
        diag_body = diag.json()
        assert diag_body["recovery_actions_24h"] >= 2

        with SessionLocal() as db:
            notif = db.get(JobEventConsumerDelivery, "recovery-delivery-notif")
            auto = db.get(JobEventConsumerDelivery, "recovery-delivery-auto")
            assert notif is not None
            assert auto is not None
            assert notif.status == "failed"
            assert notif.attempts == 0
            assert notif.last_error == "recovery_requeued_by_operator"
            assert auto.status == "failed"
            assert auto.attempts == 2


def test_event_consumer_recovery_cooldown_guard(app) -> None:
    from app.db.session import SessionLocal
    from app.core.config import get_settings

    settings = get_settings()
    settings.jobs_event_recovery_cooldown_seconds = 3600
    settings.jobs_event_recovery_max_exec_per_hour = 100

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"cooldown": True}, max_attempts=1)
            db.commit()
            event = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == job.id).one()
            db.add(
                JobEventConsumerDelivery(
                    id="recovery-cooldown-delivery",
                    consumer_name="notifications-consumer",
                    event_id=event.id,
                    stream_name="jobs:lifecycle",
                    stream_entry_id="11-0",
                    status="failed",
                    attempts=1,
                    last_error="boom",
                    delivered_at=None,
                )
            )
            db.commit()

        first = client.post(
            "/api/v1/jobs/event-consumer-recovery",
            headers={**_auth_headers(token), "X-Recovery-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "dry_run": False,
                "limit": 10,
                "reason_code": "downstream_outage",
                "change_ticket_ref": "CHG-2001",
            },
        )
        assert first.status_code == 200, first.text

        second = client.post(
            "/api/v1/jobs/event-consumer-recovery",
            headers={**_auth_headers(token), "X-Recovery-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "dry_run": False,
                "limit": 10,
                "reason_code": "downstream_outage",
                "change_ticket_ref": "CHG-2002",
            },
        )
        assert second.status_code == 429, second.text


def test_event_consumer_recovery_governance_validation_and_dual_control(app) -> None:
    from app.db.session import SessionLocal
    from app.core.config import get_settings

    settings = get_settings()
    settings.jobs_event_recovery_cooldown_seconds = 0
    settings.jobs_event_recovery_max_exec_per_hour = 100
    settings.jobs_event_recovery_require_change_ticket = True
    settings.jobs_event_recovery_dual_control_required = True

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        with SessionLocal() as db:
            job = create_job_run(db, task_name="system.echo", payload={"gov": True}, max_attempts=1)
            db.commit()
            event = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == job.id).one()
            db.add(
                JobEventConsumerDelivery(
                    id="recovery-governance-delivery",
                    consumer_name="notifications-consumer",
                    event_id=event.id,
                    stream_name="jobs:lifecycle",
                    stream_entry_id="12-0",
                    status="failed",
                    attempts=1,
                    last_error="boom",
                    delivered_at=None,
                )
            )
            db.commit()

        missing_reason = client.post(
            "/api/v1/jobs/event-consumer-recovery",
            headers={**_auth_headers(token), "X-Recovery-Confirm": "CONFIRM"},
            json={"consumer_name": "notifications-consumer", "dry_run": False, "limit": 10, "change_ticket_ref": "CHG-3001"},
        )
        assert missing_reason.status_code == 400

        missing_approver = client.post(
            "/api/v1/jobs/event-consumer-recovery",
            headers={**_auth_headers(token), "X-Recovery-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "dry_run": False,
                "limit": 10,
                "reason_code": "bugfix_rollout",
                "change_ticket_ref": "CHG-3002",
            },
        )
        assert missing_approver.status_code == 400

        same_actor_approver = client.post(
            "/api/v1/jobs/event-consumer-recovery",
            headers={**_auth_headers(token), "X-Recovery-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "dry_run": False,
                "limit": 10,
                "reason_code": "bugfix_rollout",
                "change_ticket_ref": "CHG-3003",
                "approved_by_email": "root@sbs.local",
            },
        )
        assert same_actor_approver.status_code == 400

        ok = client.post(
            "/api/v1/jobs/event-consumer-recovery",
            headers={**_auth_headers(token), "X-Recovery-Confirm": "CONFIRM"},
            json={
                "consumer_name": "notifications-consumer",
                "dry_run": False,
                "limit": 10,
                "reason_code": "bugfix_rollout",
                "change_ticket_ref": "CHG-3004",
                "approved_by_email": "admin@sbs.local",
            },
        )
        assert ok.status_code == 200, ok.text


def test_create_outbox_entry_is_idempotent_by_job_and_queue(app) -> None:
    from app.db.session import SessionLocal
    from app.services.jobs import create_outbox_entry

    with TestClient(app):
        with SessionLocal() as db:
            first = create_outbox_entry(db, job_id="job-x", queue_name="jobs:queue")
            second = create_outbox_entry(db, job_id="job-x", queue_name="jobs:queue")
            replay_first = create_outbox_entry(
                db,
                job_id="job-x",
                queue_name="jobs:queue",
                operation_id="replay-event-1",
            )
            replay_second = create_outbox_entry(
                db,
                job_id="job-x",
                queue_name="jobs:queue",
                operation_id="replay-event-1",
            )
            db.commit()

    assert first.id == second.id
    assert replay_first.id == replay_second.id
    assert replay_first.id != first.id
    assert replay_first.dedup_key != first.dedup_key


def test_development_schema_backfills_job_lifecycle_sequence(tmp_path) -> None:
    from sqlalchemy import create_engine, text

    from app.services.jobs.schema import ensure_jobs_schema

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-jobs.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE job_lifecycle_events (
                    id VARCHAR(36) PRIMARY KEY,
                    job_id VARCHAR(36) NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO job_lifecycle_events (id, job_id, created_at)
                VALUES
                    ('event-b', 'job-1', '2026-08-14 12:00:00'),
                    ('event-a', 'job-1', '2026-08-14 12:00:00'),
                    ('event-c', 'job-2', '2026-08-14 12:00:00')
                """
            )
        )

    ensure_jobs_schema(engine)
    ensure_jobs_schema(engine)

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, job_id, sequence FROM job_lifecycle_events ORDER BY job_id, sequence")
        ).all()
    assert rows == [
        ("event-a", "job-1", 1),
        ("event-b", "job-1", 2),
        ("event-c", "job-2", 1),
    ]


def test_get_job_by_id_returns_detail(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        created = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.echo", "payload": {"k": "v"}},
        ).json()
        response = client.get(f"/api/v1/jobs/{created['id']}", headers=_auth_headers(token))
    assert response.status_code == 200
    detail = response.json()
    assert detail["id"] == created["id"]
    assert detail["result"] == {"echoed": {"k": "v"}, "task_name": "system.echo", "attempt": 1}


def test_get_job_events_returns_lifecycle_sequence(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        created = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token, correlation_id="evt-seq-1"),
            json={"task_name": "system.echo", "payload": {"k": "v"}},
        ).json()
        response = client.get(f"/api/v1/jobs/{created['id']}/events", headers=_auth_headers(token))

    assert response.status_code == 200
    events = response.json()
    assert [event["event_type"] for event in events] == ["queued", "running", "success"]
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert all(event["job_id"] == created["id"] for event in events)
    assert all(event["correlation_id"] == "evt-seq-1" for event in events)


def test_get_job_unknown_id_returns_404(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000", headers=_auth_headers(token))
    assert response.status_code == 404


def test_replay_dead_letter_job_requeues_in_redis_mode(app, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.db.session import SessionLocal

    settings = get_settings()
    settings.jobs_executor_mode = "redis"
    settings.jobs_queue_name = "jobs:test"

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        created = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.echo", "payload": {"k": "v"}, "max_attempts": 2},
        ).json()

        with SessionLocal() as db:
            job = db.get(JobRun, created["id"])
            assert job is not None
            job.status = "dead_letter"
            job.attempts = 2
            job.error_message = "failed twice"
            db.commit()

        replay = client.post(f"/api/v1/jobs/{created['id']}/replay", headers=_auth_headers(token))

    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["status"] == "queued"
    assert body["attempts"] == 0
    assert body["error_message"] is None
    with SessionLocal() as db:
        outbox_rows = db.query(JobQueueOutbox).filter(JobQueueOutbox.job_id == created["id"]).all()
        replay_events = db.query(JobLifecycleEvent).filter(JobLifecycleEvent.job_id == created["id"]).all()
    assert len(outbox_rows) == 2
    assert len({row.dedup_key for row in outbox_rows}) == 2
    assert outbox_rows[0].published_at is None
    assert outbox_rows[1].published_at is None
    assert replay_events[-1].event_type == "replayed"


def test_replay_rejects_non_dead_letter_job(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        created = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.echo", "payload": {"k": "v"}},
        ).json()
        replay = client.post(f"/api/v1/jobs/{created['id']}/replay", headers=_auth_headers(token))

    assert replay.status_code == 409
