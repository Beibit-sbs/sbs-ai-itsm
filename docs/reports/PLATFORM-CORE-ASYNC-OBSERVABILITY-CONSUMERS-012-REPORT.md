# PLATFORM-CORE-ASYNC-OBSERVABILITY-CONSUMERS-012 Report

## Scope

Added side-by-side diagnostics for lifecycle event consumers with per-consumer lag, retry pressure, failure rate, stale-offset detection, and operator guidance.

## Delivered

- Consumer diagnostics service:
  - Added `job_event_consumers_diagnostics(...)` to aggregate health for configured consumers on one stream.
  - Metrics per consumer include:
    - `delivery_rows`, `delivered`, `pending`, `failed`
    - `retryable_failed`, `exhausted_failed`
    - `unseen_events`, `lag_events`, `failure_rate_pct`
    - `oldest_undelivered_age_seconds`
    - `offset_updated_at`, `stale_offset`
    - `status` and `recommended_actions`
  - Added overall status rollup across consumers.
- Config thresholds:
  - `jobs_event_consumer_lag_alert_threshold` (default `25`).
  - `jobs_event_consumer_stale_offset_seconds` (default `300`).
- API endpoint:
  - Added `GET /api/v1/jobs/event-consumers-diagnostics` returning side-by-side diagnostics for `notifications-consumer` and `automation-consumer`.
- Tests:
  - Added API test for diagnostics response shape and expected consumer list semantics.

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (39 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.prod.yml --env-file .env.production config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS (after warm-up retry).
- Runtime endpoint check:
  - Authenticated `GET /api/v1/jobs/event-consumers-diagnostics` -> PASS (`overall_status=healthy`, `consumer_count=2`).

## Notes

- Diagnostics are computed from durable DB state (`job_lifecycle_events`, consumer delivery and offset tables), so they remain available even if Redis transport is transient.
- Warm-up reconnect immediately after container rebuild can cause one transient smoke failure; rerun succeeds once backend healthcheck settles.
