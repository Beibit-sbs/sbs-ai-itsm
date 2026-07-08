def _login_admin(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@sbs.local", "password": "Sbs!2026"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_notifications_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert isinstance(payload, list)
        assert len(payload) >= 12


def test_unread_count(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.get("/api/v1/notifications/unread-count", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["unread_count"] >= 1


def test_mark_notification_as_read(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        notifications = client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"}).json()
        target = next((item for item in notifications if item["status"] != "READ"), notifications[0])

        response = client.patch(f"/api/v1/notifications/{target['id']}/read", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "READ"
        assert payload["read_at"] is not None


def test_read_all_notifications(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.patch("/api/v1/notifications/read-all", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["updated"] >= 0

        unread = client.get("/api/v1/notifications/unread-count", headers={"Authorization": f"Bearer {token}"}).json()
        assert unread["unread_count"] == 0


def test_templates_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.get("/api/v1/notifications/templates", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        templates = response.json()
        assert len(templates) >= 8
        assert {item["code"] for item in templates} >= {"ticket_created", "sla_breached", "ai_recommendation_ready"}


def test_email_log_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.get("/api/v1/notifications/email-log", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert isinstance(response.json(), list)


def test_test_email_creates_log(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.post(
            "/api/v1/notifications/test-email",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "to_email": "demo.user@sbs.local",
                "subject": "Mock mail",
                "body": "This is a mock email",
            },
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["provider"] == "mock"
        assert payload["status"] == "SENT"


def test_ticket_create_creates_notification(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        before = client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"}).json()
        before_count = len(before)

        create_response = client.post(
            "/api/v1/tickets",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "Новая заявка для проверки уведомлений",
                "description": "Тест создания уведомления",
                "requester_name": "Тестовый пользователь",
                "requester_email": "test.user@sbs.local",
                "department": "QA",
                "location": "Test Lab",
                "category": "NETWORK_INTERNET",
                "priority": "HIGH",
                "assignee_name": "Инженер поддержки",
            },
        )
        assert create_response.status_code == 201

        after = client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"}).json()
        assert len(after) >= before_count + 1
        assert any(item["type"] == "ticket_created" for item in after[:4])


def test_ticket_status_change_creates_notification(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        ticket_id = client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {token}"}).json()[0]["id"]

        patch_response = client.patch(
            f"/api/v1/tickets/{ticket_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "RESOLVED"},
        )
        assert patch_response.status_code == 200

        notifications = client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"}).json()
        related = [item for item in notifications if item["related_ticket_id"] == ticket_id]
        types = {item["type"] for item in related}
        assert "ticket_status_changed" in types
        assert "ticket_resolved" in types
