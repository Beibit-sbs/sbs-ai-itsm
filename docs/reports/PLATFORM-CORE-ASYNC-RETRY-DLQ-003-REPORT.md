# PLATFORM-CORE-ASYNC-RETRY-DLQ-003 Report

## Scope

Implemented retry with exponential backoff and dead-letter handling for Redis worker mode.

## Delivered

- Jobs runtime settings extended in backend config:
  - `JOBS_DEAD_LETTER_QUEUE_NAME`
  - `JOBS_RETRY_BASE_SECONDS`
  - `JOBS_RETRY_MAX_SECONDS`
- Worker retry/dead-letter logic in `app.workers.jobs_worker`:
  - Failed jobs with remaining attempts are requeued with exponential backoff.
  - Jobs that exhaust `max_attempts` transition to `dead_letter` and are pushed into DLQ Redis list.
  - Redis socket timeout handling in poll loop preserved.
- Jobs API/runtime updates:
  - `POST /api/v1/jobs/enqueue` now accepts `max_attempts` (1..10).
  - `GET /api/v1/jobs/runtime` now returns dead-letter and retry policy metadata.
  - Summary now includes `dead_letter` counter.
- Built-in tasks updated with `system.flaky` for retry-path validation.
- Frontend diagnostics updates:
  - `/admin/system` now displays dead-letter queue and retry policy values.
  - Jobs summary now displays dead-letter counter.
- Deployment/config updates:
  - Added retry + DLQ env vars to `.env.example` and `.env.production.example`.
  - Added retry + DLQ env wiring in both compose files.

## Validation

- Tests:
  - `pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS
- Frontend:
  - `npm run build` -> PASS
- Compose:
  - `docker compose config` -> PASS
  - `docker compose -f docker-compose.prod.yml config` -> PASS
- Runtime smoke:
  - `system.flaky` with `max_attempts=3` recovered to `success` on attempt 2.
  - `system.fail` with `max_attempts=2` transitioned to `dead_letter`.
  - Redis DLQ contains dead-lettered job ids.

## Notes

- Current retry strategy is process-local sleep-based backoff inside worker loop; sufficient for foundation stage.
- Next hardening step can move retries to delayed queue scheduling to avoid worker thread sleep during backoff windows.
