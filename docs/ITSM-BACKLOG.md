# SBS AI ITSM — Audited Backlog

**Baseline:** 2026-08-29; Gate 0 evidence updated 2026-08-30  
**Priority scale:** P0 blocker/security/data loss; P1 critical business/release; P2 important; P3 improvement; P4 cosmetic.  
**Rule:** `P0/P1` требуют evidence-backed closure до production launch. Gate 0 full regression не выявил активных P0 в его scope; это не заменяет Gate 1+ acceptance, DAST/pentest или проверку реальной серверной конфигурации.

## Gate 0 closure register

| ID | Gate 0 status | Closure evidence / remaining action |
|---|---|---|
| STB-001 | `CLOSED` | One backend Ticket contract contains all 10 canonical states and the complete transition matrix; `OPEN`, `PENDING` and `WAITING` are rejected. |
| STB-002 | `CLOSED` | REST, workflow, automation and bulk status paths use the canonical transition service with lock/version, history, audit, SLA, notifications and idempotency. The only business `ticket.status =` assignment is inside that service. |
| STB-003 | `CLOSED` | The 10-by-10 matrix plus negative, security, concurrency, idempotency, workflow, automation and API tests pass in the 891-test full regression. |
| REL-001 | `BLOCKED` | All 705 paths (`157` tracked + `548` untracked, `0` staged/deletions) are classified and pattern-scanned, but no release SHA exists. Tool safety requires explicit user approval before the classified worktree is staged/committed on `main`; no push is planned. |
| REL-002 | `CLOSED` | Full result: 891 collected, 875 passed, 16 documented legacy skips, 0 failed/errors; 28/28 local release checks pass in 19.3 s with evidence SHA-256 `d8d37d0219b08e14b3fbee27a0e408629dc2dd15f0da3473b3d12c7d06b5f4b5`. |
| I18N-001 | `CLOSED` | RU/KK/EN catalogs and production page/component localization implemented; static inventory maps 4,562 of 4,562 visible candidates with zero unresolved findings. |
| I18N-002 | `CLOSED` | Strict catalog/key/placeholder/visible-literal audit is wired into package and release/CI checks; recorded critical/other violations are 0/0. |
| I18N-003 | `CLOSED` | Seven critical routes pass in RU/KK/EN without alert; every EN route has zero Cyrillic UI strings. `SD-3409` passes create/native validation, authoritative NEW actions, `NEW → CANCELLED`, terminal controls and final localized RU/EN/KK history. User/external values remain verbatim by design. |

`CLOSED` means implemented and backed by the evidence in `docs/gates/GATE-0-REPORT.md`. It does not mean that Gate 1+ production-readiness work is complete.

## P1 — active critical/release blockers

