# SC-004 — Self-service Catalog Portal

## Outcome

The catalog is now a durable self-service portal rather than a static list.
Users can personalize discovery, return to frequently used services, review
relevant published knowledge before ordering, and explicitly record that an
article prevented a request. The flow remains tenant-safe and survives reloads.

## Delivered

- Additive Alembic revision `20260729_0032`.
- Tenant- and user-scoped catalog preferences:
  - favorites;
  - view and request counters;
  - last-viewed and last-requested timestamps.
- Personal catalog panels for favorite and recently used services.
- Favorite-only filtering and accessible, uniquely labelled card actions.
- View telemetry when details or the request flow are opened.
- Request telemetry only for genuinely new requests; idempotent retries do not
  inflate demand.
- Knowledge deflection before request submission:
  - relevance-ranked public/internal published articles;
  - article summary, metadata, and preview;
  - durable knowledge deep links;
  - an explicit “resolved without request” action and usage log.
- Knowledge category creation for authorized knowledge managers.
- Requester knowledge boundary hardened across list, pagination, search, and
  direct article reads: drafts, archived articles, and restricted visibility
  are not exposed.
- Keyboard and accessibility baseline:
  - focus restoration after closing dialogs;
  - Escape closes the active catalog dialog;
  - visible global `:focus-visible` state;
  - explicit dialog labelling;
  - distinct accessible names for repeated card actions.
- Responsive CSS baseline for catalog cards, personal panels, deflection cards,
  forms, and mobile action stacking.

## API surface

- `POST /api/v1/catalog/items/{item_id}/view`
- `PUT /api/v1/catalog/items/{item_id}/favorite`
- `GET /api/v1/catalog/items/{item_id}/knowledge-suggestions`
- `POST /api/v1/catalog/items/{item_id}/knowledge/{article_id}/resolved`
- `POST /api/v1/knowledge/categories`

Existing catalog list/detail responses now include the current user's
preference state and usage counters.

## Security and data invariants

- Preference identity is unique for tenant, user, and catalog item.
- Catalog-item lookup remains tenant-scoped before preference mutation.
- Cross-tenant favorite mutation returns not found.
- Deflection suggestions only include published articles visible to a
  requester.
- Knowledge list/search/direct-read paths apply the same visibility rule.
- Request counters advance after successful new request persistence, not on an
  idempotent replay.
- Deflection usage logs retain article, catalog item, and request-avoidance
  context for later analytics.

## Local acceptance

- Related backend regression: **55 passed**.
- Ruff on all touched backend files: passed.
- TypeScript production build: passed.
- PostgreSQL migration head: `20260729_0032`.
- Docker staging:
  - backend: healthy;
  - frontend: healthy;
  - PostgreSQL: healthy;
  - Redis: healthy;
  - worker: running.
- Readiness checks:
  - PostgreSQL: ok;
  - Redis: ok;
  - migrations: ok;
  - runtime: ready;
  - websocket transport: ready.
- Browser acceptance:
  1. favorited a published service and confirmed persistence after reload;
  2. opened the request flow and confirmed the recently-used panel;
  3. created a knowledge category through the administrator UI;
  4. created and published article `KB-1001`;
  5. opened its `article_id` deep link and confirmed it survived reload;
  6. received the article as a catalog deflection suggestion;
  7. marked the article as resolving the need and confirmed the request dialog
     closed without creating a request.

Responsive behavior is implemented in CSS and the keyboard/ARIA interaction was
verified in the live browser. A separate physical-device matrix remains part of
release-candidate UX acceptance.

## Production boundary

SC-004 is production-grade locally. SC-005 must still add enforceable catalog
entitlements, cost and funding snapshots, policy-driven approval, SLA/OLA
timers, escalation, and tenant-safe demand/fulfillment analytics. Server
cutover remains intentionally deferred.

## Next product stage

`SC-005-ENTITLEMENTS-COST-SLA`.
