# PLATFORM-CORE-ASYNC-CONSUMER-SAFETY-014 Report

## Scope

Added safety guardrails for consumer recovery operations: cooldown and rate-limit enforcement, operator audit trail, and diagnostics visibility for recovery activity.

## Delivered

- Recovery safety controls:
  - Added configurable cooldown and hourly execution limits for recovery execute mode.
  - Safety is evaluated per consumer before mutation operations.
  - Execute requests that violate guardrails now return `429 Too Many Requests`.
- Protected recovery execution path:
  - Existing confirmation header requirement preserved.
  - Added explicit preview/execute audit actions for every operator call.
- Recovery observability extensions:
  - `GET /api/v1/jobs/event-consumers-diagnostics` now includes:
    - per-consumer recovery counters (`preview_24h`, `execute_24h`)
    - last recovery execute timestamp and actor email
    - global `recovery_actions_24h`
    - `recent_recovery_actions` feed for operator awareness.
- Datetime safety hardening:
  - Added UTC normalization helper for DB timestamps to avoid naive/aware subtraction issues in sqlite-backed tests and diagnostics computations.

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (41 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.prod.yml --env-file .env.production config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS (after warm-up retry).
- Runtime API checks:
  - First execute recovery call -> `200`.
  - Immediate second execute recovery call -> `429` (cooldown/rate guardrail active).
  - Diagnostics endpoint includes recovery action counters -> PASS.

## Notes

- Safety limits are per consumer and do not affect standard worker flow.
- Recovery audit records are now first-class diagnostics inputs for operator troubleshooting.
