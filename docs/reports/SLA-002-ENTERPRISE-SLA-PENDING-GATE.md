# SLA-002 Enterprise SLA, OLA, and Calendars — Implementation Pending Runtime Gate

**Date:** 2026-07-29  
**Status:** implementation complete; runtime acceptance pending

## Delivered

- tenant-scoped, versioned business calendars with IANA time zones, weekly
  intervals, holidays, exceptional working days, default/active controls, and
  optimistic concurrency;
- DST-safe business-minute addition and elapsed-time calculation using local
  calendar boundaries and UTC persistence;
- extended versioned SLA policies with calendar, ordered match priority,
  category/department/location scope, pause governance, warning threshold,
  multi-stage escalation, and multiple target definitions;
- immutable policy and calendar snapshots for each Ticket SLA instance;
- response, resolution, fulfillment, OLA, and supplier targets with warning,
  due time, progress, remaining business time, owner, breach evidence, and
  escalation level;
- audited pause/resume history with approved reasons and business-time
  deadline extension;
- governed recalculation that preserves superseded commitments;
- integration with Ticket creation, assignment, status transition, priority
  update, resolve, close, reopen, cancel, and monitoring-created incidents;
- automatic 30-second worker evaluation, warning/breach transitions,
  notifications, escalation, Ticket compatibility-field synchronization, and
  audit;
- tenant-safe API for calendars, exceptions, policies, live queue, instance
  evidence, manual pause/resume, target completion, recalculation, evaluation,
  overview, and breach register;
- complete SLA Control Center UI with organization scope, live queue, target
  progress, deadlines, timeline, pause/resume, policy designer, OLA/supplier
  targets, calendar scheduling, holidays, activation controls, and breach
  register;
- direct deep-link support from SLA records into the Ticket workspace;
- focused tests for DST/holiday calendar math, policy matching, target
  creation, response completion, pause/resume, tenant isolation, and overview.

## Additive schema

Migration `20260729_0042_enterprise_sla.py` creates:

- `sla_business_calendars`;
- `sla_calendar_exceptions`;
- `ticket_sla_instances`;
- `ticket_sla_targets`;
- `ticket_sla_pauses`;
- `ticket_sla_timeline`;

and extends `sla_policies` with enterprise configuration and version fields.
The Alembic chain remains single-head through `0042`.

## Static acceptance evidence

- Ruff: passed for changed models, services, routes, worker, migration, and
  focused tests.
- Python compileall: passed.
- Frontend TypeScript no-emit project check: passed.
- OpenAPI: 16 SLA paths and 20 operations.
- Alembic: single head `20260729_0042`.
- Runtime and production bundle gates remain deferred as described below.

## Pending runtime gate

The focused PostgreSQL/FastAPI regression and production frontend bundle were
not run because the current Codex environment blocks privileged test/Docker
execution by usage policy and blocks the native Vite dependency process with
`spawn EPERM`. No runtime-complete claim is made.

When the environment gate is available:

1. run `backend/tests/test_enterprise_sla.py`;
2. run the full backend regression;
3. apply migration `0042` to isolated PostgreSQL;
4. verify partial uniqueness and concurrent recalculation;
5. exercise worker warning, breach, and multi-stage escalation;
6. run the production frontend bundle;
7. perform browser acceptance for calendars, exceptions, policies, queue,
   pause/resume, lifecycle automation, and tenant isolation;
8. capture audit, notification, Ticket, and SLA timeline evidence.

## Result

SLA-002 is ready for the deferred runtime release gate. Product implementation
continues with CHANGE-002 Change Calendar and Advanced Governance.
