# PLATFORM-CORE-ASYNC-CONSUMER-AUTOREMEDIATION-016 Report

## Scope

Implemented guarded worker-side auto-remediation for exhausted consumer deliveries with explicit opt-in controls, bounded execution limits, and separate diagnostics/audit visibility from manual recovery.

## Delivered

- Config and policy controls:
  - Added auto-remediation settings in backend config:
    - `jobs_event_autoremediation_enabled`
    - `jobs_event_autoremediation_consumers`
    - `jobs_event_autoremediation_allowed_event_types`
    - `jobs_event_autoremediation_min_failed_age_seconds`
    - `jobs_event_autoremediation_max_requeued_per_cycle`
    - `jobs_event_autoremediation_cooldown_seconds`
    - `jobs_event_autoremediation_max_per_hour`
  - Added CSV parsing validator for list-like env values and non-negative validation for auto-remediation limits.

- Jobs services extensions:
  - Added `job_event_consumer_autoremediation_safety_state(...)` to compute per-consumer cooldown and hourly rate-limit state from audit history.
  - Added `job_event_consumer_autoremediate(...)` to requeue only exhausted failed deliveries under policy constraints:
    - consumer scoped
    - stream scoped
    - minimum failed age
    - allowed event type filter
    - bounded batch size
  - Extended diagnostics aggregation to separate automatic actions from operator recovery actions.

- Diagnostics contract updates:
  - Per-consumer diagnostics now include `autoremediation_24h`.
  - Global diagnostics now include:
    - `autoremediation_actions_24h`
    - `recent_autoremediation_actions`

- Worker integration:
  - Added `_run_auto_remediation_cycle(...)` in worker loop.
  - Cycle is gated by explicit enablement + consumer allowlist + safety checks.
  - Automatic requeue actions write dedicated audit entries under `jobs.event_consumer_recovery.auto`.
  - Manual recovery/governance path remains unchanged and isolated.

- Tests:
  - Updated jobs diagnostics API shape test for new autoremediation fields.
  - Added worker auto-remediation tests for:
    - execution path with audit emission
    - cooldown guard path

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (44 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS.

## Notes

- Auto-remediation emits a distinct audit action and diagnostics stream, preventing conflation with manual operator recovery execution metrics.
- Worker-side orchestration tests pin settings via monkeypatch to avoid cached settings divergence across test modules.
