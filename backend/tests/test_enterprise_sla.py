from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.services.enterprise_sla import (
    add_business_minutes,
    business_minutes_between,
)


def _login(client: TestClient, email: str = "admin@sbs.local") -> tuple[str, dict]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sbs!2026"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["access_token"], body["user"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_business_calendar_skips_weekends_holidays_and_preserves_timezone() -> None:
    snapshot = {
        "timezone": "Europe/Berlin",
        "weekly_hours": {
            "0": [["09:00", "17:00"]],
            "1": [["09:00", "17:00"]],
            "2": [["09:00", "17:00"]],
            "3": [["09:00", "17:00"]],
            "4": [["09:00", "17:00"]],
        },
        "exceptions": {
            "2026-03-30": {
                "kind": "HOLIDAY",
                "name": "Company holiday",
                "intervals": [],
            }
        },
    }
    # Friday 16:00 local, immediately before the DST weekend.
    started_at = datetime(2026, 3, 27, 15, 0, tzinfo=UTC)
    due_at = add_business_minutes(started_at, 120, snapshot)
    # One hour Friday + one hour Tuesday; Monday is a holiday.
    assert due_at == datetime(2026, 3, 31, 8, 0, tzinfo=UTC)
    assert business_minutes_between(started_at, due_at, snapshot) == 120


def test_policy_calendar_targets_pause_resume_and_tenant_isolation(app) -> None:
    with TestClient(app) as client:
        token, admin = _login(client)
        other_token, _ = _login(client, "other.admin@sbs.local")

        calendar_response = client.post(
            "/api/v1/sla/calendars",
            headers=_headers(token),
            json={
                "name": "24x7 operational calendar",
                "timezone": "UTC",
                "weekly_hours": {
                    str(day): [["00:00", "23:59"]] for day in range(7)
                },
                "is_default": True,
                "is_active": True,
            },
        )
        assert calendar_response.status_code == 201, calendar_response.text
        calendar = calendar_response.json()

        holiday_response = client.put(
            f"/api/v1/sla/calendars/{calendar['id']}/exceptions/2026-12-31",
            headers=_headers(token),
            json={
                "exception_date": "2026-12-31",
                "kind": "HOLIDAY",
                "name": "New Year closure",
                "intervals": [],
            },
        )
        assert holiday_response.status_code == 200, holiday_response.text
        assert holiday_response.json()["exceptions"][0]["name"] == "New Year closure"

        policy_response = client.post(
            "/api/v1/sla/policies",
            headers=_headers(token),
            json={
                "name": "Enterprise medium operations",
                "priority": "MEDIUM",
                "calendar_id": calendar["id"],
                "priority_order": 1,
                "scope": {"category": "NETWORK_INTERNET"},
                "targets": [
                    {
                        "type": "RESPONSE",
                        "name": "First response",
                        "minutes": 30,
                        "warning_percent": 80,
                    },
                    {
                        "type": "RESOLUTION",
                        "name": "Resolution",
                        "minutes": 240,
                        "warning_percent": 80,
                    },
                    {
                        "type": "OLA",
                        "name": "Network L2 OLA",
                        "minutes": 120,
                        "warning_percent": 75,
                        "owner_type": "TEAM",
                        "owner_ref": "network-l2",
                    },
                ],
                "pause_statuses": ["WAITING_USER", "WAITING_VENDOR"],
                "pause_reasons": [
                    "WAITING_CUSTOMER",
                    "WAITING_VENDOR",
                    "APPROVED_HOLD",
                ],
                "warning_percent": 80,
                "escalations": [
                    {"at_percent": 80, "label": "Owner warning"},
                    {"at_percent": 100, "label": "Manager breach"},
                ],
                "is_active": True,
            },
        )
        assert policy_response.status_code == 201, policy_response.text

        ticket_response = client.post(
            "/api/v1/tickets",
            headers=_headers(token),
            json={
                "title": "Network latency is above threshold",
                "description": "Production users report intermittent latency.",
                "requester_name": "Business Requester",
                "requester_email": "requester@sbs.local",
                "on_behalf_reason": "Requester reported service degradation",
                "department": "Business",
                "location": "HQ",
                "category": "NETWORK_INTERNET",
                "priority": "MEDIUM",
                "assignee_name": "Network Service Desk",
            },
        )
        assert ticket_response.status_code == 201, ticket_response.text
        ticket = ticket_response.json()

        queue_response = client.get(
            "/api/v1/sla/queue",
            headers=_headers(token),
        )
        assert queue_response.status_code == 200, queue_response.text
        instance = next(
            item
            for item in queue_response.json()
            if item["ticket_id"] == ticket["id"]
        )
        assert instance["policy_name"] == "Enterprise medium operations"
        assert {target["target_type"] for target in instance["targets"]} == {
            "RESPONSE",
            "RESOLUTION",
            "OLA",
        }
        assert next(
            target
            for target in instance["targets"]
            if target["target_type"] == "RESPONSE"
        )["status"] == "MET"

        waiting = client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            headers=_headers(token),
            json={"status": "in_progress"},
        )
        assert waiting.status_code == 200, waiting.text
        waiting = client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            headers=_headers(token),
            json={"status": "waiting_user"},
        )
        assert waiting.status_code == 200, waiting.text

        paused = client.get(
            f"/api/v1/sla/instances/{instance['id']}",
            headers=_headers(token),
        )
        assert paused.status_code == 200
        assert paused.json()["status"] == "PAUSED"
        assert paused.json()["pauses"][0]["reason_code"] == "WAITING_CUSTOMER"

        resumed = client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            headers=_headers(token),
            json={"status": "in_progress"},
        )
        assert resumed.status_code == 200, resumed.text
        detail = client.get(
            f"/api/v1/sla/tickets/{ticket['id']}",
            headers=_headers(token),
        )
        assert detail.status_code == 200
        assert detail.json()["status"] == "ACTIVE"
        assert detail.json()["pauses"][0]["ended_at"] is not None

        isolated = client.get(
            f"/api/v1/sla/instances/{instance['id']}",
            headers=_headers(other_token),
        )
        assert isolated.status_code == 404

        overview = client.get(
            "/api/v1/sla/overview",
            headers=_headers(token),
        )
        assert overview.status_code == 200
        assert overview.json()["active_instances"] >= 1
        assert admin["tenant_id"] == instance["tenant_id"]
