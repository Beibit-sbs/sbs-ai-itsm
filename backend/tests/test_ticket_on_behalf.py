from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> tuple[str, dict]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["access_token"], body["user"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "On-behalf registration acceptance",
        "description": "Request received by the service desk",
        "department": "IT",
        "location": "HQ",
        "category": "NETWORK_INTERNET",
        "priority": "MEDIUM",
    }
    payload.update(overrides)
    return payload


def test_requester_cannot_override_own_identity_or_read_candidate_directory(app) -> None:
    with TestClient(app) as client:
        requester_token, requester = _login(client, "requester@sbs.local")

        directory = client.get(
            "/api/v1/tickets/requester-candidates",
            headers=_headers(requester_token),
        )
        assert directory.status_code == 403

        forged = client.post(
            "/api/v1/tickets",
            headers=_headers(requester_token),
            json=_payload(
                requester_id="00000000-0000-0000-0000-000000000000",
                requester_name="Another User",
                requester_email="another.user@sbs.local",
            ),
        )
        assert forged.status_code == 403

        own = client.post(
            "/api/v1/tickets",
            headers=_headers(requester_token),
            json=_payload(
                requester_id=requester["id"],
                requester_name="Ignored snapshot override",
                requester_email=requester["email"],
                requester_contact="+7 700 100 20 30",
            ),
        )
        assert own.status_code == 201, own.text
        body = own.json()
        assert body["requester_id"] == requester["id"]
        assert body["requester_name"] == requester["full_name"]
        assert body["created_by_id"] == requester["id"]
        assert body["created_by_name"] == requester["full_name"]
        assert body["requester_contact"] == "+7 700 100 20 30"
        assert body["creation_channel"] == "SELF_SERVICE"


def test_agent_registers_on_behalf_with_reason_history_and_audit(app) -> None:
    with TestClient(app) as client:
        agent_token, agent = _login(client, "agent.network@sbs.local")
        admin_token, _ = _login(client, "admin@sbs.local")

        directory = client.get(
            "/api/v1/tickets/requester-candidates",
            headers=_headers(agent_token),
        )
        assert directory.status_code == 200, directory.text
        requester = next(
            item for item in directory.json() if item["email"] == "requester@sbs.local"
        )

        missing_reason = client.post(
            "/api/v1/tickets",
            headers=_headers(agent_token),
            json=_payload(
                requester_id=requester["id"],
                requester_name=requester["full_name"],
                requester_email=requester["email"],
            ),
        )
        assert missing_reason.status_code == 422

        reason = "User called the service desk and confirmed their employee number"
        created = client.post(
            "/api/v1/tickets",
            headers=_headers(agent_token),
            json=_payload(
                requester_id=requester["id"],
                requester_name="Forged name must not be used",
                requester_email="forged@example.invalid",
                requester_contact="+7 700 222 33 44",
                on_behalf_reason=reason,
            ),
        )
        assert created.status_code == 201, created.text
        ticket = created.json()
        assert ticket["requester_id"] == requester["id"]
        assert ticket["requester_name"] == requester["full_name"]
        assert ticket["requester_email"] == requester["email"]
        assert ticket["requester_contact"] == "+7 700 222 33 44"
        assert ticket["created_by_id"] == agent["id"]
        assert ticket["created_by_name"] == agent["full_name"]
        assert ticket["creation_channel"] == "ON_BEHALF"

        history = client.get(
            f"/api/v1/tickets/{ticket['id']}/history",
            headers=_headers(agent_token),
        )
        assert history.status_code == 200, history.text
        assert any(item["event_type"] == "created_on_behalf" for item in history.json())
        assert reason not in history.text

        audit = client.get(
            "/api/v1/admin/audit-logs?action=ticket_created_on_behalf",
            headers=_headers(admin_token),
        )
        assert audit.status_code == 200, audit.text
        item = next(item for item in audit.json() if item["entity_id"] == ticket["id"])
        assert item["actor_email"] == "agent.network@sbs.local"
        assert item["metadata"]["requester_id"] == requester["id"]
        assert item["metadata"]["reason"] == reason


def test_on_behalf_registration_rejects_cross_tenant_requester(app) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        other_token, _ = _login(client, "other.admin@sbs.local")
        other_directory = client.get(
            "/api/v1/tickets/requester-candidates",
            headers=_headers(other_token),
        )
        assert other_directory.status_code == 200, other_directory.text
        other_requester = other_directory.json()[0]

        response = client.post(
            "/api/v1/tickets",
            headers=_headers(manager_token),
            json=_payload(
                requester_id=other_requester["id"],
                on_behalf_reason="Cross tenant request must be rejected",
            ),
        )
        assert response.status_code == 400
        assert response.json()["error"]["message"] == "Unknown or inactive requester"


def test_on_behalf_migration_is_current_head() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260814_0080_ticket_on_behalf_registration.py"
    )
    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert 'revision: str = "20260814_0080"' in text
    assert 'down_revision: str | None = "20260814_0079"' in text
