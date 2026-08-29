# CMDB-001/002 implementation note

Date: 2026-07-29  
Status: implementation complete, runtime release gate pending

## Outcome

The local platform now contains the implementation for the first two M3
stages:

- governed CI class definitions with immutable published versions;
- class inheritance with exact parent-version pinning;
- typed and validated class attributes;
- CI lifecycle, owner, support group, criticality, environment, and optimistic
  version controls;
- governed relationship types with direction, inverse labels, class
  constraints, ONE/MANY cardinality, self-link policy, and cycle policy;
- auditable relationship creation and retirement recorded on both endpoint
  CIs;
- bounded, tenant-safe upstream/downstream/bidirectional topology traversal;
- administrator UI for class schemas, CI creation, relationship policies, and
  layered service maps.
- idempotent CMDB bootstrap for every newly provisioned tenant, including
  standard classes, relationship types, and classification of legacy assets;
- Excel asset reconciliation that creates Generic CI snapshots, preserves the
  class of governed CIs, distinguishes update candidates from duplicate input
  rows, and skips duplicate rows deterministically.

Migration `20260729_0035` upgrades flat assets into classified CI snapshots.
Migration `20260729_0036` adds relationship storage and standard
Business Service, Technical Service, Application, Infrastructure, and Location
classes with an initial service-model vocabulary.

## Static evidence

- Ruff: passed for all CMDB backend, migration, and test files.
- Python compileall: passed.
- TypeScript project build (`tsc -b`): passed.
- Alembic: one linear head at `20260729_0036`.
- OpenAPI inspection: all class, CI, relationship, and topology paths are
  registered.
- `git diff --check`: passed for the implementation files.

## Deferred runtime gate

The implementation is not marked complete in the master roadmap because the
new runtime gate could not be executed in the current Codex environment:

- the privileged pytest/Docker request was rejected by the environment usage
  limit;
- the non-privileged Vite bundle reached TypeScript successfully, then native
  Tailwind/Rolldown loading failed with `spawn EPERM`.

The last completed M2 release gate remains valid. As soon as the environment
allows execution, run:

1. focused CMDB backend regression;
2. full relevant backend regression;
3. production frontend bundle;
4. PostgreSQL migrations `0035` and `0036`;
5. readiness and migration-state checks;
6. browser acceptance covering class publication, typed CI creation,
   relationship validation, topology traversal, retirement, history, audit,
   and cross-tenant denial.

Only after those checks pass may CMDB-001 and CMDB-002 move to
`COMPLETED_LOCAL`.
