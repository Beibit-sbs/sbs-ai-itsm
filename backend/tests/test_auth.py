def test_login_and_me_flow(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["token_type"] == "bearer"
        assert payload["user"]["email"] == "admin@sbs.local"
        assert payload["access_token"]
        assert payload["refresh_token"]

        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )

        assert me_response.status_code == 200
        me_payload = me_response.json()
        assert me_payload["email"] == "admin@sbs.local"
        assert me_payload["role"] == "organization_admin"


def test_login_rejects_invalid_credentials(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "wrong-password"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "HTTP_401"


def test_failed_login_creates_audit_event(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        failed = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "wrong-password"},
        )
        assert failed.status_code == 401

        token = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        ).json()["access_token"]
        logs = client.get(
            "/api/v1/admin/audit-logs?action=login_failed",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert logs.status_code == 200
        assert any(item["action"] == "login_failed" and item["actor_email"] == "admin@sbs.local" for item in logs.json())


def test_logout_endpoint_returns_ok_and_writes_audit(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )
        assert login.status_code == 200
        tokens = login.json()

        response = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

        audit = client.get(
            "/api/v1/admin/audit-logs?action=logout_success",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert audit.status_code == 200
        assert any(item["action"] == "logout_success" for item in audit.json())


def test_deactivated_user_cannot_login_and_cannot_use_existing_token(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )
        assert admin_login.status_code == 200
        admin_token = admin_login.json()["access_token"]

        manager_login = client.post(
            "/api/v1/auth/login",
            json={"email": "manager@sbs.local", "password": "Sbs!2026"},
        )
        assert manager_login.status_code == 200
        manager_token = manager_login.json()["access_token"]

        users = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"}).json()
        manager_id = next(item["id"] for item in users if item["email"] == "manager@sbs.local")
        deactivate = client.patch(
            f"/api/v1/admin/users/{manager_id}/deactivate",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert deactivate.status_code == 200

        blocked_login = client.post(
            "/api/v1/auth/login",
            json={"email": "manager@sbs.local", "password": "Sbs!2026"},
        )
        assert blocked_login.status_code == 403

        blocked_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {manager_token}"})
        assert blocked_me.status_code == 403


def test_root_user_can_list_tenants(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        tenants_response = client.get(
            "/api/v1/tenants",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert tenants_response.status_code == 200
        tenants = tenants_response.json()
        assert len(tenants) >= 1
        assert tenants[0]["slug"] == "demo-tenant"


def test_tenant_admin_cannot_list_tenants(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        tenants_response = client.get(
            "/api/v1/tenants",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert tenants_response.status_code == 403
        assert tenants_response.json()["error"]["code"] == "HTTP_403"


def test_tenant_admin_can_list_assets(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        assets_response = client.get(
            "/api/v1/assets",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert assets_response.status_code == 200
        assets = assets_response.json()["items"]
        assert len(assets) >= 3
        assert assets[0]["tenant_name"] == "Demo Tenant"


def test_root_user_can_list_assets(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        assets_response = client.get(
            "/api/v1/assets",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert assets_response.status_code == 200
        assets = assets_response.json()["items"]
        assert len(assets) >= 3
        assert {"in_use", "in_stock", "in_repair"}.issubset({asset["status"] for asset in assets})


def test_tenant_admin_can_list_sla_policies(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        sla_response = client.get(
            "/api/v1/sla",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert sla_response.status_code == 200
        policies = sla_response.json()
        assert len(policies) == 3
        assert policies[0]["tenant_name"] == "Demo Tenant"


def test_root_user_can_list_sla_policies(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        sla_response = client.get(
            "/api/v1/sla",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert sla_response.status_code == 200
        policies = sla_response.json()
        assert len(policies) == 3
        assert {policy["priority"] for policy in policies} == {"critical", "high", "medium"}


def test_production_mode_does_not_seed_demo_data(monkeypatch, tmp_path) -> None:
    import sys
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'prod.db'}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("RUN_STARTUP_DDL", "true")

    reload_prefixes = [
        "app.main",
        "app.db.session",
        "app.core.config",
        "app.services.seed",
        "app.services.service_desk",
        "app.api.v1.router",
        "app.api.v1.routes.",
    ]
    for module_name in list(sys.modules.keys()):
        if any(module_name == prefix or module_name.startswith(prefix) for prefix in reload_prefixes):
            sys.modules.pop(module_name, None)

    from app.main import app as prod_app

    with TestClient(prod_app) as client:
        demo_admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )
        assert demo_admin_login.status_code == 401

        root_login = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )
        assert root_login.status_code == 200
        root_token = root_login.json()["access_token"]

        tickets = client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {root_token}"})
        assert tickets.status_code == 200
        assert tickets.json()["total"] == 0
