# UX-004 — Branding and localization

**Status:** implementation complete; runtime acceptance gate pending  
**Date:** 2026-07-29  
**Migrations:** `20260729_0063`, `20260729_0064`

## Delivered

- Tenant-owned, versioned experience profiles with bounded identity, palette,
  formatting locale, IANA timezone, currency, date/hour/week policy, and
  controlled ITSM terminology.
- Immutable content-addressed PNG logos with size, count, dimension, chunk,
  CRC, encoding, and trailing-data controls.
- Optimistic revision locking, canonical snapshots, SHA-256 integrity,
  immutable history, minimized audit evidence, and restore-as-new rollback.
- Authenticated ETag/cache/fallback bootstrap, document and shell branding,
  shared Intl formatters, requester/operator/admin integration, and
  Configuration Center readiness.
- Tenant-scoped localized variants for knowledge articles and notification
  templates with exact schemas, supported-locale allowlist, source and payload
  hashes, version/revision controls, and bounded retention.
- Draft, edit, submit, independent approve/reject, publish, retire, and stale
  lifecycle with a database-enforced single published version.
- Four-eyes enforcement against both creator and latest submitting editor.
- Fail-closed active-content checks and exact notification placeholder
  preservation.
- Runtime resolution that serves only published, intact, source-current tenant
  content; all other states fall back to the source.
- Knowledge response evidence (`content_locale`, `translation_version`,
  `translation_status`) and tenant UI-locale notification rendering.
- Read-only global source inheritance for tenant administrators and explicit
  tenant-template precedence.
- Admin authoring workspace with root tenant selection, source and locale
  selection, draft editing, submission/review actions, version history, status,
  source currency, revision, and hash/integrity evidence.
- Three translation permissions assigned to Organization Admin and Knowledge
  Manager, with read-only visibility for IT Manager and root bypass.
- Tests-as-code for validation, placeholders, active content, RBAC, tenant
  isolation, optimistic evidence, four-eyes publication, stale fallback,
  retirement, notification rendering, global-source immutability, and audit
  minimization.

At the time of this original stage the application chrome was restricted to
Russian. The 2026-07-30 trilingual wave supersedes that limitation for the
shared shell, login, search, module headings, and Major Incident interface;
see `UX-004-TRILINGUAL-UI-WAVE-1.md`. Full specialist-module body coverage is
still not claimed.

## Static evidence

- Full backend Ruff: pass.
- Full Python compile: pass, excluding inaccessible historical pytest temp
  directories reported as warnings.
- TypeScript `tsc --noEmit`: pass.
- Accessibility baseline: pass over 71 source files, 16 named/focus-managed
  dialogs, two images with alternatives, 36 alert/status regions, and eight
  maintained contrast pairs.
- OpenAPI: 587 paths; five localized-content paths and six operations.
- Alembic: one head, `20260729_0064`.
- Local and production Compose configurations: pass.
- `git diff --check`: pass; CRLF notices are informational.

## Deferred runtime acceptance

No PostgreSQL migration execution, backend pytest result, production Vite
bundle, browser acceptance, concurrency proof, assistive-technology result, or
release-readiness claim is made while the local runtime gate is unavailable.

When runtime access returns:

1. apply migrations through `0064` on PostgreSQL;
2. run focused translation/branding tests and the full backend suite;
3. prove concurrent publication cannot create two published variants;
4. verify knowledge and notification resolution across two tenants and three
   locales with source edits and corruption simulation;
5. exercise author, independent reviewer, requester, tenant admin, and SaaS
   Root in the browser;
6. inspect narrow viewport, zoom, forced colors, keyboard, and screen-reader
   operation;
7. build the production frontend and run readiness/smoke gates.
