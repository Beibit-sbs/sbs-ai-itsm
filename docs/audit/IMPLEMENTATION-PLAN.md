# SBS AI ITSM — implementation plan to Production Ready

План выполняется последовательно. Каждый этап заканчивается тестами, evidence и
обновлением GAP matrix; existing data и API compatibility сохраняются.

## Stage 0 — Safe baseline — COMPLETE

- Git/revision/dirty state captured.
- Live SQLite online snapshot, SHA-256 and isolated restore verified.
- Initial baseline collected 729 scenarios. Current hardened revision collects
  775 scenarios. The last complete isolated regression recorded 723 passed and
  16 expected skips; later milestones are covered by focused contracts and
  runtime acceptance without misreporting a new full-suite result.
- Frontend TypeScript/build/a11y/control audits passed.
- 27/27 local/static release gate passed.
- 25 manager routes browser-smoked.
- Required audit artifacts created.

## Stage 1 — P0 production runtime rehearsal — COMPLETE_LOCAL

Completed on 2026-08-14: isolated environment, 66/2/0 preflight, current image
builds, PostgreSQL/Redis, idempotent migrations through `0081`, backend/worker/frontend,
Prometheus/Alertmanager/Grafana, strict proxy Host handling, authenticated smoke,
tenant role repair, queue/outbox/DLQ and restart exercises, migration roundtrip,
PostgreSQL concurrency/cross-tenant checks and machine-readable runtime
evidence. Public server cutover remains outside the local completion status.

1. Create an isolated rehearsal environment; never reuse or clear current data.
2. Validate `.env.production` only through non-secret status output.
3. Start PostgreSQL, Redis and migration service.
4. Execute `upgrade -> downgrade -> upgrade` where safe; prove one head and row
   preservation. If full downgrade is intentionally unavailable, document the
   forward-fix strategy instead of destructive rollback.
5. Start API, worker, frontend, Prometheus, Alertmanager and Grafana.
6. Verify readiness/deep health, queue/outbox/DLQ, graceful shutdown and restart.
7. Run cross-tenant, idempotency and concurrent approval/update tests on
   PostgreSQL.
8. Produce exact runtime evidence and hashes.

Exit: no unexpected HTTP 500/traceback/proxy error; all required services ready.

## Stage 2 — P0 security and supply chain — COMPLETE_LOCAL

Completed on 2026-08-14: current Python/frontend dependency audits, Bandit,
Git-history and dirty-worktree secret scans, final backend/frontend High/Critical
image scans, four source/image SBOMs, passive OWASP ZAP and 130 focused backend
regressions. No Critical/High finding remains open; ZAP has 0 FAIL and a
documented local-only Medium CSP risk acceptance, attachment fail-closed
security controls and local rate-limit acceptance. Real privileged MFA user
enrollment, public TLS active scan and independent penetration testing remain
server/external gates.

- Run current dependency audit, Ruff/Bandit or equivalent SAST, secret scan,
  image scan and DAST against the rehearsal contour.
- Generate SBOM for backend, frontend and container images.
- Close Critical/High findings or record explicit risk acceptance.
- Verify production demo-account gate, MFA enforcement, break-glass process,
  session revocation and privileged audit.
- Complete ClamAV/quarantine/size/type/hash acceptance for attachments.
- Add tenant/API-key/global rate limits where load evidence shows gaps.

Exit: no Critical and no unaccepted High; scanner outputs and SHA-256 saved.

## Stage 3 — Observability, backup and DR — COMPLETE_LOCAL

- Live Prometheus scrape for API/DB/Redis/worker/queues/outbox/DLQ.
- Deliver test alerts through real configured receivers; otherwise mark
  `BLOCKED_EXTERNAL`.
- Execute encrypted PostgreSQL backup and isolated restore; compare row counts,
  migrations, attachments and audit chain.
- Measure RPO/RTO and run controlled API/worker/Redis/PostgreSQL failure drills.
- Finalize SLO owners, alert-to-runbook links, DRP and BCP.

## Stage 4 — Performance and resilience — COMPLETE_LOCAL

- Execute baseline, peak and soak profiles from `performance/`.
- Record host characteristics, RPS, concurrency, p50/p95/p99 and error rate.
- Test ticket updates, approvals, change windows, reconciliation, webhooks,
  notifications, outbox and guarded AI actions under concurrency.
