# SBS AI ITSM — Production Master Roadmap

**Document status:** active  
**Last reviewed:** 2026-07-29  
**Strategic objective:** evolve the current foundation into a secure,
operationally reliable, enterprise-grade ITSM platform and only then extend it
into a commercially managed multi-tenant SaaS product.

## 1. How this roadmap is used

This document is the strategic source of truth for scope, priorities,
dependencies, and completion criteria.

`docs/operations/WORLD-CLASS-EXECUTION-LEDGER.md` is the execution source of
truth for the currently active stage, implementation evidence, test results,
and the exact next action.

At the start of every implementation stage:

1. Read this roadmap and the execution ledger.
2. Select one stage with status `NEXT` or `PLANNED`.
3. Record goal, non-goals, affected areas, risks, and validation plan in the
   execution ledger.
4. Change the stage to `IN PROGRESS`.
5. Implement backend, frontend, migration, RBAC, audit, tests, operations, and
   documentation together where they apply.
6. Do not declare the stage complete until its exit criteria and the common
   quality gate are satisfied.
7. Add a stage report under `docs/reports/` and update both documents.

## 2. Status vocabulary

| Status | Meaning |
|---|---|
| `COMPLETE` | Implemented and verified with evidence |
| `FOUNDATION` | A working base exists, but enterprise depth remains |
| `NEXT` | The next stage to execute |
| `PLANNED` | Approved roadmap scope, not started |
| `DEFERRED` | Intentionally postponed until a dependency is complete |
| `BLOCKED` | Cannot progress without a concrete external decision or resource |

## 3. Current product baseline

The platform is no longer a basic MVP. The following foundations exist:

- Service Desk tickets and SLA foundation;
- tenant-safe Service Catalog with governed lifecycle and versioned dynamic
  request forms;
- Asset Inventory / CMDB foundation;
- Change Management with risk, CAB/ECAB, windows, conflicts, rollback, and
  audit;
- Problem Management, RCA, recurrence, and Known Error Database;
- Knowledge Base and AI Copilot foundation;
- OpenAI/Gemini provider configuration with server-side secrets;
- automation, integrations, notifications, analytics, and monitoring modules;
- asynchronous jobs, outbox, retry, dead-letter, event consumers,
  auto-remediation governance, and realtime dashboard updates;
- multi-tenant RBAC, SaaS Root and organization-level administration;
- tamper-evident audit foundation;
- OIDC identity provider integration and external identity links;
- SCIM 2.0 / Microsoft Entra provisioning control plane with governed
  joiner/mover/leaver handling;
- TOTP MFA, one-time recovery codes, replay protection, protected reset, and
  privileged-role coverage;
- production Compose, migrations, preflight, backup/restore scripts,
  observability foundation, and smoke-test tooling.

Approximate maturity snapshot:

| Area | Current maturity | Roadmap target |
|---|---:|---:|
| Functional ITSM foundation | 75% | 95%+ |
| Enterprise process depth | 55–60% | 90%+ |
| Production operational readiness | 60–65% | 95%+ |
| Commercial SaaS readiness | 45–50% | 90%+ |

These percentages are directional planning indicators, not release metrics.
Release approval depends only on the explicit gates below.

## 4. Program priorities

Work is sequenced in this order:

1. Production Release Gate.
2. Service Catalog and Request Fulfillment.
3. CMDB relationships, service mapping, and impact analysis.
4. Deeper Incident, SLA, Change, Problem, and Release processes.
5. Enterprise integrations and identity lifecycle.
6. Workflow and no-code configuration.
7. Governed production AI.
8. UX, accessibility, and administrative configuration depth.
9. Commercial SaaS controls.

The sequence may change only through an explicit roadmap decision recorded in
the execution ledger.

---

# Milestone M1 — Production Release Gate

**Goal:** prove that the platform can be deployed, secured, observed, backed
up, restored, upgraded, and operated in an environment representative of
production.

**Status:** `IN_PROGRESS` — local static gate PASS; runtime acceptance pending
— 2026-07-29

**Execution mode:** `LOCAL_FIRST`. All release-gate rehearsals are completed
against isolated local Docker environments. Server provisioning, DNS, trusted
TLS, and final cutover are deferred until the local platform roadmap is
complete.

