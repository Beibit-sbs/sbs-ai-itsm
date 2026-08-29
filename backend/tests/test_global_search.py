from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from app.services.global_search import escape_like, normalize_entity_types


def _login(
    client: TestClient,
    email: str,
    password: str = "Sbs!2026",
) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_ticket(
    client: TestClient,
    token: str,
    *,
    title: str,
    requester_email: str,
    requester_name: str,
):
    response = client.post(
        "/api/v1/tickets",
        headers=_headers(token),
        json={
            "title": title,
            "description": f"{title} private description",
            "requester_name": requester_name,
            "requester_email": requester_email,
            "on_behalf_reason": "Search isolation test registration",
            "department": "IT",
            "location": "HQ",
            "category": "NETWORK_INTERNET",
            "priority": "MEDIUM",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_search_query_helpers_are_bounded_and_literal() -> None:
    assert escape_like(r"50%_done\soon") == r"50\%\_done\\soon"
    assert normalize_entity_types(["Ticket", "ticket", "ASSET"]) == [
        "ticket",
        "asset",
    ]
    with pytest.raises(ValueError, match="Unsupported"):
        normalize_entity_types(["database_table"])


def test_requester_search_cannot_discover_other_requesters_or_users(app) -> None:
    marker = "ux002-isolation-marker"
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local")
        requester_token = _login(client, "requester@sbs.local")
        own = _create_ticket(
            client,
            admin_token,
            title=f"{marker} own",
            requester_email="requester@sbs.local",
            requester_name="Business Requester",
        )
        _create_ticket(
            client,
            admin_token,
            title=f"{marker} foreign",
            requester_email="private.user@sbs.local",
            requester_name="Private User",
        )
        response = client.get(
            (
                f"/api/v1/search?q={marker}"
                "&types=ticket,user&per_type_limit=20"
            ),
            headers=_headers(requester_token),
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == [own["id"]]
    assert "user" not in payload["counts"]
    assert "private.user@sbs.local" not in response.text


def test_search_is_tenant_scoped_and_audit_omits_raw_query(app) -> None:
    marker = "ux002-cross-tenant-secret-marker"
    with TestClient(app) as client:
        primary_token = _login(client, "admin@sbs.local")
        other_token = _login(client, "other.admin@sbs.local")
        primary = _create_ticket(
            client,
            primary_token,
            title=f"{marker} primary",
            requester_email="requester@sbs.local",
            requester_name="Business Requester",
        )
        _create_ticket(
            client,
            other_token,
            title=f"{marker} other",
            requester_email="other.admin@sbs.local",
            requester_name="Other Tenant Admin",
        )
        response = client.get(
            f"/api/v1/search?q={marker}&types=ticket",
            headers=_headers(primary_token),
        )
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()["items"]] == [primary["id"]]
        audit_response = client.get(
            "/api/v1/admin/audit-logs?action=global_search.executed",
            headers=_headers(primary_token),
        )
        assert audit_response.status_code == 200, audit_response.text
        audit = audit_response.json()[0]
    metadata = audit["metadata"]
    assert metadata["query_sha256"] == response.json()["query_sha256"]
    assert marker not in json.dumps(audit, ensure_ascii=False)


def test_saved_views_enforce_sharing_ownership_and_revision(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local")
        requester_token = _login(client, "requester@sbs.local")
        created = client.post(
            "/api/v1/search/views",
            headers=_headers(admin_token),
            json={
                "name": "Shared incidents",
                "query": {"q": "network", "types": ["ticket"]},
                "is_shared": True,
                "shared_role_codes": ["requester"],
            },
        )
        assert created.status_code == 201, created.text
        view = created.json()

        visible = client.get(
            "/api/v1/search/views",
            headers=_headers(requester_token),
        )
        assert visible.status_code == 200, visible.text
        shared = next(item for item in visible.json() if item["id"] == view["id"])
        assert shared["is_owner"] is False

        forbidden_update = client.patch(
            f"/api/v1/search/views/{view['id']}",
            headers=_headers(requester_token),
            json={
                "expected_revision": view["revision"],
                "name": "Hijacked",
            },
        )
        assert forbidden_update.status_code == 404

        conflict = client.patch(
            f"/api/v1/search/views/{view['id']}",
            headers=_headers(admin_token),
            json={"expected_revision": 99, "name": "Stale update"},
        )
        assert conflict.status_code == 409

        requester_share = client.post(
            "/api/v1/search/views",
            headers=_headers(requester_token),
            json={
                "name": "Unauthorized share",
                "query": {"q": "network", "types": ["ticket"]},
                "is_shared": True,
                "shared_role_codes": ["requester"],
            },
        )
        assert requester_share.status_code == 403
