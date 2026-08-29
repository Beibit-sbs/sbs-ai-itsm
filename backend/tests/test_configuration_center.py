from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.services.configuration_center import (
    ConfigurationValueError,
    SETTING_CATALOG,
    parse_setting_value,
)


def test_typed_setting_validation_is_fail_closed() -> None:
    password = SETTING_CATALOG["password_min_length"]
    copilot = SETTING_CATALOG["ai_copilot_enabled"]
    assert parse_setting_value(password, "16") == 16
    assert parse_setting_value(copilot, "true") is True
    with pytest.raises(ConfigurationValueError):
        parse_setting_value(password, 8)
    with pytest.raises(ConfigurationValueError):
        parse_setting_value(copilot, "sometimes")
    with pytest.raises(ConfigurationValueError):
        parse_setting_value(password, True)


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_configuration_center_exposes_guided_domains_without_secrets(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get(
            "/api/v1/admin/configuration-center",
            headers=_headers(token),
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scope"]["type"] == "tenant"
    assert payload["domains"]
    assert payload["settings"]
    assert payload["guide"]["version"] == "2026.07.1"
    assert payload["guide"]["total_checks"] == sum(
        len(domain["checks"]) for domain in payload["domains"]
    )
    assert all(domain["evidence_sha256"] for domain in payload["domains"])
    assert all(
        check["evidence_sha256"]
        and check["runbook"].startswith("docs/operations/")
        and check["required_permission"]
        and check["safe_default"]
        for domain in payload["domains"]
        for check in domain["checks"]
    )
    assert {
        check["status"]
        for domain in payload["domains"]
        for check in domain["checks"]
    } <= {
        "PASS",
        "INFO",
        "WARNING",
        "ACTION_REQUIRED",
        "NOT_APPLICABLE",
    }
    assert payload["secret_storage"]["plaintext_returned"] is False
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["etag"].startswith('"')
    assert response.headers["x-configuration-guide-version"] == "2026.07.1"
    serialized = response.text.lower()
    assert "openai_api_key" not in serialized
    assert "gemini_api_key" not in serialized
    assert "client_secret" not in serialized


def test_guidance_is_deterministic_role_aware_and_tenant_isolated(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local", "Sbs!2026")
        manager = _login(client, "manager@sbs.local", "Sbs!2026")
        first = client.get(
            "/api/v1/admin/configuration-center",
            headers=_headers(admin),
        )
        second = client.get(
            "/api/v1/admin/configuration-center",
            headers=_headers(admin),
        )
        read_only = client.get(
            "/api/v1/admin/configuration-center",
            headers=_headers(manager),
        )
        tenants = client.get(
            "/api/v1/tenants",
            headers=_headers(admin),
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_hashes = {
        (domain["code"], check["code"]): check["evidence_sha256"]
        for domain in first.json()["domains"]
        for check in domain["checks"]
    }
    second_hashes = {
        (domain["code"], check["code"]): check["evidence_sha256"]
        for domain in second.json()["domains"]
        for check in domain["checks"]
    }
    assert first_hashes == second_hashes
    assert read_only.status_code == 200, read_only.text
    assert any(
        not action["can_manage"]
        for action in read_only.json()["guide"]["next_actions"]
    )
    assert tenants.status_code == 403


def test_tenant_admin_cannot_read_another_tenant_guidance(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local", "Sbs!2026")
        root = _login(client, "saas.root@sbs.local", "Sbs!2026")
        tenants = client.get(
            "/api/v1/tenants",
            headers=_headers(root),
        )
        assert tenants.status_code == 200, tenants.text
        other = next(
            item for item in tenants.json() if item["slug"] == "demo-tenant-2"
        )
        denied = client.get(
            (
                "/api/v1/admin/configuration-center"
                f"?tenant_id={other['id']}"
            ),
            headers=_headers(admin),
        )
    assert denied.status_code == 404


def test_typed_setting_revision_conflict_history_and_rollback(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        first = client.patch(
            "/api/v1/admin/configuration-center/settings/ai_copilot_enabled",
            headers=_headers(token),
            json={
                "expected_revision": 0,
                "value": False,
                "reason": "Controlled disable for revision test",
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["revision"] == 2
        assert first.json()["value"] is False
        conflict = client.patch(
            "/api/v1/admin/configuration-center/settings/ai_copilot_enabled",
            headers=_headers(token),
            json={
                "expected_revision": 0,
                "value": True,
                "reason": "Stale browser update",
            },
        )
        assert conflict.status_code == 409
        second = client.patch(
            "/api/v1/admin/configuration-center/settings/ai_copilot_enabled",
            headers=_headers(token),
            json={
                "expected_revision": 2,
                "value": True,
                "reason": "Validated re-enable",
            },
        )
        assert second.status_code == 200, second.text
        assert second.json()["revision"] == 3
        history = client.get(
            "/api/v1/admin/configuration-center/settings/ai_copilot_enabled/history",
            headers=_headers(token),
        )
        assert history.status_code == 200, history.text
        assert [item["revision"] for item in history.json()] == [3, 2, 1]
        rolled_back = client.post(
            "/api/v1/admin/configuration-center/settings/ai_copilot_enabled/rollback",
            headers=_headers(token),
            json={
                "expected_revision": 3,
                "target_revision": 2,
                "reason": "Rollback acceptance test",
            },
        )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["revision"] == 4
    assert rolled_back.json()["value"] is False


def test_root_must_select_valid_tenant_for_tenant_scope(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get(
            "/api/v1/admin/configuration-center?tenant_id=missing",
            headers=_headers(token),
        )
    assert response.status_code == 422
