# PLATFORM-CORE-ASYNC-CONSUMER-DETERMINISTIC-RUNBOOKS-021 Report

## Scope

Implemented deterministic consumer runbooks for common incident patterns with dry-run/execute safety, persisted execution history, and diagnostics outcome metrics.

## Delivered

- Deterministic jobs runbook execution API:
  - Added `POST /api/v1/jobs/event-consumer-runbook`.
  - Supports explicit dry-run and execute modes.
  - Execute mode requires `X-Runbook-Confirm: CONFIRM`.

- Runbook catalog over existing persistence:
  - Reused existing `Runbook` and `RunbookExecution` tables instead of introducing a parallel execution ledger.
  - Added lazy creation of deterministic jobs runbook definitions for:
    - `jobs.consumer.repeated_failures_requeue`
    - `jobs.consumer.lag_spike_triage`
    - `jobs.consumer.stale_offset_triage`
    - `jobs.consumer.emergency_brake_reset`

- Deterministic runbook behaviors:
  - Repeated failures runbook:
    - dry-run preview of bounded failed-delivery recovery,
    - confirmed execute path for bounded requeue.
  - Lag spike runbook:
    - deterministic diagnostics snapshot with guardrail blocking when lag is absent.
  - Stale offset runbook:
    - deterministic diagnostics snapshot with guardrail blocking when offset is not stale.
  - Emergency brake reset runbook:
    - dry-run preview and confirmed reset flow via existing brake-reset logic.

- Persisted execution history and observability:
  - Runbook executions are persisted in `runbook_executions` with structured JSON result summaries.
  - Consumer diagnostics now include:
    - `runbook_executions_24h`
    - `last_runbook_execution_at`
  - Global diagnostics now include:
    - `runbook_executions_24h`
    - `runbook_failures_24h`
    - `recent_runbook_executions`

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (56 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS (after warm-up retry).

## Notes

- Runbook executions intentionally reuse shared runbook tables so operator action history stays in one durable model family.
- Guardrail-blocked runs are persisted as execution outcomes to make dry-run/operator behavior auditable in diagnostics history.
