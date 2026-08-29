from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from app.services.localized_content import (
    LocalizedContentError,
    RESOURCE_KNOWLEDGE,
    RESOURCE_NOTIFICATION,
    validate_translation_payload,
)


def _login(client: TestClient, email: str) -> tuple[str, dict[str, object]]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sbs!2026"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["access_token"], payload["user"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_translation_validation_preserves_placeholders_and_rejects_active_content() -> None:
    source = {
        "name": "Assigned",
        "subject_template": "[{{ticket_number}}] Assigned",
        "body_template": "{{title}} assigned to {{assignee_name}}",
    }
    translated = validate_translation_payload(
        RESOURCE_NOTIFICATION,
        {
            "name": "Назначение",
            "subject_template": "[{{ticket_number}}] Назначено",
            "body_template": "{{title}} назначено: {{assignee_name}}",
        },
        source=source,
    )
    assert translated["name"] == "Назначение"

    with pytest.raises(LocalizedContentError, match="placeholders"):
        validate_translation_payload(
            RESOURCE_NOTIFICATION,
            {
                "name": "Назначение",
                "subject_template": "Назначено",
                "body_template": "{{title}} назначено: {{unknown_user}}",
            },
            source=source,
        )

    with pytest.raises(LocalizedContentError, match="unsafe active content"):
        validate_translation_payload(
            RESOURCE_KNOWLEDGE,
            {
                "title": "Unsafe",
                "summary": "Unsafe article",
                "content": "<script>alert(1)</script>",
            },
            source={
                "title": "Source",
                "summary": "Source article",
                "content": "Safe source",
            },
        )


