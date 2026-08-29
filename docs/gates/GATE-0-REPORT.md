# SBS AI ITSM — GATE 0 Report

**Gate:** Lifecycle Integrity, I18N and Release Baseline  
**Started:** 2026-08-29, Asia/Qyzylorda  
**Evidence updated:** 2026-08-30, Asia/Qyzylorda  
**Status:** `PASS` — `REL-001` is closed by the authorized local release source commit `abbced1e02d5be5f4394d96847feceaa9157f56b`. Code, database, regression, final RU/KK/EN browser acceptance, runtime and clean source-provenance checks passed. No push was requested or performed. `I18N-003` and `REL-002` are also closed.

This report separates verified Gate 0 facts from later production-release actions. It is not a claim that the complete product is production-ready: Gate 1+ acceptance, integrations, representative data, external security testing and server deployment remain in the audited backlog.

## Baseline

| Evidence | Start value |
|---|---|
| Absolute project path | `C:\projects\sbs-ai-itsm-foundation-001` |
| Branch | `main` |
| Start HEAD | `0b04ada23744349f565b44d60d52182da7f6da38` |
| Origin | `https://github.com/Beibit-sbs/sbs-ai-itsm.git` |
| Upstream divergence | local branch ahead of `origin/main` by 101 commits, behind by 0 |
| Tracked modified | 151 files |
| Untracked | 12,128 filesystem files; 621 collapsed status entries before Gate implementation |
| Staged | 0 files |
| Stash | 0 entries |
| Migration revision | `20260829_0081 (head)` |
| Database connectivity | PASS; PostgreSQL accepted connections on the compose network |
| Backend collection | PASS; 891 tests in 88 files |
| Frontend typecheck | PASS (`tsc -b`) |
| Frontend host production build | PASS; `tsc -b` and a permitted direct Vite host build completed, transforming 152 modules. The first restricted-sandbox attempt hit `spawn EPERM`; this was an execution-sandbox limitation, not a product build failure |
| Runtime | frontend healthy; three backend replicas healthy; PostgreSQL and Redis healthy; worker and scheduler running; Prometheus, Alertmanager and Grafana running |

### Baseline safety record

The worktree materially predates Gate 0 and contains user-owned product work. No `reset`, `clean`, checkout/revert of user changes, database drop/truncate, recursive deletion or destructive migration was performed. The rehearsal database was not replaced. Gate 0 added representative QA records and accounts through normal application/provisioning paths; those records were closed or cancelled instead of being deleted.

## Implemented

- Added the authoritative backend Ticket lifecycle contract in `backend/app/services/ticket_lifecycle.py`.
- Routed REST transition, patch, assignment and bulk behavior plus workflow, automation and event-operation status changes through the same lifecycle service.
- Removed acceptance of Ticket states `OPEN`, `PENDING` and `WAITING`; retained only the documented historical `TRIAGED` to `TRIAGE` compatibility alias.
- Added database row locking, governance-version/state conflict checks and deterministic idempotency evidence.
- Centralized lifecycle history, audit, semantic timestamps, SLA synchronization and transition notification creation.
- Exposed backend-authoritative `allowed_transitions` in Ticket responses; the UI does not maintain an independent business transition matrix.
- Added a complete 10-by-10 transition matrix and positive, negative, authorization, tenant-boundary, concurrency and idempotency regression coverage.
- Added strict RU/KK/EN catalog parity, placeholder and visible-literal auditing, including CI/local release-gate enforcement.
- Localized the shared shell and production pages/components, including admin, operational, monitoring and AI surfaces.
- Made UI-owned localized form defaults locale-reactive without translating user/server data; user and external values remain verbatim.
- Made Ticket history localization exhaustive for all 27 current event types and added an AST contract across eight event-producer files.
- Added `scripts/runtime_ticket_lifecycle_acceptance.py` for repeatable live invalid-transition, idempotency, concurrency and history acceptance.
- Extended the local release gate to 28 deterministic code/config/static checks and generated source-bound hashed evidence.
- Classified the complete 705-path release delta, tightened `.gitignore` for confirmed generated/runtime artifacts and scanned the committed source for secrets and operational data.

## Lifecycle Evidence

### Authoritative contract

Canonical persisted values are:

```text
NEW
TRIAGE
ASSIGNED
IN_PROGRESS
WAITING_USER
WAITING_VENDOR
RESOLVED
CLOSED
REOPENED
CANCELLED
```

The authoritative matrix is:

| From | Allowed targets |
|---|---|
| `NEW` | `TRIAGE`, `ASSIGNED`, `CANCELLED` |
| `TRIAGE` | `ASSIGNED`, `WAITING_USER`, `CANCELLED` |
| `ASSIGNED` | `IN_PROGRESS`, `WAITING_USER`, `WAITING_VENDOR` |
| `IN_PROGRESS` | `RESOLVED`, `WAITING_USER`, `WAITING_VENDOR` |
| `WAITING_USER` | `IN_PROGRESS`, `CANCELLED` |
| `WAITING_VENDOR` | `IN_PROGRESS` |
| `RESOLVED` | `CLOSED`, `REOPENED` |
| `CLOSED` | `REOPENED` |
| `REOPENED` | `TRIAGE`, `ASSIGNED` |
| `CANCELLED` | none |

`CANCELLED` is graph-terminal. `CLOSED` is a closure state with the explicit governed `CLOSED -> REOPENED` edge.

### Mutation-path inventory

- The final direct-mutation scan found one business assignment, `ticket.status = target`, and it is inside the lifecycle service after all validation and locking. Other matches are comparisons, model declarations or test fixtures.
- Ticket API routes, workflow execution, automation and bulk status operations call the service rather than assigning a status independently.
- Bulk processing returns explicit per-item results; failed transitions cannot become silent partial corruption.
- The single-Ticket action UI presents only the `allowed_transitions` supplied by the backend response. Bulk UI offers canonical target states, but first executes the backend preview and returns explicit per-item eligibility/results; it does not define or bypass transition rules.

### Atomicity, authorization and side effects

- The service locks and refreshes the Ticket row with `SELECT ... FOR UPDATE`, validates the canonical current and target states, and checks `expected_version` and optional `expected_status` before mutation.
- Actor policy covers requester ownership, assigned-agent ownership and cross-tenant denial. Requester close requires satisfaction evidence; requester reopen requires a reason.
- A successful transition increments `governance_version`, writes one status-history record and records actor, timestamp, old/new value and reason. Source and version are included in the audit metadata.
- `resolved_at`, `closed_at` and `reopened_at` are updated only by their corresponding lifecycle events; reopening clears obsolete resolution/closure timestamps. Cancellation does not reuse `closed_at`.
- SLA state is synchronized through the existing enterprise SLA service with the prior status supplied. The legacy calculated SLA status is used only when no enterprise SLA instance applies.
- Notification creation is part of the same database transaction and produces notification history evidence. Runtime checks found the outbox 12/12 published with no pending, failed or locked work, and both consumers had no pending or failed deliveries after acceptance.
- Existing domain/event consumers remain the publication mechanism; no independent workflow or API side-effect implementation remains.

### Concurrency and idempotency

- Concurrent writes use a row lock plus governance-version conflict detection. Live acceptance raced `IN_PROGRESS -> RESOLVED` against `IN_PROGRESS -> WAITING_USER`; responses were `[200, 409]`, so one operation won and the stale operation was rejected.
- An idempotency key generates a deterministic UUIDv5 status-history identifier. Replay of the same key and target returns `already_applied` without a second status/history/audit/SLA/notification business effect. Reuse for a different target is rejected as an idempotency conflict.
- The live acceptance Ticket `SD-3408` ended `CLOSED`; the winning race state was `WAITING_USER`. Its canonical history contained exactly one record for each applied edge.

### API and browser evidence

- REST responses include `governance_version` and backend-authoritative `allowed_transitions`.
- Every frontend transition sends `expected_version` and a unique idempotency key; on conflict it refreshes the Ticket instead of overwriting another actor.
- API acceptance returned `401` for anonymous mutation and rejected invalid `NEW -> CLOSED` with a governed `400` response.
- In the earlier runtime race browser check, the closed Ticket showed only `REOPENED` as the available next state. History showed `NEW -> TRIAGE -> ASSIGNED -> IN_PROGRESS -> WAITING_USER -> IN_PROGRESS -> RESOLVED -> CLOSED`, version 8, with one entry per edge.
- Final browser acceptance covered seven critical routes in each of RU, KK and EN without alert; each EN route contained zero Cyrillic UI strings. `SD-3409` passed create/native required validation, exposed only `TRIAGE`, `ASSIGNED`, `CANCELLED` while `NEW`, transitioned `NEW -> CANCELLED`, then correctly showed no status dropdown in the terminal state. Its final history rendered correctly in RU/EN/KK. A user-authored RU QA comment remained verbatim in EN/KK by design; no system mixed-language UI was found.