## PRG-001 — Staging production topology

**Status:** `COMPLETED_LOCAL`

Scope:

- deploy PostgreSQL, Redis, migrate, backend, worker, frontend, Prometheus,
  Alertmanager, and Grafana through production Compose;
- use `DEMO_MODE=false` and `RUN_STARTUP_DDL=false`;
- configure explicit HTTPS origins and defer trusted TLS termination to the
  final server-cutover stage;
- generate distinct Docker secrets outside version control;
- verify container hardening, health checks, restart policy, and network
  isolation;
- make the staging deployment reproducible from documented commands.

Exit criteria:

- production preflight reports no failures;
- Compose configuration validates;
- migration container exits successfully;
- every required service is healthy;
- the local application passes the full production smoke suite through its
  loopback edge;
- no demo credentials or example secrets are active;
- deployment evidence is recorded.

## PRG-002 — Database migration rehearsal

**Status:** `COMPLETED_LOCAL`

Scope:

- restore a production-like database copy into staging;
- run all Alembic upgrades to current head;
- measure migration duration and lock impact;
- verify constraints, indexes, tenant isolation, and data counts;
- test application compatibility before and after migration;
- define rollback/forward-fix decision rules.

Exit criteria:

- migration is repeatable and idempotency assumptions are documented;
- schema head matches the application;
- no unexplained record loss or tenant leakage;
- maintenance-window requirement is known;
- rollback or forward-fix procedure is approved.

## PRG-003 — Backup, restore, and disaster recovery

**Status:** `COMPLETED_LOCAL`

Scope:

- schedule encrypted PostgreSQL and application-data backups;
- define retention, off-site copy, and access policy;
- perform restore into an isolated environment;
- validate restored record counts, authentication, attachments, and audit;
- establish RPO, RTO, incident owner, and escalation path.

Exit criteria:

- a full restore drill succeeds;
- measured RPO/RTO meet the approved target;
- backup failure creates an alert;
- runbook includes evidence, owners, and recovery decision points.

## PRG-004 — Identity and security cutover

**Status:** `DEFERRED` — server identity-provider and cutover dependencies

Scope:

- enroll MFA for every privileged local account;
- reach `Privileged gap = 0`;
- enable `MFA_ENFORCEMENT_ENABLED=true`;
- configure production OIDC and verify issuer, PKCE, nonce, state, and JWKS
  rotation;
- preserve and test a controlled local break-glass root;
- define joiner/mover/leaver procedure;
- verify session revocation, lockout, audit retention, and administrator
  separation of duties;
- run dependency, container, secret, and external penetration scans.

Exit criteria:

- privileged password-only login is rejected;
- OIDC and break-glass paths are both tested;
- sensitive administrative actions require step-up authentication;
- critical/high security findings are resolved or formally accepted;
- security operations checklist is signed off.

## PRG-005 — Observability and operational SLOs

**Status:** `IN_PROGRESS` — local implementation complete; runtime acceptance
gate pending — 2026-07-29

Scope:

- define availability, latency, error-rate, queue-lag, notification, and SLA
  SLOs;
- create dashboards for API, database, Redis, workers, queues, integrations,
  AI providers, and business transactions;
- configure actionable alerts with severity and owner;
- add structured correlation across request, job, audit, and integration logs;
- verify alert delivery and on-call response.

Exit criteria:

- every critical service has an SLI, SLO, dashboard, and actionable alert;
- synthetic checks cover login and core ticket flow;
- alert tests reach the responsible operator;
- noise and duplicate-alert behavior are acceptable.

## PRG-006 — Performance, resilience, and security acceptance

**Status:** `IN_PROGRESS` — local implementation complete; runtime acceptance
gate pending — 2026-07-29

Scope:

- define realistic user, API, websocket, import, notification, and queue load;
- run baseline, peak, soak, and controlled failure tests;
- verify database pool, worker throughput, Redis recovery, and retry behavior;
- validate tenant isolation under concurrency;
- test rate limits, large payloads, malformed imports, and abuse cases;
- establish capacity limits and scaling triggers.

Exit criteria:

- approved peak load meets latency and error targets;
- no unbounded queue, memory, connection, or storage growth;
- recovery after dependency failure is demonstrated;
- capacity report and scaling runbook exist.

## PRG-007 — CI/CD and release governance

**Status:** `IN_PROGRESS` — implementation complete, accumulated runtime gate pending — 2026-07-29

Scope:

- automated backend tests, frontend typecheck/build, lint, migration graph,
  dependency scan, image scan, and Compose validation;
- immutable versioned images and artifact provenance;
- staging promotion, approval, production deployment, smoke test, and rollback;
- release notes and database-change classification;
- branch protection and required checks.

Exit criteria:

- a release can be built and promoted without manual artifact mutation;
- failed gates block deployment;
- rollback to a known-good image is tested;
- release evidence is auditable.

### M1 release gate

Milestone M1 is complete only when PRG-001 through PRG-007 are complete and a
formal go-live review finds no unresolved blocker.

---

# Milestone M2 — Service Catalog and Request Fulfillment

**Goal:** provide a true service catalog rather than only generic ticket
creation.

**Status:** `COMPLETED_LOCAL` — 2026-07-29

## SC-001 — Catalog data model and lifecycle

**Status:** `COMPLETED_LOCAL` — 2026-07-28

- service categories, services, offerings, and catalog items;
- draft, review, published, retired lifecycle;
- owners, support groups, entitlement rules, and tenant scope;
- versioning and immutable history;
- RBAC and audit.

## SC-002 — Dynamic forms and custom fields

**Status:** `COMPLETED_LOCAL` — 2026-07-29

- typed fields, validation, required/optional rules;
- conditional visibility and dependencies;
- reusable form sections;
- safe schema versioning;
- attachment rules;
- preview and test mode.

## SC-003 — Request fulfillment

**Status:** `COMPLETED_LOCAL` — 2026-07-29

- request, requested item, fulfillment task, approval, and activity history;
- sequential/parallel approvals;
- assignment and escalation;
- cancellation, rejection, rework, and fulfillment evidence;
- atomic status transitions and idempotent automation hooks.

## SC-004 — Self-service catalog portal

**Status:** `COMPLETED_LOCAL` — 2026-07-29

- catalog browse, search, filters, favorites, and recently used items;
- clear service descriptions and expected delivery time;
- request tracking and user-visible timeline;
- mobile and accessibility baseline;
- knowledge deflection before request submission.

## SC-005 — Entitlements, cost, and SLA

**Status:** `COMPLETED_LOCAL` — 2026-07-29

- department, role, location, and tenant entitlements;
- approval policy by cost/risk;
- cost center and chargeback/showback fields;
- catalog-item SLA, OLA, calendar, pause, and escalation;
- fulfillment and demand analytics.

### M2 release gate

- a requester can order at least three representative service types;
- approvals and fulfillment tasks are auditable and tenant-safe;
- form versions do not corrupt existing requests;
- catalog metrics and SLA are visible to operators and managers.

---

# Milestone M3 — Enterprise CMDB and Service Mapping

**Goal:** evolve Asset Inventory into a governed CMDB that supports impact and
service decisions.

**Status:** `IN_PROGRESS` — all listed local stages implementation complete,
runtime gate pending — 2026-07-29

## CMDB-001 — CI class model

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending —
2026-07-29

- configuration item classes and inheritance;
- class-specific typed attributes;
- lifecycle, owner, support group, criticality, and environment;
- controlled custom fields and schema versioning.

## CMDB-002 — Relationships and service model

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending —
2026-07-29

- typed CI relationships with direction and cardinality;
- business services, technical services, applications, infrastructure, and
  locations;
- relationship graph and service topology;
- cycle and invalid-relationship controls.

## CMDB-003 — Source ingestion and reconciliation

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- source registry and import history;
- identification and reconciliation rules;
- duplicate detection and merge workflow;
- source precedence and field ownership;
- SCCM/Intune/Lansweeper/cloud discovery adapters as separate stages.

## CMDB-004 — Impact analysis

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- affected CI/service selection for Incident, Problem, Change, and Release;
- upstream/downstream impact;
- critical service and customer impact;
- change collision and blast-radius calculation;
- cached graph traversal with tenant isolation.

