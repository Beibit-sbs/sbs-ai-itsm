# PLATFORM-CORE-ASYNC-EVENT-BUS-009 Report

## Scope

Implemented relay/fan-out from durable job lifecycle events into Redis Stream transport with delivery-state tracking, retry semantics, and idempotent relay protection.

## Delivered

- Relay-state schema on durable events:
  - Extended `job_lifecycle_events` with stream name, relay publish timestamps, failure counters, last error, and relay lock metadata.
  - Added additive Alembic migration `20261119_0013_job_lifecycle_event_bus`.
- Event bus configuration:
  - Added `jobs_event_stream_name` setting with default `jobs:lifecycle`.
- Relay worker path:
  - Added `_relay_job_events_batch(...)` to worker loop.
  - Relay uses DB lock metadata to avoid multi-worker double processing.
  - Relay uses Redis dedup key `jobs:event-relay:<event_id>` for replay safety.
  - On `XADD` failure, the dedup key is explicitly released so retry can succeed.
- Consumer-safe event payload contract:
  - Redis stream entries include `event_id`, `job_id`, `event_type`, `task_name`, `tenant_id`, `actor_user_id`, `correlation_id`, `previous_status`, `current_status`, `payload_json`, `created_at`, and `source`.
- Diagnostics API:
  - Extended jobs runtime with `event_stream_name`.
  - Added `GET /jobs/event-bus-summary` for delivery-state visibility.
- Tests:
  - Added worker tests for relay success, relay retry after publish failure, and dedup skip semantics.
  - Added API tests for event-bus runtime field and event-bus summary endpoint.

## Validation

- Targeted backend tests:
  - `pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (32 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.prod.yml config` -> PASS.
- Alembic migration:
  - Host-side upgrade against compose PostgreSQL -> PASS.
  - Current revision: `20261119_0013 (head)`.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `GET /jobs/event-bus-summary` -> PASS.
  - `GET /jobs/{id}/events` -> PASS.
  - Redis Stream `jobs:lifecycle` length increased by 3 for `queued`, `running`, `success` on a smoke job.

## Notes

- The relational `job_lifecycle_events` table remains the source of truth; Redis Stream fan-out is a relay projection with retry and dedup protection.
- Backend runtime images still do not embed Alembic project files; migration execution remains a host/project-environment responsibility.
