from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _first_asset_id(client: TestClient, token: str) -> str:
    response = client.get("/api/v1/assets?page_size=1", headers=_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["items"][0]["id"]


def _create_change(
    client: TestClient,
    token: str,
    *,
    change_type: str = "NORMAL",
    asset_id: str | None = None,
    title: str = "Production network maintenance",
) -> dict:
    payload = {
        "title": title,
        "description": "Controlled production change for the campus network service.",
        "change_type": change_type,
        "service_name": "Campus Network",
        "impact_level": "MEDIUM",
        "likelihood": 2,
        "business_justification": "Remove a known availability risk before peak usage.",
        "implementation_plan": "Validate health, apply the configuration, monitor telemetry.",
        "test_plan": "Run synthetic connectivity and latency checks.",
        "rollback_plan": "Restore the signed previous configuration and restart the service.",
        "validation_plan": "Confirm service KPIs and business-owner acceptance.",
        "asset_ids": [asset_id] if asset_id else [],
    }
    response = client.post("/api/v1/changes", headers=_headers(token), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _transition(
    client: TestClient,
    token: str,
    change: dict,
    action: str,
    **extra,
) -> dict:
    response = client.post(
        f"/api/v1/changes/{change['id']}/transitions",
        headers=_headers(token),
        json={"action": action, "expected_version": change["version"], **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approve(client: TestClient, token: str, change: dict) -> dict:
    response = client.post(
        f"/api/v1/changes/{change['id']}/decisions",
        headers=_headers(token),
        json={
            "decision": "APPROVED",
            "comment": "Risk and rollback controls accepted by CAB.",
            "expected_version": change["version"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approved_change(
    client: TestClient,
    requester_token: str,
    approver_token: str,
    asset_id: str,
    *,
    title: str,
) -> dict:
    change = _create_change(client, requester_token, asset_id=asset_id, title=title)
    change = _transition(client, requester_token, change, "SUBMIT")
    change = _transition(client, requester_token, change, "REQUEST_APPROVAL")
    return _approve(client, approver_token, change)


def test_normal_change_enforces_dual_control_and_full_lifecycle(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        admin = _login(client, "admin@sbs.local")
        asset_id = _first_asset_id(client, manager)
        change = _create_change(client, manager, asset_id=asset_id)

        stale_patch = client.patch(
            f"/api/v1/changes/{change['id']}",
            headers=_headers(manager),
            json={"expected_version": 999, "title": "Stale write"},
        )
        assert stale_patch.status_code == 409

        change = _transition(client, manager, change, "SUBMIT")
        change = _transition(client, manager, change, "REQUEST_APPROVAL")
        own_decision = client.post(
            f"/api/v1/changes/{change['id']}/decisions",
            headers=_headers(manager),
            json={
                "decision": "APPROVED",
                "comment": "Self approval must be rejected.",
                "expected_version": change["version"],
            },
        )
        assert own_decision.status_code == 403

        change = _approve(client, admin, change)
        start_at = datetime.now(UTC) + timedelta(days=1)
        change = _transition(
            client,
            manager,
            change,
            "SCHEDULE",
            planned_start_at=start_at.isoformat(),
            planned_end_at=(start_at + timedelta(hours=2)).isoformat(),
        )
        change = _transition(client, manager, change, "START")
        change = _transition(client, manager, change, "COMPLETE")
        change = _transition(
            client,
            manager,
            change,
            "CLOSE",
            comment="Validation passed; availability and latency remained within SLO.",
        )

        assert change["status"] == "COMPLETED"
        assert change["approval_status"] == "APPROVED"
        assert len(change["approvals"]) == 1
        assert {item["event_type"] for item in change["history"]} >= {
            "CREATED",
            "SUBMIT",
            "REQUEST_APPROVAL",
            "CAB_DECISION",
            "SCHEDULE",
            "START",
            "COMPLETE",
            "CLOSE",
        }


def test_standard_change_is_pre_authorized_but_still_requires_assessment(app) -> None:
    with TestClient(app) as client:
        agent = _login(client, "agent.network@sbs.local")
        manager = _login(client, "manager@sbs.local")
        asset_id = _first_asset_id(client, agent)
        change = _create_change(
            client,
            agent,
            change_type="STANDARD",
            asset_id=asset_id,
            title="Approved standard access-point restart",
        )
        change = _transition(client, agent, change, "SUBMIT")
        change = _transition(client, agent, change, "REQUEST_APPROVAL")
        assert change["status"] == "APPROVED"
        assert change["approval_status"] == "NOT_REQUIRED"
        assert change["cab_required"] is False

        start_at = datetime.now(UTC) + timedelta(days=2)
        change = _transition(
            client,
            manager,
            change,
            "SCHEDULE",
            planned_start_at=start_at.isoformat(),
            planned_end_at=(start_at + timedelta(minutes=30)).isoformat(),
        )
        assert change["status"] == "SCHEDULED"


def test_overlapping_asset_windows_are_rejected(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        admin = _login(client, "admin@sbs.local")
        asset_id = _first_asset_id(client, manager)
        first = _approved_change(
            client, manager, admin, asset_id, title="Primary firewall maintenance"
        )
        second = _approved_change(
            client, manager, admin, asset_id, title="Competing firewall maintenance"
        )
        start_at = datetime.now(UTC) + timedelta(days=3)
        first = _transition(
            client,
            manager,
            first,
            "SCHEDULE",
            planned_start_at=start_at.isoformat(),
            planned_end_at=(start_at + timedelta(hours=2)).isoformat(),
        )
        assert first["status"] == "SCHEDULED"

        response = client.post(
            f"/api/v1/changes/{second['id']}/transitions",
            headers=_headers(manager),
            json={
                "action": "SCHEDULE",
                "expected_version": second["version"],
                "planned_start_at": (start_at + timedelta(minutes=30)).isoformat(),
                "planned_end_at": (start_at + timedelta(hours=3)).isoformat(),
            },
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["message"] == "Implementation window conflicts with another change"
        assert error["details"]["conflicts"][0]["change_number"] == first["change_number"]


def test_requester_cannot_access_change_register_and_failed_change_can_roll_back(app) -> None:
    with TestClient(app) as client:
        requester = _login(client, "requester@sbs.local")
        assert client.get("/api/v1/changes", headers=_headers(requester)).status_code == 403

        manager = _login(client, "manager@sbs.local")
        admin = _login(client, "admin@sbs.local")
        asset_id = _first_asset_id(client, manager)
        change = _approved_change(
            client, manager, admin, asset_id, title="Risky network firmware change"
        )
        start_at = datetime.now(UTC) + timedelta(days=4)
        change = _transition(
            client,
            manager,
            change,
            "SCHEDULE",
            planned_start_at=start_at.isoformat(),
            planned_end_at=(start_at + timedelta(hours=1)).isoformat(),
        )
        change = _transition(client, manager, change, "START")
        change = _transition(
            client,
            manager,
            change,
            "FAIL",
            comment="Synthetic validation failed after firmware activation.",
        )
        change = _transition(
            client,
            manager,
            change,
            "ROLLBACK",
            comment="Previous firmware restored and service health verified.",
        )
        assert change["status"] == "ROLLED_BACK"
        assert change["failure_reason"]

        summary = client.get("/api/v1/changes/summary", headers=_headers(manager))
        assert summary.status_code == 200
        assert set(summary.json()) == {
            "open_changes",
            "awaiting_approval",
            "scheduled_next_7_days",
            "high_risk_open",
            "failed_last_30_days",
        }
