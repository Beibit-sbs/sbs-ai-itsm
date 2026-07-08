# SERVICE-DESK-PRODUCTION-001 Report

## Scope

Production hardening of Tickets module without adding a new large module and without breaking existing system modules.

## Backend Endpoints Added or Updated

Updated endpoints in `backend/app/api/v1/routes/tickets.py`:

- `GET /api/v1/tickets`
  - Added queue support via `queue` query param:
    - `all`
    - `mine`
    - `unassigned`
    - `critical`
    - `sla_breached`
    - `due_today`
    - `created_by_me`
    - `closed`
  - Preserved pagination envelope:
    - `{ items, total, page, page_size }`
- `POST /api/v1/tickets/{ticket_id}/transition`
  - Validates role permissions
  - Validates allowed status transition matrix
  - Writes history and audit
  - Handles timestamps:
    - `resolved_at`
    - `closed_at`
    - `reopened_at`
  - Creates notification events (safe mock flow)
- `POST /api/v1/tickets/{ticket_id}/assign`
  - Manager/admin/root can assign by `assignee_id`
  - Agent can take only unassigned ticket to self
  - Requester forbidden
  - Writes history/audit and notification
- `POST /api/v1/tickets/{ticket_id}/comments`
  - Added `is_internal`
  - Requester cannot add internal comments
  - Staff can add internal/public
- `GET /api/v1/tickets/{ticket_id}`
  - Requester sees only public comments
  - Staff sees public + internal comments

## Role Restrictions Implemented

- Requester:
  - Sees only own tickets
  - Can create tickets
  - Can comment own tickets (public only)
  - Cannot assign tickets
- IT Agent:
  - Sees own assigned + unassigned
  - Can take unassigned ticket
  - Can transition own tickets through allowed matrix
- IT Manager / Organization Admin / SaaS Root:
  - Full tenant ticket visibility
  - Can assign, change priority/category/SLA-related fields, close/reopen
- Security and other non-ticket modules remained intact

Also updated requester permissions seed in `backend/app/services/seed.py`:
- Added `tickets.comment` for requester role.

## Queues Implemented

Server-side queues implemented in `GET /api/v1/tickets`:

- all
- mine
- unassigned
- critical
- sla_breached
- due_today
- created_by_me
- closed

## Status Lifecycle and Compatibility

Canonical lifecycle covered:

- `new`
- `triage`
- `assigned`
- `in_progress`
- `waiting_user`
- `waiting_vendor`
- `resolved`
- `closed`
- `reopened`
- `cancelled`

Transition rules implemented exactly for transition endpoint.

Compatibility:
- Legacy `TRIAGED` mapped to canonical `TRIAGE` in API output compatibility flow.

## Comments and History Changes

Model updates:
- `backend/app/models/ticket_comment.py`:
  - Added `author_id`
  - Added `is_internal`
- `backend/app/models/ticket.py`:
  - Added `requester_id`
  - Added `assignee_id`
  - Added `closed_at`
  - Added `reopened_at`

History events now cover:
- creation
- status changes
- assignment
- comments
- close/reopen related events

## SLA State Behavior

Added service layer `backend/app/services/sla.py` with:
- `calculate_sla_state(ticket)` returning:
  - `badge`
  - `response_remaining_minutes`
  - `resolution_remaining_minutes`
  - `is_response_breached`
  - `is_resolution_breached`

Ticket API includes these SLA fields in list/detail responses.

## Frontend Changes

Updated `frontend/src/api/client.ts`:
- Added queue param support in `fetchTicketsPage`
- Added types for new SLA fields and internal comments
- Added API methods:
  - `transitionTicket(...)`
  - `assignTicket(...)`

Updated `frontend/src/pages/TicketsPage.tsx`:
- Queue switcher:
  - Все
  - Моя очередь
  - Неназначенные
  - Критичные
  - SLA просрочено
  - На сегодня
  - Созданные мной
  - Закрытые
- Filters:
  - search
  - status
  - priority
  - category
  - assignee
  - page_size
- Detail modal actions:
  - take ticket
  - assign
  - transition status
  - close
  - reopen
  - add comment
- Modal tabs:
  - Обзор
  - Комментарии
  - История
  - SLA
  - Актив
  - AI

## Tests Added or Expanded

Replaced/expanded `backend/tests/test_tickets.py` with coverage for:
- requester sees only own tickets
- requester cannot assign
- requester cannot write internal comment
- agent sees own + unassigned
- agent can take unassigned ticket
- manager can assign ticket
- invalid transition rejected
- valid transition writes history and audit
- public/internal comment visibility
- pagination envelope still works
- queue filters work
- SLA state fields present
- closed ticket can be reopened by manager

## Validation Results

Backend tests:
- Command: `/home/sbs/sbs-ai-itsm-foundation-001/.venv/bin/python -m pytest -q`
- Result: `120 passed, 2 warnings`

Frontend typecheck:
- Command: `cd frontend && npx tsc -b --pretty false`
- Result: PASS

Frontend build:
- Command: `cd frontend && npm run build`
- Result: PASS

Docker compose config:
- Command: `docker compose config`
- Result: PASS

## Migration Gate (RUN_STARTUP_DDL=false)

Production migration requirement is satisfied with a dedicated Alembic revision:

- File: `backend/migrations/versions/20261109_0002_service_desk_ticket_fields.py`
- Revision: `20261109_0002`
- Down revision: `20261108_0001`

Schema changes covered by migration:

- `tickets.requester_id` (nullable, FK -> `users.id`, `ON DELETE SET NULL`)
- `tickets.assignee_id` (nullable, FK -> `users.id`, `ON DELETE SET NULL`)
- `tickets.closed_at` (nullable timestamptz)
- `tickets.reopened_at` (nullable timestamptz)
- `ticket_comments.author_id` (nullable, FK -> `users.id`, `ON DELETE SET NULL`)
- `ticket_comments.is_internal` (boolean, non-null, server default `false`)

Indexes added by migration:

- `ix_tickets_requester_id`
- `ix_tickets_assignee_id`
- `ix_ticket_comments_author_id`

Implementation note:

- Migration is written with schema-introspection guards to be idempotent/safe against partially upgraded local environments.

## Browser Smoke-Check

Target:
- `http://localhost:5173/tickets`

Observed:
- During browser-tool checks, shared tab context intermittently returned stale snapshot from previous bundle and later produced `net::ERR_CONNECTION_RESET` in automation browser context.
- Runtime bundle inspection from built artifact confirms new tickets UI code and modal tabs/actions are present in deployed JS bundle.
- Container services were healthy after rebuild (`backend` healthy, `frontend` up, `docker compose up --build -d` successful).

Smoke checklist status:
- Page opening in real stack: PASS (validated previously in shared page before browser-tool instability)
- Queue switch / modal flow / tabs / actions: Implemented and bundled; browser-automation verification partially blocked by transport instability.
- Console errors in browser-tool context: saw transient 401 (expected before login) and browser transport reset; no backend crash.

## Known Limitations

- Browser automation tool had intermittent transport/reset issues while validating latest page instance after rebuild, so part of smoke-check was confirmed by build artifact + service logs instead of full interactive automation.
- `PATCH /tickets/{id}` keeps manager/admin compatibility for direct status update to avoid regressions in existing tests/modules; strict transition matrix is enforced by dedicated transition endpoint.

## Safety Constraints Compliance

- No data deletion performed
- No DB recreation performed
- No `docker compose down -v`
- RBAC not disabled
- Pagination envelope preserved
- No external real email/integration calls enabled
- `.env.production` not touched/staged in this stage
- Secrets not printed
