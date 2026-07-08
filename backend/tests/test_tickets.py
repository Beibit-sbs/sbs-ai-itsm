def test_tenant_admin_can_list_seeded_tickets(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        tickets_response = client.get(
            "/api/v1/tickets",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert tickets_response.status_code == 200
        tickets = tickets_response.json()
        assert len(tickets) >= 12
        assert tickets[0]["ticket_number"].startswith("SD-")


def test_root_user_can_list_seeded_tickets(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        tickets_response = client.get(
            "/api/v1/tickets",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert tickets_response.status_code == 200
        tickets = tickets_response.json()
        assert len(tickets) >= 12
        assert {ticket["status"] for ticket in tickets} >= {"NEW", "TRIAGED", "ASSIGNED", "IN_PROGRESS", "WAITING_USER", "RESOLVED", "CLOSED", "REOPENED"}