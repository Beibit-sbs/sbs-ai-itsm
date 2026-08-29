# SC-003 — Request, Approval, and Fulfillment

## Outcome

Published catalog forms now create dedicated, tenant-safe service requests
instead of incident tickets. A request moves through governed approval and
fulfillment states, exposes its complete history to authorized users, and
finishes only when its fulfillment tasks reach a terminal result.

## Delivered

- Additive Alembic revision `20260729_0031`.
- Dedicated aggregate entities:
  - service request;
  - requested item;
  - approval decision;
  - fulfillment task;
  - immutable activity event.
- Catalog-form snapshot identity using published form version and schema hash.
- Server-side form validation and normalization before request persistence.
- Idempotency-key protection for repeat submissions.
- Sequential and parallel approval modes with decision comments.
- Rejection, requester rework, request cancellation, and open-work shutdown.
- Fulfillment task assignment, optimistic version checks, controlled status
  transitions, completion evidence, and request status recomputation.
- Tenant isolation and permissions for read, create, manage, approve, fulfill,
  and comment actions.
- Audit events for request, approval, assignment, transition, rework, comment,
  and cancellation actions.
- Production seed synchronization for existing tenant roles.
- Dedicated `/requests` workspace with:
  - searchable/filterable queue and operational counters;
  - requester-visible progress and form answers;
  - approver decision controls;
  - fulfiller task controls and evidence;
  - comments, internal notes, cancellation, rework, and full timeline.
- Catalog submission now opens the created request directly.
- Deep links retain `request_id` through session restoration and page reload.

## API surface

- `POST /api/v1/requests`
- `GET /api/v1/requests`
- `GET /api/v1/requests/{request_id}`
- `POST /api/v1/requests/{request_id}/comments`
- `POST /api/v1/requests/{request_id}/cancel`
- `POST /api/v1/requests/{request_id}/items/{item_id}/rework`
- `POST /api/v1/requests/approvals/{approval_id}/decision`
- `POST /api/v1/requests/tasks/{task_id}/assign`
- `POST /api/v1/requests/tasks/{task_id}/transition`

## Lifecycle invariants

- A request is inserted before requested items, and requested items are inserted
  before approval/task/activity children. This explicit order is required
  because the lightweight models do not declare broad ORM relationships.
- Published form values are validated authoritatively on the backend.
- Approval and task mutations use version/state checks and reject stale or
  illegal transitions.
- A rejected item can be reworked into a new approval round.
- Cancellation closes pending approvals and active tasks.
- A request reaches `COMPLETED` only after all requested items complete.
- Requester access is limited to owned requests; management access remains
  tenant-scoped; SaaS Root has controlled global visibility.

## Local acceptance

- Focused lifecycle tests: **3 passed**.
- Catalog, forms, requests, migration graph, and production-safety regression:
  **38 passed**.
- Ruff: passed.
- TypeScript production build: passed.
- PostgreSQL migration head: `20260729_0031`.
- Production-local readiness:
  - PostgreSQL: ready;
  - Redis: ready;
  - migrations: ready;
  - application runtime: ready;
  - websocket transport: ready.
- Core Docker services were healthy; staging data and volumes were preserved.
- Browser console errors: none.
- Direct request deep link and page reload: passed.
- Live PostgreSQL browser E2E:
  1. selected published `REQ_BUSINESS_APP_ACCESS`;
  2. submitted CRM plus a validated business justification;
  3. created `REQ-20260728-26283ED7`;
  4. approved the request with a decision comment;
  5. created and started fulfillment task `RITM-20260728-47413055`;
  6. completed the task with fulfillment evidence;
  7. confirmed request, item, counters, progress, and timeline reached
     `COMPLETED`.

## Defects found and closed during acceptance

- PostgreSQL initially rejected request activity rows inserted ahead of their
  request parent.
- A second PostgreSQL check exposed requested-item insertion ahead of the
  service-request parent.
- Persistence now flushes the parent and item explicitly before child events.
- Terminal tasks no longer show a meaningless self-assignment action.
- Global SaaS Root no longer receives a self-assignment control that cannot
  satisfy tenant membership.
- Authentication restoration now preserves query strings and hash fragments,
  so request deep links survive a full reload.

## Production boundary

This stage is production-grade locally, but organization-specific approval
policies, entitlement/cost rules, OLA/SLA escalation, protected attachments,
and outbound notification delivery remain later roadmap stages. Server cutover
also remains intentionally deferred.

## Next product stage

`SC-004-SELF-SERVICE-CATALOG-PORTAL`:

- favorites and recently used services;
- knowledge deflection before submission;
- stronger catalog discovery and personalization;
- mobile and accessibility acceptance;
- preserved request tracking from direct links.
