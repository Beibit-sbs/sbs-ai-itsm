def test_create_ticket_links_asset_and_assigns_sla(app) -> None:
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
        asset_id = assets_response.json()["items"][0]["id"]

        create_response = client.post(
            "/api/v1/tickets",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "title": "Ноутбук требует замены SSD",
                "description": "Пользователь жалуется на медленную работу устройства.",
                "requester_name": "Ирина Соколова",
                    "requester_email": "irina.sokolova@sbs.local",
                    "on_behalf_reason": "Requester reported the hardware issue",
                "department": "Учебный центр",
                "location": "Moscow / HQ / Floor 4",
                "category": "HARDWARE_WORKSTATION",
                "priority": "HIGH",
                "assignee_name": "Инженер поддержки",
                "asset_id": asset_id,
            },
        )

        assert create_response.status_code == 201
        ticket = create_response.json()
        assert ticket["asset_id"] == asset_id
        assert ticket["asset_tag"]
        assert ticket["sla_policy_id"]
        assert ticket["response_due_at"]
        assert ticket["resolution_due_at"]
        assert ticket["sla_status"] == "OK"

        asset_tickets_response = client.get(
            f"/api/v1/assets/{asset_id}/tickets",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert asset_tickets_response.status_code == 200
        asset_tickets = asset_tickets_response.json()
        assert any(item["id"] == ticket["id"] for item in asset_tickets)


def test_sla_overview_and_breach_endpoints(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )
        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        policies_response = client.get(
            "/api/v1/sla/policies",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert policies_response.status_code == 200
        policies = policies_response.json()
        assert len(policies) >= 3
        assert {policy["priority"] for policy in policies} >= {
            "CRITICAL",
            "HIGH",
            "MEDIUM",
        }

        overview_response = client.get(
            "/api/v1/sla/overview",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert overview_response.status_code == 200
        overview = overview_response.json()
        assert "breached_tickets" in overview
        assert "problematic_assets" in overview

        breaches_response = client.get(
            "/api/v1/sla/breaches",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert breaches_response.status_code == 200
        breaches = breaches_response.json()
        assert isinstance(breaches, list)
