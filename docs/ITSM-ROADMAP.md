# SBS AI ITSM — Evidence-Based Development Roadmap

**Baseline:** 2026-08-30  
**Source:** [ITSM-SYSTEM-MASTER.md](ITSM-SYSTEM-MASTER.md)  
**Rule:** каждый Gate закрывается evidence `CODE + DB + API + TEST + RUNTIME + UI`, где это применимо. Наличие endpoint или страницы само по себе не закрывает Gate.

## Gate sequence

| Gate | Название | Основной результат | Блокирует запуск |
|---|---|---|---|
| 0 | Lifecycle Integrity, I18N and Release Baseline | безопасный канонический lifecycle, полные RU/KK/EN, проверенный локальный кандидат | **TECHNICAL PASS; FORMALLY BLOCKED solely by REL-001 commit/SHA** |
| 1 | Multi-Role Representative Acceptance | все роли и основные процессы приняты на representative data | **NO — only after approved Gate 0 commit and evidence binding** |
| 2 | Service Desk Productivity | macros, routing, rosters, shift-ready operation | Для Service Desk launch |
| 3 | Service Portfolio, Requests and SLA | реальный каталог, approvals, SLA/OLA and escalation | Для self-service launch |
| 4 | Assets, CMDB and Discovery | trusted CI/asset inventory and topology | Для impact/change/operations |
| 5 | Problems, Changes, Releases and Major Incidents | управляемая operational governance | Для enterprise operations |
| 6 | Integrations, Communications and Monitoring | реальные enterprise channels/connectors | Для production operations |
| 7 | Governed Production AI | external AI with corpus/evals/budgets/evidence | Нет, отдельный controlled rollout |
| 8 | Security, Scale and Server Cutover | доказанный server production release | Финальный launch gate |

# GATE 0 — Lifecycle Integrity, I18N and Release Baseline

## GOAL

Удалить подтверждённые data/release blockers и создать первый воспроизводимый кандидат, на котором можно честно проводить многоролевую приемку.

## CURRENT STATE

- Ticket lifecycle centralized in `backend/app/services/ticket_lifecycle.py`; API, bulk, workflow, automation and event operations use the same authority.
- Canonical states: `NEW/TRIAGE/ASSIGNED/IN_PROGRESS/WAITING_USER/WAITING_VENDOR/RESOLVED/CLOSED/REOPENED/CANCELLED`; invalid `OPEN/PENDING/WAITING` rejected, only `TRIAGED → TRIAGE` retained as historical alias.
- RU/KK/EN strict static coverage: 4 562/4 562 visible candidates, unresolved/critical/other = 0; CI audit enabled. Seven critical routes × three locales pass without alert; every EN route contains zero Cyrillic UI strings.
- Full backend: 891 collected / 875 passed / 16 reviewed legacy skips / 0 failed.
- Local release gate: 28/28 PASS in 19.3 s, evidence SHA-256 `d8d37d0219b08e14b3fbee27a0e408629dc2dd15f0da3473b3d12c7d06b5f4b5`; clean PostgreSQL 17 upgrade: 81 revisions, one head `20260829_0081`, 216 tables.
- Production-like Docker runtime, production smoke and live lifecycle race pass.
- Final frontend image `sha256:4f80d483ec1c01a8e86d65e995991c8b8853c20aa9f35b0097e2d05e3f1d2215` contains 152 modules. Main chunk remains P2 at 1 050.49 kB / 289.18 kB gzip; Tickets chunk is 97.38 kB / 20.97 kB gzip.
- Release candidate: 705 classified files (`157` tracked + `548` untracked, `0` staged/deletions); coherent commit and CI binding to final SHA still pending explicit user approval.
- Frontend still has no active unit/component/E2E runner; this is documented P2 and does not replace Gate 1 acceptance.

## DELIVERED