## I18N Evidence

### Static inventory and parity

`frontend/scripts/i18n-audit.mjs` is wired as `pnpm run check:i18n` and into the local/CI release gate. The recorded run passed with:

| Metric | Result |
|---|---:|
| Catalog messages | 1,020 |
| Explicit aliases | 183 |
| Direct source messages | 2,693 |
| English source messages | 1,358 |
| Literal key usages | 506 |
| Literal translation calls | 335 |
| File-local producers / JSX expressions checked | 93 / 5,171 |
| Visible candidates | 4,562 |
| Visible candidates mapped | 4,562 |
| Allowlisted occurrences | 194 (`2` non-UI, `38` proper nouns, `154` technical identifiers) |
| Unresolved Cyrillic/mixed candidates | 0 of 3,145 |
| Unresolved Latin candidates | 0 of 1,417 |
| Critical/other violations | 0 / 0 |

RU, KK and EN catalogs have structural parity. Placeholder/interpolation parity passed. The allowlist is exact and usage-checked rather than a broad suppression list. Canonical Ticket values remain machine values in the database and are translated only in the presentation layer.

### UI checks

- TypeScript build check passed.
- Accessibility static audit passed across 87 source files and 16 dialogs with zero issues.
- Interactive-control audit passed for 681 buttons and 39 links.
- Browser review passed on seven critical routes in RU, KK and EN with no alert; every EN route contained zero Cyrillic UI strings.
- `SD-3409` passed create/native validation, authoritative NEW actions, `NEW -> CANCELLED`, terminal controls and final localized RU/EN/KK history. User/external values are deliberately rendered verbatim.
- The history renderer covers all 27 current event types, while a deterministic AST validator checks eight producer files against that renderer contract. `I18N-003` is `CLOSED`.

## Repository Evidence

### Release source classification

The authorized local release source commit `abbced1e02d5be5f4394d96847feceaa9157f56b` records exactly 705 parent-to-release paths: 548 added, 155 modified and two deleted generated index artifacts.

| Class | Paths | Disposition |
|---|---:|---|
| A — product/release source | 383 | committed |
| B — migrations | 68 | committed; graph and fresh upgrade verified |
| C — backend tests | 88 | committed |
| D — documentation | 164 | committed |
| E — generated tracked artifacts | 2 | deleted from the Git index; retained locally and ignored as `*.tsbuildinfo` |
| **Total** | **705** | exact committed release-source delta |

The only Git deletions are `frontend/tsconfig.app.tsbuildinfo` and `frontend/tsconfig.node.tsbuildinfo`; both remain local ignored build artifacts. The committed manifest SHA-256 is `16246fb733d01eae10b37f0df39ca163c3225a2b0dc108a95b936c6f1856c3f4`, and the ordered path-list SHA-256 is `e0361c013cde6d68a4c9ec633b334ee22ba1d38b83226d8df7f80ad1062bae07`.

`.gitignore` covers confirmed `.pytest-tmp-*`, `.ruff_cache`, `.pnpm-store`, `release/evidence`, `*.tsbuildinfo` and local runtime/secret paths. `secrets.example` remains explicitly includable. Ignored local stores and operational/test artifacts were not deleted.

### Secret and source-integrity checks

- Final pattern and classification scans covered all 705 paths and found no runtime, secret or operational data in the commit.
- Credential-like findings are deliberately fake fixtures confined to tests; no review-required production credential was found.
- No candidate AWS, GitHub, Slack, Stripe or JWT high-confidence live token was found.
- Local Gitleaks is not installed; the CI pipeline includes Gitleaks. This local-tool parity gap remains P2 and is not described as a local Gitleaks PASS.
- The clean-HEAD `diff-check` passed in the local release gate. Independently, the parent-to-release `git diff --check` reports 121 formatting findings restricted to Markdown (113) and versioned audit JSON (8), with zero production-source findings; this is P2 documentation/evidence hygiene rather than a Gate 0 blocker.

### Commit state

| Evidence | Current value |
|---|---|
| Start HEAD | `0b04ada23744349f565b44d60d52182da7f6da38` |
| Release source SHA | `abbced1e02d5be5f4394d96847feceaa9157f56b` |
| Release source parent | `0b04ada23744349f565b44d60d52182da7f6da38` |
| Release source tree | `9d59a2c55027fc2d5d4de20e7a1667d0d9991b8d` |
| Branch | `main` |
| Release delta | 705 paths = 383 product/release + 68 migrations + 88 backend tests + 164 documentation + 2 generated index removals |
| Push | not requested; not performed |
| Final documentation/mode closure HEAD | recorded after commit in ignored local evidence and the handoff; deliberately not embedded in its own commit |

