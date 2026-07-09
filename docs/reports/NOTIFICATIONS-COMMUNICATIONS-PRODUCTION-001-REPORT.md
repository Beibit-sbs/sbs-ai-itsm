# NOTIFICATIONS-COMMUNICATIONS-PRODUCTION-001 Report

## Scope
- Upgraded notifications and communications module to production-ready contracts.
- Preserved compatibility for legacy notification records and existing routes consuming notification services.
- Kept all changes additive and non-destructive.

## Backend Changes
- Extended models:
  - `Notification`: added `user_id`, `tenant_id`, `event_type`, `severity`, `entity_type`, `entity_id`, `action_url`, `is_read`, `expires_at`, `metadata_json`.
  - `NotificationTemplate`: added `tenant_id`, `key`, `event_type`, `locale`.
  - `EmailMessageLog`: added queue/retry and metadata fields (`tenant_id`, `notification_id`, `event_type`, `provider_message_id`, `to_name`, `attempt_count`, `max_attempts`, `next_retry_at`, `payload_json`, `metadata_json`).
  - Added new `NotificationPreference` model/table.
- Refactored `app/services/notifications.py`:
  - Paged notifications and email log listing.
  - Preferences seed/get/patch.
  - Retry for email log records.
  - Generic domain event notification helper.
  - Legacy compatibility retained (`create_ticket_event_notification`, old fields).
- Refactored `app/api/v1/routes/notifications.py`:
  - `GET /notifications` now returns paged envelope with `unread_count`.
  - Added preferences endpoints:
    - `GET /notifications/preferences`
    - `PATCH /notifications/preferences`
  - Split template permissions (`read` and `update`).
  - Upgraded email log endpoint to paged response and added retry endpoint:
    - `POST /notifications/email-log/{id}/retry`
  - Kept `POST /notifications/test-email` mock-safe.
- Runtime schema patcher discipline hardening:
  - `app/services/notifications_schema.py` is now strictly gated to `sqlite` only.
  - No startup DDL is executed for PostgreSQL production runtime.
  - Production schema authority remains Alembic migration `20261112_0006`.
- Added migration:
  - `backend/migrations/versions/20261112_0006_notifications_communications_production.py`
  - Migration upgraded to idempotent-additive behavior for environments where columns may already exist from previous bootstrap flows.

## RBAC Changes
- Updated permission catalog and role mappings in `app/services/seed.py`:
  - `notifications.read`
  - `notifications.update`
  - `notifications.manage`
  - `notifications.templates.read`
  - `notifications.templates.update`
  - `notifications.email_log.read`
  - `notifications.email_log.retry`
  - `notifications.preferences.update`

## Event Integrations Added
- Assets routes (`move`, `verify`, `dispose`) now emit notification events.
- Automation route emits notification on failed/manual run error state and rejected approvals.
- Knowledge routes emit publication notifications.
- Reports export emits notification event.

## Frontend Changes
- `frontend/src/api/client.ts`:
  - Updated notification/email contracts to paged responses.
  - Added preferences and retry APIs.
  - Added backward-compatible parsing for legacy array responses.
- `NotificationsPage`:
  - Added 5-tab flow: center, unread, settings, templates, email-log.
  - Settings tab supports preference toggles.
  - Templates tab supports activation toggle.
- `EmailLogPage`:
  - Added pagination, retry action, and detail panel.
- `AppShell`:
  - Notification badge polling tuned from 15s to 30s.
- `DashboardPage`:
  - Adapted to new notifications response envelope.

## Testing and Validation
- Alembic validation:
  - `/home/sbs/sbs-ai-itsm-foundation-001/.venv/bin/python -m alembic heads` -> `20261112_0006 (head)`.
  - `upgrade head` executed against localhost Postgres with credentials from local `.env` (without printing secrets).
  - `current` -> `20261112_0006 (head)`.
  - Migration 0006 checks passed for additive behavior (no table recreation, no destructive operations in upgrade path).
- Backend pytest (full):
  - `/home/sbs/sbs-ai-itsm-foundation-001/.venv/bin/python -m pytest -q` -> `139 passed, 3 warnings`.
- Targeted notifications tests:
  - `/home/sbs/sbs-ai-itsm-foundation-001/.venv/bin/python -m pytest -q backend/tests/test_notifications.py` -> module passed.
- Frontend type/build validation:
  - `npx tsc -b --pretty false` passed.
- Frontend build:
  - `npm run build` passed.
- Docker compose config:
  - `docker compose config` passed.
- Runtime rebuild/start:
  - `docker compose up -d --build backend frontend` passed.
- Backend smoke checks:
  - Admin and manager logins succeeded.
  - `GET /api/v1/notifications` -> 200.
  - `GET /api/v1/notifications/unread-count` -> 200.
  - `GET /api/v1/notifications/preferences` -> 200.
  - `GET /api/v1/notifications/templates` -> 200.
  - `GET /api/v1/notifications/email-log` -> 200.
  - `POST /api/v1/notifications/test-email` -> 201 (mock `SENT`).
  - `POST /api/v1/notifications/email-log/{id}/retry` -> 200 (attempt incremented).
- Browser smoke checks:
  - `/notifications` opened, unread badge visible.
  - Single `mark read` action worked.
  - `mark all read` worked (unread count dropped to 0).
  - Preferences tab opened and toggle persisted.
  - Templates tab opened and rendered.
  - `/notifications/email-log` opened; retry button correctly hidden when no failed/pending row is available.
  - `/tickets` opened and rendered normally.
  - `/analytics` opened and rendered normally.
  - No critical blocking UI errors were observed during route smoke-check.

## Notes
- No external email providers are used; all flows remain mock-safe.
- No destructive DB operations were performed.
- No commit or push was performed.
- Known limitations:
  - Test run shows 3 non-blocking warnings (FastAPI/Starlette deprecation and one unraisable warning on interrupt context), no failing tests.
  - Frontend build reports bundle size warning (>500kb), non-blocking for this stage.
