# PLATFORM-CORE-ASYNC-REPLAY-SCHEDULED-004 Report

## Scope

Implemented dead-letter replay API and switched retry flow from blocking sleep to scheduled retries.

## Delivered

- Jobs API:
  - Added `POST /api/v1/jobs/{job_id}/replay` (SaaS root only).
  - Replay is allowed for jobs in `dead_letter` status.
  - Replay resets attempts/error/result/runtime fields and re-enqueues in Redis mode.
- Jobs service:
  - Added public `enqueue_job_id(...)` helper for requeue/replay flows.
  - Kept `_enqueue_job_id(...)` alias for backward compatibility in tests.
- Worker retry model:
  - Added scheduled retry queue key convention: `<jobs_queue>:scheduled`.
  - Failed jobs with remaining attempts are scheduled with exponential backoff via Redis sorted set.
  - Worker drains due scheduled jobs into main queue every loop iteration.
  - Removed blocking retry `sleep` behavior.
- Tests:
  - Added replay API coverage in `tests/test_jobs.py`.
  - Added scheduled queue helper tests in `tests/test_jobs_worker.py`.

## Validation

- Backend tests:
  - `pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS
- Frontend build:
  - `npm run build` -> PASS
- Runtime smoke:
  - dead-letter job can be replayed (status reset to `queued`).
  - scheduled retry helpers validated by unit tests.

## Notes

- Replay currently reuses the same job row (same `job_id`) for operational trace continuity.
- For stronger exactly-once guarantees, a future outbox/transactional enqueue stage is still recommended.
