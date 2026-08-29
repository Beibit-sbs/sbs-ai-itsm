# INT-COLLAB-001 — Teams Collaboration Pending Runtime Gate

## Outcome

The local implementation is complete and statically verified. Runtime
acceptance remains part of the accumulated release gate because the current
execution environment cannot run the project test/container runtime.

## Delivered

- tenant-scoped Teams Workflow connectors with separate Service Desk,
  approvals, Major Incident, and security purposes;
- encrypted webhook storage, Microsoft-host allowlisting, no redirect
  following, explicit timeouts, and secret-safe API responses/audit;
- Adaptive Card payloads with redaction and same-origin authenticated ITSM
  actions;
- transactional outbox, idempotency, retry/backoff, `Retry-After`,
  dead-letter, manual recovery, and delivery health;
- automatic Teams fan-out from domain notifications without network work in
  request transactions;
- automatic Major Incident room records and cards for declare, update, and
  transition operations;
- Teams administration workspace for readiness, connectors, delivery queue,
  Major Incident rooms, and guided setup;
- RBAC, audit events, migration `20260729_0048`, configuration examples,
  worker integration, tests, and operations runbook.

## Security decisions

- Ordinary app-only Microsoft Graph channel posting is excluded because the
  documented application permission is intended for migration.
- Workflow Webhooks use `Action.OpenUrl`; approval decisions are not accepted
  from unauthenticated card callbacks.
- Every action returns to the configured HTTPS ITSM origin and is evaluated by
  the existing login, tenant, RBAC, object-state, and audit controls.
- Workflow URLs are encrypted with connector- and tenant-bound additional
  authenticated data and never returned by the API.

## Static evidence

The stage is required to pass:

- Ruff over the complete backend and relevant tests/scripts;
- Python compileall;
- TypeScript `tsc --noEmit`;
- Alembic single-head inspection through `0048`;
- OpenAPI route inspection;
- development and production Compose parsing;
- `git diff --check`.

Runtime pytest, database migration execution, worker/provider delivery,
production frontend bundling, and browser acceptance remain pending and must not
be represented as completed.

## Runtime acceptance checklist

- create/test/activate a Mock connector in demo mode;
- prove tenant isolation and connector secret non-disclosure;
- create an event and observe `QUEUED → SENT`;
- prove duplicate suppression and manual retry;
- inject timeout, `429`, permanent `4xx`, and exhausted retry cases;
- verify approval link requires authentication and rejects cross-tenant access;
- declare/update/resolve/close a Major Incident and verify room lifecycle;
- test a real Teams Workflow in the target Microsoft 365 tenant;
- execute focused tests in `backend/tests/test_teams_collaboration.py`;
- run the full regression suite and browser acceptance.

