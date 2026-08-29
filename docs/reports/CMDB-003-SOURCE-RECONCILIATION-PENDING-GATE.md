# CMDB-003 source reconciliation implementation note

Date: 2026-07-29  
Status: implementation complete, runtime release gate pending

## Outcome

The local platform now has a governed ingestion and reconciliation layer
rather than independent imports that overwrite the asset registry directly.

Implemented capabilities:

- tenant-scoped source registry with priority, type, default CI class,
  identification rules, authoritative fields, external-system linkage,
  freshness threshold, status, and optimistic version;
- persistent `source + external_id -> CI` identity binding;
- immutable preview/apply runs with canonical payload hash and per-source
  idempotency key;
- typed normalization and class-schema validation;
- deterministic create, update, unchanged, protected, invalid, and ambiguous
  outcomes;
- duplicate detection for both existing CIs and duplicate identifiers inside
  the incoming payload;
- fail-closed apply when invalid or ambiguous records remain;
- per-field ownership with priority enforcement (lower numeric priority is
  stronger);
- safe duplicate dismiss and merge. Merge never deletes the duplicate CI: it
  retires it, records history, and moves supported operational references to
  the primary CI;
- relationship merge safety that collapses exact duplicates and retires
  links that would violate self-link, cardinality, or cycle constraints;
- source health metrics, run/record inspection, duplicate queue, and field
  provenance API;
- administrator UI for source policies, JSON preview/apply, run evidence,
  duplicate decisions, and CI field ownership;
- built-in Excel import routed through the same reconciliation engine, with
  500-record chunking and atomic asset/audit commit.

## Persistence

Migration `20260729_0037_cmdb_reconciliation.py` adds:

- `cmdb_sources`;
- `cmdb_reconciliation_runs`;
- `cmdb_source_identities`;
- `cmdb_reconciliation_records`;
- `cmdb_field_ownership`;
- `ci_duplicate_candidates`.

It also seeds the governed `EXCEL_ASSET_IMPORT` source for existing tenants.
The tenant bootstrap creates the same source idempotently for future tenants.

## Static evidence

- Ruff: passed for the backend implementation, routes, migrations, and
  focused tests.
- Python compileall: passed.
- TypeScript project no-emit check: passed.
- OpenAPI inspection: 21 CMDB paths and 27 HTTP operations registered.
- Alembic: one linear head at `20260729_0037`.
- Targeted `git diff --check`: passed.

Focused tests were added for source validation, idempotency, identity
stability, field precedence, tenant isolation, payload duplicate detection,
ambiguous apply blocking, merge optimistic concurrency, retained duplicate
history, and Excel reconciliation/ownership.

## Deferred runtime gate

Runtime completion is not claimed. The existing environment restriction still
prevents the privileged pytest/Docker release gate, and the production Vite
bundle remains blocked at native dependency startup by `spawn EPERM`.

When the environment allows it, execute:

1. focused CMDB and asset-import regression;
2. full relevant backend regression;
3. production frontend bundle;
4. PostgreSQL migrations `0035`, `0036`, and `0037`;
5. readiness and migration-state checks;
6. browser acceptance for source creation, preview/apply, protected fields,
   ambiguous blocking, duplicate dismiss/merge, Excel reconciliation, field
   ownership, audit, and cross-tenant denial.

CMDB-003 can move to `COMPLETED_LOCAL` only after that gate passes.
