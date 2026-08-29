# AI-004 — Privacy, cost, and residency controls

**Status:** implementation complete; runtime release gate pending  
**Date:** 2026-07-29  
**Migration:** `20260729_0057_ai_runtime_controls.py`

## Delivered

- Tenant data policies with explicit external-processing opt-in, provider
  allowlist, provider-region mapping, data-class ceiling, PII redaction policy,
  reversible-token policy, retention, revision, RBAC, and audit.
- Conservative runtime classification for PII and operational source types.
- Fail-closed external preflight for policy, provider, region, governed cost
  rates, classification, PII method, hard budget, and circuit state.
- Monthly/daily request limits and monthly estimated-cost hard limit with
  PostgreSQL serialization.
- Hash-only usage ledger with token/cost estimate, latency, provider/model,
  region, outcome, fallback reason, prompt version, and no raw payload fields.
- Tenant/provider circuit breaker with failure threshold, cooldown, serialized
  half-open probe, automatic recovery, and audited operator reset.
- Safe local fallback integrated into ticket classification and grounded RAG.
- Confirmed tenant-scoped retention purge with tamper-evident audit counts.
- Six API operations, three permissions, tests-as-code, full Copilot
  Privacy/FinOps UI, and operations runbook.

## Static acceptance

- Full application/test/migration Ruff passed.
- Full Python compileall passed.
- TypeScript `tsc --noEmit` passed.
- OpenAPI generated with 563 total paths and six runtime-control operations.
- Alembic reports one head: `20260729_0057`.

The privileged runtime regression, migration execution, native production
frontend build, and multi-user/browser/provider-failure acceptance remain in
the accumulated deferred runtime gate. No runtime completion claim is made.

## Next stage

`AI-005-GUARDED-AI-ACTIONS`.

