# Security Guide

## Scope

This document describes security controls implemented in the SBS AI ITSM foundation.
It is focused on production hardening and does not introduce new business modules.

## Auth

- Passwords are hashed with `pbkdf2_sha256` and per-password random salt.
- Inactive users cannot authenticate.
- Inactive users are denied access even with previously issued access tokens.
- Access and refresh token TTL are configurable through env:
  - `ACCESS_TOKEN_TTL_MINUTES`
  - `REFRESH_TOKEN_TTL_MINUTES`
- Token validation verifies signature, expiry, token type, and required claims.
- Failed login attempts are written to audit (`login_failed`).
- Logout endpoint (`POST /api/v1/auth/logout`) writes audit (`logout_success`).

## RBAC

- Backend enforces permissions with `require_permissions` checks.
- Tenant isolation is enforced server-side for non-root users.
- Requester and IT Agent roles are blocked from admin/security/integration/automation manage actions unless explicit permissions exist.
- SaaS Root retains global visibility.

## Password Policy

- Minimum length is read from `system_settings.password_min_length`.
- In production mode (`DEMO_MODE=false`) weak demo-like passwords are rejected for user creation.
- Password hashes are never returned by API responses.

## Audit Coverage

Audit events include (non-exhaustive):

- `login_success`
- `login_failed`
- `logout_success`
- `user_created`
- `user_deactivated`
- `role_assigned`
- `setting_changed`
- `ticket_status_changed`
- `asset_import_uploaded`
- `asset_import_preview_generated`
- `asset_import_committed`
- `integration_health_check_executed`
- `automation_manual_run_executed`
- `demo_export_requested`

## Upload Security (Assets)

- Only `.xlsx` is accepted.
- File size is capped (`FILE_SIZE_LIMIT_BYTES`).
- Corrupted/invalid files return safe 400-level messages.
- File payload is not published as public static storage.
- Upload, preview, and commit actions are audited.

## API Error Security

- API returns structured errors:
  - `HTTP_401`, `HTTP_403`, `HTTP_404`
  - `VALIDATION_ERROR` (422)
  - `INTERNAL_ERROR` (500)
- Unhandled exceptions return sanitized 500 response without traceback leaks.

## Docker Production Hardening

- Backend runs as non-root user in container.
- Frontend runs on unprivileged nginx runtime image.
- Restart policies and healthchecks are configured in production compose.
- `docker-compose.prod.yml` uses read-only filesystems with tmpfs where applicable.
- Security headers are configured in nginx.
- Upload body limit is explicitly configured in nginx.
- Secrets are expected from environment files, not baked into images.

## Operational Notes

- Do not run destructive volume commands in production.
- Keep `DEMO_MODE=false` and `RUN_STARTUP_DDL=false` for production.
- Apply Alembic migrations before application rollout.
