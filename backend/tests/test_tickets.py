from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user_id_by_email(client: TestClient, admin_token: str, email: str) -> str:
    users = client.get("/api/v1/admin/users", headers=_headers(admin_token))
    assert users.status_code == 200, users.text
    user = next(item for item in users.json() if item["email"] == email)
    return user["id"]


def _first_asset_id(client: TestClient, token: str) -> str:
    response = client.get("/api/v1/assets", headers=_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["items"][0]["id"]


def _create_ticket(client: TestClient, token: str, **overrides):
    payload = {
        "title": "Проблема с сервисом",
        "description": "Тестовая заявка",
        "requester_name": "Business Requester",
        "requester_email": "requester@sbs.local",
        "department": "Business",
        "location": "HQ",
        "category": "NETWORK_INTERNET",
        "priority": "MEDIUM",
    }
    payload.update(overrides)
    response = client.post("/api/v1/tickets", headers=_headers(token), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_tenant_admin_can_list_seeded_tickets(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        tickets = client.get("/api/v1/tickets", headers=_headers(token))
        assert tickets.status_code == 200
        payload = tickets.json()
        assert payload["total"] >= 12
        assert payload["items"]
        assert {"items", "total", "page", "page_size"}.issubset(payload.keys())


def test_requester_sees_only_own_tickets(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        requester_token = _login(client, "requester@sbs.local")

        requester_id = _user_id_by_email(client, admin_token, "requester@sbs.local")
        _create_ticket(client, admin_token, title="Own ticket", requester_id=requester_id)
        _create_ticket(client, admin_token, title="Foreign ticket", requester_name="Other", requester_email="other.user@sbs.local")

        list_response = client.get("/api/v1/tickets", headers=_headers(requester_token))
        assert list_response.status_code == 200
        items = list_response.json()["items"]
        assert items
        assert all(item["requester_email"].lower() == "requester@sbs.local" for item in items)


def test_requester_cannot_assign_ticket(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        requester_token = _login(client, "requester@sbs.local")
        requester_id = _user_id_by_email(client, admin_token, "requester@sbs.local")
        assignee_id = _user_id_by_email(client, admin_token, "agent.network@sbs.local")

        ticket = _create_ticket(client, admin_token, requester_id=requester_id)
        response = client.post(
            f"/api/v1/tickets/{ticket['id']}/assign",
            headers=_headers(requester_token),
            json={"assignee_id": assignee_id, "comment": "Назначаю"},
        )
        assert response.status_code == 403


def test_requester_cannot_write_internal_comment(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        requester_token = _login(client, "requester@sbs.local")
        requester_id = _user_id_by_email(client, admin_token, "requester@sbs.local")

        ticket = _create_ticket(client, admin_token, requester_id=requester_id)
        response = client.post(
            f"/api/v1/tickets/{ticket['id']}/comments",
            headers=_headers(requester_token),
            json={"body": "internal", "is_internal": True},
        )
        assert response.status_code == 403


def test_agent_sees_own_plus_unassigned(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        agent_token = _login(client, "agent.network@sbs.local")

        agent_id = _user_id_by_email(client, admin_token, "agent.network@sbs.local")
        _create_ticket(client, admin_token, title="Assigned to agent", assignee_id=agent_id)
        _create_ticket(client, admin_token, title="Unassigned")
        _create_ticket(client, admin_token, title="Assigned to other", assignee_name="Support Agent")

        response = client.get("/api/v1/tickets", headers=_headers(agent_token))
        assert response.status_code == 200
        titles = {item["title"] for item in response.json()["items"]}
        assert "Assigned to agent" in titles
        assert "Unassigned" in titles
        assert "Assigned to other" not in titles


def test_agent_can_take_unassigned_ticket(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        agent_token = _login(client, "agent.network@sbs.local")

        ticket = _create_ticket(client, admin_token, title="Take me")
        response = client.post(
            f"/api/v1/tickets/{ticket['id']}/assign",
            headers=_headers(agent_token),
            json={"comment": "Беру в работу"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["assignee_name"] == "Network Agent"


def test_manager_can_assign_ticket(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        manager_token = _login(client, "manager@sbs.local")
        assignee_id = _user_id_by_email(client, admin_token, "agent.support@sbs.local")

        ticket = _create_ticket(client, admin_token, title="Assign by manager")
        response = client.post(
            f"/api/v1/tickets/{ticket['id']}/assign",
            headers=_headers(manager_token),
            json={"assignee_id": assignee_id, "comment": "Назначено"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["assignee_id"] == assignee_id


def test_invalid_status_transition_rejected(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        ticket = _create_ticket(client, admin_token, title="Bad transition")

        response = client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            headers=_headers(admin_token),
            json={"status": "CLOSED", "comment": "invalid from new"},
        )
        assert response.status_code == 400


def test_valid_transition_writes_history_and_audit(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        ticket = _create_ticket(client, admin_token, title="History transition")

        to_assigned = client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            headers=_headers(admin_token),
            json={"status": "assigned", "comment": "Назначаем"},
        )
        assert to_assigned.status_code == 200, to_assigned.text

        history = client.get(f"/api/v1/tickets/{ticket['id']}/history", headers=_headers(admin_token))
        assert history.status_code == 200
        assert any(item["event_type"] == "status_changed" for item in history.json())

        audit = client.get("/api/v1/admin/audit-logs?action=ticket_status_changed", headers=_headers(admin_token))
        assert audit.status_code == 200
        assert any(item["entity_id"] == ticket["id"] for item in audit.json())


def test_comment_visibility_public_internal(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        requester_token = _login(client, "requester@sbs.local")
        requester_id = _user_id_by_email(client, admin_token, "requester@sbs.local")
        ticket = _create_ticket(client, admin_token, title="Comments visibility", requester_id=requester_id)

        public_comment = client.post(
            f"/api/v1/tickets/{ticket['id']}/comments",
            headers=_headers(admin_token),
            json={"body": "Публичный", "is_internal": False},
        )
        assert public_comment.status_code == 201
        internal_comment = client.post(
            f"/api/v1/tickets/{ticket['id']}/comments",
            headers=_headers(admin_token),
            json={"body": "Внутренний", "is_internal": True},
        )
        assert internal_comment.status_code == 201

        requester_view = client.get(f"/api/v1/tickets/{ticket['id']}", headers=_headers(requester_token))
        assert requester_view.status_code == 200
        comments = requester_view.json()["comments"]
        assert any(item["body"] == "Публичный" for item in comments)
        assert all(not item["is_internal"] for item in comments)


def test_ticket_pagination_and_queue_filters_work(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        requester_id = _user_id_by_email(client, admin_token, "requester@sbs.local")

        _create_ticket(client, admin_token, title="Queue critical", priority="CRITICAL", requester_id=requester_id)
        closed_ticket = _create_ticket(client, admin_token, title="Queue closed", requester_id=requester_id)

        close_flow_1 = client.post(
            f"/api/v1/tickets/{closed_ticket['id']}/transition",
            headers=_headers(admin_token),
            json={"status": "assigned"},
        )
        assert close_flow_1.status_code == 200
        close_flow_2 = client.post(
            f"/api/v1/tickets/{closed_ticket['id']}/transition",
            headers=_headers(admin_token),
            json={"status": "in_progress"},
        )
        assert close_flow_2.status_code == 200
        close_flow_3 = client.post(
            f"/api/v1/tickets/{closed_ticket['id']}/transition",
            headers=_headers(admin_token),
            json={"status": "resolved"},
        )
        assert close_flow_3.status_code == 200
        close_flow_4 = client.post(
            f"/api/v1/tickets/{closed_ticket['id']}/transition",
            headers=_headers(admin_token),
            json={"status": "closed"},
        )
        assert close_flow_4.status_code == 200

        page = client.get("/api/v1/tickets?page=1&page_size=5", headers=_headers(admin_token))
        assert page.status_code == 200
        payload = page.json()
        assert payload["page"] == 1
        assert payload["page_size"] == 5
        assert len(payload["items"]) <= 5

        critical_queue = client.get("/api/v1/tickets?queue=critical", headers=_headers(admin_token))
        assert critical_queue.status_code == 200
        assert any(item["priority"] == "CRITICAL" for item in critical_queue.json()["items"])

        closed_queue = client.get("/api/v1/tickets?queue=closed", headers=_headers(admin_token))
        assert closed_queue.status_code == 200
        assert any(item["id"] == closed_ticket["id"] for item in closed_queue.json()["items"])


def test_sla_state_fields_present(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        asset_id = _first_asset_id(client, admin_token)
        ticket = _create_ticket(client, admin_token, title="SLA fields", priority="HIGH", asset_id=asset_id)

        response = client.get(f"/api/v1/tickets/{ticket['id']}", headers=_headers(admin_token))
        assert response.status_code == 200
        payload = response.json()
        assert payload["sla_badge"] in {"OK", "RISK", "BREACHED"}
        assert "response_remaining_minutes" in payload
        assert "resolution_remaining_minutes" in payload
        assert "is_response_breached" in payload
        assert "is_resolution_breached" in payload


def test_closed_ticket_can_be_reopened_by_manager(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        manager_token = _login(client, "manager@sbs.local")
        ticket = _create_ticket(client, admin_token, title="Reopen flow")

        assert client.post(f"/api/v1/tickets/{ticket['id']}/transition", headers=_headers(admin_token), json={"status": "assigned"}).status_code == 200
        assert client.post(f"/api/v1/tickets/{ticket['id']}/transition", headers=_headers(admin_token), json={"status": "in_progress"}).status_code == 200
        assert client.post(f"/api/v1/tickets/{ticket['id']}/transition", headers=_headers(admin_token), json={"status": "resolved"}).status_code == 200
        assert client.post(f"/api/v1/tickets/{ticket['id']}/transition", headers=_headers(admin_token), json={"status": "closed"}).status_code == 200

        reopen = client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            headers=_headers(manager_token),
            json={"status": "reopened", "comment": "Пользователь вернул"},
        )
        assert reopen.status_code == 200, reopen.text
        assert reopen.json()["status"] == "REOPENED"


def test_due_today_queue_excludes_closed_tickets(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        ticket = _create_ticket(client, admin_token, title="Due today filter")

        # Make ticket due today using public API, then close it.
        patch_due = client.patch(
            f"/api/v1/tickets/{ticket['id']}",
            headers=_headers(admin_token),
            json={"sla_due_at": datetime.now(UTC).isoformat()},
        )
        assert patch_due.status_code == 200, patch_due.text

        assert client.post(f"/api/v1/tickets/{ticket['id']}/transition", headers=_headers(admin_token), json={"status": "assigned"}).status_code == 200
        assert client.post(f"/api/v1/tickets/{ticket['id']}/transition", headers=_headers(admin_token), json={"status": "in_progress"}).status_code == 200
        assert client.post(f"/api/v1/tickets/{ticket['id']}/transition", headers=_headers(admin_token), json={"status": "resolved"}).status_code == 200
        assert client.post(f"/api/v1/tickets/{ticket['id']}/transition", headers=_headers(admin_token), json={"status": "closed"}).status_code == 200

        due_today = client.get("/api/v1/tickets?queue=due_today", headers=_headers(admin_token))
        assert due_today.status_code == 200
        assert all(item["id"] != ticket["id"] for item in due_today.json()["items"])
