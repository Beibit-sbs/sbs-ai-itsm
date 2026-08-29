from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_ticket(client: TestClient, manager: str, requester: dict[str, str]) -> dict[str, object]:
    response = client.post(
        "/api/v1/tickets",
        headers=_headers(manager),
        json={
            "title": "Participant workflow acceptance",
            "description": "Verify watcher preferences and privacy boundaries",
            "requester_id": requester["id"],
            "requester_name": requester["full_name"],
            "requester_email": requester["email"],
            "on_behalf_reason": "Requester contacted the service desk",
            "department": "IT",
            "location": "HQ",
            "category": "NETWORK_INTERNET",
            "priority": "MEDIUM",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _candidates(client: TestClient, manager: str, ticket_id: str) -> list[dict[str, str]]:
    response = client.get(
        f"/api/v1/tickets/{ticket_id}/participant-candidates",
        headers=_headers(manager),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_manager_adds_watcher_and_public_comments_fan_out(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        agent = _login(client, "agent.network@sbs.local")
        requester_token = _login(client, "requester@sbs.local")

        seed_ticket = client.get("/api/v1/tickets?page_size=1", headers=_headers(manager)).json()
        assert "items" in seed_ticket
        candidates = client.get(
            "/api/v1/tickets/00000000-0000-0000-0000-000000000000/participant-candidates",
            headers=_headers(manager),
        )
        assert candidates.status_code == 404

        # Resolve stable tenant users through a newly created ticket's candidate directory.
        requester_profile = client.get("/api/v1/auth/me", headers=_headers(requester_token)).json()
        ticket = _create_ticket(client, manager, requester_profile)
        candidates = _candidates(client, manager, str(ticket["id"]))
        agent_user = next(item for item in candidates if item["email"] == "agent.network@sbs.local")

        created = client.post(
            f"/api/v1/tickets/{ticket['id']}/participants",
            headers=_headers(manager),
            json={
                "user_id": agent_user["id"],
                "participant_role": "COLLABORATOR",
                "notification_scope": "PUBLIC_ONLY",
                "notify_in_app": True,
                "notify_email": False,
                "reason": "Network specialist collaboration",
            },
        )
        assert created.status_code == 201, created.text
        participant = created.json()

        duplicate = client.post(
            f"/api/v1/tickets/{ticket['id']}/participants",
            headers=_headers(manager),
            json={
                "user_id": agent_user["id"],
                "participant_role": "WATCHER",
                "reason": "Duplicate must be rejected",
            },
        )
        assert duplicate.status_code == 409

        public_comment = client.post(
            f"/api/v1/tickets/{ticket['id']}/comments",
            headers=_headers(manager),
            json={"body": "Public participant update", "is_internal": False},
        )
        assert public_comment.status_code == 201, public_comment.text
        agent_notifications = client.get(
            "/api/v1/notifications?page_size=100",
            headers=_headers(agent),
        )
        assert agent_notifications.status_code == 200
        matching = [
            item
            for item in agent_notifications.json()["items"]
            if item["related_ticket_id"] == ticket["id"]
            and item["recipient_email"] == "agent.network@sbs.local"
            and item["event_type"] == "ticket_comment_added"
        ]
        assert len(matching) == 1
        assert matching[0]["metadata"]["participant_id"] == participant["id"]

        internal_comment = client.post(
            f"/api/v1/tickets/{ticket['id']}/comments",
            headers=_headers(manager),
            json={"body": "Internal secret note", "is_internal": True},
        )
        assert internal_comment.status_code == 201, internal_comment.text
        after_internal = client.get(
            "/api/v1/notifications?page_size=100",
            headers=_headers(agent),
        ).json()["items"]
        matching_after = [
            item
            for item in after_internal
            if item["related_ticket_id"] == ticket["id"]
            and item["recipient_email"] == "agent.network@sbs.local"
            and item["event_type"] == "ticket_comment_added"
        ]
        assert len(matching_after) == 1
        assert all("Internal secret note" not in item["message"] for item in after_internal)


def test_requester_can_watch_self_and_manage_only_own_preferences(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        requester = _login(client, "requester@sbs.local")
        requester_profile = client.get("/api/v1/auth/me", headers=_headers(requester)).json()
        ticket = _create_ticket(client, manager, requester_profile)
        agent_user = next(
            item
            for item in _candidates(client, manager, str(ticket["id"]))
            if item["email"] == "agent.support@sbs.local"
        )
        agent_participant = client.post(
            f"/api/v1/tickets/{ticket['id']}/participants",
            headers=_headers(manager),
            json={"user_id": agent_user["id"], "reason": "Support observer"},
        ).json()

        watched = client.put(
            f"/api/v1/tickets/{ticket['id']}/participants/self",
            headers=_headers(requester),
            json={
                "notification_scope": "STATUS_ONLY",
                "notify_in_app": True,
                "notify_email": True,
            },
        )
        assert watched.status_code == 200, watched.text
        own = watched.json()
        assert own["user_id"] == requester_profile["id"]
        assert own["notification_scope"] == "STATUS_ONLY"

        patched = client.patch(
            f"/api/v1/tickets/{ticket['id']}/participants/{own['id']}",
            headers=_headers(requester),
            json={
                "expected_version": own["version_number"],
                "notification_scope": "PUBLIC_ONLY",
                "notify_email": False,
                "reason": "Requester preference update",
            },
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["notification_scope"] == "PUBLIC_ONLY"

        cannot_patch_other = client.patch(
            f"/api/v1/tickets/{ticket['id']}/participants/{agent_participant['id']}",
            headers=_headers(requester),
            json={
                "expected_version": agent_participant["version_number"],
                "notify_email": True,
                "reason": "Must not change another watcher",
            },
        )
        assert cannot_patch_other.status_code == 403

        removed = client.delete(
            f"/api/v1/tickets/{ticket['id']}/participants/{patched.json()['id']}?reason=No%20longer%20needed",
            headers=_headers(requester),
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["is_active"] is False


def test_participant_tenant_isolation_history_and_audit(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        admin = _login(client, "admin@sbs.local")
        requester = _login(client, "requester@sbs.local")
        other_admin = _login(client, "other.admin@sbs.local")
        requester_profile = client.get("/api/v1/auth/me", headers=_headers(requester)).json()
        ticket = _create_ticket(client, manager, requester_profile)
        agent_user = next(
            item
            for item in _candidates(client, manager, str(ticket["id"]))
            if item["email"] == "agent.support@sbs.local"
        )
        created = client.post(
            f"/api/v1/tickets/{ticket['id']}/participants",
            headers=_headers(manager),
            json={
                "user_id": agent_user["id"],
                "participant_role": "WATCHER",
                "reason": "Audit acceptance",
            },
        )
        assert created.status_code == 201, created.text

        isolated = client.get(
            f"/api/v1/tickets/{ticket['id']}/participants",
            headers=_headers(other_admin),
        )
        assert isolated.status_code == 404

        history = client.get(
            f"/api/v1/tickets/{ticket['id']}/history",
            headers=_headers(manager),
        )
        assert history.status_code == 200
        assert any(item["event_type"] == "ticket_participant_added" for item in history.json())

        audit = client.get(
            "/api/v1/admin/audit-logs?action=ticket_participant_added",
            headers=_headers(admin),
        )
        assert audit.status_code == 200, audit.text
        assert any(item["entity_id"] == created.json()["id"] for item in audit.json())


def test_ticket_participants_migration_is_current_head() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260814_0079_ticket_participants.py"
    )
    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert 'revision: str = "20260814_0079"' in text
    assert 'down_revision: str | None = "20260814_0078"' in text
