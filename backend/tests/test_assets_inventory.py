from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _first_asset_id(client: TestClient, token: str) -> str:
    response = client.get("/api/v1/assets", headers=_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["items"][0]["id"]


def test_assets_pagination_envelope_preserved(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local")
        response = client.get("/api/v1/assets?page=1&page_size=5", headers=_headers(token))
        assert response.status_code == 200
        payload = response.json()
        assert {"items", "total", "page", "page_size"}.issubset(payload.keys())
        assert payload["page"] == 1
        assert payload["page_size"] == 5


def test_filters_room_and_responsible_and_missing_location(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local")
        asset_id = _first_asset_id(client, token)

        move = client.post(
            f"/api/v1/assets/{asset_id}/move",
            headers=_headers(token),
            json={"building": "A", "floor": "2", "room": "2-15", "location_label": "Кабинет 215"},
        )
        assert move.status_code == 200, move.text

        assign = client.post(
            f"/api/v1/assets/{asset_id}/assign",
            headers=_headers(token),
            json={"responsible_person_name": "Иванов И.И.", "responsible_department": "IT", "mol_name": "Иванов И.И."},
        )
        assert assign.status_code == 200, assign.text

        room_filtered = client.get("/api/v1/assets?room=2-15", headers=_headers(token))
        assert room_filtered.status_code == 200
        assert any(item["id"] == asset_id for item in room_filtered.json()["items"])

        resp_filtered = client.get("/api/v1/assets?responsible_person_name=Иванов%20И.И.", headers=_headers(token))
        assert resp_filtered.status_code == 200
        assert any(item["id"] == asset_id for item in resp_filtered.json()["items"])

        missing_location = client.get("/api/v1/assets?missing_location=true", headers=_headers(token))
        assert missing_location.status_code == 200
        assert "items" in missing_location.json()


def test_manager_can_update_asset_and_requester_cannot(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        requester = _login(client, "requester@sbs.local")
        asset_id = _first_asset_id(client, manager)

        updated = client.patch(
            f"/api/v1/assets/{asset_id}",
            headers=_headers(manager),
            json={"notes": "Плановая проверка", "manufacturer": "Dell"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["notes"] == "Плановая проверка"

        forbidden = client.patch(
            f"/api/v1/assets/{asset_id}",
            headers=_headers(requester),
            json={"notes": "should fail"},
        )
        assert forbidden.status_code == 403


def test_agent_can_verify_asset_if_permission_exists(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        agent = _login(client, "agent.support@sbs.local")
        asset_id = _first_asset_id(client, manager)

        response = client.post(
            f"/api/v1/assets/{asset_id}/verify",
            headers=_headers(agent),
            json={"verification_status": "verified", "comment": "Проверено агентом"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["verification_status"] == "verified"


def test_manager_can_assign_move_dispose_restore_and_history_audit(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        admin = _login(client, "admin@sbs.local")
        asset_id = _first_asset_id(client, manager)

        assigned = client.post(
            f"/api/v1/assets/{asset_id}/assign",
            headers=_headers(manager),
            json={
                "responsible_person_name": "Петров П.П.",
                "responsible_department": "Service Desk",
                "mol_name": "Петров П.П.",
                "mol_department": "IT",
                "comment": "Закрепление",
            },
        )
        assert assigned.status_code == 200, assigned.text

        moved = client.post(
            f"/api/v1/assets/{asset_id}/move",
            headers=_headers(manager),
            json={"building": "B", "floor": "1", "room": "1-07", "location_label": "Учебный класс", "comment": "Перемещение"},
        )
        assert moved.status_code == 200, moved.text

        disposed = client.post(
            f"/api/v1/assets/{asset_id}/dispose",
            headers=_headers(manager),
            json={"writeoff_reason": "Не подлежит ремонту", "comment": "Списание"},
        )
        assert disposed.status_code == 200, disposed.text
        assert disposed.json()["status"] == "disposed"

        restored = client.post(
            f"/api/v1/assets/{asset_id}/restore",
            headers=_headers(manager),
            json={"comment": "Восстановлено после проверки"},
        )
        assert restored.status_code == 200, restored.text

        history = client.get(f"/api/v1/assets/{asset_id}/history", headers=_headers(manager))
        assert history.status_code == 200
        actions = {item["action"] for item in history.json()}
        assert {"asset_assigned", "asset_moved", "asset_disposed", "asset_restored"}.issubset(actions)

        audit = client.get("/api/v1/admin/audit-logs?action=asset_disposed", headers=_headers(admin))
        assert audit.status_code == 200
        assert any(item["entity_id"] == asset_id for item in audit.json())


def test_asset_detail_returns_linked_tickets_summary(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        asset_id = _first_asset_id(client, admin)

        ticket_created = client.post(
            "/api/v1/tickets",
            headers=_headers(admin),
            json={
                "title": "Связь тикета с активом",
                "description": "Проверка linked tickets summary",
                "requester_name": "Ирина Соколова",
                "requester_email": "irina.sokolova@sbs.local",
                "department": "IT",
                "location": "HQ",
                "category": "HARDWARE_WORKSTATION",
                "priority": "MEDIUM",
                "asset_id": asset_id,
            },
        )
        assert ticket_created.status_code == 201, ticket_created.text

        detail = client.get(f"/api/v1/assets/{asset_id}", headers=_headers(admin))
        assert detail.status_code == 200
        payload = detail.json()
        assert "linked_tickets_summary" in payload
        assert any(item["id"] == ticket_created.json()["id"] for item in payload["linked_tickets_summary"])


def test_migration_file_exists_for_asset_inventory_fields() -> None:
    migration = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "20261109_0003_asset_inventory_fields.py"
    assert migration.exists(), "Expected 0003 asset inventory migration is missing"
