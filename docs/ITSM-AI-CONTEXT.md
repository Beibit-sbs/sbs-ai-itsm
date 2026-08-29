# SBS AI ITSM — Durable AI Context

**Use this file first in future development sessions.** It is a compact memory, not a substitute for code/runtime verification. Evidence updated: 2026-08-30.

## What this project is

SBS AI ITSM is a multi-tenant, role-based university IT service management platform. It contains a React portal/admin workspace and a FastAPI modular monolith backed by PostgreSQL and Redis, plus workers, scheduler, monitoring, audit/security, integrations and governed AI capabilities.

Current verdict: strong production-capable foundation with a locally verified Gate 0 candidate, **not yet a proven production release**. Gate 1+ and server cutover remain mandatory. See `docs/ITSM-SYSTEM-MASTER.md` for evidence.

## Repository identity

- Root: `C:\projects\sbs-ai-itsm-foundation-001`
- Branch: `main`
- Baseline HEAD: `0b04ada23744349f565b44d60d52182da7f6da38`
- Origin: `https://github.com/Beibit-sbs/sbs-ai-itsm.git`
- Important: the classified release candidate spans 705 files (157 tracked dirty + 548 untracked, 0 staged, 0 deletions); coherent commit is pending. Do not reset, clean, delete or overwrite user changes.
- Runtime URL: `http://127.0.0.1:18080`
- Compose project: `sbs-itsm-rehearsal`, env file `.env.rehearsal.local`, compose `docker-compose.prod.yml`.

## Architecture

- Frontend: React 19, TypeScript 6, Vite 8, React Router 7, TanStack Query 5, Tailwind 4; served by unprivileged NGINX.
- Backend: Python 3.12+, FastAPI 0.139, SQLAlchemy 2, Alembic, Pydantic Settings.
- DB: PostgreSQL 17.10; 216 tables; 81 migration files; current/head `20260829_0081`.
- Queue/realtime: Redis 8; transactional job outbox, retry/DLQ, event consumers, WebSocket transport.
- Runtime: 3 backend replicas, 1 worker, 1 leader-elected scheduler, frontend, PostgreSQL, Redis, Prometheus, Alertmanager, Grafana.
- Files: email attachments on Docker volume `/var/lib/sbs-ai-itsm/email-attachments`; object storage is a target gap.
- Edge: NGINX rate/connection limits and security headers; server deployment still needs external TLS.

## Key directories

| Path | Purpose |
|---|---|
| `backend/app/api/v1/routes/` | 51 API route modules |
| `backend/app/models/` | SQLAlchemy entities |
| `backend/app/services/` | domain logic, RBAC, AI, jobs, integrations |
| `backend/app/workers/` | jobs worker and leader scheduler |
| `backend/migrations/versions/` | Alembic migrations |
| `backend/tests/` | 88 files / 891 collected tests |
| `frontend/src/pages/` | 33 page components |
| `frontend/src/components/` | shared panels/shell/dialogs |
| `frontend/src/api/client.ts` | frontend API client |
| `frontend/src/auth/accessControl.ts` | UI route permissions |
| `frontend/src/i18n/catalog.ts` | RU/KK/EN key catalog |
| `monitoring/` | Prometheus/Alertmanager/Grafana/SLO config |
| `.github/workflows/` | CI, immutable release images, staging DAST |
| `scripts/` | preflight, smoke, acceptance, backup/restore, release tooling |
| `docs/` | master truth, roadmap, map, backlog, runbooks/reports |

## Current quantitative truth

