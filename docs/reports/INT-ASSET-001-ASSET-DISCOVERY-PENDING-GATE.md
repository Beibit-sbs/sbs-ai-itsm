# INT-ASSET-001 — Asset Discovery Implementation Pending Runtime Gate

**Stage:** `INT-ASSET-001-ASSET-DISCOVERY`  
**Status:** implementation complete; runtime release gate pending  
**Date:** 2026-07-29

## Outcome

The existing governed CMDB reconciliation foundation now has production-shaped
asset discovery for:

- Microsoft Intune managed devices;
- Azure Resource Graph cloud inventory;
- Microsoft Configuration Manager AdminService;
- Lansweeper Data API.

The implementation is local-first and additive. It does not perform server
cutover or claim runtime release acceptance.

## Delivered

### Connector control plane

- Tenant-scoped connectors bound one-to-one to active `DISCOVERY` CMDB sources.
- DRAFT, ACTIVE, PAUSED, and irreversible REVOKED lifecycle.
- Provider/auth compatibility validation.
- AES-GCM encrypted credentials bound to tenant and connector.
- Secret-safe API responses, credential hints, versioning, rotation, and audit.
- Successful test of the current credential version required before
  activation.
- Credential rotation pauses active connectors and requires retest.
- Fixed public provider hosts and exact SCCM HTTPS host allowlisting.

### Fetch and normalization

- OAuth client credentials for Microsoft Graph and Azure Resource Graph.
- Intune managed-device pagination and normalized hardware/user/OS facts.
- Azure Resource Graph API `2024-04-01`, subscription scope, KQL, and
  `$skipToken` pagination.
- SCCM AdminService OData pagination with Bearer or Basic transport.
- Lansweeper GraphQL PAT/OAuth transport with cursor pagination.
- No redirects, bounded response streaming, bounded timeouts, same-origin
  pagination, page-loop detection, and provider error redaction.
- Stable bounded external identifiers and duplicate external-ID rejection.

### Governed reconciliation

- Provider output enters the existing CMDB preview/apply pipeline in batches of
  at most 500.
- Schema validation, source priority, field ownership, duplicate handling,
  provenance, and reconciliation history remain authoritative.
- Optional auto-apply only for batches with no invalid or ambiguous records.
- Run records retain all linked reconciliation run IDs and outcome counters.

### Scheduling and recovery

- Durable scheduled/manual runs with idempotency, attempts, retry/backoff,
  `Retry-After`, failure, cancellation, and dead-letter states.
- Multiple pending runs for the same connector are rejected.
- PostgreSQL due scheduling and per-run processing use row-lock protection for
  worker replicas.
- Connector/run health counters and a discovery dashboard are available.

### Stale-device governance

- Missing state advances only after a complete successful snapshot.
- Record-limit truncation and pagination failure cannot create stale evidence.
- Configurable consecutive-missing threshold.
- Explicit OPEN, DISMISSED, RECOVERED, and RETIRED candidate lifecycle.
- No automatic deletion or retirement.
- Retirement requires optimistic version, permission, and reason; it updates CI
  lifecycle and records asset history plus audit evidence.
- Human retirement is sticky and cannot be silently reversed by discovery.

### Administration UX

- New **Активы и CMDB → Asset Discovery** workspace.
- Guided source/connector creation for all four providers.
- Provider-specific configuration and secret inputs.
- Health cards, current-credential test status, activate/pause/run actions,
  policy editing, rotation, and permanent revocation.
- Polling run history and stale-candidate review.
- SaaS Root tenant selector and permission-aware actions.

### Platform integration

- Additive Alembic migration `20260729_0050_asset_discovery.py`.
- Worker cycle integration.
- Permissions:
  `asset.discovery.read`, `asset.discovery.manage`,
  `asset.discovery.run`, and `asset.discovery.review`.
- Configuration examples for local and production deployment.
- Focused tests-as-code for validation, encryption binding, provider
  normalization, complete-snapshot safety, sticky retirement, audit history,
  duplicate rejection, and stale recovery.
- Operations runbook:
  `docs/operations/ASSET-DISCOVERY-RUNBOOK.md`.

## Static evidence

The stage quality gate includes:

- full backend Ruff inspection;
- Python bytecode compilation;
- frontend TypeScript no-emit validation;
- single Alembic head inspection through `20260729_0050`;
- generated OpenAPI inspection for the Asset Discovery surface;
- development and production Compose parsing;
- whitespace/error inspection with `git diff --check`.

These checks must remain green in the final stage snapshot.

## Runtime gate still required

The current execution environment cannot run the privileged pytest/Docker
runtime gate until its external execution allowance is restored. The following
claims are therefore deliberately deferred:

- focused and full backend pytest;
- real migration upgrade/downgrade rehearsal against the release database;
- production frontend bundle;
- API/worker readiness and browser acceptance;
- live provider contract tests using tenant-owned Intune, Azure, SCCM, and
  Lansweeper credentials.

No runtime completion claim is made by this report.

## Exit decision

Implementation may advance to `INT-API-001` under the program's single
accumulated runtime-gate policy. Production release remains prohibited until
the deferred runtime checks and provider-specific acceptance checklist in the
runbook pass.

