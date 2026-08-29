# RELEASE-001 Deployment Governance — Pending Runtime Gate

**Date:** 2026-07-29  
**Status:** implementation complete; runtime acceptance pending  
**Migration head:** `20260729_0044`

## Delivered

- tenant-scoped release portfolio with unique service versions, release
  numbers, lifecycle, risk, windows, ownership, notes, validation, rollback,
  and communication plans;
- ordered aggregation of approved RFCs;
- immutable package identity through artifact URI, version, SHA-256, build
  reference, dependency metadata, and independent verification evidence;
- formal release-to-release dependencies with cycle prevention;
- configurable Development/Test/Staging/Production/DR environments,
  promotion order, smoke-test policy, and current/previous version state;
- automated Change, Package, Dependency, Window, and Rollback readiness gates;
- manual Test, Security, Business, and custom gates with evidence and waiver
  governance;
- independent Go/No-Go/Conditional decisions with full readiness snapshot;
- conditional decision gates and readiness re-evaluation at deployment start;
- planned, active, validating, succeeded, failed, cancelled, and rolled-back
  deployment lifecycle;
- serialized promotion, production-window enforcement, evidence requirements,
  smoke-test enforcement, final publication, and rollback version restoration;
- append-only release timeline and tamper-evident platform audit events;
- release calendar, operator workspace, root organization selector, deep links
  to RFCs, and performance analytics;
- focused end-to-end test scenarios for publication, promotion, dependency
  cycles, and tenant isolation.

## Static acceptance evidence

- Ruff: passed for release backend, migration, and focused test files.
- Python `compileall`: passed for application, tests, and migrations.
- TypeScript project check (`tsc --noEmit`): passed.
- OpenAPI inspection: 20 `/api/v1/releases` paths and 23 operations.
- Alembic: one head, `20260729_0044`.

## Runtime gate still required

Privileged runtime execution remains unavailable in the current environment
until 2026-08-04. The production frontend bundle is also blocked in this
sandbox by native child-process `EPERM`. No runtime completion claim is made.

When runtime execution is available, run:

1. `backend/tests/test_release_governance.py`;
2. the full backend regression suite;
3. migration upgrade from a production-like database through `0044`;
4. production frontend build;
5. browser acceptance for tenant isolation, package verification, readiness,
   Go/No-Go separation, conditional gates, ordered promotion, production
   window, validation, publication, failure, and rollback;
6. readiness and production smoke suites.

Any runtime defect found by that gate must be corrected before RELEASE-001 is
marked `COMPLETE`.

