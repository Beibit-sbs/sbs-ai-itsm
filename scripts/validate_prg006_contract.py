from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    workload = json.loads(
        (ROOT / "performance" / "workload-profile.json").read_text(
            encoding="utf-8"
        )
    )
    security = json.loads(
        (ROOT / "security" / "acceptance-catalog.json").read_text(
            encoding="utf-8"
        )
    )
    middleware = (
        ROOT / "backend" / "app" / "core" / "middleware.py"
    ).read_text(encoding="utf-8")
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    settings = (
        ROOT / "backend" / "app" / "core" / "config.py"
    ).read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    admin_routes = (
        ROOT / "backend" / "app" / "api" / "v1" / "routes" / "admin.py"
    ).read_text(encoding="utf-8")
    admin_tests = (
        ROOT / "backend" / "tests" / "test_admin_security.py"
    ).read_text(encoding="utf-8")
    identity_lifecycle = (
        ROOT / "backend" / "app" / "services" / "identity_lifecycle.py"
    ).read_text(encoding="utf-8")
    admin_ui = (
        ROOT / "frontend" / "src" / "pages" / "AdminPage.tsx"
    ).read_text(encoding="utf-8")
    dast = (
        ROOT / ".github" / "workflows" / "staging-dast.yml"
    ).read_text(encoding="utf-8")

    profiles = workload.get("profiles", {})
    _require(
        {"baseline", "peak", "soak"} <= profiles.keys(),
        "Workload contract must define baseline, peak and soak profiles",
    )
    for name, profile in profiles.items():
        thresholds = profile.get("thresholds", {})
        _require(
            int(profile.get("duration_seconds", 0)) > 0,
            f"{name} duration must be positive",
        )
        _require(
            int(profile.get("concurrency", 0)) > 0,
            f"{name} concurrency must be positive",
        )
        _require(
            {
                "http_error_percent_max",
                "http_p95_ms_max",
                "http_p99_ms_max",
                "websocket_failure_percent_max",
            }
            <= thresholds.keys(),
            f"{name} misses acceptance thresholds",
        )

    controls = security.get("controls", [])
    control_types = {item["type"] for item in controls}
    _require(
        {
            "SCA",
            "SAST",
            "IMAGE",
            "SECRET",
            "ABUSE",
            "ISOLATION",
            "EDGE",
            "SESSION",
            "DAST",
        }
        <= control_types,
        "Security catalog misses a required control type",
    )
    _require(
        all(item.get("owner") and item.get("acceptance") for item in controls),
        "Every security control must have owner and acceptance criteria",
    )
    _require(
        any(item.get("id") == "SEC-PRIVILEGE-DELEGATION" for item in controls),
        "Security catalog misses privilege-delegation enforcement",
    )
    _require(
        {
            "SEC-SYSTEM-ROLE-INTEGRITY",
            "SEC-TENANT-ADMIN-CONTINUITY",
            "SEC-ROUTE-AUTHENTICATION-CONTRACT",
            "SEC-EDGE-HOST-BOUNDARY",
            "SEC-FORWARDED-IDENTITY-CHAIN",
            "SEC-REFRESH-TOKEN-FAMILY",
            "SEC-SELF-SERVICE-SESSIONS",
            "SEC-SELF-PASSWORD-CHANGE",
            "SEC-LEGACY-INTEGRATION-SIMULATION-BOUNDARY",
            "SEC-AUTOMATION-EXECUTION-INTEGRITY",
            "SEC-EMAIL-DELIVERY-INTEGRITY",
            "SEC-TEAMS-DELIVERY-INTEGRITY",
        }
        <= {str(item.get("id")) for item in controls},
        "Security catalog misses protected-role continuity controls",
    )
    _require(
        "_ensure_permissions_delegable" in admin_routes
        and admin_routes.count("_ensure_permissions_delegable(") >= 4
        and "Permission.code.in_(tuple(current_user.permissions))"
        in admin_routes,
        "Role mutation and assignment paths do not enforce bounded delegation",
    )
    _require(
        "test_organization_admin_cannot_amplify_or_delegate_privileges"
        in admin_tests
        and "test_system_tenant_roles_are_read_only_for_organization_admin"
        in admin_tests
        and "test_last_active_organization_admin_cannot_remove_own_admin_role"
        in admin_tests,
        "Administrative role-governance regression is missing",
    )
    _require(
        "role.tenant_id is None or role.is_system" in admin_routes
        and "def ensure_tenant_admin_continuity(" in identity_lifecycle
        and identity_lifecycle.count("ensure_tenant_admin_continuity(") >= 2
        and "selectedRole.is_system" in admin_ui,
        "System-role integrity or tenant-admin continuity enforcement is missing",
    )
    _require(
        "roleAssignRoleIds" in admin_ui
        and "roleIds: roleAssignRoleIds" in admin_ui
        and "test_multiple_roles_produce_an_effective_permission_union"
        in admin_tests,
        "Multi-role administration or effective-permission regression is missing",
    )
    _require(
        "role_ids: list[str]" in admin_routes
        and "ordered_roles = [roles_by_id[role_id] for role_id in role_ids]"
        in admin_routes
        and "test_create_user_with_multiple_roles_preserves_primary_order"
        in admin_tests,
        "Atomic multi-role user creation or primary-role ordering is missing",
    )

    _require(
        "class RequestBodyLimitMiddleware" in middleware
        and "REQUEST_BODY_TOO_LARGE" in middleware,
        "Application streamed body limit is missing",
    )
    _require(
        "limit_req zone=sbs_api_per_ip" in nginx
        and "limit_conn sbs_connections_per_ip" in nginx,
        "Nginx rate/connection limits are missing",
    )
    for variable in (
        "api_max_request_body_bytes",
        "database_pool_size",
        "database_max_overflow",
        "database_pool_timeout_seconds",
        "database_pool_recycle_seconds",
    ):
        _require(variable in settings, f"Capacity setting {variable} is missing")
    for gate in (
        "pip-audit",
        "bandit -r app",
        "npm audit",
        "anchore/scan-action",
        "gitleaks",
    ):
        _require(gate in ci, f"CI security gate {gate} is missing")
    _require(
        "--maxmemory-policy noeviction" in compose
        and "x-logging: &default-logging" in compose
        and compose.count("resources:") >= 7,
        "Compose resource, Redis memory, or log bounds are missing",
    )
    _require(
        "zaproxy/action-baseline@v0.15.0" in dast
        and "environment: staging-security" in dast
        and "STAGING_DAST_URL" in dast,
        "Governed staging DAST workflow is missing",
    )

    for path in (
        "scripts/run_performance_acceptance.py",
        "scripts/run_resilience_acceptance.py",
        "scripts/validate_route_authentication.py",
        "scripts/validate_edge_security.py",
        "scripts/validate_session_security.py",
        "scripts/validate_canary_evidence.py",
        "scripts/validate_alert_delivery.py",
        "scripts/validate_legacy_integration_boundary.py",
        "scripts/validate_automation_execution_integrity.py",
        "scripts/validate_email_delivery_integrity.py",
        "scripts/validate_teams_delivery_integrity.py",
        "docs/operations/PERFORMANCE-RESILIENCE-SECURITY-ACCEPTANCE-RUNBOOK.md",
        "docs/operations/EDGE-TRUST-BOUNDARY-RUNBOOK.md",
        "docs/operations/ACCOUNT-SESSION-SECURITY-RUNBOOK.md",
        "docs/operations/CANARY-EVIDENCE-GOVERNANCE-RUNBOOK.md",
        "docs/operations/ALERT-DELIVERY-INTEGRITY-RUNBOOK.md",
        "docs/operations/LEGACY-INTEGRATION-SIMULATION-BOUNDARY-RUNBOOK.md",
        "docs/operations/AUTOMATION-EXECUTION-INTEGRITY-RUNBOOK.md",
        "docs/operations/EMAIL-DELIVERY-INTEGRITY-RUNBOOK.md",
        "docs/operations/TEAMS-DELIVERY-INTEGRITY-RUNBOOK.md",
    ):
        _require((ROOT / path).exists(), f"Required acceptance artifact {path} is missing")

    print(
        "PRG-006 contract valid: "
        f"{len(profiles)} load profiles, {len(controls)} security controls."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PRG-006 contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
