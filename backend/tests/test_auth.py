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
        assets = assets_response.json()
        assert len(assets) == 3
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
        assets = assets_response.json()
        assert len(assets) == 3
        assert {asset["status"] for asset in assets} == {"in_use", "in_stock", "in_repair"}


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
