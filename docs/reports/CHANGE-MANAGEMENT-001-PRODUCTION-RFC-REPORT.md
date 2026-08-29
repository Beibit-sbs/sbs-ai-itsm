# CHANGE-MANAGEMENT-001 — Production RFC Control

## Outcome

SBS AI ITSM now includes an end-to-end, tenant-scoped Change Management module rather
than using tickets or generic automation approvals as a substitute for production change
control.

## Delivered

- Change Request model with versioned assessment, risk, outage and implementation data.
- Explicit state machine from draft through CAB, schedule, execution, review and terminal
  outcomes.
- Server-calculated risk and Standard Change pre-authorization guardrails.
- Immutable CAB/ECAB decision records and requester/approver separation of duties.
- PostgreSQL advisory locking and overlap detection for maintenance on linked assets.
- Links from RFCs to assets and incident/request tickets.
- Immutable business timeline plus tamper-evident security audit events.
- Seven granular RBAC permissions with least-privilege default role mappings.
- Register, summary, RFC creation, decision, execution and timeline UI at `/changes`.
- Additive Alembic revision `20260720_0026` and an upgrade test from the previous head.
- Operator runbook at `docs/operations/CHANGE-MANAGEMENT-RUNBOOK.md`.

## API surface

- `GET /api/v1/changes`
- `GET /api/v1/changes/summary`
- `GET /api/v1/changes/{id}`
- `POST /api/v1/changes`
- `PATCH /api/v1/changes/{id}`
- `POST /api/v1/changes/{id}/decisions`
- `POST /api/v1/changes/{id}/transitions`

All mutation APIs use `expected_version`; stale operations return HTTP 409.

## Safety controls

- Tenant ownership is checked for the RFC and every linked asset/ticket.
- Requesters cannot access the internal change register.
- An RFC requester cannot approve the same RFC.
- Standard Changes with high risk or an outage cannot use the pre-authorized path.
- Scheduling is impossible before approval or without a valid window.
- Conflicting active windows on one linked asset are rejected.
- Post-implementation review, failure, rollback and cancellation outcomes require evidence.

## Validation

- Focused Change Management tests cover Normal, Standard, failure/rollback, stale writes,
  requester denial, self-approval denial and overlapping asset windows.
- Migration test builds a previous-head schema and upgrades it to `20260720_0026`.
- Backend suite: `478 passed, 16 skipped`; Ruff is clean for application and tests.
- Frontend TypeScript and production Vite build pass.
- Browser QA completed a real Normal RFC through creation, CAB handoff, approval,
  scheduling, implementation, review and `COMPLETED` closure.
- Desktop and 390 px mobile layouts pass without horizontal overflow; browser console has
  no errors or warnings, and logout clears retained credentials.

## Next recommended product stage

`PROBLEM-MANAGEMENT-001-KNOWN-ERROR`:

- problem records and root-cause lifecycle;
- incident clustering and problem links;
- workarounds and Known Error Database;
- corrective-action linkage to RFCs;
- recurring-incident and problem-aging analytics.