The release source SHA above is immutable and is the product/release provenance anchor. The closure commit updates these documents and restores mode `100755` on `scripts/backup-data.sh`, `scripts/backup-db.sh`, `scripts/check-production-env.sh` and `scripts/restore-db.sh`; their contents are unchanged. Its resulting HEAD and final ignored-evidence hash are written only after that commit and reported in the handoff, avoiding a self-referential SHA claim.

## Database Evidence

- Migration graph: 81 revisions, one base, one head, no branch or merge ambiguity.
- Head/current revision: `20260829_0081`.
- A separate disposable PostgreSQL 17 instance upgraded from an empty database to head successfully and produced 216 tables.
- The temporary clean-migration container/database was removed after validation; the rehearsal database was not dropped, truncated or reset.
- Production compose migration service exited `0`, and the live database reported `20260829_0081 (head)` after stack recreation.
- Final rehearsal counts: 2 tenants, 7 users, 2,459 tickets and 22,799 audit-log events.
- No blind legacy-status data migration was introduced. The compatibility layer recognizes only the actually supported historical `TRIAGED` alias; invalid Ticket states are rejected.

## Tests

### Backend full regression

The complete backend regression on release source `abbced1e02d5be5f4394d96847feceaa9157f56b` completed with:

```text
collected: 891
passed:    875
failed:    0
skipped:   16
warnings:  48
duration:  1561.28 s
```

The 16 documented skips are legacy contract suites:

- 7 in `test_policy_approval_stage_026.py` — the Stage 026 endpoint/model contract has evolved;
- 9 in `test_policy_enforcement_stage_027.py` — the Stage 027 rollout API/fixtures have evolved.

Those skips are P2 test-debt items; they are not counted as PASS coverage.

Lifecycle-specific coverage includes the full 100-pair state matrix, invalid/null/unknown values, forbidden transitions, requester/agent/tenant policies, version conflict, stale identity refresh under lock, idempotent replay/conflict, workflow integration, automation integration and REST behavior.

### Frontend and static validation

| Check | Result |
|---|---|
| Clean package install in production Docker build | PASS |
| TypeScript `tsc -b` | PASS |
| Production Vite build in Docker | PASS; 152 modules |
| Ruff (`backend/app`, `backend/tests`, `scripts`) | PASS |
| Python `compileall` | PASS |
| I18N audit | PASS |
| Accessibility audit | PASS |
| Interactive-controls audit | PASS |
| Local release gate | PASS, 28/28 checks; clean source provenance |
| Frontend lint | `NOT AVAILABLE`; ESLint is a dependency, but no lint script/config exists |
| Frontend unit/component/E2E runner | `NOT AVAILABLE` |
| Final post-correction browser acceptance | PASS; seven routes × RU/KK/EN plus `SD-3409` lifecycle/history |

The clean post-source verification run reports 28/28 checks passing, release/source SHA `abbced1e02d5be5f4394d96847feceaa9157f56b` and all four image digests below; its internal evidence SHA-256 is `e0f788ade60439e75a6ff277d3d7c9e82762446f10457cd9662475806ccc13bd`. After the closure commit, `release/evidence/gate0-local.json` is regenerated to record both that immutable release source and the final clean closure HEAD; the resulting final evidence hash is reported in the handoff rather than self-referenced here.

Additional recorded validators include 621 OpenAPI paths, 746 API endpoints with 739 protected and seven governed public endpoints, eight SLOs, 21 alerts, 20 dashboards/panels, 24 composite operational surfaces and 171 query sources.

### Security regression

- Anonymous transition: denied (`401`).
- Invalid direct transition: denied.
- Assigned-agent/requester ownership policy: covered.
- Cross-tenant lifecycle actor: denied.
- Version conflict/race: one winner, one `409`.
- Workflow, automation, patch, assignment and bulk bypass paths: routed through lifecycle service and covered by contract tests/static scans.
- Release-source secret scan: no high-confidence production secret found.

## Runtime

### Production compose rehearsal

The release-source production images built successfully after the localization corrections:

| Component | Version/image evidence |
|---|---|
| Backend | package `0.1.0`; `sha256:b4e533c94c9e9e27336c828e9abf65d20b6a88afc46582c8fd003910cbe81940` |
| Frontend | package `0.1.0`; `sha256:4f80d483ec1c01a8e86d65e995991c8b8853c20aa9f35b0097e2d05e3f1d2215`; 152 modules |
| Worker | `sha256:e6f703821321e03e8cc5ad4739d1efcd65d12a72ad669c09f980e69195d228c6` |
| Scheduler | `sha256:9780caf27e531b856bd85db97791339598f7b780576edcc40655eee7bfe100fc` |
| Migration | `20260829_0081` |

These four image digests are recorded in the clean local evidence and bound to the immutable release source SHA.

`docker compose` recreated the migration service, three backend replicas, worker, scheduler and frontend. Health/readiness passed for frontend, backend, PostgreSQL 17 and Redis 8; worker and scheduler remained running. Prometheus, Grafana and Alertmanager were available.

`scripts/smoke-production.py` passed all eight checks: liveness, readiness (database, Redis, migrations and runtime), frontend delivery, anonymous API rejection, authenticated metrics, Grafana, Alertmanager and login/me/logout.

All containers were healthy/running, and the migration service exited `0`. A final review of 3,087 runtime log lines found zero errors and zero HTTP 5xx responses.

### Queue/outbox integrity

Post-acceptance diagnostics reported:

```text
outbox: total=12, published=12, pending=0, failures=0, locked=0
notification consumer: delivered=69, pending=0, failed=0
automation consumer:   delivered=69, pending=0, failed=0
deliveries: total=138, delivered=138, pending=0, failed=0
```

Each consumer contained 69 delivered records (138 across both consumers), with no pending or failed work.

### Representative data

- `SD-3408` is the labelled Gate 0 lifecycle race ticket; it ended `CLOSED` after the complete canonical scenario.
- An earlier interrupted QA Ticket `SD-3407` was safely transitioned from `NEW` to `CANCELLED` instead of being deleted.
- `SD-3409` is the final browser-acceptance Ticket; it passed native required validation, exposed only the three legal NEW transitions, ended `CANCELLED`, and retained localized RU/EN/KK history with user-authored content verbatim.
- `gate0.manager@rehearsal.local` was provisioned through the standard local smoke-user operation and used as an organization administrator for diagnostics/browser acceptance. Its secret remains in the ignored local secret store and is not included in this report or release source.

## Open Defects and Follow-up

### P0

None confirmed in Gate 0 scope.

### P1 — Gate 0

None. Independent audit found no open Gate 0 P0/P1 after `REL-001` closed on the authorized local source commit; no push was performed.

### P1 — Gate 1+ / external readiness

The existing audited backlog still requires all-role acceptance, representative service/CMDB/KB/SLA data, tenant-isolation acceptance across every surface, production identity and communication integrations, and external security testing. These items prevent a general production launch but are outside Gate 0 implementation scope.

### P2

- No frontend unit/component/E2E runner.
- No configured frontend lint script/rules; lint status is `NOT AVAILABLE`.
- The main frontend JavaScript chunk is 1,050.48 kB (289.17 kB gzip), above the 500 kB warning threshold; route/vendor splitting is required. The Tickets chunk is 97.38 kB (20.97 kB gzip).
- Sixteen legacy Stage 026/027 tests are skipped and need migration or retirement.
- Local Gitleaks is unavailable even though CI runs it.
- The standard non-interactive package-manager path still needs a pinned, documented clean-install workflow; the permitted direct Windows host build itself passes.
- Parent-to-release formatting hygiene has 121 findings confined to Markdown (113) and versioned audit JSON (8); production-source findings are zero and the clean-HEAD gate passes.

### P3

- Large backend route and frontend page modules remain maintainability work.
- Manual keyboard/screen-reader/responsive role acceptance remains after the static accessibility checks.
- Generated client/types and documentation freshness enforcement remain planned.

## Final Verdict

```text
GATE 0 = PASS
```

The lifecycle, localization/static/browser, database, backend regression, production-runtime and clean source-provenance evidence pass. `REL-001`, `REL-002` and `I18N-003` are closed on immutable release source `abbced1e02d5be5f4394d96847feceaa9157f56b`.

**Decision: Gate 1 = YES — next authorized gate, NOT STARTED.** Overall production rollout remains `NO-GO`: Gate 1 representative acceptance and the later domain, integration, security, scale and server-cutover gates remain mandatory.
