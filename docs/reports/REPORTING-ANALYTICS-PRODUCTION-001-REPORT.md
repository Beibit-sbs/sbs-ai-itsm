# REPORTING-ANALYTICS-PRODUCTION-001 Report

## Scope
Production hardening for analytics and reporting module with:
- backend endpoint contract update
- granular RBAC and audit coverage
- reporting schema extension and migration
- frontend API/client alignment for new endpoints
- regression and smoke validation

## Implemented Backend API Contract

### Analytics
- `GET /api/v1/analytics/executive`
- `GET /api/v1/analytics/tickets`
- `GET /api/v1/analytics/sla`
- `GET /api/v1/analytics/assets`
- `GET /api/v1/analytics/knowledge`
- `GET /api/v1/analytics/ai`
- `GET /api/v1/analytics/security`
- `GET /api/v1/analytics/automation`

Filters supported on module endpoints:
- `date_from`
- `date_to`
- `group_by` (`day|week|month`)
- `category`
- `priority`
- `assignee_id`
- `status`

Legacy compatibility preserved:
- `GET /api/v1/analytics/executive-summary` delegates to executive endpoint
- `GET /api/v1/analytics/overview` preserved

### Reports
- `GET /api/v1/reports`
- `POST /api/v1/reports`
- `GET /api/v1/reports/{report_id}`
- `POST /api/v1/reports/{report_id}/run`
- `GET /api/v1/reports/snapshots`
- `POST /api/v1/reports/snapshots`
- `GET /api/v1/reports/snapshots/{snapshot_id}`
- `POST /api/v1/reports/export`

Export behavior:
- `format=json` returns JSON payload envelope
- `format=csv` returns `text/csv` with `Content-Disposition`

Legacy compatibility preserved:
- `GET /api/v1/reports/saved`
- `POST /api/v1/reports/saved`
- `GET /api/v1/reports/export-demo`

## KPI and Payload Coverage
Executive analytics payload now includes cross-module KPI blocks:
- tickets: volume, open/critical/overdue, distributions
- sla: compliance, breaches, at-risk, response/resolution averages
- assets: totals, active/disposed, missing room/MOL, verification counters
- knowledge: article totals, published/draft, views, helpfulness rate, top used
- ai: total/accepted/rejected, acceptance rate, confidence, type distributions
- security: failed logins, admin actions, high-risk events, inactive users
- automation: runs/success/failed/pending approvals
- integrations: system counts, health and failed events

## RBAC and Audit

### Added granular analytics permissions
- `analytics.executive.read`
- `analytics.tickets.read`
- `analytics.sla.read`
- `analytics.assets.read`
- `analytics.knowledge.read`
- `analytics.ai.read`
- `analytics.security.read`
- `analytics.automation.read`

### Added reports permission
- `reports.run`

### Role mapping updates
- `organization_admin`, `it_manager` expanded with full analytics module reads and `reports.run`
- `security_officer` expanded with executive/security analytics read
- legacy broad permissions remain for backward compatibility

### Audit actions emitted
- `analytics_viewed`
- `executive_analytics_viewed`
- `report_created`
- `report_run`
- `report_snapshot_created`
- `report_exported`

## Schema and Migration

### Model/schema additions
`saved_reports`:
- `visibility`
- `schedule_enabled`
- `created_by_id`

`report_snapshots`:
- `saved_report_id`
- `filters_json`
- `generated_by_id`
- `generated_at`

### Migration
- `backend/migrations/versions/20261111_0005_reporting_analytics_production.py`
- additive-only changes with downgrade support

### SQLite bootstrap helper
- `ensure_reporting_schema` updated for newly added reporting columns

## Frontend Alignment

Updated frontend API client and analytics page integration:
- analytics executive endpoint switched to `/analytics/executive`
- reports endpoints switched to `/reports` REST contract
- support for `run report`, snapshot details, and `/reports/export`
- added separate tabs for `Knowledge`, `AI`, `Automation`
- backward-compatible response mapping preserved in client layer

## Validation Results

### Backend tests
- `pytest tests/test_reporting_analytics.py -q`: passed (`19 passed`)
- `pytest -q`: passed (full suite, warnings only)

### Frontend validation
- `npx tsc -b --pretty false`: passed
- `npm run build`: passed

### Alembic
- `alembic heads`: `20261111_0005 (head)`
- local default DB upgrade failed due unresolved host `postgres` in host shell context
- fallback applied successfully with localhost URL:
  - `DATABASE_URL=postgresql+psycopg://sbs_itsm:change_me_before_production@localhost:5432/sbs_itsm alembic upgrade head`
  - `alembic current` => `20261111_0005 (head)`

### Docker Compose
- `docker compose config`: valid
- `docker compose up -d --build backend frontend`: initial backend startup failed before migration
- after migration upgrade on local postgres container: backend became healthy

### Runtime smoke check
Verified against running services:
- `GET /api/v1/health` -> 200
- auth login (manager) -> token issued
- `GET /api/v1/analytics/executive` -> 200 + KPI payload
- `GET /api/v1/reports` -> 200 + saved reports list
- `POST /api/v1/reports/export` with CSV -> 200 + `metric,value` CSV data

## Git Safety
- `.env.production` ignore check passed (`.gitignore:3:.env.production`)
- no auto-commit executed for this stage

## Known Limitations
- legacy endpoint aliases intentionally retained for compatibility and can be removed in a future cleanup milestone
- frontend still uses compatibility adapters for some legacy UI cards; direct consumption of new backend schemas can be simplified in next iteration
- full browser visual/manual UX smoke for every tab was not exhaustively scripted; API and build/runtime checks passed
