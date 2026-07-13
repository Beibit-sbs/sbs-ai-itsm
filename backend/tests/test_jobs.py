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
        "governance_execute_actions_24h",
        "governance_compliant_actions_24h",
        "governance_compliance_rate_pct",
        "recent_recovery_actions",
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
        "governance_compliant_execute_24h",
        "governance_missing_execute_24h",
        "last_recovery_execute_at",
        "last_recovery_execute_actor_email",
        "status",
        "recommended_actions",
    ):
        assert key in first


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
            db.commit()

    assert first.id == second.id


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
    assert len(outbox_rows) == 1
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
