# INT-API-001 — Integration Platform Controls Pending Runtime Gate

**Stage:** `INT-API-001-INTEGRATION-PLATFORM-CONTROLS`  
**Status:** implementation complete; runtime release gate pending  
**Date:** 2026-07-29

## Outcome

The platform now has a production-shaped, tenant-isolated integration control
plane alongside the clearly separated legacy demo registry.

Administrators can create least-privilege machine identities, issue and rotate
opaque API tokens, configure signed outgoing webhooks, inspect delivery health,
recover dead letters, and use a versioned connector contract from the product
UI.

## Delivered

### Service accounts and API tokens

- Tenant-scoped service accounts with ACTIVE, SUSPENDED, and irreversible
  REVOKED lifecycle.
- Scope allowlists, IP/CIDR restrictions, per-minute limits, token TTL policy,
  active-token cap, usage counters, and optimistic versioning.
- High-entropy opaque bearer tokens returned once.
- Only SHA-256 token verifiers, lookup prefixes, and safe hints persist.
- Atomic token rotation and account-wide revocation.
- `whoami`, event publishing, tenant-safe ticket read, and asset read SDK
  endpoints.
- Effective permissions are the intersection of account and token scopes.
- Secret-safe allowed/denied request logging.

### Governed connector intake

- Service-account-scoped idempotency with PostgreSQL transaction advisory
  locking for concurrent duplicate events.
- Stable integration event records and outbound fanout.
- Bounded payloads, event-type validation, nesting limits, and rejection of
  secret-like fields.
- Tenant isolation on every SDK lookup.

### Signed outgoing webhooks

- DRAFT, ACTIVE, PAUSED, and irreversible REVOKED lifecycle.
- Exact HTTPS destination allowlist and local-demo-only HTTP exception.
- No URL credentials/fragments, no redirects, bounded timeout, bounded
  response reads.
- AES-GCM encrypted target URLs, signing secrets, and queued CloudEvent
  payloads with tenant/resource-bound associated data.
- CloudEvents 1.0 structured JSON.
- HMAC-SHA256 signature over timestamp and exact raw body.
- Current target and signing-secret versions must pass a queued test before
  activation.
- URL/secret changes pause the subscription and invalidate test evidence.
- Pending business deliveries remain queued while paused.

### Delivery reliability and operations

- Durable PENDING, PROCESSING, RETRY, SUCCEEDED, FAILED, DEAD_LETTER, and
  CANCELLED states.
- Retry for network errors, `408`, `425`, `429`, and `5xx`.
- Exponential backoff, bounded `Retry-After`, maximum attempts, and DLQ.
- Permanent errors fail without unbounded retry.
- Replay produces a new linked, freshly encrypted delivery.
- Per-attempt HTTP status, latency, provider request ID, safe error, and
  target/secret versions used.
- Replica-safe worker locking and batch limits.
- Configurable request-log and completed-delivery retention with hourly
  worker cleanup.
- Notification events and SDK events fan out transactionally to active matching
  subscriptions.

### Administration UX

- **Integrations → Production API & Webhooks** is now the default workspace.
- Tenant selector for SaaS Root.
- Health dashboard and outbound allowlist readiness.
- Service-account create/edit/suspend/revoke.
- Scope, CIDR, rate-limit, and TTL policy controls.
- Token issue/rotation/revocation with one-time copy panel.
- Webhook create/edit/test/activate/pause/rotate/revoke.
- Polling delivery/DLQ console with governed replay.
- Machine API audit filters.
- Connector SDK and signature examples.
- Legacy tabs are explicitly labelled demo/mock.

### Platform integration

- Five additive tables and migration
  `20260729_0051_integration_platform.py`.
- Nine dedicated RBAC permissions with role mappings.
- Worker integration and deployment configuration examples.
- Legacy mock credential writes and legacy inbound webhooks return `410`
  outside demo mode.
- Focused tests-as-code cover hashing, scope/IP/rate/revocation, active-token
  cap, exact allowlisting, encryption, CloudEvents, HMAC, idempotency,
  retry/DLQ/replay, pause preservation, SDK idempotency, and secret-field
  rejection.
- Operations runbook:
  `docs/operations/INTEGRATION-PLATFORM-RUNBOOK.md`.

## Static evidence

The stage gate includes:

- full backend Ruff inspection;
- Python bytecode compilation;
- frontend TypeScript no-emit validation;
- single Alembic head inspection through `20260729_0051`;
- generated OpenAPI inspection for control-plane and SDK routes;
- development and production Compose parsing;
- whitespace/error inspection with `git diff --check`.

Static acceptance completed successfully on 2026-07-29:

- Ruff: all backend application, migration, and test files passed;
- compileall: backend application, migrations, and tests compiled;
- TypeScript: `tsc -p tsconfig.app.json --noEmit` passed;
- Alembic: exactly one head, `20260729_0051`;
- OpenAPI: 488 total paths, including 19 integration-platform paths and 22
  operations; SDK endpoints advertise `ServiceAccountBearer`;
- development and production Compose configurations parsed successfully;
- `git diff --check` found no whitespace errors (only expected Windows line
  ending notices).

## Runtime gate still required

Privileged pytest/Docker execution and the native production frontend bundle
are unavailable in the current execution environment. The following claims
are deliberately deferred:

- focused and full backend pytest;
- real migration upgrade/downgrade rehearsal against PostgreSQL;
- production frontend bundle;
- API/worker readiness and browser acceptance;
- live HTTPS receiver signature/retry contract test.

No runtime completion claim is made.

## Exit decision

Implementation may advance to `WF-001` under the program's single accumulated
runtime-gate policy. Production release remains prohibited until the deferred
checks and the runbook release checklist pass.
