# AI-005 — Guarded AI actions

**Status:** implementation complete; runtime release gate pending  
**Date:** 2026-07-29  
**Migration:** `20260729_0058_guarded_ai_actions.py`

## Delivered

- Tenant-scoped guarded-action policy with fail-closed initial state, bounded
  TTL, optimistic revision, server allowlist, and independent HIGH-risk
  approval.
- Immutable-style proposal evidence with idempotency, canonical parameter
  SHA-256, hash-only source query, bounded citation metadata, expiry, actor
  decisions, and target fingerprint.
- Four fixed action schemas and handlers: ticket update, ticket
  classification, knowledge draft, and inactive approval-required runbook
  draft.
- Defense against arbitrary tools/fields, prompt injection, credential-like
  payloads, stale targets, policy drift, permission drift, replay, and
  cross-tenant access.
- Execution evidence with one execution per proposal, before/after state
  hashes, domain history, and drift-aware rollback.
- Six dedicated RBAC permissions and underlying domain permission rechecks.
- Seven API operations for metadata, policy, proposal list/create,
  approve/reject, execute, and rollback.
- Copilot control plane for policy, proposal creation, queue review,
  execution, evidence inspection, and rollback.
- Tests-as-code for validation, evidence minimization, target drift,
  idempotency, four-eyes approval, execution, and rollback.

## Static acceptance

- Full application/test/migration Ruff and Python compile checks passed.
- TypeScript `tsc --noEmit` passed with the action control plane.
- OpenAPI generated with 569 total paths and seven guarded-action operations.
- Alembic reports one head: `20260729_0058`.
- Local and production Compose configurations parse successfully.
- `git diff --check` passed; Windows line-ending notices are informational.

The privileged runtime regression, migration execution, native production
frontend build, multi-user runtime acceptance, and browser acceptance remain
in the accumulated deferred runtime gate. No runtime completion claim is made.

## Next stage

`UX-001-UNIFIED-CONFIGURATION-CENTER`.