## CMDB-005 — Data quality governance

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- completeness, correctness, freshness, duplicate, and orphan scores;
- accountable data owners;
- remediation queues and aging;
- audit history and certification campaigns.

### M3 release gate

- operators can trace a service to supporting CIs;
- a change shows its likely blast radius;
- imports reconcile deterministically;
- CMDB quality is measured and owned.

---

# Milestone M4 — ITIL Process Depth

**Status:** `IN_PROGRESS` — all listed local stages implementation complete,
runtime gate pending — 2026-07-29

## INC-001 — Major Incident Management

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- major incident declaration and roles;
- commander, communications lead, technical leads, and timeline;
- war-room links and stakeholder communication;
- parent/child incidents;
- service status updates;
- post-incident review and action tracking.

## INC-002 — Event-to-Incident and escalation

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- monitoring event normalization and deduplication;
- correlation and suppression;
- automatic incident creation/update/closure policy;
- on-call routing and escalation;
- alert evidence and noise analytics.

## SLA-002 — Enterprise SLA, OLA, and calendars

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- business calendars, holidays, time zones, and working hours;
- pause/resume and exception reasons;
- response, resolution, fulfillment, OLA, and supplier targets;
- multi-stage escalation and breach forecasting;
- auditable recalculation.

## CHANGE-002 — Change calendar and advanced governance

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- visual change calendar and maintenance windows;
- collision/blackout detection;
- reusable Standard Change models;
- richer CAB agenda and decision evidence;
- implementation tasks, validation, rollback, and PIR;
- change success and failure analytics.

## RELEASE-001 — Release train and deployment governance

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- release records, versions, packages, environments, and dependencies;
- aggregation of approved changes;
- readiness gates and go/no-go;
- deployment evidence and coordinated rollback;
- deployment frequency and change-failure metrics.

## PROBLEM-002 — Advanced RCA and trend management

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- Five Whys, Ishikawa, and structured RCA templates;
- recurring-incident clustering;
- corrective action ownership and effectiveness review;
- proactive trend detection;
- known-error usage and value metrics.

---

# Milestone M5 — Enterprise Integrations and Identity Lifecycle

**Status:** `IN_PROGRESS` — all listed local stages implementation complete,
runtime gate pending — 2026-07-29

## INT-IDENTITY-001 — SCIM / Entra provisioning

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- users, groups, roles, and organization structure synchronization;
- immutable external identifiers;
- joiner/mover/leaver handling;
- safe deactivation and ownership reassignment;
- provisioning audit and retry.

## INT-MAIL-001 — Production email channel

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- inbound email to ticket/request;
- threading, attachments, sender validation, and loop prevention;
- outbound templates, bounce handling, retry, and delivery status;
- Microsoft 365/Exchange integration.

## INT-COLLAB-001 — Teams and collaboration

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- ticket notifications and actionable cards;
- secure links, comments, and approval actions;
- major-incident channel/meeting integration;
- tenant and permission checks.

## INT-MON-001 — Monitoring connectors

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- Prometheus/Alertmanager, Zabbix, Grafana, Sentry, and generic webhook intake;
- signed requests, deduplication, normalization, rate limits, and dead-letter;
- event-to-incident policy and connector health.

## INT-ASSET-001 — Asset discovery

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- Intune, SCCM, Lansweeper, cloud inventory, or agreed priority sources;
- incremental import, reconciliation, stale-device handling, and provenance.

## INT-API-001 — Integration platform controls

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- service accounts and scoped API tokens;
- token rotation and revocation;
- signed outgoing webhooks;
- retry/dead-letter/replay console;
- connector SDK contract and integration observability.

---

# Milestone M6 — Workflow and No-Code Configuration

**Status:** `IN_PROGRESS` — all listed local stages implementation complete,
runtime gate pending — 2026-07-29

## WF-001 — Versioned workflow engine

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- triggers, conditions, actions, timers, branches, and approvals;
- immutable published versions;
- draft validation and simulation;
- idempotency, retries, compensation, and execution history.
- production control-plane API, worker recovery, RBAC, audit, event-chain
  verification, and administration workspace delivered.

