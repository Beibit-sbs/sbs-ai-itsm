# AI-002 — Permission-aware RAG

**Status:** implementation complete; runtime release gate pending  
**Date:** 2026-07-29  
**Migration:** `20260729_0055_permission_aware_rag.py`

## Outcome

AI Copilot now has a tenant-isolated retrieval and grounded-answer layer for
Knowledge, resolved Incidents, Problems/KEDB, completed Changes, and approved
Assets/CI. The retrieval index never grants access: every candidate is
re-authorized and freshness-checked against its live source immediately before
answer generation.

## Delivered controls

- Tenant ownership added to Knowledge articles and AI suggestions.
- Tenant/global source identities and deletion-aware retrieval documents.
- Deterministic chunking, SHA-256 evidence, sparse multilingual feature-hash
  embeddings, lexical/semantic/title/freshness ranking, and bounded context.
- Source lifecycle eligibility and deletion propagation.
- Live tenant, permission, knowledge-visibility, requester-ticket, and
  IT-agent-ticket ACL checks.
- Stale-source refusal when the live record is newer than the index.
- Query and source prompt-injection detection.
- OpenAI/Gemini strict JSON grounded answers with supplied citation-ID
  allowlists; invalid, unavailable, or ungrounded responses fall back to a
  local extractive answer.
- Unique-segment PII redaction before external provider calls.
- Redacted/hash-only query evidence: raw questions and answers are not stored.
- Four dedicated permissions and role defaults.
- Dashboard, ingestion history, retrieval search, grounded ask, and redacted
  query-log APIs.
- AI Copilot workspace with source selection, citations, filtering counters,
  index synchronization, and health metrics.
- Operations runbook and tests-as-code for isolation, object ACL, freshness,
  deletion, injection resistance, privacy, and provider citation validation.

## Static acceptance completed

- Full backend/test/migration Ruff passed.
- Full Python compileall passed.
- TypeScript `tsc --noEmit` passed.
- OpenAPI generated with 547 total paths and seven AI RAG operations.
- Alembic reports one head: `20260729_0055`.
- Development and production Compose configurations parse successfully.
- `git diff --check` passed; only expected Windows line-ending notices remain.

## Deferred runtime gate

Runtime execution is not claimed. The local environment cannot currently run
the privileged pytest/Docker acceptance gate, and the native frontend
production bundler is blocked by host `spawn EPERM`. When runtime access is
restored, execute:

1. migration upgrade through `0055`;
2. focused AI retrieval tests and full backend regression;
3. production frontend build;
4. multi-role, multi-tenant API/browser acceptance;
5. provider failure/fallback and no-raw-content database inspection;
6. readiness and production Compose smoke.

## Next stage

`AI-003-EVALUATION-PROMPT-GOVERNANCE`.