| ID | Priority | Module | Problem | Required Change | Dependencies | Risk | Acceptance Criteria |
|---|---|---|---|---|---|---|---|
| REL-001 | P1 | Repository | The classified 705-path candidate is not represented by a release SHA | Obtain explicit user authorization, remove the two tracked generated `*.tsbuildinfo` paths from the index, create the coherent local commit and bind final evidence to it | user approval | unreproducible release/supply chain | final source and evidence resolve to one reviewed SHA; no secret/generated/runtime data is included |
| ACC-001 | P1 | Acceptance | Only requester runtime route surface audited | Execute read/write UI/API acceptance for all seven roles | REL-001/002 | critical actions may fail or over-authorize | 7/7 role journeys and negative permission checks pass |
| ACC-002 | P1 | Data/Acceptance | Most ITSM domains have zero representative records | Build repeatable acceptance dataset with services, assets, KB, SLA and workflows | REL-001 | false confidence from empty screens | dataset reproducible; each critical process has at least one lifecycle scenario |
| ACC-003 | P1 | Tenant security | Application tenant isolation not accepted across all surfaces on current candidate | Run tenant isolation against API/search/export/websocket/files/jobs | ACC-002 | cross-tenant exposure | all positive/negative vectors pass and audit evidence exists |
| CAT-001 | P1 | Service Catalog | Runtime catalog items = 0 | Create governed university service portfolio data and owners | ACC-002, business owners | portal cannot deliver real services | approved published services visible by entitlement in RU/KK/EN |
| SLA-001 | P1 | SLA/OLA | SLA policies and ticket SLA instances = 0 | Configure priority matrix, calendars, targets and escalation policies | CAT-001, business decisions | SLA UI/metrics not operational | reference cases produce approved deadlines/breaches/escalations |
| INT-001 | P1 | Identity | OIDC disabled; production identity not accepted | Configure corporate OIDC, mappings and break-glass process | security/IdP owner | local-only login/identity lifecycle | login/logout/refresh/MFA/linking/provisioning acceptance passes |
| INT-002 | P1 | Communications | SMTP/Graph/Teams/alert receivers not configured | Configure real sandbox channels with retry/DLQ/rotation/runbooks | credentials/security owners | notifications/operations cannot reach humans | real delivery and failure/replay evidence within SLO |
| SEC-001 | P1 | Security/Release | No current DAST/pentest evidence for candidate | Run SAST/SCA/images/secrets/DAST and independent pentest | REL-001/002, staging | exploitable issue may be unknown | no open critical/high without approved exception/control |

## P2 — important completeness and production work

