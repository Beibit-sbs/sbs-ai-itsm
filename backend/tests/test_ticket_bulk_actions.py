from __future__ import annotations

from fastapi.testclient import TestClient


def _login(
    client: TestClient,
    email: str,
    password: str = "Sbs!2026",
) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_ticket(
    client: TestClient,
    token: str,
    *,
    title: str,
    requester_email: str = "requester@sbs.local",
):
    response = client.post(
        "/api/v1/tickets",
        headers=_headers(token),
        json={
            "title": title,
            "description": "Bulk action acceptance target",
            "requester_name": "Bulk Requester",
            "requester_email": requester_email,
            "on_behalf_reason": "Bulk action test registration",
            "department": "IT",
            "location": "HQ",
            "category": "NETWORK_INTERNET",
            "priority": "MEDIUM",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _preview(
    client: TestClient,
    token: str,
    ticket_ids: list[str],
    *,
    target_status: str = "TRIAGE",
):
    return client.post(
        "/api/v1/tickets/bulk/preview",
        headers=_headers(token),
        json={
            "ticket_ids": ticket_ids,
            "status": target_status,
            "comment": "Controlled bulk test",
        },
    )


def test_bulk_action_requires_server_preview_and_confirmation(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local")
        tickets = [
            _create_ticket(client, admin_token, title=f"Bulk target {index}")
            for index in range(2)
        ]
        preview = _preview(
            client,
            admin_token,
            [item["id"] for item in tickets],
        )
        assert preview.status_code == 200, preview.text
        plan = preview.json()
        assert plan["eligible_count"] == 2
        assert plan["skipped_count"] == 0
        assert len(plan["operation_sha256"]) == 64
        assert len(plan["targets_sha256"]) == 64

        wrong_confirmation = client.post(
            f"/api/v1/tickets/bulk/{plan['plan_id']}/execute",
            headers=_headers(admin_token),
            json={
                "expected_revision": plan["revision"],
                "confirmation_phrase": "APPLY ALL",
            },
        )
        assert wrong_confirmation.status_code == 422

        executed = client.post(
            f"/api/v1/tickets/bulk/{plan['plan_id']}/execute",
            headers=_headers(admin_token),
            json={
                "expected_revision": plan["revision"],
                "confirmation_phrase": plan["confirmation_phrase"],
            },
        )
        assert executed.status_code == 200, executed.text
        assert executed.json()["updated_count"] == 2
        for item in tickets:
            detail = client.get(
                f"/api/v1/tickets/{item['id']}",
                headers=_headers(admin_token),
            )
            assert detail.json()["status"] == "TRIAGE"

        replay = client.post(
            f"/api/v1/tickets/bulk/{plan['plan_id']}/execute",
            headers=_headers(admin_token),
            json={
                "expected_revision": plan["revision"],
                "confirmation_phrase": plan["confirmation_phrase"],
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["already_executed"] is True


def test_bulk_execute_refuses_any_target_drift_atomically(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local")
        first = _create_ticket(client, admin_token, title="Stable target")
        second = _create_ticket(client, admin_token, title="Drifting target")
        preview = _preview(
            client,
            admin_token,
            [first["id"], second["id"]],
        )
        assert preview.status_code == 200, preview.text
        plan = preview.json()

        drift = client.post(
            f"/api/v1/tickets/{second['id']}/assign",
            headers=_headers(admin_token),
            json={
                "assignee_id": next(
                    user["id"]
                    for user in client.get(
                        "/api/v1/admin/users",
                        headers=_headers(admin_token),
                    ).json()
                    if user["email"] == "agent.network@sbs.local"
                )
            },
        )
        assert drift.status_code == 200, drift.text

        execute = client.post(
            f"/api/v1/tickets/bulk/{plan['plan_id']}/execute",
            headers=_headers(admin_token),
            json={
                "expected_revision": plan["revision"],
                "confirmation_phrase": plan["confirmation_phrase"],
            },
        )
        assert execute.status_code == 409, execute.text
        stable_detail = client.get(
            f"/api/v1/tickets/{first['id']}",
            headers=_headers(admin_token),
        )
        assert stable_detail.json()["status"] == "NEW"


def test_bulk_action_is_bounded_and_not_available_to_requester(app) -> None:
    with TestClient(app) as client:
        requester_token = _login(client, "requester@sbs.local")
        forbidden = _preview(client, requester_token, ["missing"])
        assert forbidden.status_code == 403

        admin_token = _login(client, "admin@sbs.local")
        oversized = _preview(
            client,
            admin_token,
            [f"target-{index}" for index in range(51)],
        )
        assert oversized.status_code == 422


def test_root_cannot_mix_tenants_in_one_bulk_plan(app) -> None:
    with TestClient(app) as client:
        primary_token = _login(client, "admin@sbs.local")
        other_token = _login(client, "other.admin@sbs.local")
        root_token = _login(client, "root@sbs.local", "Root!2026")
        primary = _create_ticket(
            client,
            primary_token,
            title="Primary tenant target",
        )
        other = _create_ticket(
            client,
            other_token,
            title="Other tenant target",
            requester_email="other.admin@sbs.local",
        )
        preview = _preview(
            client,
            root_token,
            [primary["id"], other["id"]],
        )
        assert preview.status_code == 422
        assert "one tenant" in preview.text.lower()
