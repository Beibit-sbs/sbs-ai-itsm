# SBS AI ITSM — Compact System Map

**Baseline:** 2026-08-30, current HEAD `0b04ada23744349f565b44d60d52182da7f6da38`, classified 705-file candidate (`157` tracked + `548` untracked, `0` staged/deletions); coherent commit pending  
**Назначение:** быстрый контекст для разработчика/AI; подробности и readiness — в [ITSM-SYSTEM-MASTER.md](ITSM-SYSTEM-MASTER.md).

## Runtime topology

| Component | Count | Network/port | Depends on | Status |
|---|---:|---|---|---|
| frontend NGINX | 1 | host `127.0.0.1:18080` → 8080 | backend | healthy |
| FastAPI backend | 3 | internal 8000 | PostgreSQL, Redis, migrate | healthy |
| migrate | one-shot | internal | PostgreSQL | completed at `20260829_0081` |
| PostgreSQL 17.10 | 1 | internal 5432 | volume | healthy |
| Redis 8 | 1 | internal 6379 | volume | healthy |
| jobs worker | 1 | internal | PostgreSQL, Redis | running; periodic cycles disabled |
| scheduler | 1 | internal | PostgreSQL, Redis | running; Redis leader lease |
| Prometheus 3.13.1 | 1 | internal 9090 | backend | running |
| Alertmanager 0.33.1 | 1 | host 19093 | Prometheus | running; receivers not configured |
| Grafana 13.1.0 | 1 | host 13000 | Prometheus | running |

## Module/submodule map

Status vocabulary: `ACTIVE` = runtime data/behavior observed; `IMPLEMENTED` = code/schema/API/UI exist; `EMPTY` = runtime tables have no representative records; `UNCONFIGURED` = provider/owner/data missing; `PARTIAL` = known functional gap; `LEGACY` = compatibility/demo boundary.

