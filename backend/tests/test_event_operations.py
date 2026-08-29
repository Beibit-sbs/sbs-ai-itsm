from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select


def login(client: TestClient, email: str) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sbs!2026"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["access_token"], body["user"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ingest_headers(source_id: str, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Event-Source": source_id,
    }


def event(
    key: str,
    *,
    fingerprint: str,
    alert_name: str,
    state: str = "FIRING",
    severity: str = "CRITICAL",
    service: str = "payments",
    resource: str = "api-01",
) -> dict:
    return {
        "idempotency_key": key,
        "external_id": f"external-{key}",
        "fingerprint": fingerprint,
        "state": state,
        "severity": severity,
        "summary": f"{alert_name} on {resource}",
        "description": "Monitoring threshold is breached.",
        "service": service,
        "resource": resource,
        "environment": "production",
        "occurred_at": datetime.now(UTC).isoformat(),
        "labels": {"alertname": alert_name, "team": "platform"},
        "annotations": {"runbook": "https://runbooks.example.test/alert"},
    }


def test_event_correlation_incident_resolution_suppression_and_isolation(app) -> None:
    with TestClient(app) as client:
        admin_token, admin = login(client, "admin@sbs.local")
        manager_token, manager = login(client, "manager@sbs.local")
        other_token, _ = login(client, "other.admin@sbs.local")
        requester_token, _ = login(client, "requester@sbs.local")
        denied = client.get(
            "/api/v1/event-operations/summary",
            headers=auth(requester_token),
        )
        assert denied.status_code == 403

        created_source = client.post(
            "/api/v1/event-operations/sources",
            headers=auth(admin_token),
            json={
                "code": "alertmanager-primary",
                "name": "Primary Alertmanager",
                "source_type": "ALERTMANAGER",
            },
        )
        assert created_source.status_code == 201, created_source.text
        source = created_source.json()
        source_token = source["ingest_token"]
        assert source_token.startswith("evt_")

        listed_sources = client.get(
            "/api/v1/event-operations/sources",
            headers=auth(admin_token),
        )
        assert listed_sources.status_code == 200
        assert "ingest_token" not in listed_sources.json()[0]
        assert "token_hash" not in listed_sources.json()[0]

        policy_response = client.post(
            "/api/v1/event-operations/policies",
            headers=auth(admin_token),
            json={
                "name": "Critical platform alerts",
                "description": "Correlate repeated platform alerts.",
                "priority_order": 10,
                "matchers": [
                    {
                        "field": "label.alertname",
                        "operator": "EQUALS",
                        "value": "HighErrorRate",
                    }
                ],
                "group_by": ["service", "resource"],
                "correlation_window_minutes": 60,
                "min_occurrences": 2,
                "incident_mode": "CREATE_UPDATE",
                "fixed_priority": "CRITICAL",
                "category": "NETWORK_INTERNET",
                "title_template": "{service}: {summary}",
                "resolution_action": "RESOLVE",
                "primary_user_id": manager["id"],
                "fallback_user_id": admin["id"],
                "acknowledge_within_minutes": 15,
                "escalate_after_minutes": 15,
            },
        )
        assert policy_response.status_code == 201, policy_response.text

        first_payload = event(
            "event-1",
            fingerprint="payments-errors",
            alert_name="HighErrorRate",
        )
        first = client.post(
            "/api/v1/event-operations/ingest",
            headers=ingest_headers(source["id"], source_token),
            json=first_payload,
        )
        assert first.status_code == 200, first.text
        assert first.json()["disposition"] == "CORRELATED"
        assert first.json()["ticket_id"] is None

        duplicate = client.post(
            "/api/v1/event-operations/ingest",
            headers=ingest_headers(source["id"], source_token),
            json=first_payload,
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["duplicate"] is True

        second = client.post(
            "/api/v1/event-operations/ingest",
            headers=ingest_headers(source["id"], source_token),
            json=event(
                "event-2",
                fingerprint="payments-errors",
                alert_name="HighErrorRate",
            ),
        )
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert second_body["disposition"] == "INCIDENT_CREATED"
        assert second_body["ticket_id"]

        group_response = client.get(
            f"/api/v1/event-operations/groups/{second_body['group_id']}",
            headers=auth(manager_token),
        )
        assert group_response.status_code == 200, group_response.text
        group = group_response.json()
        assert group["occurrence_count"] == 2
        assert group["ticket_number"].startswith("EVT-")
        assert group["assigned_user_id"] == manager["id"]
        assert len(group["events"]) == 2

        hidden = client.get(
            f"/api/v1/event-operations/groups/{group['id']}",
            headers=auth(other_token),
        )
        assert hidden.status_code == 404

        acknowledged = client.post(
            f"/api/v1/event-operations/groups/{group['id']}/acknowledge",
            headers=auth(manager_token),
            json={
                "expected_version": group["version"],
                "note": "Platform team owns the response.",
            },
        )
        assert acknowledged.status_code == 200, acknowledged.text
        group = acknowledged.json()
        assert group["acknowledged_by_id"] == manager["id"]
        assert group["next_escalation_at"] is None

        recovery = client.post(
            "/api/v1/event-operations/ingest",
            headers=ingest_headers(source["id"], source_token),
            json=event(
                "event-3",
                fingerprint="payments-errors",
                alert_name="HighErrorRate",
                state="RESOLVED",
            ),
        )
        assert recovery.status_code == 200, recovery.text
        assert recovery.json()["disposition"] == "RESOLVED"

        resolved_group = client.get(
            f"/api/v1/event-operations/groups/{group['id']}",
            headers=auth(manager_token),
        ).json()
        assert resolved_group["status"] == "RESOLVED"
        assert resolved_group["ticket_status"] == "RESOLVED"

        suppression = client.post(
            "/api/v1/event-operations/suppressions",
            headers=auth(admin_token),
            json={
                "name": "Backup maintenance",
                "reason": "Approved backup maintenance window.",
                "matchers": [
                    {
                        "field": "service",
                        "operator": "EQUALS",
                        "value": "backup",
                    }
                ],
                "starts_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
                "ends_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "is_active": True,
            },
        )
        assert suppression.status_code == 201, suppression.text
        suppressed = client.post(
            "/api/v1/event-operations/ingest",
            headers=ingest_headers(source["id"], source_token),
            json=event(
                "event-4",
                fingerprint="backup-lag",
                alert_name="BackupLag",
                severity="HIGH",
                service="backup",
                resource="backup-01",
            ),
        )
        assert suppressed.status_code == 200, suppressed.text
        assert suppressed.json()["disposition"] == "SUPPRESSED"
        assert suppressed.json()["ticket_id"] is None

        alertmanager = client.post(
            "/api/v1/event-operations/ingest/alertmanager",
            headers=ingest_headers(source["id"], source_token),
            json={
                "status": "firing",
                "receiver": "sbs-event-operations",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {
                            "alertname": "UnmatchedAlert",
                            "severity": "warning",
                            "service": "identity",
                            "instance": "idp-01",
                        },
                        "annotations": {
                            "summary": "Identity latency is elevated"
                        },
                        "startsAt": datetime.now(UTC).isoformat(),
                        "fingerprint": "alertmanager-adapter-test",
                    }
                ],
            },
        )
        assert alertmanager.status_code == 200, alertmanager.text
        assert alertmanager.json()["accepted"] == 1
        assert alertmanager.json()["results"][0]["disposition"] == "IGNORED"

        summary = client.get(
            "/api/v1/event-operations/summary",
            headers=auth(manager_token),
        )
        assert summary.status_code == 200, summary.text
        assert summary.json()["incidents_24h"] == 1
        assert summary.json()["suppressed_24h"] == 1
        assert summary.json()["duplicates_lifetime"] == 1

        wrong_token = client.post(
            "/api/v1/event-operations/ingest",
            headers=ingest_headers(source["id"], "wrong-token"),
            json=event(
                "event-5",
                fingerprint="unauthorized",
                alert_name="Unauthorized",
            ),
        )
        assert wrong_token.status_code == 401


