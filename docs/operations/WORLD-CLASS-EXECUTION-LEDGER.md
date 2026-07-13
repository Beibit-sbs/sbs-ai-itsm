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
- Last completed stage: `PLATFORM-CORE-ASYNC-CONSUMER-POLICY-TUNING-017`
- Latest stage implementation commit: `9fb54e5`

## Stage Log (Newest First)

- `9fb54e5` PLATFORM-CORE-ASYNC-CONSUMER-POLICY-TUNING-017
  - Added per-consumer auto-remediation policy profiles with overrideable limits and allowed event scopes.
  - Added UTC suppression windows and denylist filters to reduce noisy or unsafe automatic retries.
  - Added `GET /jobs/event-consumer-autoremediation-preview` dry-run preview with effective policy visibility.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-CONSUMER-POLICY-TUNING-017-REPORT.md`

- `5850ef4` PLATFORM-CORE-ASYNC-CONSUMER-AUTOREMEDIATION-016
  - Added guarded worker-side auto-remediation cycle for exhausted failed consumer deliveries with per-consumer allowlist and policy limits.
  - Added dedicated auto-remediation safety checks (cooldown + hourly rate cap) and audit action `jobs.event_consumer_recovery.auto`.
  - Extended consumer diagnostics to separate auto-remediation counters/actions from manual recovery/governance signals.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-CONSUMER-AUTOREMEDIATION-016-REPORT.md`

- `5d19068` PLATFORM-CORE-ASYNC-CONSUMER-GOVERNANCE-015
  - Added governance validation for execute recovery: reason code, change ticket linkage, and optional dual-control approver.
  - Persisted structured governance metadata in recovery audit records.
  - Extended diagnostics with governance compliance counters and rate indicators.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-CONSUMER-GOVERNANCE-015-REPORT.md`

- `df24c10` PLATFORM-CORE-ASYNC-CONSUMER-SAFETY-014
  - Added per-consumer recovery safety controls: cooldown and hourly execution rate limit.
  - Added operator audit actions for recovery preview/execute and surfaced them in diagnostics.
  - Extended diagnostics with recovery counters and recent operator action feed.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-CONSUMER-SAFETY-014-REPORT.md`

- `1beb8a6` PLATFORM-CORE-ASYNC-CONSUMER-RECOVERY-013
  - Added protected replay tooling for consumer deliveries with bounded filters and dry-run preview.
  - Execution path now requires explicit confirmation header to avoid accidental mass requeue.
  - Recovery is isolated per consumer and preserves immutable lifecycle source records.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-CONSUMER-RECOVERY-013-REPORT.md`

- `1a58564` PLATFORM-CORE-ASYNC-OBSERVABILITY-CONSUMERS-012
  - Added `/jobs/event-consumers-diagnostics` with side-by-side per-consumer health, lag, retry, failure-rate, and stale-offset indicators.
  - Added operator-focused remediation recommendations and overall status rollup.
  - Added diagnostics thresholds in settings for lag and stale offset detection.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-OBSERVABILITY-CONSUMERS-012-REPORT.md`

- `983bd85` PLATFORM-CORE-ASYNC-AUTOMATION-HOOKS-011
  - Added dual downstream consumers over lifecycle stream with isolated delivery/retry state per consumer.
  - Introduced automation hooks consumer mapped from `job_lifecycle.<event_type>` triggers.
  - Extended event-consumer summary API to inspect specific consumer state.
  - Report: `docs/reports/PLATFORM-CORE-ASYNC-AUTOMATION-HOOKS-011-REPORT.md`

- `a841857` PLATFORM-CORE-ASYNC-CONSUMERS-010
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
- `PLATFORM-CORE-ASYNC-CONSUMER-RUNBOOK-AUTOMATION-018`

Scope proposal:
- Add operator runbook endpoint(s) to safely activate/deactivate suppression windows and profile flags at runtime.
- Add policy drift diagnostics (effective policy hash + last policy change audit context) in consumer diagnostics.
- Add optional canary mode that limits auto-remediation to a tiny sample per cycle before full rollout.

Exit criteria:
- Operators can adjust policy safely through audited API calls without direct env edits.
- Diagnostics expose policy drift/canary status with clear remediation hints.
- Tests cover runbook controls and canary safety boundaries.

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