| Module | Submodule/function | Primary roles | Main entities | API tag/path family | Page | Status |
|---|---|---|---|---|---|---|
| Identity | local login/password | all users, admin | users, auth_sessions | `auth` (17 ops) | `/login`, `/account` | ACTIVE |
| Identity | MFA/sessions | all users, admin/security | user_mfa, challenges, auth_sessions | `auth`, `security` | `/account`, `/admin` | IMPLEMENTED |
| Identity | OIDC | admin/root | external_identities | `auth`, `admin` | `/login`, `/admin` | UNCONFIGURED/OFF |
| Identity | SCIM/provisioning | admin/root | provisioning connectors/events/groups/identities | `scim` 17, `identity-provisioning` 17 | `/identity-provisioning` | IMPLEMENTED/EMPTY |
| Tenant | organizations/profile | root/org admin | tenants | `tenants` 4, `admin` | `/admin` | ACTIVE: 2 tenants |
| RBAC | roles/permissions | root/org admin | roles, permissions, role_permissions, user_roles | `admin` | `/admin` | ACTIVE: 7 logical roles, 266 permissions |
| Service Desk | ticket CRUD/queues | requester, agent, manager, admin | tickets + lookup tables | `tickets` 24 | `/tickets` | ACTIVE |
| Service Desk | lifecycle/assignment | requester limited; agent/manager/admin | tickets, ticket_history | `tickets` | `/tickets` | ACTIVE/VERIFIED; one canonical lifecycle service |
| Service Desk | comments/knowledge links | requester/agent/manager | comments, knowledge links | `tickets` | `/tickets` | ACTIVE |
| Service Desk | on-behalf/participants | agent/manager/admin | ticket_participants, ticket_history | `tickets` | `/tickets` | IMPLEMENTED |
| Service Desk | bulk plans | agent/manager/admin | ticket_bulk_plans | `tickets` | `/tickets` | IMPLEMENTED |
| Service Desk | duplicate/merge/split | agent/manager/admin per permission | ticket_governance_actions | `tickets` | `/tickets` | IMPLEMENTED |
| Major Incident | command workflow | IT roles | major_incidents, updates, actions, participants | `major-incidents` 13 | `/major-incidents` | IMPLEMENTED/EMPTY |
| Major Incident | PIR/child tickets | IT manager/admin | major_incident_pirs, child_tickets | `major-incidents` | `/major-incidents` | IMPLEMENTED/EMPTY |
| Catalog | categories/services/offerings/items | catalog/admin; requester read | service_categories, catalog_services, offerings, items | `catalog` 26 | `/catalog` | IMPLEMENTED/EMPTY |
| Catalog | forms/publication/personalization | catalog/admin/requester | catalog_form_versions, history/preferences | `catalog` | `/catalog` | IMPLEMENTED/EMPTY |
| Requests | request/RITM/tasks | requester/fulfiller/approver | service_requests, requested_items, tasks | `requests` 13 | `/requests` | IMPLEMENTED/EMPTY |
| Requests | approvals/activity/SLA | approver/fulfiller/requester | request_approvals, activities | `requests` | `/requests` | IMPLEMENTED/EMPTY |
| Problem | lifecycle/RCA/KEDB | IT/knowledge roles | problems, problem_rcas, links, history | `problems` 7 | `/problems` | IMPLEMENTED/EMPTY |
| Problem | trends/corrective actions | manager/admin | trend_signals, corrective_actions | `problem-governance` 13 | `/problem-governance` | IMPLEMENTED/EMPTY |
| Change | RFC/approval | IT roles | change_requests, approvals, history | `changes` 7 | `/changes` | IMPLEMENTED/EMPTY |
| Change | CAB/windows/tasks/PIR/models | manager/admin | cab_*, windows, implementation_tasks, PIR, models | `change-governance` 23 | `/change-calendar` | IMPLEMENTED/EMPTY |
| Release | records/gates/packages | manager/admin | release_records, gates, packages | `releases` 23 | `/releases` | IMPLEMENTED/EMPTY |
| Release | dependencies/deployments/decisions | manager/admin | release_dependencies, deployments, decisions, timeline | `releases` | `/releases` | IMPLEMENTED/EMPTY |
| Asset | inventory/import/lifecycle | IT/asset roles | assets, types, assignments, history, imports | `assets` 19 | `/assets` | IMPLEMENTED/EMPTY |
| Asset | discovery | asset/admin | discovery connectors/runs/stale candidates | `asset-discovery` 11 | `/assets` | IMPLEMENTED/EMPTY |
| CMDB | CI classes/relationships | CMDB/IT roles | ci_classes, versions, relationship types/links | `cmdb` 42 aggregate | `/assets` | IMPLEMENTED/EMPTY |
| CMDB | reconciliation/quality/impact | CMDB/manager | reconciliation, quality, certification, impact | `cmdb` | `/assets` | IMPLEMENTED/EMPTY |
| SAM | products/licenses/installations | SAM roles | software_products, licenses, installations | `software-assets` 11 | `/software-assets` | IMPLEMENTED/EMPTY |
| SLA | policy/calendar/targets | manager/admin | sla_policies, calendars, exceptions, targets | `sla` 20 | `/sla` | IMPLEMENTED/EMPTY |
| SLA | ticket instance/pause/timeline | agents/managers/requester read | ticket_sla_instances, pauses, timeline/events | `sla` | `/sla`, `/tickets` | IMPLEMENTED/EMPTY |
| Knowledge | articles/categories/search | knowledge manager, agents, requester | articles, categories | `knowledge` 13 | `/knowledge` | IMPLEMENTED/EMPTY |
| Knowledge | feedback/usage/ticket/KEDB | all per visibility | feedback, usage, known_error_usage | `knowledge`, `tickets` | `/knowledge`, `/tickets` | IMPLEMENTED/EMPTY |
| Search | global/saved/shared views | all scoped users | saved_search_views | `global-search` 5 | global palette | ACTIVE |
| AI | provider/ticket analysis | AI users/admin | ai_suggestions, provider circuits | `ai` 7 | `/copilot`, `/tickets` | MOCK/EMPTY |
| AI | permission-aware RAG | AI/knowledge users | retrieval docs/chunks/runs/query logs | `ai-rag` 7 | `/copilot` | IMPLEMENTED/EMPTY |
| AI | prompts/evals/rollouts | AI governance | prompt policies/versions, eval datasets/cases/runs, rollouts | `ai-governance` 14 | `/copilot`, `/admin` panels | IMPLEMENTED/EMPTY |
| AI | budgets/circuits/runtime | AI/admin/security | usage budget/ledger, provider circuits | `ai-runtime-controls` 6 | `/copilot`, `/admin/system` | IMPLEMENTED/EMPTY |
| AI | guarded actions | approver/executor | action policies/proposals/executions | `ai-actions` 7 | `/copilot` | IMPLEMENTED/EMPTY |
| Automation | rules/runs/action logs | automation/IT roles | automation_rules/runs/action_logs | `automation` 31 | `/automation` | IMPLEMENTED/EMPTY + LEGACY demo actions |
| Workflow | definitions/versions/designer | workflow manager | definitions, versions | `workflow-engine` 27 | `/automation` | IMPLEMENTED/EMPTY |
| Workflow | executions/waits/approvals/events | worker/operator | executions, steps, approvals, events | `workflow-engine` | `/automation` | IMPLEMENTED/EMPTY; ticket transitions use canonical service |
| Runbooks | catalog/executions | automation/IT roles | runbooks, executions | `automation`/`system` | `/automation` | IMPLEMENTED/EMPTY |
| Notifications | inbox/preferences/templates | all/communications admin | notifications, preferences, templates | `notifications` 11 | `/notifications` | ACTIVE: 21; templates empty |
| Email | channels/Graph/conversations | email/admin | email_channels, conversations, inbound, deliveries | `email` 20 | `/email-operations` | IMPLEMENTED/UNCONFIGURED |
| Email | attachments/quarantine/download | email/security | email_attachments | `email` | `/email-operations` | IMPLEMENTED; Docker volume |
| Teams | connectors/deliveries/MI rooms | Teams/admin/IT | teams_connectors/deliveries/rooms | `teams` 13 | `/teams-collaboration` | IMPLEMENTED/UNCONFIGURED |
| Integrations | external systems/jobs/logs | integration roles | external_systems, credentials, mappings, event logs | `integrations` 38 | `/integrations` | LEGACY/EMPTY |
| Integration Platform | service accounts/tokens/request logs | integration/admin/security | service accounts, tokens, request logs | `integration-platform` 22 | `/integrations` | IMPLEMENTED/EMPTY |
| Integration Platform | signed outbound webhooks/replay | integration roles | subscriptions, deliveries | `integration-platform` | `/integrations` | IMPLEMENTED/EMPTY |
| Monitoring | system health/metrics | admin/security | operational metrics | `monitoring` + `system` | `/monitoring`, `/admin/system` | ACTIVE platform health |
| Event Ops | sources/receipts/normalize/correlate/suppress | monitoring/IT | event_sources, receipts, normalized events, policies/groups | `event-operations` 20 | `/events` | IMPLEMENTED/EMPTY |
| Analytics | operational/executive KPIs | manager/admin/security | live aggregates | `analytics` 10 | `/dashboard`, `/analytics` | IMPLEMENTED; data gaps |
| Reports | saved/snapshot/export | report roles | saved_reports, report_snapshots | `reports` 11 | `/analytics` | IMPLEMENTED/EMPTY; demo labels |
| Audit | tamper-evident log/verify | admin/security | audit_logs, audit_chain_heads | `admin`, `security` | `/admin` | ACTIVE/VERIFIED: 22 797 valid events |
| Data Governance | retention/legal hold/deletion/evidence | data/admin/security | retention, deletion, hold, evidence | `data-governance` 13 | `/admin/data-governance` | IMPLEMENTED |
| Configuration | settings/revisions/guidance | admin | system_settings, setting revisions | `configuration-center` 4 | `/admin`, `/admin/system` | ACTIVE/PARTIAL |
| Configuration | packages/deployments | config admin | packages, versions, deployments | `configuration-packages` 17 | `/admin/configuration-packages` | IMPLEMENTED |
| Custom Fields | sets/versions/values | config/admin | custom_field_sets/versions/values | `custom-fields` 18 | `/admin/custom-fields` | IMPLEMENTED |
| Tenant Experience | branding/profile/revisions/assets | tenant admin | experience profiles/revisions/assets | `tenant-experience` 6 | shared shell/admin | IMPLEMENTED |
| Localization | localized content lifecycle | translator/reviewer/admin | localized_content_variants | `localized-content` 6 | shared/admin panel | VERIFIED: RU/KK/EN 4 562/4 562; seven critical routes × three locales PASS |
| Jobs | queue/outbox/retry/DLQ | system/admin/security | job_runs, queue_outbox, lifecycle_events | `system` 68 aggregate | `/admin/system` | ACTIVE: outbox 12/12; 138 delivered; two consumers × 69, no pending/failure/retry/lag |

