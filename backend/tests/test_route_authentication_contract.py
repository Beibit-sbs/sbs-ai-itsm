from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_route_authentication_validator_has_bounded_public_allowlist() -> None:
    validator = (
        ROOT / "scripts" / "validate_route_authentication.py"
    ).read_text(encoding="utf-8")

    assert "endpoint_count < 700" in validator
    assert '"Depends(get_current_user)"' in validator
    assert '"Depends(get_scim_connector)"' in validator
    assert '"Depends(service_bearer)"' in validator
    assert "PUBLIC_ENDPOINTS" in validator
    assert '("health.py", "readiness")' in validator
    assert '("auth.py", "login")' in validator


def test_legacy_inbound_webhook_is_hidden_authenticated_and_tenant_scoped() -> None:
    routes = (
        ROOT
        / "backend"
        / "app"
        / "api"
        / "v1"
        / "routes"
        / "integrations.py"
    ).read_text(encoding="utf-8")

    assert '"/inbound/{path:path}"' in routes
    assert "include_in_schema=False" in routes
    assert "current_user: AuthUserResponse = Depends(get_current_user)" in routes
    assert 'require_permissions(current_user, "integrations.webhooks.manage")' in routes
    assert "_filter_by_tenant(" in routes
