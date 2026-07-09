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
        assert {"tickets", "sla", "assets", "ai", "knowledge", "security", "executive_summary", "executive"} <= set(payload)


def test_ticket_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/tickets", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_tickets"] >= 12
        assert "status_distribution" in payload
        assert "assignee_workload" in payload


def test_sla_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/sla", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert "compliance_percent" in payload
        assert "by_priority" in payload


def test_asset_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/assets", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_assets"] >= 3
        assert "assets_by_type" in payload


def test_ai_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/ai", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ai_suggestions_total"] >= 1
        assert "suggestions_by_type" in payload


def test_knowledge_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/knowledge", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_articles"] >= 1
        assert "most_used_articles" in payload


def test_security_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "security@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/security", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert "high_risk_events" in payload
        assert "audit_events_today" in payload


def test_executive_analytics(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/analytics/executive", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert {"itsm_health_score", "sla_compliance_percent", "ai_acceptance_rate", "total_assets"} <= set(payload)


def test_saved_reports_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 1


def test_create_saved_report(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.post(
            "/api/v1/reports",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Weekly executive pulse",
                "report_type": "executive",
                "filters_json": {"period": "7d"},
                "visibility": "tenant",
                "schedule_enabled": False,
            },
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["name"] == "Weekly executive pulse"
        assert payload["visibility"] == "tenant"


def test_get_report_by_id_and_run(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        created = client.post(
            "/api/v1/reports",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Run me", "report_type": "tickets", "filters_json": {}},
        )
        assert created.status_code == 201
        report_id = created.json()["id"]

        details = client.get(f"/api/v1/reports/{report_id}", headers={"Authorization": f"Bearer {token}"})
        assert details.status_code == 200
        assert details.json()["id"] == report_id

        run_resp = client.post(f"/api/v1/reports/{report_id}/run", headers={"Authorization": f"Bearer {token}"})
        assert run_resp.status_code == 201
        run_payload = run_resp.json()
        assert run_payload["saved_report_id"] == report_id
        assert run_payload["report_type"] == "tickets"
        assert "payload_json" in run_payload


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
            json={"report_type": "executive", "filters_json": {"group_by": "week"}},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["report_type"] == "executive"
        assert "payload_json" in payload
        assert payload["filters_json"]["group_by"] == "week"


def test_snapshot_detail(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        created = client.post(
            "/api/v1/reports/snapshots",
            headers={"Authorization": f"Bearer {token}"},
            json={"report_type": "sla"},
        )
        assert created.status_code == 201
        snapshot_id = created.json()["id"]

        details = client.get(f"/api/v1/reports/snapshots/{snapshot_id}", headers={"Authorization": f"Bearer {token}"})
        assert details.status_code == 200
        assert details.json()["id"] == snapshot_id


def test_report_export_json(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.post(
            "/api/v1/reports/export",
            headers={"Authorization": f"Bearer {token}"},
            json={"report_type": "executive", "format": "json", "filters_json": {}},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["format"] == "json"
        assert payload["report_type"] == "executive"
        assert "payload" in payload


def test_report_export_csv(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.post(
            "/api/v1/reports/export",
            headers={"Authorization": f"Bearer {token}"},
            json={"report_type": "tickets", "format": "csv", "filters_json": {}},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "metric,value" in response.text


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
        exported = client.post(
            "/api/v1/reports/export",
            headers={"Authorization": f"Bearer {manager_token}"},
            json={"report_type": "executive", "format": "json", "filters_json": {}},
        )
        assert exported.status_code == 200

        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        logs = client.get(
            "/api/v1/admin/audit-logs?action=report_exported",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert logs.status_code == 200
        assert any(item["entity_id"] == "executive" for item in logs.json())
