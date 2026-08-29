# CMDB-004 impact analysis implementation note

Date: 2026-07-29  
Status: implementation complete, runtime release gate pending

## Outcome

The local platform now converts CMDB relationships into explainable,
governed impact evidence. Operators can calculate a CI blast radius, while
Incident, Problem, Change, and future Release processes can retain immutable
assessments for later audit.

Implemented capabilities:

- tenant-safe upstream, downstream, and bidirectional traversal;
- one to 100 root CIs, depth from one to 12, deterministic ordering, node
  limits, and explicit truncation evidence;
- global graph revision hash covering active relationships, relationship type
  versions, and CI graph-relevant revisions;
- persistent 15-minute per-root cache with graph-hash invalidation and
  PostgreSQL advisory locking against cache stampedes;
- multi-root graph merge with minimal node depth and deduplicated edges;
- severity calculation from CI criticality, business-service reachability,
  critical and production scope, blast-radius size, and Change collisions;
- explicit customer-impact inference whenever a Business Service is reached;
- collision detection for Change records that share any impacted CI,
  distinguishing shared scope from overlapping implementation windows;
- immutable, canonical JSON assessment snapshots with SHA-256 integrity hash;
- exactly one CURRENT assessment per tenant/entity and retained SUPERSEDED
  assessment history;
- optimistic Change/Problem version checks and separate graph/entity stale
  indicators;
- tenant isolation, ticket visibility guard, RBAC, and tamper-evident audit;
- reusable UI embedded in CI, Ticket, Problem, and Change cards.

## Persistence and API

Migration `20260729_0038_cmdb_impact_analysis.py` adds:

- `cmdb_impact_cache`;
- `cmdb_impact_assessments`;
- a partial unique index that permits only one CURRENT assessment for a
  tenant/entity.

Registered API:

- `POST /api/v1/cmdb/impact/preview`;
- `POST /api/v1/cmdb/impact/assessments/{entity_type}/{entity_id}`;
- `GET /api/v1/cmdb/impact/assessments/{entity_type}/{entity_id}/latest`;
- `GET /api/v1/cmdb/impact/assessments/{entity_type}/{entity_id}`.

## Static evidence

- Ruff: passed for model, service, route, migration, and focused tests.
- Python compileall: passed.
- TypeScript project no-emit check: passed.
- OpenAPI inspection: three impact paths and four operations registered.
- Alembic: one linear head at `20260729_0038`.

Focused tests cover dependency depth, service/customer impact, persistent
cache reuse, cross-tenant denial, Change collisions, snapshot integrity,
optimistic entity versions, superseded history, entity staleness, and graph
staleness.

## Deferred runtime gate

Runtime completion is not claimed. The existing environment restriction still
prevents the privileged pytest/Docker release gate, and the production Vite
bundle remains blocked at native dependency startup by `spawn EPERM`.

When the environment allows it, execute:

1. focused CMDB impact, relationship, reconciliation, Change, Problem, Ticket,
   and asset regression;
2. full relevant backend regression;
3. production frontend bundle;
4. PostgreSQL migrations `0035` through `0038`;
5. readiness and migration-state checks;
6. browser acceptance for CI preview, saved Ticket/Problem/Change assessment,
   stale warning, collision evidence, audit, cache reuse, and cross-tenant
   denial.

CMDB-004 can move to `COMPLETED_LOCAL` only after that gate passes.
