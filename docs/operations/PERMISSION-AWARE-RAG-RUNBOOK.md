# Permission-aware RAG operations runbook

## Purpose

This runbook covers the tenant-isolated retrieval and grounded-answer subsystem
used by AI Copilot. The retrieval index is a performance structure, not an
authorization source. Every result is checked against the live source,
tenant scope, RBAC permission, object-level access, lifecycle eligibility, and
freshness immediately before it can be included in an answer.

## Supported sources

| Source | Indexed eligibility | Required read permission |
| --- | --- | --- |
| Knowledge | Published tenant or global article | `knowledge.read` |
| Incident | Resolved or closed ticket | `tickets.read` plus ticket ACL |
| Problem / KEDB | Published known error or resolved/closed problem | `problems.read` |
| Change | Completed, rolled back, or failed change | `changes.read` |
| Asset / CI | Active and verified/certified asset | `assets.read` |

Restricted knowledge additionally requires `knowledge.update` or
`knowledge.publish`. Requesters can retrieve only their own tickets. IT agents
can retrieve assigned or unassigned queue tickets, matching the service-desk
access rule.

## Permissions

- `ai.rag.use`: search and ask grounded questions.
- `ai.rag.read`: view retrieval health and ingestion history.
- `ai.rag.manage`: synchronize the tenant index.
- `ai.rag.audit`: view redacted query and citation evidence logs.

SaaS Root must always supply an explicit tenant ID. A root request never
implicitly merges tenant contexts.

## Initial setup

1. Apply Alembic migration `20260729_0055`.
2. Start the API and sign in as Organization Admin or IT Manager.
3. Open **AI Copilot**.
4. Select **Обновить индекс**.
5. Confirm that the health strip shows active documents and a completed
   ingestion.
6. Ask a known question and verify that every factual answer contains one or
   more clickable citations.

The index uses deterministic local sparse embeddings and does not require an
external embedding provider. OpenAI or Gemini is used only for final answer
composition when configured; mock mode produces an extractive grounded answer.

## Normal operation

Run synchronization after bulk imports or major lifecycle changes. Retrieval
also fails closed between runs:

- a deleted or ineligible source is marked deleted and its chunks are removed;
- a live source newer than the index is excluded as stale;
- an unreadable source is excluded after the live ACL check;
- source chunks containing prompt-injection patterns are excluded;
- a suspicious user query is rejected before provider invocation.

No raw query or raw answer is persisted. Query logs contain a redacted preview,
query/answer hashes, source hashes, source timestamps, provider/model metadata,
filter counters, latency, and the grounded/no-result decision.

## Incident triage

### No citations or “insufficient data”

1. Confirm the user has both `ai.rag.use` and the source-specific read
   permission.
2. Confirm the source is in an eligible lifecycle state.
3. Check **Последняя индексация** and run synchronization if required.
4. Review stale, ACL-denied, and unsafe-source counters.
5. Verify that the question shares meaningful terms with the source.

Do not reduce `minimum_score` below zero or bypass live authorization checks.

### Stale source count grows

Run synchronization for the affected tenant. If it continues:

1. inspect source `updated_at`;
2. confirm application and database clocks are synchronized;
3. check ingestion-run errors;
4. retain the fail-closed state until source freshness is restored.

### Prompt-injection event

1. Review the redacted query evidence with `ai.rag.audit`.
2. Identify whether the attempt came from the user query or indexed source.
3. Quarantine or correct an unsafe source through its owning module.
4. Synchronize the index.
5. Preserve audit evidence; never copy untrusted instructions into a system
   prompt.

### Provider failure

OpenAI/Gemini transport, HTTP, response-shape, citation, or groundedness failure
automatically falls back to the local extractive provider. Check provider
health under Administration, but do not disable citation validation to restore
service.

## Privacy and retention

PII is redacted with unique per-segment tokens before external provider calls
and restored only in the authorized response. Configure
`AI_RAG_QUERY_LOG_RETENTION_DAYS` according to the organization policy. A
scheduled retention job is part of the later AI privacy/control stage; until
then, operators must include `ai_retrieval_query_logs` in the documented
database retention procedure.

## Release gate

Before production release, prove:

- tenant A cannot retrieve tenant B records;
- requester and IT-agent object ACLs are enforced;
- deletion and lifecycle changes propagate;
- a newer live source is excluded until reindex;
- injected queries and sources fail closed;
- citation IDs cannot be invented by a provider;
- raw query/answer bodies are absent from database and audit records;
- mock, OpenAI, and Gemini provider failures preserve a usable safe fallback.

