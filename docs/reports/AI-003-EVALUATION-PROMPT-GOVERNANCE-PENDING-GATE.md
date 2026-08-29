# AI-003 — Evaluation and prompt governance

**Status:** implementation complete; runtime release gate pending  
**Date:** 2026-07-29  
**Migration:** `20260729_0056_ai_prompt_governance.py`

## Delivered

- Tenant-scoped prompt policies for ticket classification and grounded answers.
- Immutable prompt/model/parameter versions with canonical SHA-256 identity.
- Credential screening, parameter allowlist, and bounded configuration.
- Tenant-scoped evaluation datasets and weighted, hashed cases.
- Provider-backed evaluation with quality, groundedness, safety, latency,
  estimated cost, and baseline regression metrics.
- Hash-only model output evidence and deterministic run evidence hashes.
- Configurable bounded release thresholds and fail-closed regression gate.
- Passed-evidence binding, prompt integrity recheck, independent reviewer, and
  separate deployment actor enforcement.
- Deterministic user/ticket canary selection, activation, and rollback.
- Runtime selection of a valid active/canary prompt for classify and RAG calls,
  with built-in safe prompt fallback on integrity/config mismatch.
- Six RBAC permissions, audit events, 14 API operations on ten paths, and a
  full AI governance workspace in Copilot.
- Tests-as-code and operator runbook.

## Static acceptance

- Full Ruff passed for application, tests, and migrations.
- Full Python compileall passed.
- TypeScript `tsc --noEmit` passed.
- OpenAPI generated with 557 total paths and 14 AI-governance operations.
- Alembic reports a single head: `20260729_0056`.

Runtime pytest, migration execution, native production frontend build, and
multi-user browser acceptance remain in the accumulated deferred release gate;
no runtime completion claim is made.

## Next stage

`AI-004-PRIVACY-COST-RESIDENCY-CONTROLS`.