## WF-002 — Visual workflow designer

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- accessible node/step editor;
- reusable subflows;
- validation and dry-run;
- diff, approval, publish, rollback, and audit.
- synchronized Visual/JSON modes, server-authoritative structural diff,
  optional four-eyes publication review, and durable version-bound subflows
  delivered.

## CFG-001 — Custom forms and fields platform

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- admin-managed typed fields for approved entities;
- validation, visibility, indexing, search, and reporting rules;
- migration-safe schema evolution;
- tenant-level limits and governance.
- tenant-scoped field sets, immutable schema versions, encrypted sensitive
  values, compatibility/breaking-change controls, record integration, RBAC,
  audit, and visual administration workspace delivered.

## CFG-002 — Configuration packages

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- export/import of catalog, workflow, SLA, notification, and integration
  configuration;
- dependency validation;
- environment promotion;
- versioned deployment evidence.
- signed immutable artifacts, automatic dependency closure, secret-free
  portability, target dry-run/fingerprint, production four-eyes approval,
  transactional apply, and non-destructive rollback delivered.

---

# Milestone M7 — Governed Production AI

**Status:** `IN_PROGRESS` — all listed local stages implementation complete,
runtime gate pending — 2026-07-29

## AI-002 — Permission-aware RAG

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- retrieval from Knowledge, Incident, Problem, Change, and approved CMDB data;
- strict tenant and object-level permission filtering;
- citations and source freshness;
- ingestion lifecycle and deletion propagation.
- tenant ownership, live source/ACL/freshness revalidation, deterministic local
  hybrid retrieval, deletion propagation, prompt-injection refusal, strict
  provider citation allowlists, PII-safe provider payloads, hash-only evidence
  logs, operations dashboard, and Copilot workspace delivered.

## AI-003 — Evaluation and prompt governance

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- versioned prompts and model configuration;
- representative evaluation datasets;
- quality, groundedness, safety, latency, and cost metrics;
- regression gates before model/prompt rollout;
- canary and rollback.
- immutable prompt hashes, provider-backed weighted evaluation, bounded
  regression thresholds, hash-only output evidence, three-actor release,
  deterministic canary routing, runtime governed-prompt selection, and
  rollback control plane delivered.

## AI-004 — Privacy, cost, and residency controls

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- PII redaction and configurable data policy;
- provider/data residency controls;
- usage quotas, budgets, and cost dashboards;
- provider timeout, fallback, and circuit breaker;
- complete AI audit metadata without storing forbidden content.
- explicit provider/region/data-class policies, mandatory privacy preflight,
  governed cost rates, tenant hard budgets, hash-only usage attribution,
  serialized circuit breaker, local fallback, retention purge, and Privacy /
  FinOps control plane delivered.

## AI-005 — Guarded AI actions

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- proposed ticket updates, knowledge drafts, classifications, and runbook
  suggestions;
- human approval for consequential actions;
- tool allowlists and parameter validation;
- prompt-injection and data-exfiltration defenses;
- deterministic audit and rollback where possible.
- fail-closed tenant policy, fixed server schemas/handlers, idempotent
  proposals, canonical hashes, citation minimization, target fingerprint,
  independent HIGH-risk review, domain permission recheck, before/after
  evidence, drift-aware rollback, tests, runbook, and Copilot control plane
  delivered.

---

# Milestone M8 — UX and Administrative Depth

**Status:** `IN_PROGRESS` — all listed local stages implementation complete,
runtime gate pending — 2026-07-29

## UX-001 — Unified Configuration Center

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- task-oriented settings rather than raw key/value rows;
- health/readiness indicators and guided setup;
- validation, test connection, save, rollback, and audit;
- clear separation of tenant and global configuration.
- typed bounded settings, optimistic revisions, captured baseline, immutable
  hash evidence, rollback-as-new-revision, cross-domain readiness, root/tenant
  scope control, encrypted AI provider secrets, production plaintext refusal,
  read-only legacy diagnostics, tests, runbook, and responsive UI delivered.

## UX-002 — Global search and productivity

**Status:** `IN_PROGRESS` — implementation complete, runtime gate pending — 2026-07-29

- permission-aware search across tickets, requests, knowledge, CI, changes,
  problems, and users;
