# SC-002 — Dynamic Forms and Custom Fields

## Outcome

Service Catalog items can now own governed, tenant-safe request forms built
without code. Managers edit a draft, preview the requester experience, and
publish an immutable version. Requesters complete that published version, and
the backend validates the answers again before the Service Desk request is
opened.

## Delivered

- Additive `catalog_form_versions` model and Alembic revision
  `20260729_0030`.
- One editable draft per catalog item and immutable published/retired versions.
- Optimistic `revision` checks with HTTP 409 conflict protection.
- Canonical JSON and SHA-256 schema hashes for version identity and request
  traceability.
- Typed fields:
  - short and long text;
  - number and boolean;
  - single and multiple choice;
  - date and email.
- Reusable ordered sections, labels, help text, placeholders, required rules,
  choices, length/range/pattern constraints, and conditional visibility.
- Definition validation for duplicate/invalid keys, unavailable sections,
  invalid options, unsafe regular expressions, invalid ranges, and forward or
  self-referencing field dependencies.
- Submission validation that ignores hidden fields, normalizes values, rejects
  unavailable choices, and reports field-level Russian-language errors.
- Attachment policy metadata with count, size, extension, and required-file
  validation.
- Tenant isolation, `catalog.read`, `catalog.manage`, `catalog.publish`, and
  audited draft/update/publish operations.
- No-code manager designer with field ordering, sections, constraints,
  conditions, attachment policy, preview, save, publish, and version strip.
- Requester renderer with client feedback plus authoritative backend
  validation.
- Catalog-to-ticket transfer of the selected service, form version, schema hash,
  and visible normalized answers.

## API surface

- `GET /api/v1/catalog/items/{id}/form`
- `GET /api/v1/catalog/items/{id}/form?mode=draft`
- `GET /api/v1/catalog/items/{id}/form/versions`
- `POST /api/v1/catalog/items/{id}/form/draft`
- `PUT /api/v1/catalog/items/{id}/form/draft`
- `POST /api/v1/catalog/items/{id}/form/publish`
- `POST /api/v1/catalog/items/{id}/form/validate`

## Local acceptance

- New focused form tests: **2 passed**.
- Catalog, form, administration, and migration-graph regression:
  **38 passed**.
- Ruff: passed.
- TypeScript project build: passed.
- Production frontend and backend container builds: passed.
- PostgreSQL upgraded from `20260728_0029` to `20260729_0030`.
- Production-local readiness: PostgreSQL, Redis, migrations, runtime, and
  websocket transport all reported ready.
- Browser console errors: none.
- Browser E2E:
  - opened the existing published business-application access service;
  - created a no-code draft with a required system choice and required
    minimum-length justification;
  - verified preview;
  - published form v1;
  - proved empty required values are rejected;
  - selected CRM and entered a valid justification;
  - reached the Service Desk request modal with topic, catalog identity, form
    version/hash, and answers prefilled.

## Production boundary

Attachment policy and file metadata validation are implemented, but binary
upload to protected object storage and attachment-to-request persistence are
not yet present. The UI states this explicitly. They must be completed with
malware scanning, authorization, tenant-safe storage keys, download auditing,
and retention policy before attachments are considered production-complete.

SC-002 intentionally does not create dedicated requested-item, approval, or
fulfillment-task records. Those belong to SC-003.

## Next product stage

`SC-003-REQUEST-FULFILLMENT`:

- request and requested-item aggregates;
- sequential and parallel approvals;
- fulfillment tasks, assignment, escalation, and evidence;
- rejection, cancellation, rework, and atomic lifecycle transitions;
- idempotent creation and automation hooks;
- requester and fulfiller timelines.
