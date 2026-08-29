# M2-M8 Common Quality Gate — Runtime Acceptance Pending

Date: 2026-07-29

## Outcome

The accumulated local implementation for milestones M2 through M8 now has a
single machine-readable stage inventory and a reproducible static quality
gate. Every roadmap stage is linked to an implementation report, an
operational runbook, and at least one verification artifact.

This report does not claim runtime or production acceptance. The milestone
statuses remain in progress until the deferred runtime gate is executed and
its evidence is reviewed.

## Covered scope

| Milestone | Local stages | Current claim |
| --- | ---: | --- |
| M2 — Service Catalog and Request Fulfillment | 5 | Completed locally |
| M3 — Enterprise CMDB and Service Mapping | 5 | Implementation complete; runtime pending |
| M4 — ITIL Process Depth | 6 | Implementation complete; runtime pending |
| M5 — Enterprise Integrations and Identity Lifecycle | 6 | Implementation complete; runtime pending |
| M6 — Workflow and No-Code Configuration | 4 | Implementation complete; runtime pending |
| M7 — Governed Production AI | 4 | Implementation complete; runtime pending |
| M8 — UX and Administrative Depth | 5 | Implementation complete; runtime pending |
| **Total** | **35** | **Runtime acceptance pending** |

The authoritative inventory is `release/m2-m8-stage-matrix.json`. Its
validator checks exact stage parity with the master roadmap and verifies that
all referenced evidence files exist. The current result is:

```text
M2-M8 stage matrix valid: 35 stages, 107 evidence links,
runtime acceptance pending.
```

## Quality controls added

- `scripts/validate_m2_m8_stage_matrix.py` prevents a roadmap stage from
  disappearing from the evidence inventory.
- `backend/tests/test_m2_m8_stage_matrix.py` protects milestone coverage,
  evidence presence, uniqueness, and the honest runtime-pending state.
- the validator is part of CI and the consolidated local release-gate runner;
- Service Catalog / Request Fulfillment now has a consolidated operational
  runbook;
- CMDB class and relationship governance now has a consolidated operational
  runbook;
- milestone statuses M3 through M8 consistently distinguish implementation
  completion from live acceptance.

## Deferred runtime acceptance

The following checks require an executable representative environment and
remain mandatory:

1. Upgrade a populated database through Alembic revisions `0035` through
   `0064`, then verify constraints, tenant isolation, record counts, and
   rollback/forward-fix evidence.
2. Run focused and full backend regression with PostgreSQL and Redis.
3. Produce and scan a production frontend build and both container images.
4. Exercise readiness, worker, queue, notification, integration, AI, and SLA
   behavior through the deployed edge.
5. Run baseline, peak, soak, WebSocket, controlled dependency-failure, and
   recovery acceptance against the approved local or staging target.
6. Run multi-user and cross-tenant negative authorization scenarios for
   administration, catalog, CMDB, workflow, integration, AI, and bulk-action
   paths.
7. Perform browser acceptance for requester, agent, manager, tenant
   administrator, and root administrator roles, including keyboard, zoom,
   responsive, and assistive-technology checks.
8. Complete dependency, secret, image, DAST, and release-signing gates and
   retain immutable evidence.

## Release decision

Local implementation traceability: **PASS**.

Local static consolidated gate: **PASS**.

Runtime acceptance: **NOT EXECUTED**.

Production-ready / go-live approval: **NOT GRANTED**.

M9 remains deferred because commercial SaaS tenant lifecycle, plan,
licensing, and billing behavior requires an explicit product decision.