def test_event_ack_deadline_escalates_to_fallback(app) -> None:
    with TestClient(app) as client:
        admin_token, admin = login(client, "admin@sbs.local")
        manager_token, manager = login(client, "manager@sbs.local")
        source_response = client.post(
            "/api/v1/event-operations/sources",
            headers=auth(admin_token),
            json={
                "code": "zabbix-primary",
                "name": "Primary Zabbix",
                "source_type": "ZABBIX",
            },
        )
        assert source_response.status_code == 201, source_response.text
        source = source_response.json()
        policy = client.post(
            "/api/v1/event-operations/policies",
            headers=auth(admin_token),
            json={
                "name": "Disk saturation",
                "priority_order": 5,
                "matchers": [
                    {
                        "field": "label.alertname",
                        "operator": "EQUALS",
                        "value": "DiskFull",
                    }
                ],
                "group_by": ["resource"],
                "min_occurrences": 1,
                "incident_mode": "CREATE_UPDATE",
                "resolution_action": "NONE",
                "primary_user_id": manager["id"],
                "fallback_user_id": admin["id"],
                "acknowledge_within_minutes": 1,
                "escalate_after_minutes": 5,
            },
        )
        assert policy.status_code == 201, policy.text
        ingested = client.post(
            "/api/v1/event-operations/ingest",
            headers=ingest_headers(source["id"], source["ingest_token"]),
            json=event(
                "disk-1",
                fingerprint="disk-api-01",
                alert_name="DiskFull",
                severity="HIGH",
            ),
        )
        assert ingested.status_code == 200, ingested.text
        group_id = ingested.json()["group_id"]

        from app.db.session import SessionLocal
        from app.models.event_operations import EventCorrelationGroup

        with SessionLocal() as db:
            group = db.scalar(
                select(EventCorrelationGroup).where(
                    EventCorrelationGroup.id == group_id
                )
            )
            assert group is not None
            group.next_escalation_at = datetime.now(UTC) - timedelta(minutes=1)
            db.commit()

        evaluated = client.post(
            "/api/v1/event-operations/escalations/evaluate",
            headers=auth(manager_token),
        )
        assert evaluated.status_code == 200, evaluated.text
        assert evaluated.json()["evaluated"] == 1
        escalated = client.get(
            f"/api/v1/event-operations/groups/{group_id}",
            headers=auth(manager_token),
        ).json()
        assert escalated["escalation_level"] == 1
        assert escalated["assigned_user_id"] == admin["id"]
        assert escalated["next_escalation_at"] is not None
        assert any(
            item["activity_type"] == "ESCALATED"
            for item in escalated["activities"]
        )