| ID | Priority | Module | Problem | Required Change | Dependencies | Risk | Acceptance Criteria |
|---|---|---|---|---|---|---|---|
| SD-001 | P2 | Service Desk | No versioned canned responses/macros | Add draft/review/publish/retire macros, variables, scope, audit, usage | ACC-001 | low agent productivity/inconsistent replies | permission-aware macro lifecycle and rendering tests pass |
| SD-002 | P2 | Service Desk | Support groups/skills/rosters/shifts not mature | Model skills, rosters, shifts, OOO/delegation and queue ownership | organization operating model | routing/handover gaps | shift/skill routing and handover accepted by agents |
| SD-003 | P2 | Service Desk | No governed deterministic routing workbench | Add preview/reason/fallback/version/rollback/metrics | SD-002, STB-001 | lost/misrouted tickets | every decision auditable; fallback leaves no orphan |
| SD-004 | P2 | Service Desk | Agent workspace lacks productivity acceptance | Add shortcuts/next ticket/handover/safe batch UX based on user tests | SD-001/002 | slow operations | agreed journey time/clicks reduced without a11y regression |
| INC-001 | P2 | Major Incident | No live/tabletop major incident scenario | Seed roster/templates and run SEV command exercise/PIR | ACC-002, INT-002 | command flow unproven | declaration→updates→resolution→PIR→closure accepted |
| REQ-001 | P2 | Requests | Request approval/fulfillment has no end-to-end runtime evidence | Execute submit/approve/reject/resubmit/fulfill/cancel flows | CAT-001, SLA-001 | self-service failure | requester/approver/fulfiller journeys reconcile with audit |
| PRB-001 | P2 | Problem | No recurring incident candidate pipeline in runtime | Calibrate trend detector and candidate review | representative tickets | recurring incidents unmanaged | known dataset produces expected candidates without excess noise |
| PRB-002 | P2 | KEDB | No governed known-error corpus/workaround acceptance | Define owner/review/expiry/effectiveness workflow | PRB-001, KB-001 | unsafe/stale workarounds | published KEDB requires evidence and expiry review |
| CHG-001 | P2 | Change | CAB/ECAB/quorum/calendar not configured | Configure governance and representative approvals/windows | business/CAB owners | unsafe or blocked changes | normal/emergency/standard and conflict paths accepted |
| CHG-002 | P2 | Change | Standard models/risk calibration not operational | Seed approved models and CMDB-aware risk vectors | CMDB-001, CHG-001 | inconsistent risk | expected risk/approvals from golden cases |
| RELM-001 | P2 | Release | No real CI/CD adapter | Integrate signed deployment evidence/status/rollback callbacks | CI/CD owner, INT platform | release UI detached from deployment | one canary deployment and rollback trace end to end |
| CMDB-001 | P2 | CMDB | Assets/CIs/relationships/sources all empty | Define class/identifier/owner/source model and import representative inventory | source owners | impact analysis meaningless | quality thresholds and certified sample inventory achieved |
| CMDB-002 | P2 | CMDB | No network/IPAM/server topology connector | Implement approved discovery connectors and reconciliation | CMDB-001, INT security | stale/manual infrastructure data | idempotent discovery and validated topology/impact graph |
| CMDB-003 | P2 | CMDB | No PostgreSQL RLS defense-in-depth | Produce threat/performance design and implement critical-table RLS or approved alternative | ACC-003 | filter mistake exposes tenant data | DB-level negative tests and measured overhead accepted |
| SAM-001 | P2 | SAM | No real product/license/installation feeds | Integrate discovery and entitlement reconciliation | CMDB-002 | license/compliance blind spot | over/under-license cases reported correctly |
| KB-001 | P2 | Knowledge | Articles/corpus = 0 | Create governed starter KB in RU/KK/EN with ownership and review | I18N gate, domain owners | no deflection/RAG grounding | approved corpus, feedback and freshness workflow active |
| KB-002 | P2 | Knowledge/Analytics | No measured knowledge deflection/effectiveness | Define search success, helpfulness, reuse, deflection KPIs | KB-001, request/ticket data | misleading knowledge ROI | KPIs trace to auditable events and sampled validation |
| AI-001 | P2 | AI | Runtime mock; OpenAI/Gemini not configured | Complete legal/data/security decision and sandbox provider setup | KB-001, SEC-001 | unsafe external data transfer | governed config/test, no key exposure, fallback/circuit evidence |
| AI-002 | P2 | AI/RAG | RAG corpus/evals/usage empty | Ingest permission-aware corpus and golden RU/KK/EN evals | KB-001, AI-001 | hallucination/leakage | citation, role/tenant, injection, deletion tests pass thresholds |
| AI-003 | P2 | AI Actions | Guarded actions have no operational acceptance | Canary propose→approve→execute→rollback on representative entities | AI-002, ACC-001 | unsafe writes | four-eyes/drift/idempotency/rollback evidence passes |
| INT-003 | P2 | Integrations | Credentials/external systems = 0 | Register owned connectors with encrypted secrets, health, retry and runbooks | INT-001/002 | integration platform unproven | each connector has live sandbox acceptance and SLO |
| INT-004 | P2 | Legacy | Legacy mock/demo routes and UI coexist with production platform | Deprecate/isolate/remove production navigation and compatibility endpoints | INT-003 | operator confusion/false evidence | production capability registry shows no unlabelled mock action |
| MON-001 | P2 | Event Ops | Event sources = 0 | Connect monitoring sources and calibrate normalize/correlate/suppress policies | INT-003, CMDB | no event-to-incident automation | reference event storm creates expected groups/incidents only |
| NOT-001 | P2 | Notifications | Notification templates = 0 | Create versioned localized templates with owner/review/test | I18N, INT-002 | inconsistent/unlocalized messaging | template coverage for critical events in RU/KK/EN |
| ANA-001 | P2 | Analytics | Demo terminology and compatibility export remain | Replace demo labels/routes with governed reports or clearly isolate | representative data | misleading executive view | no production screen labels operational data as demo |
| ANA-002 | P2 | IT Director Dashboard | Network/server/service/license/change/security correlation incomplete | Define evidence-backed executive contract and drilldowns | CMDB/MON/CHG/SAM | incomplete management decisions | agreed KPIs reconcile with source DB and freshness SLO |
| API-001 | P2 | API | Edge does not expose versioned OpenAPI artifact | Generate/sign/version spec in CI and publish controlled docs/SDK | REL-001 | integrator drift | spec diff gate; artifact linked to release SHA |
| API-002 | P2 | API | Very large inline route schemas and manual frontend client | Introduce generated types/client gradually without breaking API | API-001 | contract mismatch | build uses versioned schema; breaking changes gated |
| UI-001 | P2 | Frontend Tests | No active unit/component/E2E runner | Add Vitest/Testing Library/Playwright or equivalent | REL-001 | UI regressions invisible | package scripts/CI execute critical components/routes/roles/locales |
| UI-002 | P2 | Frontend Lint | ESLint is installed, but there is no lint script or configuration | Define reviewed rules/config and add local/CI lint execution | REL-001 | code-quality regressions are not mechanically gated | lint is available from the package scripts and completes with documented zero-error policy |
| UI-003 | P2 | Frontend Build | Main JavaScript chunk is 1,050.49 kB (289.18 kB gzip), above Vite's 500 kB warning threshold; Tickets chunk is 97.38 kB (20.97 kB gzip) | Split routes and stable vendor groups, then measure initial-route payload | UI-001 | slower first load/cache invalidation | production build has intentional chunks and agreed initial-route budget without behavior regression |
| TST-001 | P2 | Backend Tests | 16 legacy Stage 026/027 contract tests are skipped after their endpoint/model contracts evolved | Migrate the 7 approval and 9 enforcement cases to current contracts or retire them with an approved trace | current policy owners | regression gaps can hide in permanently skipped suites | no unexplained skip remains; replacement coverage is linked to each retired case |
| SEC-002 | P2 | Secrets Tooling | Candidate-specific pattern scan passes and CI includes Gitleaks, but Gitleaks is unavailable in the local release environment | Pin/document a local scanner path or import signed CI scan evidence into release provenance | REL-001, CI | local and CI release evidence diverge | final release record contains a successful tool-backed secret scan tied to the release SHA |
| DEV-003 | P2 | Windows Build | Host Vite build hits Tailwind native-binding load failure and `spawn EPERM`; clean Docker build succeeds | Repair/pin the supported Windows Node/native dependency path and document Docker as fallback | package/runtime owners | local developer builds are unreliable | clean documented host install/typecheck/build passes without elevated/manual workarounds |
| OPS-001 | P2 | Storage | Attachments use single Docker volume | Adopt S3-compatible encrypted/versioned storage and malware pipeline | server architecture | scale/HA/data loss limitation | signed upload/download, quarantine, integrity and backup tests pass |
| OPS-002 | P2 | TLS/Edge | Compose endpoint is HTTP and assumes external TLS | Deploy governed TLS ingress/WAF/trusted proxy config | server target | transport/security failure | TLS scan, redirect/HSTS/trusted IP tests pass |
| OPS-003 | P2 | DR | Tools exist, but current revision server restore/RPO/RTO not proven | Run encrypted off-host backup + isolated timed restore/PITR drill | server storage/DB | unrecoverable outage | approved RPO/RTO met; counts/hashes/auth/audit verified |
| OPS-004 | P2 | Scale | No current representative load/soak/failover evidence | Run API/websocket/queue/DB load, soak and fault drills | ACC dataset, server target | capacity/outage surprise | SLO/headroom/recovery thresholds met |
| OPS-005 | P2 | Alerting | Alertmanager runs but accountable receivers absent | Configure paging/email/webhook, ownership, silence/escalation | INT-002 | unnoticed incidents | synthetic alerts fire/resolve to on-call within SLO |