- saved views, bulk actions, keyboard navigation, and operator shortcuts.
- tenant/object filtering, minimized results, bounded search, PostgreSQL
  trigram indexes, hash-only query audit, owned/shared revisioned views,
  global command palette/deep links, and guarded atomic bulk plans delivered.

## UX-003 — Accessibility and responsive portal

**Status:** `IN_PROGRESS` — implementation complete, runtime accessibility gate pending — 2026-07-29

- WCAG 2.2 AA target;
- keyboard and screen-reader operation;
- focus, contrast, errors, and reduced-motion behavior;
- requester mobile flows.

Delivered locally: shared focus containment/restoration for all visual
dialogs, skip/main/route announcements, mobile navigation drawer, semantic
loading/error states, core table names, requester narrow-screen focus/scroll
behavior, touch/reflow safeguards, reduced-motion and forced-colors support,
and a dependency-free accessibility regression gate. WCAG conformance remains
pending browser, axe, assistive-technology, zoom, and multi-role acceptance.

## UX-004 — Branding and localization

**Status:** `IN_PROGRESS` — trilingual UI foundation and first operational
module delivered locally; specialist-module coverage continues — 2026-07-30

- tenant logo, colors, terminology, locale, timezone, and date/number formats;
- localized templates and knowledge content;
- controlled translation lifecycle.

Delivered locally: versioned/audited tenant experience profiles, safe
contrast-checked theme tokens, validated immutable PNG assets, explicit
format locale/IANA timezone/currency/date controls, bounded terminology,
optimistic revisions, integrity history/rollback, authenticated cached
bootstrap, shared formatters, shell/requester/admin integration, and
Configuration Center readiness. Governed notification/knowledge variants now
provide exact-schema drafts, source and payload hashes, optimistic revisions,
four-eyes review, single-published-version enforcement, stale detection,
tenant-safe fallback, runtime rendering, and an evidence-rich admin workspace.
The application now has a persistent `Қазақша / Русский / English` selector,
three-locale backend experience capabilities, a typed shared message catalog,
localized document language and formatting, trilingual login, navigation,
session context, global search, health/error states, all module
titles/subtitles, and complete Major Incident static chrome. Manager-role
browser acceptance proves all three languages and persistence across reload.
Specialist forms/tables in the remaining modules, server-originated validation
messages and business-enum labels, per-locale custom tenant terminology, and
multi-role browser acceptance remain in the active translation queue.

## UX-005 — Embedded administration guidance

**Status:** `IN_PROGRESS` — local implementation complete; runtime acceptance
gate pending — 2026-07-29

- contextual help and setup checklists;
- operational diagnostics;
- safe defaults;
- links to current runbooks and audit evidence.

Delivered locally: a typed, role-aware guide with applicability-aware
checklists, prioritized next actions, safe fallback explanations, exact
remediation routes, permission and owner metadata, runbook/audit references,
and deterministic non-secret evidence hashes. The responsive UI exposes
filters and expandable diagnostics. Optional external stacks no longer create
false failures, while applicable unsafe controls remain explicit. Runtime and
multi-role browser acceptance remain pending.

---

# Milestone M9 — Commercial Multi-Tenant SaaS Controls

**Status:** `DEFERRED`

This milestone begins only after an explicit decision to commercialize the
platform as SaaS.

## SAAS-001 — Tenant lifecycle

- controlled tenant provisioning, suspension, export, archive, and deletion;
- tenant-level keys, quotas, and retention;
- verified isolation and deletion evidence.

## SAAS-002 — Plans, limits, and licensing

- feature entitlements;
- user, storage, API, AI, and integration limits;
- enforcement and usage metering;
- upgrade/downgrade behavior.

## SAAS-003 — Billing and commercial operations

- subscriptions, invoices, taxes, payments, credits, and dunning;
- billing audit and reconciliation;
- administrator and customer billing portals.

## SAAS-004 — Data residency and compliance

- regional placement and backup controls;
- retention and legal hold;
- data export and subject-request procedures;
- compliance evidence packages.

## SAAS-005 — Support and status operations

- tenant-aware support access with approval and audit;
- public status page and incident communication;
- support plans and response commitments.

---

# 5. Common quality gate for every stage

