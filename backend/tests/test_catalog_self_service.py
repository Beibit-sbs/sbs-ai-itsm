from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sbs!2026"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["access_token"], payload["user"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _published_item(client: TestClient, manager_token: str, manager: dict) -> dict:
    category_response = client.post(
        "/api/v1/catalog/categories",
        headers=_headers(manager_token),
        json={
            "code": "CAT_SELF_SERVICE",
            "name": "Access self service",
            "description": "Personalized requester portal acceptance.",
        },
    )
    assert category_response.status_code == 201, category_response.text
    category = category_response.json()
    service_response = client.post(
        "/api/v1/catalog/services",
        headers=_headers(manager_token),
        json={
            "category_id": category["id"],
            "code": "SVC_SELF_SERVICE_ACCESS",
            "name": "Access guidance",
            "description": "Self-service access and account guidance.",
        },
    )
    assert service_response.status_code == 201, service_response.text
    service = service_response.json()
    item_response = client.post(
        "/api/v1/catalog/items",
        headers=_headers(manager_token),
        json={
            "category_id": category["id"],
            "service_id": service["id"],
            "code": "REQ_ACCESS_GUIDE",
            "name": "Access to a business application",
            "short_description": "Request or troubleshoot access to a business application.",
            "description": (
                "Use the knowledge guidance first, then submit an access request "
                "when an administrator must change permissions."
            ),
            "owner_user_id": manager["id"],
            "support_group": "Identity & Access",
            "expected_delivery_minutes": 480,
            "approval_required": True,
        },
    )
    assert item_response.status_code == 201, item_response.text
    item = item_response.json()
    for target in ("IN_REVIEW", "PUBLISHED"):
        response = client.post(
            f"/api/v1/catalog/items/{item['id']}/transition",
            headers=_headers(manager_token),
            json={
                "expected_version": item["version"],
                "target_status": target,
                "reason": f"Self-service acceptance: {target}",
            },
        )
        assert response.status_code == 200, response.text
        item = response.json()
    return item


def test_catalog_favorites_recents_deflection_and_tenant_isolation(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = _login(client, "manager@sbs.local")
        requester_token, _ = _login(client, "requester@sbs.local")
        other_admin_token, _ = _login(client, "other.admin@sbs.local")
        admin_token, _ = _login(client, "admin@sbs.local")
        denied_category = client.post(
            "/api/v1/knowledge/categories",
            headers=_headers(manager_token),
            json={"code": "DENIED", "name": "Denied category"},
        )
        assert denied_category.status_code == 403
        knowledge_category = client.post(
            "/api/v1/knowledge/categories",
            headers=_headers(admin_token),
            json={
                "code": "SC004_ACCESS",
                "name": "SC-004 access guidance",
                "description": "Managed category creation from the knowledge workspace.",
            },
        )
        assert knowledge_category.status_code == 201, knowledge_category.text
        draft_article = client.post(
            "/api/v1/knowledge/articles",
            headers=_headers(admin_token),
            json={
                "title": "Unpublished self-service guidance",
                "summary": "This draft must not be visible to requesters.",
                "content": "Internal authoring content.",
                "category_id": knowledge_category.json()["id"],
                "status": "draft",
                "visibility": "internal",
                "tags": ["access"],
            },
        )
        assert draft_article.status_code == 201, draft_article.text
        hidden_draft = client.get(
            f"/api/v1/knowledge/articles/{draft_article.json()['id']}",
            headers=_headers(requester_token),
        )
        assert hidden_draft.status_code == 404
        requester_drafts = client.get(
            "/api/v1/knowledge/articles/page?status=draft",
            headers=_headers(requester_token),
        )
        assert requester_drafts.status_code == 200, requester_drafts.text
        assert requester_drafts.json()["items"] == []
        duplicate_category = client.post(
            "/api/v1/knowledge/categories",
            headers=_headers(admin_token),
            json={"code": "sc004_access", "name": "Duplicate"},
        )
        assert duplicate_category.status_code == 409
        item = _published_item(client, manager_token, manager)

        initial = client.get(
            f"/api/v1/catalog/items/{item['id']}",
            headers=_headers(requester_token),
        )
        assert initial.status_code == 200, initial.text
        assert initial.json()["is_favorite"] is False
        assert initial.json()["view_count"] == 0
        assert initial.json()["last_viewed_at"] is None

        first_view = client.post(
            f"/api/v1/catalog/items/{item['id']}/view",
            headers=_headers(requester_token),
        )
        second_view = client.post(
            f"/api/v1/catalog/items/{item['id']}/view",
            headers=_headers(requester_token),
        )
        favorite = client.put(
            f"/api/v1/catalog/items/{item['id']}/favorite",
            headers=_headers(requester_token),
            json={"is_favorite": True},
        )
        assert first_view.status_code == 200, first_view.text
        assert second_view.status_code == 200, second_view.text
        assert favorite.status_code == 200, favorite.text
        assert favorite.json()["is_favorite"] is True
        assert favorite.json()["view_count"] == 2
        assert favorite.json()["last_viewed_at"]

        personalized = client.get(
            "/api/v1/catalog/items?search=business",
            headers=_headers(requester_token),
        )
        assert personalized.status_code == 200, personalized.text
        assert personalized.json()[0]["id"] == item["id"]
        assert personalized.json()[0]["is_favorite"] is True
        assert personalized.json()[0]["view_count"] == 2

        suggestions = client.get(
            f"/api/v1/catalog/items/{item['id']}/knowledge-suggestions",
            headers=_headers(requester_token),
        )
        assert suggestions.status_code == 200, suggestions.text
        assert suggestions.json()
        assert all(entry["relevance_score"] > 0 for entry in suggestions.json())
        assert all(entry["content_preview"] for entry in suggestions.json())

        resolved = client.post(
            (
                f"/api/v1/catalog/items/{item['id']}/knowledge/"
                f"{suggestions.json()[0]['id']}/resolved"
            ),
            headers=_headers(requester_token),
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json() == {
            "status": "resolved",
            "catalog_item_id": item["id"],
            "article_id": suggestions.json()[0]["id"],
        }

        hidden = client.put(
            f"/api/v1/catalog/items/{item['id']}/favorite",
            headers=_headers(other_admin_token),
            json={"is_favorite": True},
        )
        assert hidden.status_code == 404
