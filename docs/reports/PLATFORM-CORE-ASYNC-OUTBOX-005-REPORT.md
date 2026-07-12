# PLATFORM-CORE-ASYNC-OUTBOX-005 Report

## Scope

Implemented transactional enqueue via database outbox to eliminate commit/enqueue race in Redis mode.

## Delivered

- Added outbox model and migration:
  - `app.models.job_queue_outbox`
  - Alembic revision `20261116_0010_job_queue_outbox`
- Jobs service changes:
  - Added `create_outbox_entry(...)`
  - Redis enqueue path now creates outbox entries in the same DB transaction instead of pushing directly to Redis.
  - Kept `enqueue_job_id(...)` utility for worker/runtime operations.
- Worker changes:
  - Added `_publish_outbox_batch(...)` to publish pending outbox rows to Redis and mark `published_at`.
  - Outbox publish runs each worker loop iteration before scheduled retries and BRPOP processing.
- Replay flow:
  - `POST /jobs/{job_id}/replay` in Redis mode now writes a new outbox entry (transactional) instead of direct Redis push.
- Tests:
  - Updated jobs API tests to assert outbox rows are created for enqueue/replay in Redis mode.
  - Existing worker scheduled retry tests remain green.

## Validation

- Targeted backend tests:
  - `pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS
- Frontend build:
  - `npm run build` -> PASS
- Compose validation:
  - `docker compose config` -> PASS
  - `docker compose -f docker-compose.prod.yml config` -> PASS
- Alembic head check:
  - `alembic heads` -> includes `20261116_0010` as head.
- Runtime smoke:
  - Redis-mode enqueue transitions `queued -> success` through worker (via outbox publish).
  - Dead-letter replay returns job to `queued` and worker processes it again.

## Notes

- This stage removes the enqueue-before-commit race without changing public jobs API shape.
- Next hardening step can add idempotency keys/unique constraints for outbox publish dedup across multi-worker deployments.
