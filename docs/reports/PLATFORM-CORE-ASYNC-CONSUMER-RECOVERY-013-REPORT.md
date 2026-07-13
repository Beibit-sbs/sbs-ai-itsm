# PLATFORM-CORE-ASYNC-CONSUMER-RECOVERY-013 Report

## Scope

Implemented operator-targeted recovery tooling for consumer deliveries with bounded replay selection, dry-run preview, execution protection, and consumer isolation guarantees.

## Delivered

- Recovery service logic:
  - Added `recover_job_event_consumer_deliveries(...)` in jobs service.
  - Supports bounded selection by:
    - `consumer_name`
    - `status` (`failed` and/or `pending`)
    - optional lifecycle `event_types`
    - `limit` cap
  - `dry_run=true` returns preview without mutations.
  - `dry_run=false` re-queues selected deliveries by resetting attempts and status for worker retry path.
  - Does not mutate durable lifecycle event source records.
- Protected API endpoint:
  - Added `POST /api/v1/jobs/event-consumer-recovery`.
  - Execution mode requires root permission and explicit header guard:
    - `X-Recovery-Confirm: CONFIRM`
  - Validates supported consumers and allowed statuses.
- Tests:
  - Added API coverage for:
    - dry-run preview
    - protected execution requirement
    - isolated replay semantics (notifications consumer recovery does not alter automation consumer rows)
    - repeated execution stability.

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (40 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.prod.yml --env-file .env.production config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS.
- Runtime recovery API checks:
  - Dry-run `POST /jobs/event-consumer-recovery` -> PASS.
  - Execute `POST /jobs/event-consumer-recovery` with `X-Recovery-Confirm: CONFIRM` -> PASS.

## Notes

- Recovery path intentionally re-drives downstream consumer processing state only.
- Persistent lifecycle source (`job_lifecycle_events`) remains immutable under recovery operations.
