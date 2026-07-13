# PLATFORM-CORE-ASYNC-CONSUMER-RUNBOOK-GOVERNANCE-022 Report

## Scope

Implemented governance controls for high-impact jobs consumer runbooks: mandatory metadata on execute, policy-based allow/deny decisions, per-runbook cooldown enforcement, and diagnostics visibility for compliant vs denied runbook activity.

## Delivered

- High-impact runbook governance metadata:
  - Extended `POST /api/v1/jobs/event-consumer-runbook` request with:
    - `reason_code`
    - `change_ticket_ref`
    - `approved_by_email`
  - Enforced governance requirements for high-impact execute paths:
    - valid `reason_code` from approved governance set,
    - mandatory `change_ticket_ref` (configurable),
    - optional dual-control approver that must differ from actor.

- Policy controls for runbook execution:
  - Added settings-driven allow/deny model:
    - `jobs_event_runbook_allowed_codes`
    - `jobs_event_runbook_denied_codes`
    - `jobs_event_runbook_high_impact_codes`
  - Added per-runbook execute cooldown map:
    - `jobs_event_runbook_cooldown_seconds_map`
  - Added governance toggles:
    - `jobs_event_runbook_require_change_ticket`
    - `jobs_event_runbook_dual_control_required`

- Denial audit trail and denied feed:
  - Added explicit denied audit action `jobs.event_consumer_runbook.denied` with structured denial reason/detail metadata.
  - Denied decisions are committed before response to preserve operator/audit visibility.

- Diagnostics expansion for runbook governance:
  - Per-consumer diagnostics now include:
    - `runbook_governance_compliant_24h`
    - `runbook_governance_denied_24h`
  - Global diagnostics now include:
    - `runbook_governance_compliant_actions_24h`
    - `runbook_governance_denied_actions_24h`
    - `recent_runbook_denied_actions`
  - Runbook execution summaries now persist governance metadata for compliance accounting.

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

- Cooldown guard evaluates recent `jobs.event_consumer_runbook.execute` audit actions scoped by consumer and runbook code.
- High-impact governance is applied to execute mode; dry-run remains policy-guarded (allow/deny) but does not require execute metadata.
- Governance counters aggregate persisted runbook execution summaries (compliant) plus denied audit actions (denied), providing an explicit compliant-vs-denied operator view.