## Frontend route/access map

| Route class | Routes | Runtime requester evidence |
|---|---|---|
| Public | `/login` | governed public; not revisited during active session |
| All authenticated | `/account`, `/dashboard` | verified |
| Requester self-service | `/tickets`, `/catalog`, `/requests`, `/knowledge`, `/copilot`, `/notifications` | verified |
| IT operations | `/events`, `/major-incidents`, `/changes`, `/change-calendar`, `/releases`, `/problems`, `/problem-governance`, `/assets`, `/software-assets`, `/sla` | expected denied for requester |
| Executive/admin | `/monitoring`, `/analytics`, `/automation`, `/integrations` | expected denied for requester |
| Admin/security/config | `/admin`, `/admin/system`, `/admin/data-governance`, `/identity-provisioning`, `/email-operations`, `/teams-collaboration`, `/admin/custom-fields`, `/admin/configuration-packages`, `/notifications/email-log` | expected denied for requester |
| Fallback | `*` → `/login` | code verified |

## API inventory summary

| Evidence | Value |
|---|---:|
| Route modules | 51 |
| Route entries | 746 |
| Protected route entries | 739 |
| Governed public entries | 7 |
| OpenAPI paths | 621 |
| OpenAPI operations | 738 |

Main API tags/ops: `system 68`, `cmdb 42`, `integrations 38`, `automation 31`, `admin 29`, `workflow-engine 27`, `catalog 26`, `tickets 24`, `change-governance 23`, `releases 23`, `integration-platform 22`, `email 20`, `event-operations 20`, `sla 20`, `assets 19`, `custom-fields 18`, `auth/scim/identity-provisioning/configuration-packages 17 each`, and specialized domains listed in the module map.

