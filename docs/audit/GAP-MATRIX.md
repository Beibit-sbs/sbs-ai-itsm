# SBS AI ITSM — GAP matrix

Статусы: `CONFIRMED`, `PARTIAL`, `MISSING`, `BROKEN`, `MOCK_ONLY`,
`BLOCKED_EXTERNAL`, `UNVERIFIED`.

| Область | Статус | Evidence / gap | Следующее действие |
|---|---|---|---|
| FastAPI / OpenAPI | CONFIRMED | 746 endpoints / 739 protected / 7 governed public; OpenAPI 738 operations / 621 paths; ticket-governance auth contract PASS | сохранять auth contract |
| Frontend routes | CONFIRMED | 33 route declarations including fallback; SAM production chunk built | расширить multi-role E2E |
| Alembic graph | CONFIRMED | single head `20260829_0081` | repeat PostgreSQL roundtrip at next migration boundary |
| Local SQLite UAT | CONFIRMED | 205 tables, integrity ok, readiness ready | не использовать в production |
| Isolated production-like runtime | CONFIRMED | preflight 66/2/0; migration 0081; backend 3/3 and frontend healthy | retain continuation evidence |
| Production PostgreSQL | PARTIAL | local live migration and health confirmed | current downgrade cycle + concurrency |
| Redis / worker / scheduler | CONFIRMED | separate leader-elected scheduler, live lease/heartbeat, governed DLQ 0 | server failover/scale acceptance |
| Production reverse proxy/TLS | PARTIAL | nginx live, header validator PASS, local ZAP 0 FAIL | реальный domain/TLS active scan |
| Demo production gate | CONFIRMED | settings validator и tests запрещают unsafe config | проверить на server secrets |
| CORS/trusted proxy | CONFIRMED | edge-security contract PASS | подтвердить реальными CIDR/hosts |
| Sessions/refresh/replay | CONFIRMED | session-security contract PASS | server cookie/TLS acceptance |
| Notification recipient isolation | CONFIRMED | personal list/count/read/read-all are recipient-scoped; tenant view requires `notifications.manage`; negative tests PASS | retain cross-tenant regression |
| MFA privileged roles | PARTIAL | foundation, enrollment и enforcement есть | включить с production key и пройти acceptance |
| OIDC/Entra | BLOCKED_EXTERNAL | adapter/config/tests есть | tenant app credentials + callback test |
| SCIM lifecycle | PARTIAL | provisioning foundation/tests есть | real Entra joiner/mover/leaver |
| RBAC/multi-role | CONFIRMED | central evaluator, 735 protected endpoints | expand negative browser matrix |
| Tenant isolation | PARTIAL | scoped services и negative tests есть | PostgreSQL cross-tenant concurrency suite |
| Tamper-evident audit | CONFIRMED | chain model/tests, 64 local events | production chain verification |
| Attachment storage | PARTIAL | bounded storage/email attachment services | ClamAV/quarantine live gate |
| Retention/purge | CONFIRMED | migration 0077: unified policy, legal hold, approval/execution evidence and export | server retention schedule acceptance |
| Dependency/security scans | CONFIRMED | SCA/SAST/history+worktree secrets/images: 0 open High/Critical; ZAP 0 FAIL | public TLS scan + external penetration test |
| SBOM | CONFIRMED | backend/frontend source and image SBOMs with SHA-256 | sign/publish with server release artifact |
| Global abuse protection | PARTIAL | body/login limits confirmed | tenant/API token rate limits and stress |
| Observability | CONFIRMED | 8 SLO, 21 alerts, 20 panels; 3/3 scrape; controlled firing/resolved audit | real external receiver acceptance |
| Backup/restore local | CONFIRMED | online backup + isolated restore + SHA-256 | retain evidence |
| Backup/restore PostgreSQL | PARTIAL | encrypted tooling/runbooks exist | fresh production-like restore drill |
| DR/BCP | PARTIAL | procedures and prior drills exist | current-revision timed RPO/RTO drill |
| Performance | PARTIAL | 3 profiles/31 controls contract | baseline/peak/soak with p50/p95/p99 |
| Incident/tickets | CONFIRMED | CRUD/lifecycle/SLA/comments/history/tests | enterprise productivity additions |
| Participants/watchers | CONFIRMED | migration 0079; tenant-scoped participant model, self-watch, role/scope/channel preferences, internal-comment privacy, audit/history, RU/KK/EN UI and runtime browser smoke | multi-role load and external email delivery acceptance |
| On-behalf registration | CONFIRMED | migration 0080; creator/requester/contact/channel persisted; dedicated permission, active tenant directory, mandatory reason, anti-impersonation, history/audit, RU/KK/EN UI and PostgreSQL runtime PASS | retain negative tenant/requester regression |
| Merge/split/duplicate | CONFIRMED | migration 0081; explainable scoring, tenant/RBAC scope, dismiss, soft merge, child split, optimistic versions, idempotency, history/audit, RU/KK/EN UI and PostgreSQL runtime PASS | retain concurrency and negative tenant regression |
| Macros/canned responses | MISSING | no completed evidence | versioned templates and permissions |
| Impact x urgency | CONFIRMED | priority and ticket/SLA foundations | browser acceptance |
| Shifts/on-call/delegation | MISSING | no completed evidence | schedule/escalation model |
| CSAT | PARTIAL | satisfaction field and requester close/reopen exist | survey workflow and dashboards |
| Scheduled reports/exports | PARTIAL | analytics/reporting foundation | schedules, ACL, audit, retention |
| Service Catalog | CONFIRMED | forms, entitlement, approvals, fulfillment | golden E2E automation |
| Change/CAB/calendar | CONFIRMED | lifecycle/governance/calendar/tests | PostgreSQL collision concurrency |
| Problem/KEDB/RCA | CONFIRMED | models/routes/governance/tests | golden recurrence/RCA E2E |
| Major Incident | CONFIRMED | command/updates/PIR foundation | signed-event golden E2E |
| Release governance | CONFIRMED | gates/artifacts/deployments/rollback foundation | real CI/CD adapter acceptance |
| Asset/CMDB | CONFIRMED | schema, relationships, reconciliation, impact, quality | live discovery source |
| Software Asset Management | PARTIAL | products, licenses, installations, contracts, renewals, prohibited software, compliance and cost-at-risk API/UI/tests; migration 0078 | live software inventory feed, bulk import and renewal notification E2E |
| Service mapping | PARTIAL | CMDB topology/impact foundation | business-service browser acceptance |
| Knowledge/RAG | CONFIRMED | permission-aware retrieval/governance/tests | tenant leakage eval on PostgreSQL |
| OpenAI/Gemini adapter | PARTIAL | real adapters/config/test endpoint exist | real key and provider-confirmed result |
| AI evaluation | PARTIAL | governance/runtime control foundation | signed datasets, thresholds, regression |
| AI security | PARTIAL | redaction, permission-aware RAG, guarded actions | adversarial eval and external review |
| Email/Graph | BLOCKED_EXTERNAL | Graph adapter and honest simulation boundary | mailbox/app credentials, thread E2E |
| Teams | BLOCKED_EXTERNAL | adapter/workflow/evidence boundary | real webhook/Graph acceptance |
| Monitoring connectors | BLOCKED_EXTERNAL | signed connector foundation | real monitoring sender acceptance |
| Integration platform | PARTIAL | tokens/webhooks/logs/retries foundation | external contract acceptance |
| RU/KK/EN shell | CONFIRMED | selector/nav/core chrome verified | keep shared message catalog |
| RU/KK/EN full product | PARTIAL | specialist/admin parity not proven | automated parity + human review |
| Accessibility | PARTIAL | static audit PASS: 77 files, 16 dialogs, 681 buttons, 39 links | axe, keyboard, reader, zoom, mobile |
| SaaS lifecycle/plans/quotas | MISSING | roadmap M9 deferred | business decision before build |
| Import framework | PARTIAL | Excel/asset import exists | generic preview/mapping/dry-run platform |
| Golden E2E 01–10 | PARTIAL | module tests exist; unified clean-tenant suite absent | automate all ten flows |

## Production blocker summary

`BLOCKED_EXTERNAL`: domain/TLS, server infrastructure, production secrets,
OpenAI/Gemini, Entra/SCIM, Graph email, Teams, monitoring/discovery receivers.

`MISSING/PARTIAL` internal scope must continue independently; external blockers
do not justify simulated success and do not block code, contracts or test
harnesses.
