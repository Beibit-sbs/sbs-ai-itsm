# SECURITY OPERATIONS CHECKLIST

## Privileged MFA

- Confirm `Admin → Security → Покрытие MFA` reports `Privileged gap = 0`.
- After initial enrollment, require `MFA_ENFORCEMENT_ENABLED=true` in production.
- Confirm each security administrator uses an MFA-verified session before
  resetting another user's factor.
- Store recovery codes only in an approved vault and rotate them after any
  suspected exposure.
- Alert on repeated `login_mfa_failed`, `mfa_admin_reset`, and `mfa_disabled`
  audit events.
- Follow `docs/operations/MFA-RUNBOOK.md` for lost devices and key incidents.

## Secrets And Credentials
- Use separate strong random values for JWT, bootstrap root, metrics, PostgreSQL and Redis credentials.
- Rotate database/Redis credentials and verify application connectivity after rotation.
- Confirm no default demo passwords remain in production env files.
- Remove bootstrap root credentials after the first root account is created and its password is rotated.
- Confirm `LOGIN_RATE_LIMIT_ATTEMPTS`, `LOGIN_IP_RATE_LIMIT_ATTEMPTS`, and
  `LOGIN_RATE_LIMIT_WINDOW_SECONDS` match the approved credential-abuse policy;
  investigate elevated `login_failed` and HTTP 429 rates instead of weakening
  the thresholds.
- Keep `.env.production` outside git tracking.
- Keep secret values out of `.env.production`; use files in `SECRETS_DIR` or an external secret manager.
- Confirm `secrets.example` is never selected by a production deployment.
- Keep direct alert-channel credentials in the four `jobs_alert_*` Docker
  secret files. A disabled sentinel means the channel is intentionally off;
  never replace it with a fabricated test value in production.

## Runtime Hardening
- Confirm `DEMO_MODE=false`.
- Run `python scripts/validate_legacy_integration_boundary.py`; confirm the
  Integrations UI exposes only the production control plane and every legacy
  mutation returns HTTP 410 for an authorized operator.
- Run `python scripts/validate_automation_execution_integrity.py`; require mock
  email/report actions to remain simulated, unsupported actions to remain
  skipped, and classic runbooks to remain pending until every step is reached.
- Run `python scripts/validate_email_delivery_integrity.py`; require every mock
  email and connection test to remain `SIMULATED`, with no transport ID,
  accepted/sent/delivered timestamp, success counter, or healthy readiness.
- Run `python scripts/validate_teams_delivery_integrity.py`; require every mock
  Teams card/test to remain `SIMULATED`, with no HTTP success, provider
  reference, sent timestamp, attempt, success counter, or production room route.
- Run `python scripts/validate_ai_provider_evidence.py`; require local mock AI
  and every external-provider fallback to remain explicit simulation with
  requested/effective provider, model, execution mode, zero external cost, and
  no connection-success or live-provider claim.
- Run `python scripts/validate_permission_aware_ui.py`; require navigation,
  direct routes, Dashboard requests, metrics, and actions to derive from the
  authenticated effective permission union rather than built-in role names.
- Require every non-root role with `tickets.read` to have an intentional
  `tickets.scope.all`, `tickets.scope.assigned`, or `tickets.scope.requester`;
  verify a deliberately unscoped custom role receives no ticket records.
- Confirm requester and bare ticket-reader roles do not receive
  `monitoring.events.read` or `major_incidents.read`; direct Event Operations
  and Major Incident API attempts must return 403.
- Require every non-root role with `requests.read` to have an intentional
  `requests.scope.all` or `requests.scope.requester`, unless its manage/fulfill/
  approve capability deliberately implies all-queue scope.
- Verify custom Asset roles are authorized by exact `assets.*` permissions and
  do not require an `organization_admin`, `it_manager`, or `it_agent` role code.
- Treat the permission-aware UI as defense-in-depth only. Confirm protected API
  routes still return 403 for direct bypass attempts.
