def _login(client, email: str, password: str):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_analytics_overview(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/overview", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert {"tickets", "sla", "assets", "ai", "knowledge", "notifications", "security", "executive_summary"} <= set(payload)


def test_ticket_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/tickets", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_tickets"] >= 12
        assert "by_status" in payload
        assert "top_assignees" in payload


def test_sla_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/sla", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert "sla_compliance_percent" in payload
        assert "violations_by_priority" in payload


def test_asset_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/assets", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_assets"] >= 3
        assert "top_assets_by_ticket_count" in payload


def test_ai_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/ai", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_ai_analyses"] >= 1
        assert "recommendations_by_category" in payload


def test_knowledge_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/knowledge", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_articles"] >= 1
        assert "categories_without_articles" in payload


def test_security_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "security@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/security", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert "risk_summary" in payload
        assert "audit_events_count" in payload


def test_executive_summary(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/executive-summary", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert {"health_score", "sla_risk_score", "asset_risk_score", "security_risk_score", "ai_maturity_score"} <= set(payload)


def test_saved_reports_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/reports/saved", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 1


def test_create_saved_report(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.post(
            "/api/v1/reports/saved",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Недельный executive pulse", "report_type": "executive-summary", "filters_json": {"period": "7d"}},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["name"] == "Недельный executive pulse"


def test_snapshots_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/reports/snapshots", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 1


def test_create_snapshot(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.post(
            "/api/v1/reports/snapshots",
            headers={"Authorization": f"Bearer {token}"},
            json={"report_type": "executive-summary"},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["report_type"] == "executive-summary"
        assert "payload_json" in payload


def test_demo_export(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/reports/export-demo?report_type=overview&format=csv", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["format"] == "csv"
        assert payload["report_type"] == "overview"
        assert len(payload["rows"]) >= 1


def test_requester_cannot_access_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "requester@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/overview", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def test_manager_can_access_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/overview", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200


def test_audit_log_created_for_report_export(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        manager_token = _login(client, "manager@sbs.local", "Sbs!2026")
        exported = client.get(
            "/api/v1/reports/export-demo?report_type=overview&format=json",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert exported.status_code == 200

        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        logs = client.get(
            "/api/v1/admin/audit-logs?action=demo_export_requested",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert logs.status_code == 200
        assert any(item["entity_id"] == "overview" for item in logs.json())
