# UX-001 — Unified Configuration Center

**Status:** implementation complete; runtime release gate pending  
**Date:** 2026-07-29  
**Migration:** `20260729_0059_unified_configuration_center.py`

## Delivered

- Unified global/tenant configuration dashboard with domain readiness,
  actionable issues, ownership, health percentage, and links to specialized
  consoles.
- Typed settings for security, sessions, audit retention, SLA warning,
  knowledge publication, Copilot, email notifications, and local email mode.
- Server bounds, normalization, optimistic revision, initial baseline capture,
  SHA-256 evidence, history, rollback-as-new-revision, RBAC, tenant isolation,
  and audit.
- Legacy catalog setting mutation blocked; raw settings are a collapsed
  read-only diagnostic view.
- Root scope selector and explicit tenant/global separation.
- Global AI provider mutation and connection test restricted to SaaS Root.
- OpenAI/Gemini credential values encrypted with purpose-bound AES-GCM;
  ciphertext and plaintext are never returned to the browser.
- Production provider loader refuses legacy plaintext credentials.
- AI connection tests now create audit evidence.
- Responsive task-oriented admin UI with domain cards, guided controls,
  revision history, and rollback.
- Tests-as-code for typed validation, readiness without secret leakage,
  revision conflict, baseline/history/rollback, root scope validation, global
  provider separation, and encrypted-at-rest key evidence.

## Static acceptance

- Full application/test/migration Ruff and Python compile checks passed.
- TypeScript `tsc --noEmit` passed.
- OpenAPI generated with 573 total paths and four Configuration Center
  operations.
- Alembic reports one head: `20260729_0059`.
- Local and production Compose configurations parse successfully.
- `git diff --check` passed; Windows line-ending notices are informational.

Privileged runtime regression, migration execution, native production frontend
build, multi-user runtime acceptance, and browser acceptance remain in the
accumulated deferred runtime gate. No runtime completion claim is made.

## Next stage

`UX-002-GLOBAL-SEARCH-PRODUCTIVITY`.