## P3 — maintainability and usability

| ID | Priority | Module | Problem | Required Change | Dependencies | Risk | Acceptance Criteria |
|---|---|---|---|---|---|---|---|
| ARC-001 | P3 | Backend | `jobs.py` and `tickets.py` are very large route modules | Extract cohesive routers/services after contract tests, preserving URLs | Gate 0 tests | change risk/slow review | no API/schema behavior drift; smaller bounded modules |
| ARC-002 | P3 | Frontend | Admin/Tickets/Assets pages are very large | Extract feature panels/hooks with component tests | UI-001 | regression/maintainability | identical behavior/a11y; clear ownership boundaries |
| ARC-003 | P3 | Schemas | Most Pydantic schemas inline in routes | Move stable shared contracts to domain schema modules | API-001 | duplication/cycles | OpenAPI diff proves compatibility |
| ARC-004 | P3 | Lifecycle | State models duplicated across UI/API/services | Generate/display from canonical domain contracts where safe | STB-001 | future drift | one source for each lifecycle; contract tests |
| DEV-001 | P3 | Local Tooling | pnpm wrapper hit non-TTY module-store mismatch | Pin/document package manager/runtime and clean install path | REL-001 | developer friction/non-reproducibility | fresh machine install/build scripts pass non-interactively |
| DEV-002 | P3 | Test Hygiene | Many inaccessible `.pytest-tmp-*` directories pollute scans/status | Define safe test temp root/cleanup procedure and ignore policy | REL-001 | noisy audits/disk growth | tests leave bounded ignored artifacts; no permission warnings |
| UX-001 | P3 | Empty States | Critical domains are empty and usefulness is unclear | Add role-aware onboarding/config checklist without fake data | ACC-002 | user confusion | empty pages explain owner/next action and distinguish unavailable vs empty |
| UX-002 | P3 | Admin | Configuration capabilities spread across admin/system/integrations | Add configuration readiness overview and deep links | Gate 1 | discovery/usability | admin can identify provider owner/status/test/action from one view |
| UX-003 | P3 | Accessibility | Static baseline only; no manual screen reader/mobile acceptance | Run keyboard/screen reader/zoom/contrast/responsive audit by role | UI-001 | accessibility barriers | WCAG-targeted checklist passes; defects tracked |
| DOC-001 | P3 | Documentation | Existing reports can become stale/contradictory | Add evidence date/SHA/status vocabulary and docs validation | REL-001 | false readiness | master/map/context update gate enforced in release checklist |