Authoritative composition: `backend/app/api/v1/router.py`. Full executable method/path inventory: `app.openapi()` from the current backend; edge export is not yet published.

## Database map

| Evidence | Value |
|---|---:|
| Base tables | 216 |
| ORM `__tablename__` definitions | 214 |
| Migration files | 81 |
| Current/head | `20260829_0081` |
| Indexes | 718 |
| Foreign keys | 654 |
| Unique constraints | 149 |
| Check constraints | 2 459 |
| Tables with `tenant_id` | 180 |
| PostgreSQL RLS policies | 0 |

Table families: `ai_*`, `asset_*`, `audit_*`, `automation_*`, `cab_*`, `catalog_*`, `change_*`, `ci_*`, `cmdb_*`, `configuration_*`, `custom_field_*`, `data_*`, `email_*`, `event_*`, `identity/provisioned_*`, `integration_*`, `job_*`, `knowledge_*`, `major_incident_*`, `notification_*`, `problem_*`, `release_*`, `request_*`, `service_*`, `sla_*`, `software_*`, `teams_*`, `tenant_*`, `ticket_*`, `workflow_*`, plus core users/roles/tenants/settings/webhooks/runbooks/reports.

## Canonical workflows

| Entity | Canonical states/actions | Important rule |
|---|---|---|
| Ticket | NEW, TRIAGE, ASSIGNED, IN_PROGRESS, WAITING_USER, WAITING_VENDOR, RESOLVED, CLOSED, REOPENED, CANCELLED | only matrix transitions; requester close/reopen constraints |
| Request task | OPEN, IN_PROGRESS, WAITING, COMPLETED, FAILED, CANCELLED | terminal tasks immutable; failed can reopen |
| Catalog item | DRAFT, IN_REVIEW, PUBLISHED, RETIRED | explicit publication workflow |
| Problem | NEW, INVESTIGATING, ROOT_CAUSE_IDENTIFIED, KNOWN_ERROR, RESOLVED, CLOSED, CANCELLED | evidence/RCA/KEDB gates |
| Major Incident | DECLARED, MITIGATING, MONITORING, RESOLVED, CLOSED, CANCELLED | approved PIR required for close |
| Change | draft/assessment/approval/scheduled/implementing/completed/failed/rolled back/closed/cancelled | plans, approval, conflict, PIR/rollback evidence |
| Workflow execution | QUEUED, RUNNING, WAITING_TIMER/APPROVAL/SUBFLOW, RETRY, COMPENSATING, SUCCEEDED/FAILED/CANCELLED/DEAD_LETTER/DROPPED | idempotency, event chain, compensation |
| AI action | proposed, approved/rejected, executed, rolled back | four-eyes + drift check |