- Confirm `RUN_STARTUP_DDL=false`.
- Confirm CORS origins are explicit production domains (no wildcard).
- Confirm `FRONTEND_BIND_ADDRESS=127.0.0.1` when TLS is terminated by a same-host reverse proxy.
- Confirm `TRUSTED_HOSTS` contains only approved public domains plus the
  internal `backend` scrape target.
- Confirm `TLS_PROXY_CIDR` is the exact `EDGE_GATEWAY` address and
  `FORWARDED_ALLOW_IPS` is the exact `FRONTEND_EDGE_IP`; never use `*` or a
  default route.
- Run `python scripts/validate_edge_security.py` and retain the output.
- Confirm `/api/v1/metrics` rejects requests without its bearer token.
- Confirm WebSocket handshake tokens expire within five minutes and cannot be replayed.
- Confirm admin/root accounts are reviewed and RBAC scope is minimal.
- Confirm global roles remain read-only for tenant administrators and cannot be assigned across scope.
- Confirm built-in tenant roles are read-only for non-root administrators;
  use custom tenant roles for local permission changes.
- Confirm every tenant has at least two active organization administrators
  before planned role rotation or identity deprovisioning.
- Confirm non-root role administrators can see and delegate only permissions
  they currently hold; rejected privilege-amplification attempts must return
  403 without changing the target role or user.
- Review active sessions in `Admin → Security`; revoke stale or unexpected sessions immediately.
- Require `Admin → Identity & SSO` to report `READY` after every Identity Provider
  configuration or secret rotation, then run the audited OIDC discovery check.
- Confirm the SSO console exposes only `configured` flags for client credentials and
  never returns the client secret value.
- When an account is disabled or its password is reset after suspected compromise, verify all active
  sessions were revoked and the corresponding audit event was recorded.

## Data Protection
- Verify DB backup execution (`bash scripts/backup-db.sh`).
- Verify backup artifact retention policy and storage permissions.
- Run periodic restore drills in a safe environment.
- Never run `docker compose down -v` in production operations without an approved data-loss plan.

## Network And Edge
- Enforce HTTPS/reverse proxy for external traffic.
- Restrict exposed ports with firewall/security groups.
- Ensure only required ports are reachable from untrusted networks.

## Monitoring And Audit
- Check backend/frontend/container logs regularly.
- Confirm health/readiness/liveness endpoints are reachable.
- Verify deep diagnostics are accessible only for privileged users.
- Validate external integration providers are mock-safe or explicitly disabled for non-approved environments.
- Require legacy integration events/imports to remain `simulated` with zero
  confirmed-delivery/import counters. Investigate any mock-linked `success`
  record as invalid evidence.
- Review automation `partial`, `simulated`, `skipped`, and `failed` runs rather
  than treating them as success. Investigate cross-tenant not-found probes and
  any mock email carrying a transport timestamp.
- Review email `SIMULATED` separately from `ACCEPTED`, `SENT`, and `DELIVERED`;
  a simulated message is a local preview and must never be included in
  production delivery success or retried as a transport failure.
- Review Teams `SIMULATED` separately from `SENT`; a simulated Adaptive Card is
  a local preview and proves neither a Workflow invocation nor channel receipt.
- Confirm Prometheus targets and SLO rules are healthy, and Grafana anonymous access/sign-up remain disabled.
- Confirm Alertmanager routing is healthy and its UI remains loopback-only or behind the approved TLS edge.
- Run `python scripts/validate_alert_delivery.py`; for every configured direct
  channel, require provider-side delivery evidence and correlate it with the
  `jobs.alert.delivery_attempted` audit record. Zero or partial confirmation is
  a delivery incident, not success.
- Run `GET /api/v1/admin/audit-logs/integrity` with a security account and require `valid=true`.
- Export audit events and chain-head anchors on a schedule to append-only/WORM storage under
  separate credentials; the in-database hash chain is tamper-evident, not a substitute for an
  independently retained anchor against privileged deletion of both events and their head.
- Review OIDC identity links, allowed email domains, auto-provisioning and the break-glass account quarterly.
- Review custom role permission matrices quarterly and after every administrative role change.