- Fix bottlenecks and publish capacity recommendations.

## Stage 5 — Service Desk enterprise depth

Implement in this order:

1. participants/watchers and notification preferences — **COMPLETE_LOCAL**;
2. audited on-behalf registration — **COMPLETE_LOCAL**;
3. duplicate detection plus governed merge/split — **COMPLETE_LOCAL**;
4. versioned macros, templates and canned responses;
5. shifts, on-call, absence and delegation;
6. complete CSAT survey/analytics;
7. scheduled reports and controlled exports.

Each feature requires tenant isolation, permissions, audit, idempotency,
pagination, RU/KK/EN and browser tests.

Completed locally for item 1: migration `0079`, governed internal/external
participants, self-subscription, participant roles, event scopes, in-app/email
preferences, optimistic locking, soft removal with reason, ticket history,
tamper-evident audit, private internal-comment fan-out, recipient-scoped
Notification Center and requester browser smoke in RU/KK/EN. Focused backend
and cross-contract acceptance: 26 passed, 0 failed.

Completed locally for item 2: migration `0080`, explicit
`tickets.create.on_behalf` permission, active tenant requester directory,
requester anti-impersonation checks, mandatory reason, immutable creator and
requester snapshots, saved contact and registration channel, ticket history,
tamper-evident audit and RU/KK/EN operator controls. The PostgreSQL rehearsal is
on `0080`; three backend replicas and frontend are healthy. Seventy-three
focused test executions passed after compatibility fixtures were upgraded. The
769-test monolithic run reached its 20-minute process timeout without a reported
failure and is not recorded as a full PASS; stable four-shard CI remains an
explicit quality-platform action.

Completed locally for item 3: migration `0081`, explainable duplicate scoring,
tenant- and visibility-scoped candidate search, governed false-positive
dismissal, non-destructive merge and child-ticket split. Every write requires
an explicit RBAC permission, business reason, optimistic governance versions
and idempotency key; immutable action evidence, ticket history and the
tamper-evident audit chain retain the decision. Source comments and history are
never moved or deleted during merge. RU/KK/EN UI, TypeScript, Docker build,
accessibility/control audits, 33-ticket regression, route-authentication
contract and PostgreSQL runtime acceptance pass. Rehearsal head is
`20260829_0081`; three backend replicas and frontend are healthy.

## Stage 6 — Asset/CMDB and SAM — IN PROGRESS

- Run real discovery/import source through preview/reconciliation.
- Complete business/technical service mapping acceptance.
- Completed locally: Software Asset Management as a separate tenant-scoped
  domain with products, licenses, installations, contract references,
  expiration/renewals, prohibited software, reconciliation, compliance
  positions and cost-at-risk; migration `0078`, API, RBAC, audit, RU/KK/EN UI
  and focused tests pass.
- Remaining: ingest installations from a real discovery provider, bulk import
  preview/commit and end-to-end renewal notifications.

## Stage 7 — AI and integrations

- Expand AI eval datasets, hallucination/permission leakage/prompt-injection
  checks, cost/residency budgets and guarded-action acceptance.
- Run real OpenAI or Gemini connection only after credentials are supplied.
- Complete Graph email, Teams, Entra/SCIM, monitoring and discovery acceptance;
  keep status `BLOCKED_EXTERNAL` until provider-confirmed evidence exists.

## Stage 8 — Localization, accessibility and golden E2E

- Add automated RU/KK/EN key and visible-string parity gate.
- Produce list for human Russian/Kazakh/English review.
- Remove or justify non-semantic clickable elements; run axe, keyboard, focus,
  screen reader, 200–400% zoom and mobile acceptance.
- Automate E2E-01 through E2E-10 on a disposable tenant with no writes to
  existing tenants.

## Stage 9 — SaaS/commercial controls — DEFERRED DECISION

Start only after the owner decides internal platform vs commercial SaaS.
Then implement tenant lifecycle, quotas, metering, plans, suspension/export/
deletion, white-label/custom domain and generic import framework. Payment
integration is not added without business/legal requirements.

## Final acceptance

The status `PRODUCTION READY` is allowed only when all 35 gates from the task
have numeric or machine-readable evidence. Missing external credentials are
reported per provider as `BLOCKED_EXTERNAL`; they are never replaced with mock
success.