def test_governed_translation_four_eyes_stale_fallback_and_retirement(app) -> None:
    with TestClient(app) as client:
        admin_token, admin_user = _login(client, "admin@sbs.local")
        publisher_token, publisher_user = _login(client, "knowledge@sbs.local")
        requester_token, _ = _login(client, "requester@sbs.local")
        other_token, _ = _login(client, "other.admin@sbs.local")

        categories = client.get(
            "/api/v1/knowledge/categories",
            headers=_headers(admin_token),
        )
        assert categories.status_code == 200, categories.text
        category_id = categories.json()[0]["id"]
        source = client.post(
            "/api/v1/knowledge/articles",
            headers=_headers(admin_token),
            json={
                "title": "VPN access recovery",
                "summary": "Recover corporate VPN access",
                "content": "Verify identity and rotate the VPN credential.",
                "category_id": category_id,
                "tags": ["vpn", "access"],
                "status": "published",
                "visibility": "internal",
            },
        )
        assert source.status_code == 201, source.text
        article = source.json()

        requester_denied = client.post(
            "/api/v1/tenant-content-translations",
            headers=_headers(requester_token),
            json={
                "resource_type": RESOURCE_KNOWLEDGE,
                "resource_id": article["id"],
                "locale": "kk-KZ",
                "payload": {
                    "title": "VPN қолжетімділігін қалпына келтіру",
                    "summary": "Корпоративтік VPN қолжетімділігін қалпына келтіру",
                    "content": "Тұлғаны тексеріп, VPN тіркелгі деректерін жаңартыңыз.",
                },
            },
        )
        assert requester_denied.status_code == 403

        created = client.post(
            "/api/v1/tenant-content-translations",
            headers=_headers(admin_token),
            json={
                "resource_type": RESOURCE_KNOWLEDGE,
                "resource_id": article["id"],
                "locale": "kk-KZ",
                "payload": {
                    "title": "VPN қолжетімділігін қалпына келтіру",
                    "summary": "Корпоративтік VPN қолжетімділігін қалпына келтіру",
                    "content": "Тұлғаны тексеріп, VPN тіркелгі деректерін жаңартыңыз.",
                },
            },
        )
        assert created.status_code == 201, created.text
        first = created.json()
        assert first["version"] == 1
        assert first["integrity_valid"] is True
        assert first["source_current"] is True
        assert first["created_by_id"] == admin_user["id"]

        other_scope = client.get(
            (
                "/api/v1/tenant-content-translations"
                f"?resource_id={article['id']}&locale=kk-KZ"
            ),
            headers=_headers(other_token),
        )
        assert other_scope.status_code == 200, other_scope.text
        assert other_scope.json() == []

        submitted = client.post(
            f"/api/v1/tenant-content-translations/{first['id']}/submit",
            headers=_headers(admin_token),
            json={
                "expected_revision": first["revision"],
                "submission_note": "Terminology checked against the approved glossary",
            },
        )
        assert submitted.status_code == 200, submitted.text
        in_review = submitted.json()
        assert in_review["status"] == "IN_REVIEW"

        self_approval = client.post(
            f"/api/v1/tenant-content-translations/{first['id']}/decision",
            headers=_headers(admin_token),
            json={
                "expected_revision": in_review["revision"],
                "decision": "APPROVE",
                "review_comment": "Attempt to approve my own translation",
            },
        )
        assert self_approval.status_code == 409

        approved = client.post(
            f"/api/v1/tenant-content-translations/{first['id']}/decision",
            headers=_headers(publisher_token),
            json={
                "expected_revision": in_review["revision"],
                "decision": "APPROVE",
                "review_comment": "Independent language and technical review passed",
            },
        )
        assert approved.status_code == 200, approved.text
        published = approved.json()
        assert published["status"] == "PUBLISHED"
        assert published["reviewed_by_id"] == publisher_user["id"]

        localized = client.get(
            f"/api/v1/knowledge/articles/{article['id']}?locale=kk-KZ",
            headers=_headers(requester_token),
        )
        assert localized.status_code == 200, localized.text
        assert localized.json()["title"] == "VPN қолжетімділігін қалпына келтіру"
        assert localized.json()["translation_status"] == "PUBLISHED"
        assert localized.json()["translation_version"] == 1

        source_changed = client.patch(
            f"/api/v1/knowledge/articles/{article['id']}",
            headers=_headers(admin_token),
            json={"title": "VPN access recovery v2"},
        )
        assert source_changed.status_code == 200, source_changed.text
        stale_fallback = client.get(
            f"/api/v1/knowledge/articles/{article['id']}?locale=kk-KZ",
            headers=_headers(requester_token),
        )
        assert stale_fallback.status_code == 200, stale_fallback.text
        assert stale_fallback.json()["title"] == "VPN access recovery v2"
        assert stale_fallback.json()["translation_status"] == "STALE_FALLBACK"
        assert stale_fallback.json()["translation_version"] is None

        second_created = client.post(
            "/api/v1/tenant-content-translations",
            headers=_headers(admin_token),
            json={
                "resource_type": RESOURCE_KNOWLEDGE,
                "resource_id": article["id"],
                "locale": "kk-KZ",
                "payload": {
                    "title": "VPN қолжетімділігін қалпына келтіру v2",
                    "summary": "Корпоративтік VPN қолжетімділігін қалпына келтіру",
                    "content": "Тұлғаны тексеріп, VPN тіркелгі деректерін жаңартыңыз.",
                },
            },
        )
        assert second_created.status_code == 201, second_created.text
        second = second_created.json()
        second_submitted = client.post(
            f"/api/v1/tenant-content-translations/{second['id']}/submit",
            headers=_headers(admin_token),
            json={
                "expected_revision": second["revision"],
                "submission_note": "Updated after source content revision",
            },
        ).json()
        second_approved = client.post(
            f"/api/v1/tenant-content-translations/{second['id']}/decision",
            headers=_headers(publisher_token),
            json={
                "expected_revision": second_submitted["revision"],
                "decision": "APPROVE",
                "review_comment": "Independent review of the updated source passed",
            },
        )
        assert second_approved.status_code == 200, second_approved.text
        assert second_approved.json()["version"] == 2

        history = client.get(
            (
                "/api/v1/tenant-content-translations"
                f"?resource_id={article['id']}&locale=kk-KZ"
            ),
            headers=_headers(admin_token),
        )
        assert history.status_code == 200, history.text
        by_version = {item["version"]: item for item in history.json()}
        assert by_version[1]["status"] == "RETIRED"
        assert by_version[2]["status"] == "PUBLISHED"

        audits = client.get(
            "/api/v1/admin/audit-logs?action=localized_content.published",
            headers=_headers(admin_token),
        )
        assert audits.status_code == 200, audits.text
        serialized_audits = json.dumps(audits.json(), ensure_ascii=False)
        assert "Independent review of the updated source passed" not in serialized_audits
        assert "review_comment_sha256" in serialized_audits


