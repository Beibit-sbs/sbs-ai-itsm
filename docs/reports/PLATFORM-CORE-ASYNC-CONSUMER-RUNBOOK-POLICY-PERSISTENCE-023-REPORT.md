# PLATFORM-CORE-ASYNC-CONSUMER-RUNBOOK-POLICY-PERSISTENCE-023 Report

## Scope

Implemented persistent runbook governance policy state with versioning and optimistic concurrency, added runtime API to inspect and mutate runbook governance policy without restart, and extended diagnostics with runbook policy version/hash/rollout history.

## Delivered

- Versioned DB persistence for runbook governance policy:
  - Added model `job_event_runbook_policy_states` with versioned payload state.
  - Added additive migration `20261121_0016_job_event_runbook_policy_state.py`.
  - Added service `runbook_policy_state.py` with:
    - state bootstrap from settings,
    - load/apply into runtime settings,
    - optimistic concurrency save with explicit conflict error.

- Startup/runtime policy reload:
  - Application startup now loads persisted runbook policy into settings.
  - Runbook execution path reloads policy state from DB before governance checks.

- Runtime runbook policy API:
  - Added `GET /api/v1/jobs/event-consumer-runbook-policy`.
  - Added `POST /api/v1/jobs/event-consumer-runbook-policy` with `expected_version` optimistic concurrency token.
  - Added policy update audit action `jobs.event_consumer_runbook_policy.update` with old/new hash and version metadata.

- Diagnostics expansion for runbook governance persistence:
  - Added fields to jobs consumer diagnostics:
    - `runbook_policy_version`
    - `runbook_policy_hash`
    - `runbook_policy_rollouts_24h`
    - `recent_runbook_policy_rollouts`
  - Existing runbook governance compliant/denied metrics remain and now align with persisted policy lifecycle.

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py` -> PASS.
  - `../.venv/bin/python -m pytest -q tests/test_jobs_worker.py` -> PASS.
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS (after warm-up retry).

## Notes

- Runbook policy stale writes return `409` with explicit version mismatch detail.
- Tests cover update/readback from persisted policy state and stale version conflict path.
- Policy hash is computed from normalized payload snapshot used by runtime governance checks.