- API: 621 OpenAPI paths / 738 operations.
- Route auth contract: 746 entries / 739 protected / 7 governed public.
- RBAC: 7 logical roles / 266 permission codes.
- UI: login + 31 protected routes + wildcard fallback.
- DB: 216 tables, 718 indexes, 654 foreign keys, 2 459 checks, 180 tenant-id tables, 0 PostgreSQL RLS policies.
- Rehearsal data: 2 tenants, 7 users, 2 459 tickets, 22 797 audit events, 21 notifications, 9 job runs.
- Empty operational domains: assets, catalog items, requests, problems, changes, knowledge, SLA policies/instances, automation rules, workflows, AI corpus/evals/usage/actions, integration credentials/systems, event sources.
- Audit chain verification: valid, 22 797 events, 3 chains, no failures.
- Readiness endpoint: postgres/redis/migrations/runtime/websocket all ready.
- Gate 0 regression: 891 collected / 875 passed / 16 justified legacy skips / 0 failed.
- Local release gate: 28/28 PASS in 19.3 s; evidence SHA-256 `d8d37d0219b08e14b3fbee27a0e408629dc2dd15f0da3473b3d12c7d06b5f4b5`; clean PostgreSQL 17 migration: 81 revisions, one base/head `20260829_0081`, 216 tables.
- I18N: RU/KK/EN static source/UI coverage 4 562/4 562, unresolved 0; seven critical routes pass in every locale.

## Roles

| Role | Distinct permissions | Purpose |
|---|---:|---|
| `saas_root` | 266 | global platform owner |
| `organization_admin` | 249 | tenant administrator |
| `it_manager` | 208 | ITSM manager/approver/executive |
| `it_agent` | 84 | Service Desk/operator |
| `security_officer` | 84 | security/audit/data/integration oversight |
| `knowledge_manager` | 31 | knowledge governance/RAG/search |
| `requester` | 21 | self-service and own tickets/requests |

Never infer access from a role name alone. Enforce permission codes, tenant scope and object-level visibility in backend. UI hiding is not security.

## Main modules

- identity/auth/MFA/sessions/OIDC/SCIM;
- tenant/admin/users/roles/settings/security;
- Service Desk tickets/comments/history/assignment/on-behalf/participants/bulk/duplicates/merge/split;
- Major Incident;
- Service Catalog + dynamic forms + Request Fulfillment;
- Problem/KEDB, Change/CAB, Release;
- Assets/CMDB/discovery/quality/reconciliation/impact and SAM;
- SLA/OLA calendars/targets/instances/escalation;
- Knowledge and localized content;
- AI provider/RAG/prompt-eval governance/runtime controls/guarded actions;
- automation rules/workflow engine/runbooks;
- notifications/email/Teams/integrations/webhooks;
- monitoring/events/search/analytics/reports;
- tamper-evident audit and data governance;
- configuration center/packages/custom fields/tenant experience.

## Canonical ticket lifecycle — critical contract

Canonical states and matrix:

- `NEW → TRIAGE | ASSIGNED | CANCELLED`
- `TRIAGE → ASSIGNED | WAITING_USER | CANCELLED`
- `ASSIGNED → IN_PROGRESS | WAITING_USER | WAITING_VENDOR`
- `IN_PROGRESS → RESOLVED | WAITING_USER | WAITING_VENDOR`
- `WAITING_USER → IN_PROGRESS | CANCELLED`
- `WAITING_VENDOR → IN_PROGRESS`
- `RESOLVED → CLOSED | REOPENED`
- `CLOSED → REOPENED`
- `REOPENED → TRIAGE | ASSIGNED`
- `CANCELLED → ∅`

Authoritative implementation: `backend/app/services/ticket_lifecycle.py`. API patch/transition/assign/bulk, workflow, automation and event operations must delegate to it. The service owns row locking/version conflict, authorization, timestamps, history, audit, SLA sync, notifications and deterministic idempotency. `OPEN/PENDING/WAITING` are invalid ticket statuses; the only historical alias is `TRIAGED → TRIAGE`.

## Other important workflows

