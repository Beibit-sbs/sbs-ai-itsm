# PLATFORM-CORE-ASYNC-CONSUMERS-010 Report

## Scope

Implemented the first downstream event consumer on top of the durable lifecycle-event relay, including idempotent delivery tracking, offset management, isolated retries, and API visibility.

## Delivered

- Consumer state schema:
  - Added `job_event_consumer_offsets` for per-consumer stream offsets.
  - Added `job_event_consumer_deliveries` for idempotent per-event delivery status/attempts/errors.
  - Added additive Alembic migration `20261120_0014_job_event_consumers`.
- Consumer runtime configuration:
  - Added `jobs_event_consumer_name` (default `notifications-consumer`).
  - Added `jobs_event_consumer_max_attempts` (default `3`).
- Worker downstream consumer pipeline:
  - Added `_consume_event_stream_batch(...)` using Redis `XREAD` from stored offset.
  - Added `_retry_failed_event_consumers_batch(...)` for isolated retry of failed deliveries.
  - Added idempotent consumer delivery rows keyed by `(consumer_name, event_id)`.
  - Added first consumer side-effect: in-app notifications for `failed` and `dead_letter` lifecycle events.
- Jobs API visibility:
  - Added `job_event_consumer_summary(...)` in jobs service.
  - Added `GET /api/v1/jobs/event-consumer-summary` endpoint.
- Tests:
  - Added worker tests for stream consume side-effects and retry recovery.
  - Added API test for consumer summary response shape.

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (35 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.prod.yml --env-file .env.production config` -> PASS.
- Alembic migration:
  - `DATABASE_URL=postgresql+psycopg://sbs_itsm:change_me_before_production@localhost:5432/sbs_itsm ../.venv/bin/python -m alembic upgrade head` -> PASS.
  - `DATABASE_URL=postgresql+psycopg://sbs_itsm:change_me_before_production@localhost:5432/sbs_itsm ../.venv/bin/python -m alembic current` -> `20261120_0014 (head)`.
- Runtime smoke:
  - `make smoke` -> PASS.
  - `docker compose up -d --build backend worker` -> PASS.
  - Authenticated `GET /api/v1/jobs/event-consumer-summary` -> PASS (`consumer=notifications-consumer`, `stream=jobs:lifecycle`).

## Notes

- Lifecycle events remain the durable source of truth in PostgreSQL; consumer delivery tracking and offsets are downstream processing state.
- Consumer retries are intentionally isolated from event relay/source semantics.
- Host-side Alembic calls should use localhost database credentials from `.env` when run outside containers.