Ticket matrix: `NEW → TRIAGE | ASSIGNED | CANCELLED`; `TRIAGE → ASSIGNED | WAITING_USER | CANCELLED`; `ASSIGNED → IN_PROGRESS | WAITING_USER | WAITING_VENDOR`; `IN_PROGRESS → RESOLVED | WAITING_USER | WAITING_VENDOR`; `WAITING_USER → IN_PROGRESS | CANCELLED`; `WAITING_VENDOR → IN_PROGRESS`; `RESOLVED → CLOSED | REOPENED`; `CLOSED → REOPENED`; `REOPENED → TRIAGE | ASSIGNED`; `CANCELLED → ∅`. Единственный historical alias: `TRIAGED → TRIAGE`.

## Evidence and source locations

| Concern | Authoritative location |
|---|---|
| App assembly | `backend/app/main.py`, `backend/app/api/v1/router.py` |
| API routes | `backend/app/api/v1/routes/` |
| DB models | `backend/app/models/` |
| Migrations | `backend/migrations/versions/` |
| RBAC seed | `backend/app/services/seed.py` |
| Ticket lifecycle | `backend/app/services/ticket_lifecycle.py`; callers in ticket/workflow/automation/event routes |
| Workflow engine | `backend/app/services/workflow_engine.py` |
| Runtime settings | `backend/app/core/config.py`, compose/env/secret files |
| Frontend routes | `frontend/src/App.tsx` |
| UI access | `frontend/src/auth/accessControl.ts` |
| Navigation | `frontend/src/components/AppShell.tsx` |
| I18N | `frontend/src/i18n/catalog.ts`, `TenantExperienceContext.tsx`, `frontend/scripts/i18n-audit.mjs` |
| API client | `frontend/src/api/client.ts` |
| Production runtime | `docker-compose.prod.yml`, `frontend/nginx.conf` |
| CI/release | `.github/workflows/` |
| Monitoring | `monitoring/` |
| Operations scripts | `scripts/` |

## Gate 0 evidence and next gate

1. Canonical ticket lifecycle centralized; invalid `OPEN/PENDING/WAITING` rejected; matrix, side effects, authorization, version conflict and idempotency tests pass.
2. RU/KK/EN static coverage is 4 562/4 562 with zero unresolved candidates; strict audit is part of CI. History rendering covers all 27 current event types, the AST validator checks eight producer files, and user/external values remain verbatim.
3. Full backend: 891 collected / 875 passed / 16 justified legacy skips / 0 failed.
4. Local release gate: 28/28 PASS in 19.3 s, evidence SHA-256 `d8d37d0219b08e14b3fbee27a0e408629dc2dd15f0da3473b3d12c7d06b5f4b5`; clean PostgreSQL 17 migration: 81 revisions, one head `20260829_0081`, 216 tables. Final frontend image: `sha256:4f80d483ec1c01a8e86d65e995991c8b8853c20aa9f35b0097e2d05e3f1d2215`, 152 modules.
5. Production-like Docker runtime and smoke pass. Seven critical routes pass in RU/KK/EN without alert, EN contains zero Cyrillic UI strings, and `SD-3409` passes create/native validation, authoritative NEW actions, `NEW → CANCELLED`, terminal-state controls and localized RU/EN/KK history. User-authored RU text remains verbatim by design.
6. Runtime logs: 985 lines, zero errors and zero HTTP 5xx. Formal release closure still requires the approved coherent commit and CI/artifact binding to its SHA.

**NEXT DEVELOPMENT GATE AFTER APPROVED RELEASE COMMIT AND EVIDENCE BINDING:** [GATE 1 — Multi-Role Representative Acceptance](ITSM-ROADMAP.md#gate-1--multi-role-representative-acceptance). Until then Gate 1 = `NO`.
