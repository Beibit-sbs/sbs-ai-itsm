# PLATFORM-CORE-ASYNC-WORKER-002 Report

## Scope

Implemented queue-backed asynchronous job execution with an out-of-process worker while preserving existing jobs API contracts.

## Delivered

- Added execution mode settings:
  - `JOBS_EXECUTOR_MODE` (`inline` or `redis`)
  - `JOBS_QUEUE_NAME` (default `jobs:queue`)
- Extended jobs service with Redis enqueue path:
  - `enqueue_task(...)` persists `job_runs` row as `queued` and pushes job id into Redis list.
  - `JobQueueUnavailableError` for queue submission failures.
- Extended jobs API:
  - `GET /api/v1/jobs/runtime` to expose execution mode and queue metadata.
  - `POST /api/v1/jobs/enqueue` now switches behavior by mode:
    - `inline`: execute immediately (existing behavior).
    - `redis`: persist queued row and return immediately.
- Added worker runtime:
  - New module: `app.workers.jobs_worker`.
  - Worker loop uses Redis `BRPOP` and executes queued jobs through existing `execute_job(...)` path.
  - Added resilience for Redis socket read timeouts: worker catches timeout and continues polling.
  - Added race mitigation for enqueue/commit ordering: worker requeues temporary `job_not_found` IDs with bounded retries to prevent silent job loss.
- Infrastructure wiring:
  - Added `worker` service to both `docker-compose.yml` and `docker-compose.prod.yml`.
  - Backend and worker now receive jobs execution env configuration.
- Frontend diagnostics:
  - Added jobs runtime fetcher and UI display on `/admin/system` (executor mode, queue name, worker requirement).
- Tests:
  - Added runtime endpoint test.
  - Added redis-mode enqueue test that verifies `queued` status and deferred execution semantics.

## Validation

- `backend/tests/test_jobs.py`: PASS (15 tests)
- Frontend build: PASS (`npm run build`)
- Compose config: PASS (`docker compose config`, `docker compose -f docker-compose.prod.yml config`)
- E2E worker smoke: PASS (`/jobs/runtime` reports `redis`; enqueue returns `queued`; job transitions to `success` via worker)

## Notes

- Test suite defaults to `JOBS_EXECUTOR_MODE=inline` for deterministic local execution.
- In compose environments the default mode is `redis`; ensure `worker` service is running to drain queue.
- Existing API response structure for job runs is preserved.
