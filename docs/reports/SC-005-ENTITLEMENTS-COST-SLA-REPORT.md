# SC-005 — Entitlements, Cost, and SLA

## Outcome

Catalog ordering is now governed by authoritative requester attributes,
financial and risk policy, and measurable fulfillment commitments. Policy is
enforced in both discovery and direct-order paths, and the exact decision
context is snapshotted on the request so later catalog or user changes cannot
rewrite history.

## Delivered

- Additive Alembic revision `20260729_0033`.
- Entitlements by tenant, user, role, department, location, and cost center,
  with `ALL` and `ANY` matching.
- Manager/root bypass for catalog administration without weakening requester
  enforcement.
- User profile fields for department, location, and cost center.
- Catalog governance configuration:
  - unit cost, currency, one-time/recurring/no-charge cost type;
  - risk level;
  - cost- and risk-based approval policy;
  - approver roles and sequential/parallel mode;
  - SLA, OLA, 24x7 or weekday calendar, warning, pause, and escalation policy.
- Immutable request snapshots for requester attributes, financial allocation,
  risk, entitlement, approval, and SLA policy.
- Cost/risk-driven approval rounds and task OLA deadlines.
- SLA lifecycle:
  - calculated service-calendar deadline;
  - manual pause and resume;
  - automatic pause while a fulfillment task waits;
  - automatic resume when work continues;
  - deadline shift by paused duration;
  - at-risk, breached, completed, and escalation states;
  - auditable timeline entries.
- Tenant-safe governance analytics for demand, showback, cost center, approval
  ratio, fulfillment time, and SLA health.
- Operator UI for catalog governance, request showback/SLA analytics, SLA
  controls, OLA deadlines, and user location/cost-center administration.

## API surface

- `POST /api/v1/requests/items/{requested_item_id}/sla/pause`
- `POST /api/v1/requests/items/{requested_item_id}/sla/resume`
- `POST /api/v1/requests/sla/evaluate`
- `GET /api/v1/requests/analytics/governance`

Catalog item and request APIs now expose the applicable governance fields and
snapshots.

## Security and data invariants

- Non-entitled requesters do not see restricted items in catalog lists.
- Direct item, favorite, view, knowledge-suggestion, and order paths repeat the
  entitlement check and return not found or forbidden as appropriate.
- Tenant scope is applied before entitlement and analytics evaluation.
- Cost, currency, cost center, risk, form version, and policies are copied to
  the request and requested item at submission time.
- Approval is computed from canonical policy and the snapshotted cost/risk.
- SLA transitions and escalation produce immutable activity and audit records.
- Invalid entitlement, approval, or SLA policy is rejected before persistence.

## Local acceptance

- Related backend regression: **71 passed**.
- Focused governance tests: **2 passed**.
- Ruff on touched backend and test files: passed.
- TypeScript production build: passed, 108 modules transformed.
- PostgreSQL migration head: `20260729_0033`.
- Readiness:
  - PostgreSQL: ok;
  - Redis: ok;
  - migrations: ok;
  - runtime: ready;
  - websocket transport: ready.
- Browser acceptance:
  1. created and published `REQ_GOVERNED_LICENSE`;
  2. configured requester/Finance entitlement, 125,000 KZT monthly cost,
     high risk, approval threshold, two-hour SLA, and one-hour OLA;
  3. published form version 1 and submitted a request;
  4. verified the 125,000 KZT showback and high-risk snapshot;
  5. approved the request and verified the generated task and OLA deadline;
  6. moved the task to waiting and observed automatic SLA pause plus audit;
  7. resumed work and observed automatic SLA resume;
  8. completed the task and verified request completion, zero active tasks,
     SLA completion, and the complete timeline.

The staging rollout also exposed an operational rule: the dedicated `migrate`
image must be rebuilt whenever backend migrations change. The final rollout
rebuilt `migrate`, applied `0033`, and returned all readiness checks to green
without deleting application data.

## Production boundary

SC-005 is production-grade locally. The M2 release gate still needs one formal
cross-feature acceptance pass proving three representative request types and
the milestone-level tenant/audit/snapshot invariants. Server, trusted TLS, and
external organization systems remain intentionally deferred.

## Next product stage

`M2-RELEASE-GATE-001`, then `CMDB-001-CI-CLASS-MODEL`.