def test_published_notification_translation_is_rendered_and_global_source_is_read_only(
    app,
) -> None:
    with TestClient(app) as client:
        admin_token, _ = _login(client, "admin@sbs.local")
        publisher_token, _ = _login(client, "knowledge@sbs.local")
        requester_token, requester = _login(client, "requester@sbs.local")

        sources = client.get(
            (
                "/api/v1/tenant-content-translations/sources"
                "?resource_type=NOTIFICATION_TEMPLATE"
            ),
            headers=_headers(admin_token),
        )
        assert sources.status_code == 200, sources.text
        template = next(
            item for item in sources.json() if item["code"] == "ticket_created"
        )
        assert template["inherited"] is True

        inherited_patch = client.patch(
            f"/api/v1/notifications/templates/{template['id']}",
            headers=_headers(admin_token),
            json={"is_active": False},
        )
        assert inherited_patch.status_code == 404

        translated_payload = {
            **template["payload"],
            "name": "Localized ticket created",
            "subject_template": (
                "[LOCALIZED] " + template["payload"]["subject_template"]
            ),
            "body_template": (
                "Localized: " + template["payload"]["body_template"]
            ),
        }
        created = client.post(
            "/api/v1/tenant-content-translations",
            headers=_headers(admin_token),
            json={
                "resource_type": RESOURCE_NOTIFICATION,
                "resource_id": template["id"],
                "locale": "ru-RU",
                "payload": translated_payload,
            },
        )
        assert created.status_code == 201, created.text
        draft = created.json()
        submitted = client.post(
            f"/api/v1/tenant-content-translations/{draft['id']}/submit",
            headers=_headers(admin_token),
            json={
                "expected_revision": draft["revision"],
                "submission_note": "All runtime placeholders preserved",
            },
        )
        assert submitted.status_code == 200, submitted.text
        approved = client.post(
            f"/api/v1/tenant-content-translations/{draft['id']}/decision",
            headers=_headers(publisher_token),
            json={
                "expected_revision": submitted.json()["revision"],
                "decision": "APPROVE",
                "review_comment": "Independent notification rendering review passed",
            },
        )
        assert approved.status_code == 200, approved.text

        ticket = client.post(
            "/api/v1/tickets",
            headers=_headers(admin_token),
            json={
                "title": "Localized notification verification",
                "description": "Verify governed notification template resolution.",
                "requester_id": requester["id"],
                "requester_name": requester["full_name"],
                "requester_email": requester["email"],
                "on_behalf_reason": "Localized notification acceptance",
                "department": "ITSM",
                "location": "HQ",
                    "category": "SOFTWARE_INSTALL",
                "priority": "MEDIUM",
            },
        )
        assert ticket.status_code == 201, ticket.text
        notifications = client.get(
            "/api/v1/notifications?page=1&page_size=100",
            headers=_headers(requester_token),
        )
        assert notifications.status_code == 200, notifications.text
        rendered = next(
            item
            for item in notifications.json()["items"]
            if item["related_ticket_id"] == ticket.json()["id"]
            and item["event_type"] == "ticket_created"
        )
        assert rendered["title"].startswith("[LOCALIZED]")
        assert rendered["message"].startswith("Localized:")
        assert ticket.json()["ticket_number"] in rendered["title"]
