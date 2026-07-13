# PLATFORM-CORE-ASYNC-CONSUMER-POLICY-TUNING-017 Report

## Scope

Added policy-tuning controls for consumer auto-remediation with per-consumer profile overrides, suppression windows, denylist filtering, and dry-run preview visibility.

## Delivered

- Policy controls in settings:
  - Added `jobs_event_autoremediation_policy_profiles` as JSON object for per-consumer policy override.
  - Added `jobs_event_autoremediation_suppression_windows_utc` for UTC time windows that disable auto-remediation cycle.
  - Added `jobs_event_autoremediation_error_denylist` for substring-based exclusion of known noisy/permanent failure signatures.
  - Added validators for JSON object parsing and list parsing from env values.

- Services and policy logic:
  - Added suppression-window helper `is_autoremediation_suppressed_now(...)` with support for normal and wrap-over windows.
  - Added `job_event_consumer_autoremediation_preview(...)` dry-run estimator:
    - computes raw candidate count under core selection constraints,
    - applies denylist filter,
    - returns selected/skipped counters and sample items.
  - Extended `job_event_consumer_autoremediate(...)` to apply denylist filtering at execution time.

- Worker orchestration:
  - `_run_auto_remediation_cycle(...)` now applies per-consumer effective policy profile:
    - `enabled`
    - `allowed_event_types`
    - `min_failed_age_seconds`
    - `max_requeued_per_cycle`
    - `cooldown_seconds`
    - `max_per_hour`
  - Global suppression windows now gate the cycle before consumer loops.
  - Denylist is enforced during auto-remediation execution.

- API additions:
  - Added `GET /api/v1/jobs/event-consumer-autoremediation-preview`:
    - per-consumer preview,
    - effective policy reflection,
    - suppression status and windows,
    - selected/skipped counters and sample candidates.

- Tests:
  - Added jobs API tests for preview response shape and denylist behavior.
  - Added worker tests for suppression-window gating and profile override propagation.

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (48 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS (after warm-up retry).

## Notes

- Dry-run preview is read-only and intentionally separated from execution path.
- Suppression windows are interpreted in UTC and support wrap-over intervals (for example `23:00-02:00`).
