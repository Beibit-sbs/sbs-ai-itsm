# PROBLEM-MANAGEMENT-001 — RCA and Known Error Database

## Outcome

SBS AI ITSM now has a tenant-scoped Problem Management domain that separates rapid incident
restoration from structural root-cause elimination. Recurring incidents can be correlated,
RCA evidence is lifecycle-controlled, verified workarounds are published through KEDB, and
permanent corrections can be linked to production Change Requests.

## Delivered

- Reactive and proactive Problem records with backend-calculated P1–P4 priority.
- Explicit lifecycle from intake through investigation, root cause, Known Error, resolution,
  effectiveness validation, closure, reopen, cancellation, and workaround retirement.
- Optimistic concurrency with PostgreSQL row locking and HTTP 409 stale-write protection.
- Tenant-safe incident, asset, and corrective RFC relationships.
- Immutable RCA history and tamper-evident audit events for every mutation.
- Active Known Error Database that remains searchable after Problem resolution or closure.
- Server-side publication evidence controls and dedicated KEDB publication permission.
- Aging, overdue, critical, Known Error, and recurring-incident summary metrics.
- Problem register, RCA workspace, lifecycle controls, and searchable KEDB at `/problems`.
- Active KEDB workarounds surfaced directly in the Service Desk ticket view.
- Additive Alembic revision `20260720_0027` with previous-head upgrade coverage.
- Operator runbook at `docs/operations/PROBLEM-MANAGEMENT-RUNBOOK.md`.

## API surface

- `GET /api/v1/problems`
- `GET /api/v1/problems/summary`
- `GET /api/v1/problems/known-errors`
- `GET /api/v1/problems/{id}`
- `POST /api/v1/problems`
- `PATCH /api/v1/problems/{id}`
- `POST /api/v1/problems/{id}/transitions`

All mutation APIs use `expected_version`; stale operations return HTTP 409.

## Safety controls

- Requesters cannot access the internal Problem register or KEDB.
- All linked records must exist in the same tenant.
- Known Errors cannot be published before root cause identification.
- Publication requires a searchable title and actionable workaround.
- Resolution and closure require separate evidence.
- Reopen requires a reason and reactivates investigation.
- Workarounds can be retired only after resolution or closure.
- Published Known Errors are excluded from active KEDB after controlled retirement.

## Validation

- Focused backend and migration tests cover lifecycle, evidence gates, RBAC, relationship
  validation, stale writes, KEDB persistence, reopen, and retirement.
- Full backend regression: **483 passed, 16 skipped**, with no failures.
- Ruff validation passes for the application, tests, and the new migration.
- Frontend TypeScript compilation and the production Vite build pass.
- Browser QA completed the full lifecycle from Problem creation through investigation,
  root-cause identification, Known Error publication, resolution, effectiveness validation,
  and closure at version `v6`.
- The published workaround remains searchable in KEDB after closure and is surfaced directly
  in the linked Service Desk incident `SD-1001`.
- Responsive QA at `390 x 844` found no document-level horizontal overflow; browser console
  validation reported no errors or warnings.

## Next recommended product stage

`RELEASE-MANAGEMENT-001-RELEASE-TRAIN`:

- release records, versions, packages, and environments;
- release train calendar and deployment readiness gates;
- linked RFC aggregation and dependency controls;
- go/no-go approvals, deployment evidence, and rollback coordination;
- release success, change failure, and deployment frequency analytics.
