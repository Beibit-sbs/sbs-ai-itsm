# PLATFORM-CORE-ASYNC-AUTOMATION-HOOKS-011 Report

## Scope

Added a second downstream consumer on top of lifecycle event relay for automation hooks, while preserving idempotent delivery semantics and isolated retries introduced in stage 010.

## Delivered

- Dual-consumer worker pipeline:
  - Extended worker consumer loop to process two independent consumers:
    - `notifications-consumer`
    - `automation-consumer`
  - Consumer processing/retry paths are now parameterized by consumer name and handler.
- Automation consumer hook:
  - Added automation handler that maps lifecycle events into automation triggers via `trigger_automation_event(...)`.
  - Trigger format: `job_lifecycle.<event_type>`.
  - Context includes job metadata and event payload for downstream rule evaluation.
- Runtime configuration:
  - Added `jobs_event_automation_consumer_name` setting (default: `automation-consumer`).
- API visibility:
  - Extended `GET /api/v1/jobs/event-consumer-summary` with optional `consumer_name` query parameter.
  - Endpoint now validates supported consumers and returns `400` for unknown names.
- Tests:
  - Added API tests for automation consumer summary and unknown consumer rejection.
  - Added worker test proving dual-consumer independence over the same stream.

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (38 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.prod.yml --env-file .env.production config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS (after initial warm-up reconnect).
- Runtime endpoint checks:
  - `GET /api/v1/jobs/event-consumer-summary?consumer_name=notifications-consumer` -> PASS.
  - `GET /api/v1/jobs/event-consumer-summary?consumer_name=automation-consumer` -> PASS.

## Notes

- Consumer retries remain isolated per `consumer_name`; failures in automation hooks do not affect notifications delivery state.
- Durable event source-of-truth remains in `job_lifecycle_events`; consumers stay downstream projections.
