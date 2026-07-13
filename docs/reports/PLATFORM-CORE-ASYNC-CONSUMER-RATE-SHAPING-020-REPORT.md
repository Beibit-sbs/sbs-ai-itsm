# PLATFORM-CORE-ASYNC-CONSUMER-RATE-SHAPING-020 Report

## Scope

Implemented per-consumer rate-shaping guardrails (burst + steady budgets), emergency brake handling with operator reset endpoint, and diagnostics visibility for budget usage and brake state.

## Delivered

- Rate-shaping controls:
  - Added global settings:
    - `jobs_event_autoremediation_burst_max_per_10m`
    - `jobs_event_autoremediation_brake_error_threshold`
    - `jobs_event_autoremediation_braked_consumers`
  - Added per-consumer profile override support for `burst_limit_per_10m` in effective policy.
  - Added service helper `job_event_consumer_rate_shape_state(...)` for budget-state evaluation.

- Worker safety behavior:
  - Worker now blocks auto-remediation for consumers under emergency brake.
  - Worker enforces burst/steady budgets before remediation execution.
  - Worker logs `jobs.event_consumer_recovery.auto_error` on auto-remediation failure.
  - Worker auto-activates emergency brake (persisted policy update) when recent auto errors exceed configured threshold.

- Runbook controls:
  - Added operator endpoint:
    - `POST /api/v1/jobs/event-consumer-autoremediation-brake-reset`
  - Endpoint requires optimistic concurrency token (`expected_version`) and clears brake for target consumer.

- Diagnostics/contract extensions:
  - Per-consumer diagnostics now include:
    - `rate_budget_10m_used`
    - `rate_budget_10m_limit`
    - `rate_budget_1h_used`
    - `rate_budget_1h_limit`
    - `emergency_brake_active`
    - `emergency_brake_reason`
    - `policy_version`
  - Global diagnostics now include:
    - `emergency_brake_consumers`
  - Policy runbook responses now include:
    - `emergency_brake_consumers`

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (54 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS (after warm-up retry).

## Notes

- Emergency brake state is persisted in policy payload and shared across backend and worker via policy-state reload.
- Brake reset is explicit, audited, and version-checked to avoid stale operator writes.