1. One ticket lifecycle contract for API patch/transition/assign/bulk, workflow, automation and event operations.
2. Central status validation, authorization, row lock/version conflict, timestamps, history, audit, SLA sync, notification and deterministic idempotency side effects.
3. Complete 10×10 matrix plus negative/security/concurrency/idempotency regression and live runtime race tool.
4. Strict three-locale catalog/parity/placeholder/literal audit and CI integration.
5. Static RU/KK/EN source/UI coverage 4 562/4 562; seven critical routes × three locales and the final `SD-3409` create/validation/NEW-actions/CANCELLED/localized-history journey pass on the fresh production build. History rendering covers 27 current event types; eight producer files are AST-validated; user/external values remain verbatim.
6. Safe worktree classification and `.gitignore` normalization without deletion of user data.
7. Full regression, TypeScript/i18n/a11y/control audits, production image build, smoke, route-auth and clean-migration checks.

## RELEASE CLOSURE CONDITION

- Create the explicitly approved coherent local commit without pushing.
- Bind final gate report, CI and immutable artifact provenance to that SHA.
- Do not label the complete product production-ready; Gate 1–8 remain independent acceptance gates.

## ACCEPTANCE EVIDENCE

| Criterion | Result |
|---|---|
| One canonical lifecycle service; no bypass mutation | PASS |
| Invalid legacy ticket statuses rejected | PASS |
| History/audit/timestamps/SLA/notification/idempotency | PASS |
| RU/KK/EN static UI coverage | PASS — 4 562/4 562; seven routes × three locales |
| Full backend regression | PASS — 875 passed / 16 justified skips |
| Local release gate | PASS — 28/28 in 19.3 s; evidence `d8d37d0219b0…f4b5` |
| Clean PostgreSQL 17 upgrade | PASS — 81 revisions / head 0081 / 216 tables |
| Production Docker runtime/smoke | PASS |
| Representative browser lifecycle | PASS — seven routes in RU/KK/EN, EN Cyrillic 0, `SD-3409` terminal lifecycle and localized history |
| Coherent final commit + CI/artifacts bound to SHA | PENDING explicit commit approval |

## DEFINITION OF DONE

Технические criteria Gate 0 выполнены. `I18N-003` и `REL-002` закрыты. Формальный Gate 0 остаётся `BLOCKED` исключительно по `REL-001`: release closure наступает после явного разрешения пользователя, записи final commit SHA без push и привязки связанных CI/artifact evidence в gate report. До этого Gate 1 = `NO`.

# GATE 1 — Multi-Role Representative Acceptance

## GOAL

Доказать реальную работоспособность платформы для всех семи ролей и основных ITSM процессов, а не только наличие кода.

## CURRENT STATE

- Requester baseline browser audit: 8 accessible routes, 23 expected denied, console clean.
- Organization-admin browser evidence подтверждает ticket list/detail/history и backend-authoritative transition options; это не полная role acceptance.
- Manager/agent/security/knowledge и полная admin read/write matrix ещё не проверены.
- Rehearsal data сосредоточены в tickets/audit; catalog/requests/problems/changes/releases/assets/knowledge/SLA/AI/workflows/integrations mostly empty.

## WHAT TO BUILD

1. Создать versioned, repeatable representative acceptance dataset без production secrets.
2. Завести пользователей всех ролей, IT teams, departments, services, assets/CIs, articles, catalog items, policies and integration stubs with explicit status.
3. Создать role journey matrix: visible navigation, read scope, allowed actions, forbidden actions, tenant isolation.
4. Пройти read/write browser acceptance каждой роли.
5. Подтвердить cross-tenant denial и four-eyes workflows.
6. Сформировать defect register с screenshots/request IDs/audit IDs.

## DEPENDENCIES

Gate 0 must be formally closed; stable repeatable environment; approved role definitions.

## ACCEPTANCE CRITERIA

- 7/7 roles pass navigation and permissions matrix.
- Positive and negative operation checks cover each permission family.
- Tenant A cannot read/write Tenant B through API, search, export, websocket, files or jobs.
- All critical pages have explicit loading/empty/error/permission states.
- No unclassified mock/demo data shown as real operational evidence.

## TESTS