- Catalog item: DRAFT → IN_REVIEW → PUBLISHED → RETIRED.
- Request/fulfillment: submit/approve/reject → task fulfillment → completed/cancelled; task OPEN/IN_PROGRESS/WAITING/COMPLETED/FAILED/CANCELLED.
- Problem: NEW → INVESTIGATING → ROOT_CAUSE_IDENTIFIED → KNOWN_ERROR/RESOLVED → CLOSED; reopen/retire/cancel.
- Major incident: DECLARED → MITIGATING ↔ MONITORING → RESOLVED → CLOSED; approved PIR required.
- Change: draft/assessment/approval/schedule/implement/validate/complete, or fail/rollback/cancel; risk/CAB/window/task/PIR controls.
- Workflow: draft/review/publish; QUEUED/RUNNING/WAITING/RETRY/COMPENSATING → terminal with hash-chained events.
- AI action: propose → approve/reject → execute → rollback; four-eyes and drift evidence.

## AI state

Already implemented:

- provider abstraction for `mock`, OpenAI and Gemini;
- admin provider configuration/test without exposing stored keys;
- PII/data policy and external-call gating;
- permission-aware RAG and prompt-injection patterns;
- prompt versions, datasets/evals, canary rollout/rollback;
- budgets, usage ledger, provider circuits;
- guarded action propose/approve/execute/rollback.

Runtime truth:

- provider=`mock`;
- OpenAI configured=false;
- Gemini configured=false;
- operational AI tables are empty.

Do not describe production AI as active. Before activation require data-processing approval, curated corpus, RU/KK/EN golden evals, permission leakage tests, budget/circuit/fallback evidence and human-governed rollout.

## Localization state

Three locales are enabled: `ru-RU`, `kk-KZ`, `en-US`. Strict `frontend/scripts/i18n-audit.mjs` is wired to `check:i18n` and CI. Current static truth: 1 020 messages, 183 explicit aliases, 2 693 direct source messages, 1 358 English source messages, 506 literal key usages, 335 literal translation usages, 93 file-local producers and 5 171 checked JSX expressions. All 4 562 visible candidates resolve; Cyrillic/mixed is 3 145 with 0 unresolved, Latin is 1 417 with 0 unresolved, and critical/other findings are 0/0. The 194 allowlisted occurrences are classified non-UI, proper nouns or technical IDs.

Confirmed manual browser evidence on the final production build: seven critical routes pass in RU/KK/EN with no alert, and every EN route contains zero Cyrillic UI strings. `SD-3409` passes create/native required validation; the NEW state exposes only backend-authoritative `TRIAGE`, `ASSIGNED`, `CANCELLED`; `NEW → CANCELLED` succeeds and the terminal state has no status dropdown. Final history is localized in RU/EN/KK. The renderer covers all 27 current history event types and an AST validator checks eight producer files. User/external values remain verbatim, so a user-authored RU QA comment correctly remains RU in EN/KK; no system mixed-language UI was found. This does not replace Gate 1 multi-role browser acceptance or localization of future business data.

## Test evidence

- Full backend suite: **891 collected / 875 passed / 16 skipped / 0 failed** across 88 files.
- The 16 skips are two explicitly marked legacy Stage 026/027 contract suites (`7 + 9`); review is documented.
- Complete 10×10 ticket matrix, invalid/security/concurrency/idempotency and runtime race checks pass.
- Local release gate: **28/28 PASS**; route auth contract and clean PostgreSQL 17 migration pass.
- Static frontend audits pass: i18n 4 562/4 562; accessibility 87 files/16 dialogs/0 issues; 681 buttons/39 links; `tsc -b` pass.
- Production Docker smoke passes across frontend, auth, readiness, metrics and monitoring; 3 backend replicas are healthy.
- Manual browser evidence covers seven critical routes × three locales plus the complete `SD-3409` acceptance journey; it remains representative only, and Gate 1 still owns the full role journey matrix.
- No active frontend unit/component/E2E package script.

## Runtime provider/config truth

