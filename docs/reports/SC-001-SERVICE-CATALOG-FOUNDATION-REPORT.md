# SC-001 — Service Catalog Foundation

## Outcome

SBS AI ITSM now has a real tenant-scoped Service Catalog rather than only
generic ticket creation. Administrators can bootstrap an organization, build
the catalog taxonomy, create governed catalog items, move them through review
and publication, and expose published services to requesters.

## Delivered

- Service categories, services, offerings, catalog items, and immutable item
  history.
- Draft, review, published, and retired lifecycle with explicit transition
  rules.
- Optimistic item version checks and HTTP 409 protection against stale writes.
- Owner, support group, expected delivery time, approval requirement, and
  entitlement-rule metadata.
- Tenant isolation, catalog read/manage/publish permissions, and audit events
  for all mutations.
- Audited editing of categories, services, and offerings.
- Root bootstrap of an isolated organization with six standard ITSM roles:
  Organization Admin, IT Manager, IT Agent, Requester, Security Officer, and
  Knowledge Manager.
- Tenant-aware user provisioning with an explicit organization selector,
  tenant-filtered roles, readable permission guidance, and backend protection
  against cross-tenant or global-role assignment.
- Self-service catalog at `/catalog` with summary, search, category and
  lifecycle filters, detailed service cards, and management workspace.
- A ticket bridge that opens the Service Desk request form with the catalog
  service name, code, and description already populated.
- Additive Alembic revision `20260728_0029`.

## API surface

- `GET/POST /api/v1/tenants`
- `GET/PATCH /api/v1/tenants/current`
- `GET/POST/PATCH /api/v1/catalog/categories`
- `GET/POST/PATCH /api/v1/catalog/services`
- `GET/POST/PATCH /api/v1/catalog/offerings`
- `GET/POST /api/v1/catalog/items`
- `GET/PATCH /api/v1/catalog/items/{id}`
- `POST /api/v1/catalog/items/{id}/transition`
- `GET /api/v1/catalog/items/{id}/history`
- `GET /api/v1/catalog/summary`

## Local acceptance

- Production Docker topology rebuilt successfully.
- PostgreSQL migration reached the new catalog head.
- Local tenant `sbs-local` provisioned through the product API.
- Two categories, two services, three offerings, and three representative
  items are present and published:
  - Corporate VPN access;
  - business application access;
  - approved software installation.
- Browser QA verified the storefront, catalog management workspace,
  organization bootstrap screen, UTF-8 content, and catalog-to-ticket bridge.
- Focused catalog tests: **5 passed**.
- Related auth, admin-security, ticket, migration, and catalog regression:
  **64 passed**.
- Ruff and TypeScript checks passed.
- Production frontend and backend container builds passed.

## Known boundary

Catalog ordering currently opens a governed, prefilled Service Desk ticket.
Dedicated requested-item, approval, fulfillment-task, and request-timeline
entities belong to SC-003. Typed and conditional request forms belong to
SC-002.

## Next product stage

`SC-002-DYNAMIC-FORMS-AND-CUSTOM-FIELDS`:

- typed fields and validation;
- conditional visibility and dependencies;
- reusable form sections;
- immutable form schema versions;
- attachment rules;
- administrative preview and test mode.
