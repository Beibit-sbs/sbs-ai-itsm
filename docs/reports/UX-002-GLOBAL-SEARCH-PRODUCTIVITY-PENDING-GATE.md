# UX-002 — Global Search and Productivity

**Status:** implementation complete; runtime release gate pending  
**Date:** 2026-07-29  
**Migrations:** `0060` saved views, `0061` guarded bulk plans, `0062`
PostgreSQL search indexes

## Delivered

- Permission-aware global search for incidents, service requests, knowledge,
  assets/CI, changes, problems, and users.
- Tenant, requester, agent-assignee, knowledge visibility, and domain RBAC
  filters applied before result construction.
- Minimal result contract without raw descriptions, article content,
  requester identities, or credentials.
- Literal wildcard escaping, fixed entity allowlist, query/type/result caps,
  deterministic ranking, query duration, and hash-only audit evidence.
- Composite PostgreSQL `pg_trgm` GIN indexes for all seven search documents
  with a portable SQLite fallback.
- Personal and role-shared saved views with owner/tenant scope, 50-view cap,
  role validation, optimistic revision, query hash, audit, and owner-only
  mutation.
- Global responsive command palette with `Ctrl/Cmd+K`, `/`, Escape, arrows,
  Enter, focus restoration, type filters, saved views, and direct links.
- Direct deep-link opening added for problems, assets, and admin users,
  complementing existing incident, request, knowledge, and change links.
- Browser-side sequential ticket bulk mutations removed.
- Server-owned incident bulk plans limited to 50 targets and one tenant, with
  ten-minute expiry, explicit `APPLY N` confirmation, operation/target hashes,
  target fingerprints, assignee/transition validation, plan ownership,
  optimistic revision, row locks, atomic drift refusal, audit, notifications,
  automation triggers, and idempotent replay.
- Tests-as-code for wildcard/type validation, requester/user isolation,
  cross-tenant search, raw-query audit exclusion, saved-view ownership/share/
  revision, bulk confirmation, execution, replay, atomic drift refusal,
  requester denial, selection cap, and mixed-tenant denial.
- Four permissions added: `search.use`, `search.views.manage`,
  `search.views.share`, and `tickets.bulk.execute`.

## Static acceptance

- Full application Ruff and Python compile checks passed.
- New test modules pass Ruff/compile checks.
- TypeScript `tsc --noEmit` passed.
- OpenAPI generated with 578 total paths: five global search/saved-view
  operations and two guarded bulk operations.
- Alembic reports one head: `20260729_0062`.
- Local and production Compose configurations parse successfully.
- `git diff --check` passed; Windows line-ending notices are informational.

Privileged runtime regression, migration execution against PostgreSQL,
PostgreSQL index-plan evidence, native production frontend build, multi-role
runtime acceptance, and browser accessibility acceptance remain in the
accumulated deferred runtime gate. No runtime completion claim is made.

## Next stage

`UX-003-ACCESSIBILITY-RESPONSIVE-PORTAL`.