API authorization contract, tenant isolation, browser E2E by role, audit-chain verification, websocket scope, export/file permission tests.

## DEFINITION OF DONE

Signed role acceptance matrix; all P0/P1 fixed; P2 documented with owner/target; reproducible dataset and automation stored in repository.

# GATE 2 — Service Desk Productivity

## GOAL

Сделать ежедневную работу первой линии быстрой, управляемой и измеримой.

## CURRENT STATE

Ticket core глубокий: queues, assignment, comments/history, on-behalf, participants, bulk, duplicate/merge/split, AI/KB hooks. Нет зрелых macros/skills/rosters/shift handover.

## WHAT TO BUILD

1. Versioned canned responses/macros with variables, scope, ownership, review, usage analytics and audit.
2. Support groups, skills, rosters, working shifts, queue ownership and out-of-office delegation.
3. Deterministic routing rules with preview, reason, fallback, throttling and rollback.
4. Agent workspace: keyboard shortcuts, next-best ticket, safe batch operations and handover queue.
5. Quality metrics: first response, reassignment, reopen, CSAT, FCR, backlog aging.

## DEPENDENCIES

Gates 0–1; approved operating model/service groups.

## ACCEPTANCE CRITERIA

- Macro lifecycle draft/review/publish/retire and permission matrix work.
- Routing never silently loses a ticket; every decision is auditable and replay-safe.
- Shift handover preserves ownership/context and SLA.
- Agent acceptance demonstrates measurable reduction in repetitive actions.

## TESTS

Macro rendering/security, routing matrix, concurrency, fallback, timezone/shift, UI keyboard/accessibility, load tests for queues/bulk.

## DEFINITION OF DONE

Real agents complete agreed scenarios; metrics dashboard and runbook exist; no P0/P1 defects.

# GATE 3 — Service Portfolio, Requests and SLA/OLA

## GOAL

Запустить полноценный университетский self-service portal с реальными услугами, согласованиями, fulfillment и измеримым SLA/OLA.

## CURRENT STATE

Catalog/request/SLA code implemented, but runtime catalog items, requests, SLA policies and instances are zero.

## WHAT TO BUILD

1. Service portfolio taxonomy: business/technical services, owners, support groups, lifecycle and criticality.
2. University catalog: accounts/access, Platonus, Moodle, M365/email, VPN, Wi-Fi, classroom/AV, workplace/equipment, software, procurement, joiner/mover/leaver.
3. Versioned forms, entitlements, approvers, fulfillment templates and knowledge deflection.
4. Business-approved priority matrix, calendars, holidays, response/resolution targets, OLA and escalations.
5. SLA pause/resume governance and breach notifications.

## DEPENDENCIES

Gate 1 representative data; organization owners; real calendar/approval decisions; Gate 2 support groups.

## ACCEPTANCE CRITERIA

- Published catalog has owner, support model, form, entitlement, approval and SLA for every item.
- Request submit→approve/reject→fulfill→confirm/cancel works end to end.
- SLA engine matches approved test clock/calendar vectors and produces exactly-once escalations.
- RU/KK/EN catalog content complete.

## TESTS

Form/version compatibility, entitlements, approvals, task workflow, SLA calendar/timezone/DST, breach and pause abuse, browser requester/approver/fulfiller journeys.

## DEFINITION OF DONE

Business owners sign catalog/SLA matrix; representative services live in rehearsal; reports reconcile with DB evidence.

# GATE 4 — Assets, CMDB and Discovery

## GOAL

Создать доверенный источник конфигураций, оборудования, ПО и связей для impact, incident and change management.

## CURRENT STATE

Rich asset/CMDB/SAM schema and UI exist; runtime assets/CIs/sources are empty; no accepted live discovery.

## WHAT TO BUILD

1. Data model/ownership for campus/building/room/rack/network/server/VM/cloud/workplace/device/software/license/service.
2. Production connectors for directory/device management/network/server/cloud and approved file imports.
3. Identification/reconciliation precedence, duplicate workbench, stale lifecycle and certification campaigns.
4. IPAM/network topology and service-to-CI relationships.
5. License entitlements, installations and compliance reconciliation.
6. Data quality SLOs and exception ownership.

