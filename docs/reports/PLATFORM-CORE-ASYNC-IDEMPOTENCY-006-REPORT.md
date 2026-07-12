# PLATFORM-CORE-ASYNC-IDEMPOTENCY-006 Report

## Scope

Implemented outbox publish idempotency guarantees for multi-worker safety and added outbox diagnostics visibility for operations.

## Delivered

- Outbox schema/model hardening:
  - Added `dedup_key` (non-null), `publish_attempted_at`, `lock_owner`, `lock_expires_at`.
  - Added migration `20261117_0011_job_outbox_idempotency`.
- Migration resiliency:
  - Added duplicate cleanup before unique index creation to support upgrading environments with historical duplicate outbox rows.
- Jobs service updates:
  - `create_outbox_entry(...)` now uses deterministic dedup key (`<queue>:<job_id>`) and idempotent lookup semantics.
  - Added `outbox_summary(...)` aggregation for total/pending/published/with_failures.
- API updates:
  - Added `GET /jobs/outbox-summary` endpoint for diagnostics.
- Worker idempotency updates:
  - Added lock metadata usage in outbox publish selection.
  - Added Redis publish dedup guard with `SET NX EX` key (`jobs:publish-dedup:<dedup_key>`) to avoid duplicate `LPUSH` under concurrent workers.
- Frontend diagnostics:
  - Added outbox summary client API call.
  - Added outbox metrics section to admin system diagnostics page.
- Tests:
  - Added/updated tests for outbox summary and idempotent outbox entry behavior.
  - Adjusted replay outbox expectations to match deduplicated outbox semantics.

## Validation

- Targeted backend tests:
  - `pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (23 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.prod.yml config` -> PASS.
- Alembic migration:
  - Host-side upgrade against compose PostgreSQL -> PASS.
  - Current revision: `20261117_0011 (head)`.
- Runtime smoke:
  - Redis enqueue processed by worker to `success`.
  - `GET /jobs/outbox-summary` returned expected counters after processing.

## Notes

- Backend/worker runtime images currently include application package code but not Alembic project files (`alembic.ini` and `migrations/`), so DB migrations must be run from host/project environment.
- This stage closes the planned idempotency scope for outbox publish and replay dedup behavior.
