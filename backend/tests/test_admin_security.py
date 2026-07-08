def _login(client, email: str, password: str):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_admin_users_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        users = response.json()
        assert len(users) >= 7


def test_create_user(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        roles = client.get("/api/v1/admin/roles", headers={"Authorization": f"Bearer {token}"}).json()
        role_id = next(item["id"] for item in roles if item["code"] == "requester")

        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "new.requester@sbs.local",
                "full_name": "New Requester",
                    "password": "Sbs!2026-Strong",
                "position": "Specialist",
                "department": "Business",
                "phone": "+70000000111",
                "role_id": role_id,
            },
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["email"] == "new.requester@sbs.local"


def test_update_user(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        user_id = next(item["id"] for item in client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json() if item["email"] == "requester@sbs.local")
        response = client.patch(
            f"/api/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"position": "Senior Specialist"},
        )
        assert response.status_code == 200
        assert response.json()["position"] == "Senior Specialist"


def test_deactivate_user(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        user_id = next(item["id"] for item in client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json() if item["email"] == "agent.support@sbs.local")
        response = client.patch(f"/api/v1/admin/users/{user_id}/deactivate", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["is_active"] is False


def test_roles_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/roles", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert {item["code"] for item in payload} >= {"organization_admin", "it_agent", "requester"}


def test_permissions_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/permissions", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 20
        assert {item["code"] for item in payload} >= {"admin.users.read", "security.audit.read"}


def test_assign_role_to_user(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        users = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json()
        target_user = next(item for item in users if item["email"] == "requester@sbs.local")
        roles = client.get("/api/v1/admin/roles", headers={"Authorization": f"Bearer {token}"}).json()
        requester_role = next(item for item in roles if item["code"] == "requester")

        response = client.post(
            f"/api/v1/admin/users/{target_user['id']}/roles",
            headers={"Authorization": f"Bearer {token}"},
            json={"role_ids": [requester_role["id"]]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert any(item["code"] == "requester" for item in payload)


def test_audit_logs_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "security@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/audit-logs", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 1


def test_settings_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/settings", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert {item["key"] for item in payload} >= {"password_min_length", "ai_copilot_enabled"}


def test_update_setting(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.patch(
            "/api/v1/admin/settings/session_timeout_minutes",
            headers={"Authorization": f"Bearer {token}"},
            json={"value": "75"},
        )
        assert response.status_code == 200
        assert response.json()["value"] == "75"


def test_organization_admin_cannot_see_other_tenant_users(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        users = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json()
        assert all(item["email"] != "other.admin@sbs.local" for item in users)


def test_requester_cannot_access_admin_endpoints(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "requester@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def test_it_agent_cannot_access_admin_endpoints(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "agent.support@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def test_requester_cannot_access_security_endpoints(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "requester@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/security/risk-summary", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def test_audit_log_created_on_user_update(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        users = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json()
        target_user = next(item for item in users if item["email"] == "requester@sbs.local")
        patch_response = client.patch(
            f"/api/v1/admin/users/{target_user['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"department": "Updated Department"},
        )
        assert patch_response.status_code == 200

        logs = client.get("/api/v1/admin/audit-logs?action=user_updated", headers={"Authorization": f"Bearer {token}"}).json()
        assert any(item["entity_id"] == target_user["id"] for item in logs)


def test_login_creates_audit_event(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post("/api/v1/auth/login", json={"email": "manager@sbs.local", "password": "Sbs!2026"})
        assert login_response.status_code == 200
        token = _login(client, "security@sbs.local", "Sbs!2026")

        logs_response = client.get("/api/v1/security/login-events", headers={"Authorization": f"Bearer {token}"})
        assert logs_response.status_code == 200
        logs = logs_response.json()
        assert any(item["action"] == "login_success" and item["actor_email"] == "manager@sbs.local" for item in logs)