## P4 — cosmetic/polish

| ID | Priority | Module | Problem | Required Change | Dependencies | Risk | Acceptance Criteria |
|---|---|---|---|---|---|---|---|
| COS-001 | P4 | UI Copy | Mixed Russian/English technical labels remain after functional translation | Editorial terminology glossary per locale | I18N-001 | inconsistent tone | approved glossary applied to key screens |
| COS-002 | P4 | Navigation | Dense admin/IT navigation can overwhelm users | Validate information architecture with role-based ordering/favorites | ACC-001 | discoverability | user test shows critical tasks found within agreed time |
| COS-003 | P4 | Visuals | Large tables need consistent compact/density/mobile patterns | Standardize table toolbar, density and responsive fallback | UI-001 | usability | consistent behavior across Tickets/Assets/Admin/Requests |
| COS-004 | P4 | Branding | Tenant branding assets/profile need production content QA | Add preview/contrast/logo sizing checks and editorial review | Gate 1 | brand/readability | branded tenant passes contrast/layout review |

## Recommended execution queue

1. `I18N-003` and `REL-002` are closed. Obtain explicit user approval → create the local `REL-001` release SHA without push → bind final evidence/artifacts to it. Do not start Gate 1 while Gate 0 is blocked.
2. After Gate 0 PASS: `ACC-002` → `ACC-001` → `ACC-003`.
3. Service Desk/catalog/SLA rollout (`SD-*`, `CAT-001`, `REQ-001`, `SLA-001`).
4. Integrations/CMDB/operations and optional governed AI follow the evidence-based Gates in `docs/ITSM-ROADMAP.md`.
5. Schedule P2 engineering debt (`UI-001/002/003`, `TST-001`, `SEC-002`, `DEV-003`) without misrepresenting unavailable checks as PASS.

## Closure record template

When closing an item, append evidence to the implementation report:

- final commit SHA and migration(s);
- exact tests and totals;
- runtime services/config status without secrets;
- API/DB/UI evidence;
- role/tenant/locale scenarios;
- rollback/compatibility result;
- remaining risks and linked backlog IDs.
