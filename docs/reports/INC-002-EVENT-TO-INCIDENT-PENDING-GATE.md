# INC-002 Event-to-Incident and Escalation — Implementation Pending Runtime Gate

**Date:** 2026-07-29  
**Status:** implementation complete; runtime acceptance pending

## Delivered

- tenant-scoped source registry with one-time high-entropy bearer tokens,
  one-way token hashes, disable/enable, optimistic updates, rotation, source
  counters, and audit;
- bounded canonical event contract and Alertmanager adapter;
- immutable normalized events with stable idempotency, exact retry
  deduplication, payload SHA-256 evidence, source context, and disposition;
- ordered first-match correlation policies with bounded matchers, stable
  grouping, occurrence threshold, correlation window, incident mode, priority,
  title/category, recovery action, and on-call routing;
- maintenance suppression rules with reason, bounded matchers, active window,
  optimistic version, and audit;
- concurrency-safe PostgreSQL advisory locks for source event identity and
  correlation groups plus partial unique protection for one open group;
- threshold-based Ticket creation, correlated Ticket history, reopen behavior,
  SLA lookup, primary assignment, notification, and trusted source recovery;
- append-only group activity timeline and normalized evidence;
- primary/fallback acknowledgment deadlines and automatic worker escalation
  with Ticket reassignment, notification, activity, audit, and reminder;
- operational summary with 24-hour event/incident/suppression metrics, open
  groups, overdue acknowledgment, MTTA, lifetime duplicates, and noise
  reduction;
- complete Event Operations UI for queue/detail, acknowledgment, sources,
  token rotation, policies, suppression windows, event evidence, tenant
  selection, and manual escalation recovery;
- focused tests for idempotency, threshold correlation, incident creation,
  acknowledgment, recovery, suppression, Alertmanager normalization,
  escalation, authentication, and tenant isolation.

## Additive schema

Migration `20260729_0041_event_operations.py` creates:

- `event_sources`;
- `event_correlation_policies`;
- `event_suppression_rules`;
- `event_correlation_groups`;
- `normalized_events`;
- `event_group_activities`.

The Alembic chain remains single-head through `0041`.

## Static acceptance evidence

- Ruff: passed for models, service, routes, worker, migration, and focused
  tests.
- Python compileall: passed.
- Frontend TypeScript no-emit project check: passed.
- OpenAPI: 14 managed Event Operations paths and 17 operations; ingress
  endpoints intentionally excluded from public OpenAPI.
- Alembic: single head `20260729_0041`.
- `git diff --check`: passed (line-ending warnings only).

## Pending runtime gate

The focused PostgreSQL/FastAPI regression and production frontend bundle were
not rerun because the current Codex environment still blocks privileged
test/Docker execution by usage policy and blocks the native Vite dependency
process with `spawn EPERM`. No runtime-complete claim is made.

When the environment gate is available:

1. run `backend/tests/test_event_operations.py`;
2. run full backend regression;
3. apply migration `0041` to isolated PostgreSQL;
4. run concurrent idempotency/correlation ingestion;
5. verify the worker performs a real acknowledgment escalation;
6. run the frontend production build;
7. perform browser acceptance for source/token, policy, suppression, queue,
   Ticket creation, recovery, and tenant isolation;
8. inspect audit, notification, Ticket history, and normalized payload hashes.

## Result

INC-002 is ready for the deferred runtime release gate. Product implementation
continues with SLA-002 Enterprise SLA, OLA, and calendars.