- `APP_ENV=production`, `DEMO_MODE=false`.
- Redis job executor and realtime transport active.
- Final frontend image: `sha256:4f80d483ec1c01a8e86d65e995991c8b8853c20aa9f35b0097e2d05e3f1d2215`, 152 modules. Main chunk: 1 050.49 kB / 289.18 kB gzip; Tickets chunk: 97.38 kB / 20.97 kB gzip.
- Runtime smoke PASS; all containers healthy/running; 985 inspected log lines contain 0 errors and 0 HTTP 5xx.
- Outbox: 12/12 published with zero pending/failures/locked/stale; 138 deliveries are DELIVERED; notification and automation consumers contain 69 records each and zero pending/failed/retryable/exhausted/unseen/lag.
- OIDC disabled.
- AI mock; OpenAI/Gemini keys absent.
- SMTP/Slack/PagerDuty/custom alert receivers absent.
- Integration systems/credentials absent.
- Legacy mock integration actions are blocked outside demo mode, but legacy code/UI terminology remains.

## Do not break

1. Do not reset/clean/delete the dirty worktree or overwrite unrelated changes.
2. Do not change architecture merely to reduce file size; modular monolith is the current target until measured need.
3. Do not bypass backend RBAC/tenant/object-level filters.
4. Do not expose passwords, API keys, OAuth secrets, refresh tokens or secret file content.
5. Do not weaken the 7-route public allowlist or 739 protected route contract.
6. Do not mutate ticket lifecycle outside one canonical transition service.
7. Do not edit published/versioned governance artifacts in place; create revisions and preserve audit evidence.
8. Do not turn demo/mock/simulation output into production success evidence.
9. Do not claim production-ready without current tests, role UAT, configured providers, representative data and server evidence.
10. Do not perform destructive migrations/restores/cleanup without exact target verification and explicit authority.

## What is complete enough to preserve

- core FastAPI/React/PostgreSQL/Redis architecture;
- route authentication contract and broad RBAC model;
- migration chain to `20260829_0081`;
- healthy 3-replica production-like compose;
- deep Service Desk foundation including on-behalf/participants/duplicates/merge/split;
- broad ITSM domain schemas/APIs/UIs;
- tamper-evident audit chain;
- workflow/AI/integration governance foundations;
- observability, CI/release security and backup/restore tooling.

“Preserve” does not mean every module is accepted; it means evolve through compatible, tested changes.

## Current blockers

1. Candidate is not yet a coherent commit and CI/artifacts are not bound to a final SHA.
2. No complete multi-role read/write browser acceptance.
3. Empty representative business modules/data.
4. External identity/AI/comms/integrations unconfigured.
5. No server TLS/object storage/off-site DR/load/pentest evidence.
6. No active frontend unit/component/E2E runner; main production bundle needs code splitting.
7. Sixteen legacy Stage 026/027 contract tests remain explicitly skipped pending migration/removal/replacement.

## NEXT DEVELOPMENT GATE

Gate 0 technical implementation and local validation are complete. Gate 0 remains `BLOCKED` solely by `REL-001`: the 705-path candidate has no approved coherent commit/release SHA. Formal closure requires explicit user approval, a local commit without push, and evidence/artifact binding to that SHA. Gate 1 remains `NO` until then.

After that, execute **GATE 1 — Multi-Role Representative Acceptance** from `docs/ITSM-ROADMAP.md`:

1. create a versioned representative dataset and users for all seven roles;
2. verify role navigation, positive/negative writes, object scope and tenant isolation;
3. capture browser/API/audit evidence for each critical journey;
4. keep external providers and server cutover disabled until their later gates pass.

## Required update discipline

After each Gate, update all four truth files together:

- `docs/ITSM-SYSTEM-MASTER.md`
- `docs/ITSM-SYSTEM-MAP.md`
- `docs/ITSM-AI-CONTEXT.md`
- `docs/ITSM-BACKLOG.md`

Record exact commit, migrations, test totals, runtime config, verified roles/screens and unresolved gaps. Never silently convert `IMPLEMENTED` to `VERIFIED`.
