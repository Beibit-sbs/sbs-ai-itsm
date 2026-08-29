def _login_admin(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@sbs.local", "password": "Sbs!2026"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _login(client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sbs!2026"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_personal_ticket(client, token: str, *, title: str = "Personal notification test") -> dict:
    profile = client.get("/api/v1/auth/me", headers=_headers(token)).json()
    response = client.post(
        "/api/v1/tickets",
        headers=_headers(token),
        json={
            "title": title,
            "description": "Notification recipient isolation acceptance",
            "requester_id": profile["id"],
            "requester_name": profile["full_name"],
            "requester_email": profile["email"],
            "department": "QA",
            "location": "Test Lab",
            "category": "NETWORK_INTERNET",
            "priority": "HIGH",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_notifications_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert isinstance(payload, dict)
        assert payload["page"] == 1
        assert isinstance(payload["items"], list)
        assert all(item["recipient_email"] == "admin@sbs.local" for item in payload["items"])

        tenant_response = client.get(
            "/api/v1/notifications?scope=tenant&page_size=100",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert tenant_response.status_code == 200
        assert tenant_response.json()["total"] >= 12


def test_unread_count(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        _create_personal_ticket(client, token)
        response = client.get("/api/v1/notifications/unread-count", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["unread_count"] >= 1


def test_mark_notification_as_read(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        _create_personal_ticket(client, token)
        notifications = client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"}).json()["items"]
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
        _create_personal_ticket(client, token)
        response = client.patch("/api/v1/notifications/read-all", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["updated"] >= 0

        unread = client.get("/api/v1/notifications/unread-count", headers={"Authorization": f"Bearer {token}"}).json()
        assert unread["unread_count"] == 0


def test_notification_center_is_recipient_scoped(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        admin = _login_admin(client)
        requester = _login(client, "requester@sbs.local")
        _create_personal_ticket(client, admin, title="Private admin notification")
        admin_items = client.get("/api/v1/notifications", headers=_headers(admin)).json()["items"]
        private_item = next(item for item in admin_items if item["recipient_email"] == "admin@sbs.local")

        tenant_scope = client.get(
            "/api/v1/notifications?scope=tenant",
            headers=_headers(requester),
        )
        assert tenant_scope.status_code == 403

        requester_items = client.get("/api/v1/notifications", headers=_headers(requester))
        assert requester_items.status_code == 200
        assert all(item["recipient_email"] == "requester@sbs.local" for item in requester_items.json()["items"])

        cannot_mark_other = client.patch(
            f"/api/v1/notifications/{private_item['id']}/read",
            headers=_headers(requester),
        )
        assert cannot_mark_other.status_code == 404


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
        payload = response.json()
        assert isinstance(payload, dict)
        assert "items" in payload


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
        assert payload["status"] == "SIMULATED"
        assert payload["provider_message_id"] is None


def test_ticket_create_creates_notification(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        before_count = client.get("/api/v1/notifications", headers=_headers(token)).json()["total"]
        _create_personal_ticket(client, token, title="Новая заявка для проверки уведомлений")

        after = client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"}).json()["items"]
        assert len(after) >= before_count + 1
        assert any(item["type"] == "ticket_created" for item in after[:4])


def test_ticket_status_change_creates_notification(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        ticket_id = _create_personal_ticket(client, token, title="Status notification test")["id"]

        # Exercise the canonical lifecycle instead of relying on the removed
        # NEW -> RESOLVED shortcut.
        for target_status in ("TRIAGE", "ASSIGNED", "IN_PROGRESS", "RESOLVED"):
            patch_response = client.patch(
                f"/api/v1/tickets/{ticket_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"status": target_status},
            )
            assert patch_response.status_code == 200

        notifications = client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"}).json()["items"]
        related = [item for item in notifications if item["related_ticket_id"] == ticket_id]
        types = {item["type"] for item in related}
        assert "ticket_status_changed" in types
        assert "ticket_resolved" in types


def test_preferences_get_and_patch(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.get("/api/v1/notifications/preferences", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        items = response.json()
        assert len(items) >= 1

        first = items[0]
        patch_response = client.patch(
            "/api/v1/notifications/preferences",
            headers={"Authorization": f"Bearer {token}"},
            json={"items": [{"event_type": first["event_type"], "is_muted": not first["is_muted"]}]},
        )
        assert patch_response.status_code == 200
        patched = patch_response.json()
        assert any(item["event_type"] == first["event_type"] for item in patched)


def test_email_log_retry(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        create_response = client.post(
            "/api/v1/notifications/test-email",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "to_email": "retry.user@sbs.local",
                "subject": "Retry candidate",
                "body": "mock",
            },
        )
        assert create_response.status_code == 201
        log_id = create_response.json()["id"]

        retry_response = client.post(
            f"/api/v1/notifications/email-log/{log_id}/retry",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert retry_response.status_code == 409
        assert "simulated" in retry_response.json()["error"]["message"].lower()
