from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> int:
    auth = _read("backend/app/api/v1/routes/auth.py")
    admin = _read("backend/app/api/v1/routes/admin.py")
    settings = _read("backend/app/core/config.py")
    security_routes = _read("backend/app/api/v1/routes/security.py")
    audit_model = _read("backend/app/models/audit_log.py")
    model = _read("backend/app/models/auth_session.py")
    user_model = _read("backend/app/models/user.py")
    migration = _read(
        "backend/migrations/versions/20260729_0065_auth_session_context.py"
    )
    password_change_migration = _read(
        "backend/migrations/versions/20260729_0066_required_password_change.py"
    )
    login_abuse_migration = _read(
        "backend/migrations/versions/20260729_0067_login_abuse_indexes.py"
    )
    tests = _read("backend/tests/test_auth.py")
    admin_tests = _read("backend/tests/test_admin_security.py")
    account_page = _read("frontend/src/pages/AccountPage.tsx")
    client = _read("frontend/src/api/client.ts")
    app = _read("frontend/src/App.tsx")
    shell = _read("frontend/src/components/AppShell.tsx")
    require_auth = _read("frontend/src/auth/RequireAuth.tsx")
    controls = json.loads(
        _read("security/acceptance-catalog.json")
    )["controls"]
    control_ids = {str(item["id"]) for item in controls}

    _require(
        ".with_for_update()" in auth
        and "refresh_token_reuse_detected" in auth
        and "_revoke_replacement_chain" in auth
        and "descendant_sessions_revoked" in auth,
        "Refresh rotation lock or descendant-family replay response is missing",
    )
    _require(
        'user.identity_source != "LOCAL"' in auth
        and "Password is managed by the external identity provider" in auth,
        "External identity local-password boundary is missing",
    )
    for route in (
        '@router.get("/account"',
        '@router.get("/sessions"',
        '"/sessions/{session_id}/revoke"',
        '@router.post("/password/change"',
    ):
        _require(route in auth, f"Self-service account route is missing: {route}")
    _require(
        "AuthSession.user_id == current_user.id" in auth
        and "self_session_revoked" in auth
        and "self_password_changed" in auth,
        "Self-session ownership or audit enforcement is missing",
    )

    for field in ("ip_address", "user_agent", "auth_method"):
        _require(
            field in model and field in migration and field in security_routes,
            f"Session context field is not end-to-end: {field}",
        )
    _require(
        'revision: str = "20260729_0065"' in migration
        and 'down_revision: str | None = "20260729_0064"' in migration,
        "Session context migration does not extend the single migration head",
    )
    _require(
        "must_change_password" in user_model
        and 'revision: str = "20260729_0066"' in password_change_migration
        and 'down_revision: str | None = "20260729_0065"'
        in password_change_migration,
        "Required-password-change state or additive migration is missing",
    )
    _require(
        "Password change required before accessing this resource" in auth
        and "password_change_paths" in auth
        and "user.must_change_password = False" in auth,
        "Server-side temporary-password restriction or completion is missing",
    )
    _require(
        "must_change_password=True" in admin
        and "Session revocation is mandatory" in admin
        and '"password_change_required": True' in admin,
        "Administrative temporary-password lifecycle is incomplete",
    )
    _require(
        "DUMMY_PASSWORD_HASH" in auth
        and "candidate_hash" in auth
        and "password_valid = verify_password" in auth
        and "login_ip_rate_limit_attempts" in auth,
        "Constant-work login or two-dimensional abuse control is missing",
    )
    _require(
        "login_ip_rate_limit_attempts" in settings
        and "LOGIN_IP_RATE_LIMIT_ATTEMPTS must be greater" in settings,
        "Login IP-rate configuration is missing or unbounded",
    )
    for index_name in (
        "ix_audit_login_email_window",
        "ix_audit_login_ip_window",
    ):
        _require(
            index_name in audit_model and index_name in login_abuse_migration,
            f"Login abuse query index is missing: {index_name}",
        )
    _require(
        'revision: str = "20260729_0067"' in login_abuse_migration
        and 'down_revision: str | None = "20260729_0066"'
        in login_abuse_migration,
        "Login abuse indexes do not extend the single migration head",
    )

    for test_name in (
        "test_refresh_token_is_rotated_and_cannot_be_replayed",
        "test_every_user_can_inspect_and_revoke_only_own_sessions",
        "test_self_password_change_revokes_sessions_and_never_exposes_secret",
        "test_external_identity_cannot_change_provider_managed_password",
    ):
        _require(test_name in tests, f"Session regression is missing: {test_name}")
    _require(
        "refreshed_access_token" in tests
        and "session family revoked" in tests
        and "descendant_sessions_revoked" in tests,
        "Refresh replay regression does not prove descendant invalidation",
    )
    _require(
        "test_admin_password_reset_revokes_sessions_and_never_audits_password"
        in admin_tests
        and '"revoke_sessions": False' in admin_tests
        and '["must_change_password"] is True' in admin_tests
        and '["must_change_password"] is False' in admin_tests,
        "Temporary-password server enforcement regression is missing",
    )
    for test_name in (
        "test_login_is_rate_limited_by_ip_across_distinct_accounts",
        "test_unknown_account_uses_dummy_password_verification",
        "test_login_input_is_bounded_before_credential_work",
    ):
        _require(test_name in tests, f"Login abuse regression is missing: {test_name}")

    _require(
        "fetchMyAccount" in client
        and "fetchMySessions" in client
        and "revokeMySession" in client
        and "changeMyPassword" in client,
        "Self-service account API client is incomplete",
    )
    _require(
        "MfaEnrollmentPanel" in account_page
        and "local_password_supported" in account_page
        and "account.must_change_password" in account_page
        and "current_session_revoked" in account_page
        and 'path="/account"' in app
        and 'to="/account"' in shell,
        "Every-role account/security UI is not fully reachable",
    )
    _require(
        "session.user.must_change_password" in require_auth
        and 'to="/account"' in require_auth,
        "Client-side required-password-change redirect is missing",
    )

    required_controls = {
        "SEC-REFRESH-TOKEN-FAMILY",
        "SEC-SELF-SERVICE-SESSIONS",
        "SEC-SELF-PASSWORD-CHANGE",
        "SEC-REQUIRED-PASSWORD-CHANGE",
        "SEC-LOGIN-CREDENTIAL-ABUSE",
    }
    _require(
        required_controls <= control_ids,
        "Security catalog misses session lifecycle controls",
    )

    print(
        "Session security contract valid: "
        "5 lifecycle controls, 4 self-service routes, "
        "refresh-family replay containment enabled."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Session security contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
