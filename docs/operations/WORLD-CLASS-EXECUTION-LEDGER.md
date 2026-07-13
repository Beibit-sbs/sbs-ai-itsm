# WORLD-CLASS EXECUTION LEDGER

## Purpose

This file is the single source of truth for long-running autonomous execution.
It prevents context drift and keeps roadmap, status, and next actions explicit.

Use this file to:
- track progress by roadmap track and stage;
- record decisions and constraints;
- define the exact next stage to implement;
- keep continuity when conversation context is compressed.

## Guardrails

- Do not push automatically.
- Do not run destructive data operations.
- Never commit `.env.production` or backup artifacts.
- Keep changes additive where possible.
- Validate every stage with tests/build/compose/runtime smoke.

## Roadmap Tracks (12)

1. PLATFORM-CORE
2. SECURITY-ENTERPRISE
3. AI-REAL
4. CMDB-CORE
5. CHANGE-PROBLEM-RELEASE
6. SERVICE-CATALOG
7. AIOPS
8. PORTAL-SELF-SERVICE
9. NOTIFICATIONS-OMNI
10. OBSERVABILITY-PROD
11. DEVOPS-K8S
12. QUALITY-CI

Current execution policy:
- Focus on Track 1 first until the async/reliability baseline is production-strong.
- Then move to Track 2 or Track 3 based on product priority.

## Current Position

- Branch: `main`
- Last completed stage: `PLATFORM-CORE-ASYNC-CONSUMERS-010`
- Latest stage implementation commit: `PENDING_COMMIT`

## Stage Log (Newest First)

- `PENDING_COMMIT` PLATFORM-CORE-ASYNC-CONSUMERS-010
  - Added first downstream consumer pipeline over relayed lifecycle events with per-consumer offsets and idempotent delivery state.
  - Added isolated consumer retry loop and notification side-effects for `failed`/`dead_letter` job events.
  - Added `GET /jobs/event-consumer-summary` for runtime visibility of consumer throughput/failures.
  - Added additive migration `20261120_0014_job_event_consumers`.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-CONSUMERS-010-REPORT.md`

- `e2e5dff` PLATFORM-CORE-ASYNC-EVENT-BUS-009
  - Added Redis Stream relay for durable lifecycle events with DB lock + Redis dedup protection.
  - Added relay delivery-state metadata, retry handling, and event-bus summary endpoint.
  - Consumer-safe event payload contract now published to `jobs:lifecycle`.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-EVENT-BUS-009-REPORT.md`

- `51d6781` PLATFORM-CORE-ASYNC-EVENTS-008
  - Added durable `job_lifecycle_events` storage and additive migration.
  - Emitted lifecycle events for queued, running, success, failed, retry_scheduled, dead_letter, and replayed transitions.
  - Added `GET /jobs/{job_id}/events` for ordered lifecycle event inspection.
  - Tests cover success, retry, dead-letter, and replay event flows.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-EVENTS-008-REPORT.md`

- `52500a2` PLATFORM-CORE-ASYNC-OBSERVABILITY-007
  - Added `/jobs/outbox-diagnostics` for runbook-level queue/outbox triage.
  - Exposed lock contention, stale locks, dedup skips, and publish failure rate.
  - Added threshold-based status evaluation and recommended operator actions.
  - Extended admin diagnostics UI with actionable outbox SLO indicators.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-OBSERVABILITY-007-REPORT.md`

- `fbd8ab1` PLATFORM-CORE-ASYNC-IDEMPOTENCY-006
  - Outbox idempotency metadata and unique dedup key enforcement.
  - Migration hardening: duplicate cleanup before unique index creation.
  - Redis publish dedup guard (`SET NX EX`) for multi-worker safety.
  - Added jobs outbox diagnostics endpoint and admin diagnostics UI metrics.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-IDEMPOTENCY-006-REPORT.md`

- `d37f582` PLATFORM-CORE-ASYNC-OUTBOX-005
  - Transactional enqueue via `job_queue_outbox`.
  - Worker publishes outbox entries to Redis.
  - Replay in Redis mode also goes through outbox.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-OUTBOX-005-REPORT.md`

- `309f33c` PLATFORM-CORE-ASYNC-REPLAY-SCHEDULED-004
  - Dead-letter replay endpoint.
  - Scheduled retries via `<queue>:scheduled` (no blocking sleep).
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-REPLAY-SCHEDULED-004-REPORT.md`

- `a323c6f` PLATFORM-CORE-ASYNC-RETRY-DLQ-003
  - Retry backoff + dead-letter transition.
  - Runtime diagnostics extended.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-RETRY-DLQ-003-REPORT.md`

- `3bf98c9` PLATFORM-CORE-ASYNC-WORKER-002
  - Dedicated Redis worker runtime.
  - Queue mode wiring in compose.
  - Race/timeout hardening.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-WORKER-002-REPORT.md`

- `af34f6f` PLATFORM-CORE-ASYNC-FOUNDATION-001
  - Job runs telemetry, jobs API, correlation IDs.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-FOUNDATION-001-REPORT.md`

- `e221aa9` AI-REAL-LLM-PROVIDER-001
  - OpenAI/Gemini provider abstraction, PII redaction.
  - Report: `docs/reports/AI-REAL-LLM-PROVIDER-001-REPORT.md`

## Open Focus Queue

### Active track
- Track 1: PLATFORM-CORE

### Next recommended stage
- `PLATFORM-CORE-ASYNC-AUTOMATION-HOOKS-011`

Scope proposal:
- Add the second downstream consumer path for automation hooks with the same idempotent delivery contract.
- Reuse delivery/offset model from 010 and keep retries isolated per consumer.
- Define minimal rule matching and bounded payload contract for automation follow-up actions.

Exit criteria:
- Automation consumer reacts to lifecycle events and records delivery status with retries.
- Existing notifications consumer behavior remains stable and idempotent.
- Tests cover consumer coexistence and isolated retry semantics.

## Stage Execution Template

For each new stage, fill this block before coding and update after completion.

- Stage ID:
- Track:
- Goal:
- Non-goals:
- Files expected to change:
- Validation plan:
  - backend tests:
  - frontend build/typecheck:
  - compose config:
  - runtime smoke:
- Status: planned | in_progress | completed
- Commit:
- Report file:

## Handoff Protocol

At end of each stage:
1. Update this ledger (`Current Position`, `Stage Log`, `Open Focus Queue`).
2. Add/update stage report under `docs/reports/`.
3. Ensure working tree is clean after commit.
4. Continue with next stage from `Open Focus Queue` unless user reprioritizes.
