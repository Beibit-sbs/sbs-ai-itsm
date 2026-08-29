# INC-001 Major Incident Management — Implementation Pending Runtime Gate

**Date:** 2026-07-29  
**Status:** implementation complete; runtime acceptance pending

## Delivered

- tenant-scoped Major Incident, participant, child-Ticket, immutable timeline,
  PIR, and corrective-action data model;
- additive Alembic migration `20260729_0040`;
- SEV1/SEV2 declaration with named Incident Commander and Communications Lead;
- 30/60-minute communication cadence and overdue command-center metrics;
- governed lifecycle from declaration through mitigation, monitoring,
  resolution, PIR approval, and closure;
- internal/stakeholder/public communication with channel and service-status
  validation;
- one-parent child-Ticket control, active-tenant responder selection, war-room
  links, CMDB impact, and append-only response timeline;
- corrective actions with owner, due date, optimistic version, status,
  completion evidence, and overdue state;
- independently approved immutable PIR as a mandatory closure gate;
- audited business mutations and Ticket-permission integration;
- manager workspace with declaration, command team, related Tickets,
  communications, lifecycle, actions, timeline, impact, and PIR controls;
- focused tenant-isolation and lifecycle regression tests.

## Static acceptance evidence

- Ruff: passed for model, route, migration, and focused tests.
- Python compileall: passed.
- Frontend TypeScript no-emit project check: passed.
- OpenAPI: 12 Major Incident paths and 13 operations.
- Alembic: single head `20260729_0040`.
- `git diff --check`: passed (line-ending warnings only).

## Pending runtime gate

The focused PostgreSQL/FastAPI regression and production frontend bundle were
not rerun because the current Codex execution environment blocks privileged
test/Docker execution by usage policy and blocks the native Vite dependency
process with `spawn EPERM`. No runtime-complete claim is made.

When the environment gate is available, run:

1. `pytest backend/tests/test_major_incidents.py`;
2. full backend regression;
3. apply migration `0040` to an isolated PostgreSQL database;
4. production frontend build;
5. browser acceptance for declaration, communication deadline, child link,
   action evidence, independent PIR approval, and closure;
6. tenant-isolation and audit inspection.

## Result

INC-001 is ready for the deferred runtime release gate. Product implementation
continues with INC-002 Event-to-Incident and escalation.

