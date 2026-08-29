def _login(client, email: str, password: str):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _get_system_id(client, token: str, code: str) -> str:
    systems = client.get("/api/v1/integrations/systems", headers={"Authorization": f"Bearer {token}"}).json()
    return next(item["id"] for item in systems if item["code"] == code)


def test_integrations_systems_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/integrations/systems", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 8
        assert any(item["code"] == "zimbra_main" for item in payload)


def test_create_external_system(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.post(
            "/api/v1/integrations/systems",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": "custom_api_demo",
                "name": "Custom API Demo",
                "system_type": "custom_api",
                "base_url": "https://mock-custom-api.sbs.local",
                "status": "demo",
                "is_enabled": True,
                "description": "Demo custom API connector",
            },
        )
        assert response.status_code == 201
        assert response.json()["code"] == "custom_api_demo"


def test_health_check_system(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        system_id = _get_system_id(client, token, "ldap_main")
        response = client.post(f"/api/v1/integrations/systems/{system_id}/health-check", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["status"] == "simulated"
        assert response.json()["health_status"] == "simulated"


def test_test_connection_system(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        system_id = _get_system_id(client, token, "smtp_main")
        response = client.post(f"/api/v1/integrations/systems/{system_id}/test-connection", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["status"] == "simulated"


def test_providers_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/integrations/providers", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert any(item["code"] == "zimbra" for item in payload)
        assert any(item["code"] == "webhook" for item in payload)


def test_provider_capabilities(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/integrations/providers/ldap/capabilities", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert "pull_users" in payload["capabilities"]


def test_events_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "security@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/integrations/events", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 20


def test_import_jobs_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/integrations/import-jobs", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert len(response.json()) >= 5


def test_create_import_job(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        system_id = _get_system_id(client, token, "ldap_main")
        response = client.post(
            "/api/v1/integrations/import-jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"external_system_id": system_id, "job_type": "ldap_users_preview"},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["job_type"] == "ldap_users_preview"
        assert payload["status"] == "pending"
        assert payload["records_total"] == 0
        assert payload["records_success"] == 0


def test_webhooks_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "security@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/integrations/webhooks", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert len(response.json()) >= 5


def test_legacy_inbound_webhook_requires_permission_and_tenant_scope(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        unauthenticated = client.post(
            "/api/v1/integrations/inbound/hooks/custom-incident",
            json={"payload": {"event": "unauthenticated"}},
        )
        assert unauthenticated.status_code == 401

        requester_token = _login(client, "requester@sbs.local", "Sbs!2026")
        denied = client.post(
            "/api/v1/integrations/inbound/hooks/custom-incident",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={"payload": {"event": "denied"}},
        )
        assert denied.status_code == 403

        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        accepted = client.post(
            "/api/v1/integrations/inbound/hooks/custom-incident",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"payload": {"event": "authorized-demo"}},
        )
        assert accepted.status_code == 202
        assert accepted.json()["status"] == "simulated"


def test_simulate_webhook(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        webhooks = client.get("/api/v1/integrations/webhooks", headers={"Authorization": f"Bearer {token}"}).json()
        webhook = webhooks[0]
        webhook_id = webhook["id"]
        response = client.post(
            f"/api/v1/integrations/webhooks/{webhook_id}/simulate",
            headers={"Authorization": f"Bearer {token}"},
            json={"payload": {"severity": "high", "source": "demo"}, "create_demo_ticket": True},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "simulated"
        assert payload.get("demo_ticket_id")
        event = client.get(
            f"/api/v1/integrations/events/{payload['event_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert event.status_code == 200
        assert event.json()["status"] == "simulated"
        refreshed = client.get(
            "/api/v1/integrations/webhooks",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        refreshed_webhook = next(
            item for item in refreshed if item["id"] == webhook_id
        )
        assert refreshed_webhook["success_count"] == webhook["success_count"]
        assert (
            refreshed_webhook["last_received_at"]
            == webhook["last_received_at"]
        )


def test_mappings_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "security@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/integrations/mappings", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert len(response.json()) >= 6


def test_mock_ldap_pull_users(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.post("/api/v1/integrations/mock/ldap/pull-users", headers={"Authorization": f"Bearer {token}"}, json={})
        assert response.status_code == 200
        payload = response.json()
        assert payload["records_total"] == 5
        assert any(item["email"] == "rector@university.local" for item in payload["users"])


def test_mock_zimbra_pull_mailboxes(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.post("/api/v1/integrations/mock/zimbra/pull-mailboxes", headers={"Authorization": f"Bearer {token}"}, json={})
        assert response.status_code == 200
        payload = response.json()
        assert payload["records_total"] == 4
        assert any(item["email"] == "support@university.kz" for item in payload["mailboxes"])


def test_requester_cannot_access_integrations(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "requester@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/integrations/systems", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def test_manager_can_access_integrations(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/integrations/systems", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200


def test_it_agent_cannot_manage_integrations(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "agent.support@sbs.local", "Sbs!2026")
        response = client.post(
            "/api/v1/integrations/systems",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": "forbidden_system",
                "name": "Forbidden",
                "system_type": "custom_api",
                "status": "planned",
            },
        )
        assert response.status_code == 403


def test_audit_log_created_for_health_check(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        manager_token = _login(client, "manager@sbs.local", "Sbs!2026")
        system_id = _get_system_id(client, manager_token, "ldap_main")
        response = client.post(f"/api/v1/integrations/systems/{system_id}/health-check", headers={"Authorization": f"Bearer {manager_token}"})
        assert response.status_code == 200

        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        logs = client.get("/api/v1/admin/audit-logs?action=integration_health_check_executed", headers={"Authorization": f"Bearer {admin_token}"}).json()
        assert any(item["entity_id"] == system_id for item in logs)