## DEPENDENCIES

Gates 1/3; authoritative source owners; integration security patterns from Gate 6 may be delivered incrementally.

## ACCEPTANCE CRITERIA

- Each CI class has owner, identifier, mandatory fields, source precedence and certification policy.
- Discovery is idempotent; manual verified fields are not silently overwritten.
- Impact graph produces validated blast radius on representative incidents/changes.
- Quality dashboard reports completeness, uniqueness, freshness and ownership.

## TESTS

Import scale, reconciliation conflict, topology cycles, tenant isolation, source failure/retry, dispose/restore, license over/under-use.

## DEFINITION OF DONE

Approved sample inventory reconciles against source systems; quality thresholds met; operations use CMDB links in real rehearsals.

# GATE 5 — Problems, Changes, Releases and Major Incidents

## GOAL

Доказать управляемость сложных operational workflows и снизить recurring incidents/change risk.

## CURRENT STATE

All control planes implemented but runtime data and operational acceptance are absent.

## WHAT TO BUILD

1. Recurring incident detection → problem candidate → RCA/KEDB/corrective action.
2. Approved problem and KEDB operating model.
3. CAB/ECAB membership, quorum, calendar, blackout and emergency review.
4. Standard change models and risk calibration using CMDB impact.
5. Release-to-CI/deployment evidence and CI/CD adapter contract.
6. Major incident roster, stakeholder templates, status page channel and PIR actions.

## DEPENDENCIES

Gates 2–4; service ownership; communications channel from Gate 6.

## ACCEPTANCE CRITERIA

- Full Incident→Major/Problem→Change→Release→Knowledge traceability.
- No closure without required evidence/PIR/corrective actions.
- Conflicting/blackout changes are blocked or explicitly overridden with authority.
- Rollback and forward-fix are rehearsed and measured.

## TESTS

Lifecycle matrices, approvals/quorum, conflicts, emergency path, PIR gates, cross-entity links, audit, browser command exercise.

## DEFINITION OF DONE

Tabletop exercise and technical rehearsal pass; owners sign runbooks and KPI definitions.

# GATE 6 — Integrations, Communications and Monitoring

## GOAL

Заменить неактивные/mock контуры реальными надежными enterprise connections.

## CURRENT STATE

Integration platform, Graph email, Teams, SCIM, OIDC, monitoring/webhooks implemented. Runtime credentials/systems/event sources are zero; external alert receivers not configured.

## WHAT TO BUILD

1. Corporate OIDC/SCIM, group-to-role mapping, joiner/mover/leaver acceptance.
2. Microsoft Graph email ingestion/reply and attachment quarantine with real mailbox.
3. Teams major incident/notification flows with real tenant permissions.
4. Platonus/Moodle/directory connectors via production contract; retire or isolate legacy mock endpoints.
5. Monitoring sources, event normalization/correlation/suppression and incident creation.
6. Signed webhooks, credential rotation, allowlists, replay/dead-letter operations.
7. Real Alertmanager receivers and on-call escalation.

## DEPENDENCIES

Security approval, test accounts/endpoints, data owners, network egress, Gate 1 permission acceptance.

## ACCEPTANCE CRITERIA

- Each connector has owner, secret reference, scope, test, health, retry/DLQ, metrics and runbook.
- No secret appears in UI/log/audit/export.
- Failure, timeout, duplicate, replay and rotation behave deterministically.
- Alerts reach real accountable receivers within SLO.

## TESTS

Contract/sandbox tests, timeout/retry/idempotency, signature/allowlist, secret rotation, attachment malware cases, end-to-end alert delivery.

## DEFINITION OF DONE

Configured connector registry and live acceptance evidence; legacy demo surface disabled/removed from production navigation.

# GATE 7 — Governed Production AI

## GOAL

Активировать AI только после доказанной точности, безопасности, стоимости и human oversight.

## CURRENT STATE