A stage cannot be marked `COMPLETE` unless all applicable items are satisfied.

## Architecture and data

- [ ] Tenant boundary is explicit and tested.
- [ ] State transitions and invariants are enforced on the backend.
- [ ] Migration is additive or has an approved destructive-change plan.
- [ ] Indexes, constraints, pagination, and concurrency behavior are reviewed.
- [ ] Secrets and sensitive data are not returned to the browser or logs.

## Security and governance

- [ ] RBAC permissions are defined and seeded.
- [ ] Sensitive actions have step-up/dual-control where required.
- [ ] Audit records include actor, target, result, timestamp, and context.
- [ ] Abuse, replay, rate-limit, and idempotency behavior are considered.
- [ ] Tenant isolation and negative authorization tests exist.

## Backend

- [ ] Unit and integration tests pass.
- [ ] Error responses use the common API contract.
- [ ] Background work is retry-safe and observable.
- [ ] API pagination and bounded result sizes are used.
- [ ] Ruff/lint checks pass.

## Frontend

- [ ] Loading, empty, error, success, and permission-denied states exist.
- [ ] TypeScript check and production build pass.
- [ ] Forms provide validation and safe confirmation.
- [ ] Responsive and keyboard behavior is checked.
- [ ] Browser acceptance is performed against the live backend.

## Operations

- [ ] Configuration and secrets are documented.
- [ ] Health, metrics, logs, and alerts cover the new capability.
- [ ] Backup/restore impact is understood.
- [ ] Deployment, rollback, and operator runbook are updated.
- [ ] Smoke test covers the critical path.

## Delivery evidence

- [ ] Stage report exists in `docs/reports/`.
- [ ] Execution ledger contains validation results.
- [ ] No unrelated or destructive changes were introduced.
- [ ] Known limitations and follow-up stages are explicit.

# 6. Global release blockers

The platform must not receive production approval while any of these remain:

- active demo credentials or example secrets;
- production running on SQLite;
- runtime DDL enabled in production;
- untested database migrations;
- no successful restore drill;
- privileged accounts without enforced MFA or approved upstream MFA;
- no controlled break-glass access;
- critical/high unresolved security vulnerabilities;
- missing tenant-isolation evidence;
- no actionable monitoring for database, Redis, API, worker, or queues;
- no measured capacity or rollback procedure;
- failing backend tests, frontend build, or production smoke test.

# 7. Open strategic decisions

These decisions must be resolved before their dependent stages. `D-005` is
resolved as local-first execution. External hosting and trusted TLS are
intentionally deferred until the platform is ready to move to a server.

| ID | Decision | Needed before |
|---|---|---|
| D-001 | Internal enterprise platform first or commercial SaaS launch | M9 |
| D-002 | Primary IdP: Entra ID, another OIDC provider, or both | PRG-004 |
| D-003 | Primary email/collaboration stack | M5 |
| D-004 | Priority discovery sources: Intune, SCCM, Lansweeper, cloud | CMDB-003 |
| D-005 | Resolved: local-first Docker Compose; server model and trusted TLS are selected only for final cutover | Final server cutover |
| D-006 | Local engineering targets accepted: RPO 24h, RTO 30m, retention 7 daily/4 weekly/6 monthly; business/SLO approval remains before server cutover | PRG-005/final cutover |
| D-007 | AI data residency and allowed provider policy | M7 |
| D-008 | Billing, legal entity, tax, and supported regions | M9 |

# 8. Immediate next action

Audit the accumulated local M2 through M8 implementation against the common
quality gate and close any remaining code/documentation/contract gaps. M1 now
has a passing reproducible local/static gate; retain database rehearsal, live
scrape/alert/synthetic, baseline/peak/soak, controlled failure, DAST, security
scan, browser, and server acceptance as explicit deferred gates. M9 remains
deferred until an explicit commercial-SaaS decision.

The execution ledger must record:

- SLI/SLO ownership, metric/query definitions, and alert/runbook linkage;
- performance budgets, concurrency/idempotency controls, and threat checks;
- locally executable static/contract evidence without fabricated runtime data;
- exact deferred runtime commands, thresholds, owners, and acceptance outputs;
- deferred runtime gate items without claiming server readiness.
