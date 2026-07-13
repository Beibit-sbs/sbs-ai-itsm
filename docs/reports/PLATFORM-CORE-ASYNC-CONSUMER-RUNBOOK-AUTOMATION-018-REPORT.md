# PLATFORM-CORE-ASYNC-CONSUMER-RUNBOOK-AUTOMATION-018 Report

## Scope

Implemented runtime runbook controls for consumer auto-remediation policy, added policy drift diagnostics context, and introduced canary-mode limiting in worker execution.

## Delivered

- Runtime policy controls:
  - Added runbook endpoints:
    - `GET /api/v1/jobs/event-consumer-autoremediation-policy`
    - `POST /api/v1/jobs/event-consumer-autoremediation-policy`
  - Operators can now adjust per-consumer policy at runtime:
    - `enabled`
    - `allowed_event_types`
    - `min_failed_age_seconds`
    - `max_requeued_per_cycle`
    - `cooldown_seconds`
    - `max_per_hour`
    - `canary_mode`
    - `canary_limit_per_cycle`
  - Runtime updates also support global policy surfaces:
    - `suppression_windows_utc`
    - `error_denylist`

- Audit and drift visibility:
  - Added audited policy update action:
    - `jobs.event_consumer_autoremediation_policy.update`
  - Diagnostics now include per-consumer policy context:
    - `effective_policy_hash`
    - `policy_canary_mode`
    - `last_policy_change_at`
    - `last_policy_change_actor_email`

- Worker canary automation:
  - Added global settings:
    - `jobs_event_autoremediation_canary_mode`
    - `jobs_event_autoremediation_canary_limit_per_cycle`
  - Worker now applies effective canary limit (global or per-consumer override) to bound requeue sample size per cycle.

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (50 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS (after warm-up retry).

## Notes

- Runbook policy updates are currently runtime-scoped (process memory/config object) and are explicitly audited for operator traceability.
- Policy drift visibility is intentionally surfaced in diagnostics so operators can correlate delivery behavior with the latest policy changes.
