# CMDB-005 data quality governance implementation note

Date: 2026-07-29  
Status: implementation complete, runtime release gate pending

## Outcome

The local platform now measures whether CMDB data can be trusted, assigns
remediation accountability, and retains periodic certification evidence.
Quality is no longer an informal administrator judgement.

Implemented capabilities:

- immutable quality snapshots with SHA-256 integrity evidence and trend;
- completeness, correctness, freshness, duplicate, and orphan scores plus a
  weighted overall index;
- deterministic findings for missing ownership, support group, location,
  governed schema, lifecycle mismatch, invalid owner, stale CI/source, open
  duplicate candidate, and isolated service-mapping CI;
- severity based on CI criticality and production environment;
- stable finding identity across scans, occurrence count, first/last detected,
  age, due date, overdue state, accountable owner, and optimistic version;
- manual `OPEN`, `IN_PROGRESS`, `RESOLVED`, and `WAIVED` lifecycle;
- automatic resolution after the underlying defect disappears and automatic
  reopening if it recurs;
- PostgreSQL tenant advisory lock to serialize concurrent scans;
- certification campaigns with bounded CI scope and owner/default certifier;
- immutable CI version snapshot and per-item SHA-256 integrity hash;
- stale-version and integrity fail-closed controls before certification;
- certified CI verification evidence in asset history;
- rejected certification converted into an owned remediation finding;
- draft, active, completed, and cancelled campaign lifecycle with progress
  and pending-item completion gate;
- tenant isolation, RBAC, optimistic concurrency, and tamper-evident audit;
- complete administrator workspace under **Качество CMDB**.

## Persistence and API

Migration `20260729_0039_cmdb_quality_governance.py` adds:

- `cmdb_quality_snapshots`;
- `cmdb_quality_findings`;
- `cmdb_certification_campaigns`;
- `cmdb_certification_items`.

OpenAPI contains 10 quality paths and 11 operations for summary, scans,
findings, campaign lifecycle, item decisions, completion, and cancellation.

## Static evidence

- Ruff: passed for models, services, API, migration, and focused tests.
- Python compileall: passed.
- TypeScript project no-emit check: passed.
- OpenAPI inspection: 10 quality paths and 11 operations registered.
- Alembic: one linear head at `20260729_0039`.

Focused tests cover quality scoring, stable finding generation, assignment,
underlying CI remediation, automatic finding resolution, immutable trend,
campaign activation, snapshot integrity, certification, completion,
stale-version blocking, and cross-tenant denial.

## Deferred runtime gate

Runtime completion is not claimed. The existing environment restriction still
prevents the privileged pytest/Docker release gate, and the production Vite
bundle remains blocked at native dependency startup by `spawn EPERM`.

When the environment allows it:

1. execute focused CMDB quality/impact/reconciliation/relationship regression;
2. execute full relevant backend regression;
3. build the production frontend bundle;
4. migrate PostgreSQL through `0039`;
5. verify readiness and migration state;
6. complete browser acceptance for scans, filters, owner/status updates,
   auto-resolution, campaign activation, certify/reject, stale blocking,
   hashes, audit, and tenant denial.

CMDB-005 and the M3 local release gate can move to `COMPLETED_LOCAL` only after
that runtime gate passes.
