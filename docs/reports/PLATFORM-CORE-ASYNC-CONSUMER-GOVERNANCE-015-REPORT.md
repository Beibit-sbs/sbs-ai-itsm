# PLATFORM-CORE-ASYNC-CONSUMER-GOVERNANCE-015 Report

## Scope

Added governance controls for recovery execution with structured operator context, optional dual-control policy, and diagnostics compliance indicators.

## Delivered

- Governance validations on execute recovery path:
  - `reason_code` required and validated against allowed governance codes.
  - `change_ticket_ref` required when governance setting is enabled.
  - Optional dual-control mode with required `approved_by_email` different from actor.
- Structured recovery audit metadata:
  - Recovery preview/execute audit entries now persist governance context fields:
    - `reason_code`
    - `change_ticket_ref`
    - `approved_by_email`
- Diagnostics governance indicators:
  - Extended `/jobs/event-consumers-diagnostics` with:
    - `governance_execute_actions_24h`
    - `governance_compliant_actions_24h`
    - `governance_compliance_rate_pct`
  - Per-consumer governance counters:
    - `governance_compliant_execute_24h`
    - `governance_missing_execute_24h`
  - Recent recovery actions now include governance compliance flag and governance fields.
- Settings:
  - Added governance toggles in config:
    - `jobs_event_recovery_require_change_ticket`
    - `jobs_event_recovery_dual_control_required`
- Reliability hardening:
  - Preserved UTC normalization in diagnostics/recovery timestamp arithmetic for sqlite/postgres consistency.

## Validation

- Targeted backend tests:
  - `../.venv/bin/python -m pytest -q tests/test_jobs.py tests/test_jobs_worker.py` -> PASS (42 passed).
- Frontend build:
  - `npm run build` -> PASS.
- Compose validation:
  - `docker compose config` -> PASS.
  - `docker compose -f docker-compose.prod.yml --env-file .env.production config` -> PASS.
- Runtime smoke:
  - `docker compose up -d --build backend worker` -> PASS.
  - `make smoke` -> PASS (after warm-up retry).
- Runtime governance checks:
  - Execute recovery without governance context -> `400`.
  - Execute recovery with governance context -> `200`.
  - Diagnostics expose governance compliance counters and rate -> PASS.

## Notes

- Governance validation applies to execute mode only; dry-run remains lightweight preview.
- Dual-control enforcement is configurable and can be enabled without code changes.