Provider/RAG/governance/evaluation/budget/action foundation implemented; runtime provider mock; all operational AI tables empty.

## WHAT TO BUILD

1. Approve OpenAI and/or Gemini data-processing model, region, retention and tenant policies.
2. Configure secret through governed admin UI/secret manager; connection test and circuit monitoring.
3. Curate permission-aware KB/ITSM corpus with source freshness and deletion propagation.
4. Build golden datasets for classification, routing, answers, risk and action proposals in RU/KK/EN.
5. Define quality/safety/cost thresholds and canary rollout.
6. Activate assistants sequentially: Knowledge → Agent Assist → Dispatcher → Problem/Change/CMDB → Director.
7. Keep guarded writes four-eyes and reversible; no autonomous destructive action.

## DEPENDENCIES

Gates 0–6, especially clean data/permissions/knowledge and real process owners.

## ACCEPTANCE CRITERIA

- Citations are permission-safe and traceable; cross-tenant leakage tests pass.
- PII policy/redaction and external-call decision are logged without leaking content.
- Golden eval thresholds and hallucination/refusal criteria pass per locale.
- Budget/circuit/timeout/fallback work; mock is clearly labelled fallback.
- Human approval and rollback evidence pass for every write-capable action.

## TESTS

Offline evals, prompt injection, data exfiltration, tenant/role leakage, stale/deleted source, provider outage, budget exhaustion, action drift/rollback.

## DEFINITION OF DONE

Approved evaluation report, model/prompt versions, cost limits, rollback plan, operator runbook and canary evidence.

# GATE 8 — Security, Scale and Server Cutover

## GOAL

Перенести доказанный релиз на сервер и разрешить реальный пользовательский traffic.

## CURRENT STATE

Production-like compose healthy; local release gate 28/28, production smoke and clean PostgreSQL 17 migration pass. Нет committed-candidate CI evidence, external TLS/SSO/connectors, current DAST/pentest, representative scale and server DR proof.

## WHAT TO BUILD

1. Server topology, DNS, TLS, WAF/firewall/egress and secret manager.
2. Managed/HA PostgreSQL/Redis decision, capacity and connection budgets.
3. S3-compatible attachments with scanning, retention and signed delivery.
4. Off-host encrypted backups, PITR and timed isolated restore; approved RPO/RTO.
5. Load, soak, failover, worker lag, database/Redis/network fault drills.
6. RLS/defense-in-depth decision for critical tenant tables.
7. Current SAST/SCA/image/secret/DAST and independent penetration test.
8. Immutable signed release, SBOM/provenance, canary/rollback and operational ownership.

## DEPENDENCIES

Gates 0–6; Gate 7 only for AI launch, not core ITSM launch.

## ACCEPTANCE CRITERIA

- All P0/P1 closed; business UAT signed.
- Capacity SLOs met at approved peak with headroom.
- Restore/failover/rollback drills meet RPO/RTO.
- TLS/identity/secrets/storage/alerts validated in server environment.
- Monitoring/on-call/runbooks/ownership active.
- Final release manifest maps commit, migrations, images, SBOM, tests and approvals.

## TESTS

Full regression, E2E roles/locales, performance/soak, resilience/DR, security/DAST/pentest, migration forward/rollback strategy, smoke and synthetic monitoring.

## DEFINITION OF DONE

Go/No-Go board has objective evidence for every criterion. Only a GO decision allows production traffic; unresolved items remain explicit exceptions with owner, expiry and compensating control.

## NEXT DEVELOPMENT GATE

> После явно одобренного coherent Gate 0 release commit и привязки evidence к его SHA следующим этапом выполнить **GATE 1 — Multi-Role Representative Acceptance**. До этого Gate 1 = `NO`.

Порядок Gate 1: подготовить repeatable representative dataset, затем пройти позитивные и негативные read/write journeys всех семи ролей, tenant/object isolation и audit evidence. Gate 0 нельзя трактовать как production launch approval; внешние providers, реальные business domains и server cutover закрываются последующими gates.
