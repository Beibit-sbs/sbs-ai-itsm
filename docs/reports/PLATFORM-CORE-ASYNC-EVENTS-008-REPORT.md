# PLATFORM-CORE-ASYNC-EVENTS-008 Report

## Scope

Implemented a durable lifecycle event stream for async jobs by persisting structured job transition events in the database and exposing them through the jobs API.

## Delivered

- Durable lifecycle event storage:
  - Added `job_lifecycle_events` model and additive Alembic migration `20261118_0012_job_lifecycle_events`.
  - Event rows persist `job_id`, `event_type`, `task_name`, `tenant_id`, `actor_user_id`, `correlation_id`, `previous_status`, `current_status`, and JSON payload metadata.
- Event emission helpers:
  - Added `create_job_lifecycle_event(...)` and `list_job_events(...)` in jobs service.
- Lifecycle transition coverage:
  - `queued` emitted when job row is created.
  - `running`, `failed`, and `success` emitted during execution.
  - `retry_scheduled` emitted when worker requeues a failed job for scheduled retry.
  - `dead_letter` emitted when attempts are exhausted.
  - `replayed` emitted when a dead-letter job is replayed.
- API surface:
  - Added `GET /jobs/{job_id}/events` for ordered lifecycle event retrieval.
- Test coverage:
  - Added API coverage for lifecycle event sequence retrieval.
  - Added worker coverage for retry and dead-letter event emission.
  - Added replay coverage asserting `replayed` event persistence.

## Validation

- Targeted backend tests:
  - `pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (28 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.prod.yml config` -> PASS.
- Alembic migration:
  - Host-side upgrade against compose PostgreSQL -> PASS.
  - Current revision: `20261118_0012 (head)`.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - Redis/inline job lifecycle API smoke returned `queued -> running -> success` event sequence.

## Notes

- This stage keeps event durability in the primary relational store, which makes downstream fan-out to streams/webhooks safe to add later without losing source-of-truth ordering.
- Backend runtime images still do not embed Alembic project files; migration execution remains a host/project-environment responsibility.
