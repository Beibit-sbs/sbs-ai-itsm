# M2 — Service Catalog and Request Fulfillment Release Gate

## Decision

**GO / COMPLETED_LOCAL — 2026-07-29**

The local product now satisfies the M2 release gate. Published catalog items
remain inside the governed Service Request process, form and policy history is
immutable, fulfillment is auditable and tenant-scoped, and operational
SLA/showback metrics are visible.

## Gate evidence

### Three representative order types

1. `REQ_BUSINESS_APP_ACCESS`
   - always-approved access workflow;
   - approval and fulfillment completed;
   - zero-cost showback retained.
2. `REQ_GOVERNED_LICENSE`
   - 125,000 KZT monthly cost;
   - high-risk, cost/risk-driven approval;
   - OLA task and automatic SLA pause/resume;
   - completed with SLA met.
3. `REQ_VPN_ACCESS`
   - no-charge, low-risk, no-approval workflow;
   - standard published form v1 backfilled by migration;
   - Network Operations task and OLA;
   - completed with SLA met.

### Process and data integrity

- Approvals, task transitions, SLA pause/resume, and request completion are
  present in immutable request activity and audit history.
- Direct catalog and order paths enforce tenant scope and entitlement.
- Requests retain catalog form version, schema hash, normalized values,
  requester attributes, cost, risk, entitlement, approval, and SLA snapshots.
- Editing or superseding a form does not mutate prior requested items.
- Demand, approval rate, showback, fulfillment duration, and SLA state are
  visible in the operator workspace.

### Orderability safeguard

The gate found that legacy published items without a dynamic form were routed
to generic incident creation. That behavior was removed.

- New catalog publication automatically creates an immutable standard order
  form if no published form exists.
- Migration `20260729_0034` backfills every existing published item without a
  published form.
- The UI no longer offers a generic incident as a fallback for catalog order
  failure.

## Verification

- Backend M2 release-gate suite: **82 passed**.
- Focused catalog orderability/regression suite: **13 passed**.
- Ruff: passed.
- Frontend TypeScript/Vite production build: passed, 108 modules.
- PostgreSQL Alembic head: `20260729_0034`.
- Local staging:
  - backend and frontend healthy;
  - PostgreSQL and Redis healthy;
  - worker running;
  - migrations, runtime, and websocket readiness green.
- Browser E2E: all three representative requests created and completed in the
  Request Fulfillment workspace.

## Deferred boundary

Server, DNS, trusted TLS, external identity-provider cutover, holiday-calendar
integration, ERP posting, and protected binary attachment storage remain
separate production/environment stages. None blocks local M2 product depth.

## Next milestone

`M3 — Enterprise CMDB and Service Mapping`, beginning with
`CMDB-001-CI-CLASS-MODEL`.
