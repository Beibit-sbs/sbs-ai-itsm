# PLATFORM-CORE-ASYNC-OBSERVABILITY-007 Report

## Scope

Implemented outbox observability diagnostics for operator triage, including contention counters, dedup-skip visibility, threshold-based status evaluation, and actionable runbook guidance.

## Delivered

- Backend diagnostics aggregation:
  - Added `outbox_diagnostics(...)` to compute outbox totals plus operational counters for:
    - pending rows;
    - published rows;
    - rows with failures;
    - active locks;
    - stale locks;
    - dedup skips (`dedup_skip_already_published`);
    - publish failure rate percentage.
- Threshold and status evaluation:
  - Added alert thresholds for pending backlog, failure count, and stale locks.
  - Added derived outbox status: `ok`, `warn`, `critical`.
  - Added `recommended_actions` to speed operator triage.
- API surface:
  - Kept `GET /jobs/outbox-summary` for compact counters.
  - Added `GET /jobs/outbox-diagnostics` for runbook-level diagnostics.
- Frontend diagnostics:
  - Added typed client support for outbox diagnostics.
  - Extended admin system diagnostics page with outbox status, lock counters, dedup skips, failure rate, thresholds, and recommended action text.
- Tests:
  - Added coverage for diagnostics endpoint shape.
  - Added coverage for threshold breach escalation to `critical` with expected counters.

## Validation

- Targeted backend tests:
  - `pytest -q tests/test_jobs.py` -> PASS (22 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.prod.yml config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend frontend` -> PASS.
  - `GET /jobs/outbox-summary` -> PASS.
  - `GET /jobs/outbox-diagnostics` -> PASS.

## Notes

- This stage is intentionally additive: it does not change worker publish semantics, only exposes existing outbox state in an actionable operational form.
- Backend runtime images still do not embed Alembic project files; migration execution remains a host/project-environment responsibility.
