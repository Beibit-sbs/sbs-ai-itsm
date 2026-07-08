# SECURITY-HARDENING-001 Report

## Goal

Strengthen production security posture of the existing foundation without adding business modules.

## Implemented Changes

### 1. Auth hardening

- Added configurable token lifetimes via settings:
  - `access_token_ttl_minutes`
  - `refresh_token_ttl_minutes`
- JWT payload now includes `jti` and validation checks required claims.
- Refresh flow now blocks inactive users.
- Added audited logout endpoint: `POST /api/v1/auth/logout`.

### 2. Password policy

- User creation in admin now enforces password policy.
- Minimum length is loaded from `password_min_length` system setting.
- In `DEMO_MODE=false`, weak demo-like passwords are rejected.

### 3. RBAC and tenant safety

- Existing backend permission checks preserved and verified by tests.
- Additional denial tests added for requester/IT Agent on sensitive endpoints.

### 4. API error safety

- Added global sanitized 500 handler to prevent traceback leaks.
- Existing structured 401/403/404/422 behavior preserved.

### 5. Upload security

- Asset preview now safely converts unexpected parse failures into controlled 400 response.
- Added tests for wrong extension and oversized upload payload.

### 6. Docker and nginx production hardening

- Backend Docker image runs as non-root user.
- Frontend runtime switched to unprivileged nginx image.
- nginx config updated with:
  - security headers
  - explicit upload size limit
  - unprivileged port listen
- Production compose updated with:
  - read-only root filesystems (backend/frontend)
  - tmpfs mounts
  - frontend healthcheck
  - unprivileged frontend port mapping

### 7. Docs

- Added security guide: `docs/SECURITY.md`.
- Updated env templates with token TTL vars.

## Test Coverage Added/Extended

- Inactive user login denied and token-based access denied after deactivation.
- Failed login audit event asserted.
- Logout endpoint audit event asserted.
- Requester denied admin/security endpoints.
- IT Agent denied admin/integrations manage/automation manage endpoints.
- Upload wrong extension denied.
- Oversized upload denied.
- Audit for automation manual run and report export asserted.
- Production mode no-demo-seed behavior asserted.

## Validation Commands

- `backend`: pytest
- `frontend`: `npx tsc -b --pretty false`
- `frontend`: `npm run build`
- `infra`: `docker compose config`

## Result

- Security controls tightened with no business module expansion.
- Existing module behavior preserved.
- Added checks align with requested acceptance criteria for SECURITY-HARDENING-001.
