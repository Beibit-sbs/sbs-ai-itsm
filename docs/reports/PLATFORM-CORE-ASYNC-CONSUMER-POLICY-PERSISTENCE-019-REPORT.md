# PLATFORM-CORE-ASYNC-CONSUMER-POLICY-PERSISTENCE-019 Report

## Scope

Implemented persisted auto-remediation policy state with versioning, optimistic concurrency in runbook updates, and diagnostics visibility for policy version and rollout history.

## Delivered

- Persistence model and migration:
  - Added model `JobEventAutoremediationPolicyState`.
  - Added additive migration `20261121_0015_job_event_autoremediation_policy_state.py`.
  - State stores:
    - global policy payload (profiles, suppression windows, denylist, canary defaults),
    - monotonic `version`,
    - update actor metadata and timestamps.

- Policy state service:
  - Added `app/services/jobs/policy_state.py` with:
    - initialization/default bootstrap,
    - startup/runtime load into settings,
    - persisted save with optimistic concurrency check (`expected_version`).
  - Added explicit conflict error path for stale version updates.

- Startup/runtime integration:
  - Backend startup now loads persisted policy into runtime settings.
  - Worker auto-remediation cycle reloads persisted policy state before evaluating cycle guards and policy.

- Runbook API hardening:
  - `POST /api/v1/jobs/event-consumer-autoremediation-policy` now requires `expected_version`.
  - Stale writes return `409 Conflict`.
  - Policy update audit metadata now includes previous/new policy versions.
  - `GET /api/v1/jobs/event-consumer-autoremediation-policy` now returns `policy_version`.

- Diagnostics policy observability:
  - Per-consumer diagnostics now include:
    - `policy_version`
    - `effective_policy_hash`
    - `policy_canary_mode`
    - `last_policy_change_at`
    - `last_policy_change_actor_email`
  - Global diagnostics now include:
    - `policy_version`
    - `policy_rollouts_24h`
    - `recent_policy_rollouts`

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (51 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS (after warm-up retry).

## Notes

- Policy persistence currently centralizes all auto-remediation runbook state under one versioned payload to prevent cross-process drift.
- Optimistic concurrency token (`expected_version`) prevents operator overwrite races in concurrent runbook sessions.
