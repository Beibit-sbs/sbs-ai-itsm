# Performance, resilience, and security acceptance runbook

## Purpose and safety boundary

This is the acceptance contract for PRG-006. It defines workloads, thresholds,
capacity math, controlled dependency failures, abuse checks, security gates,
owners, and required evidence.

Never run write load or controlled failures against production. The performance
harness is read-only unless `--confirm-write-load` is supplied. The resilience
harness refuses to run without both a `local`/`staging` environment selection and
`--confirm-controlled-failure`; it never deletes containers or volumes.

Validate the local contract first:

```powershell
python scripts/validate_prg006_contract.py
```

## Workload profiles

The machine-readable source is `performance/workload-profile.json`.

| Profile | Duration | HTTP concurrency | WebSockets | Write mix | Error | p95 | p99 |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 3m | 10 | 5 | 2% | <=0.5% | <=750ms | <=1500ms |
| peak | 5m | 50 | 25 | 5% | <=1% | <=1000ms | <=2000ms |
| soak | 60m | 25 | 10 | 2% | <=1% | <=1000ms | <=2000ms |

Read traffic covers ticket queues, global search, notifications, and health.
Approved write traffic creates and closes a low-priority `[LOAD]` ticket through
the governed transition sequence. That path exercises authorization, database
transactions, audit, SLA, notifications, queues, and WebSocket publication.

Use a dedicated performance tenant and least-privilege operator. Credentials are
read from a protected file and never written to evidence:

```powershell
python scripts/run_performance_acceptance.py `
  --profile baseline `
  --base-url https://staging.example.com/api/v1 `
  --email performance-operator@example.com `
  --password-file .\secrets\performance_operator_password
```

Write-path acceptance requires the explicit flag:

```powershell
python scripts/run_performance_acceptance.py `
  --profile peak `
  --base-url https://staging.example.com/api/v1 `
  --email performance-operator@example.com `
  --password-file .\secrets\performance_operator_password `
  --confirm-write-load
```

The JSON result contains effective load, status/operation counts, p50/p95/p99/max,
WebSocket failures, threshold decisions, timestamps, and evidence SHA-256.

## Import, notification, and queue scenarios

Run these after the API peak profile while the same monitoring window is open:

1. Import a valid 5,000-row asset workbook through preview/commit.
2. Submit a malformed workbook with an invalid MIME type, missing columns,
   formula-like text, duplicate identities, and the maximum accepted file size.
3. Trigger 1,000 idempotent notification events split across enabled channels.
4. Queue the approved job mix up to the peak depth in the capacity worksheet.
5. Open the approved WebSocket count and verify tenant-scoped delivery.
6. Repeat one idempotency key concurrently and prove a single durable effect.

Acceptance:

- invalid or oversized inputs fail with 4xx and no partial mutation;
- preview/commit counts and hashes match;
- no cross-tenant row, notification, job, audit, search, or socket event appears;
- outbox/queue age returns below two minutes after load;
- no dead-letter growth remains unresolved;
- memory, open connections, Redis memory, and database storage stabilize after
  the soak observation window.

## Capacity contract

The default SQLAlchemy pool per process is:

- pool size: 10;
- overflow: 5;
- checkout timeout: 30 seconds;
- recycle: 1,800 seconds;
- pre-ping: enabled.

Before scaling, calculate:

```text
maximum application connections =
  (backend processes + worker processes) * (pool_size + max_overflow)

required PostgreSQL capacity =
  maximum application connections + migration/admin reserve + monitoring reserve
```

Keep at least 20% of PostgreSQL `max_connections` outside application pools.
The default one backend plus one worker can burst to 30 connections. Scaling to
four backend processes plus one worker can burst to 75 and therefore requires at
least 100 usable connections after external tools are counted, or a reviewed
smaller pool/PgBouncer design.

Do not increase a pool in isolation. Approve database `max_connections`, memory
per connection, backend/worker replica count, migration reserve, and monitoring
reserve together.

Scaling review triggers:

- API p95 above 800ms or error rate above 0.5% for 15 minutes;
- checked-out database connections above 70% for 15 minutes;
- oldest job/outbox age above 120 seconds for 10 minutes;
- delivery queue age above 180 seconds for 10 minutes;
- worker heartbeat flaps twice in one hour;
- host CPU above 70% or memory above 75% for 15 minutes;
- Redis memory above 70% of its approved limit;
- storage growth exceeds 80% of the forecast or retention cleanup cannot catch up.

## Controlled dependency recovery

The harness verifies fail-closed readiness and bounded recovery for Redis and
PostgreSQL:

```powershell
python scripts/run_resilience_acceptance.py `
  --environment staging `
  --compose-file .\docker-compose.prod.yml `
  --env-file .\.env.production `
  --project-name sbs-itsm-production `
  --readiness-url https://staging.example.com/api/v1/health/readiness `
  --host-header staging.example.com `
  --output .\evidence\resilience.json `
  --confirm-controlled-failure
```

Acceptance:

- readiness changes to 503 within 45 seconds of dependency loss;
- traffic is not advertised ready while the dependency is missing;
- the dependency restarts without data-volume deletion;
- readiness returns to 200 within 120 seconds;
- Redis queues/outbox resume without duplicate durable effects;
- PostgreSQL transactions resume without corruption or stuck pool checkouts;
- alert firing/resolution and recovery timestamps are attached to evidence.

Additional controlled scenarios:

- restart the worker during queued load and verify heartbeat recovery plus
  idempotent continuation;
- make an outbound provider return 429/500/timeout and verify bounded retry,
  backoff, circuit behavior, and dead-letter handling;
- interrupt a client after commit and retry the same idempotency key;
- expire a Redis WebSocket token and prove reconnection requires a fresh one-time
  token;
- run migration rollback/re-upgrade only where the migration classification says
  rollback is supported.

## Abuse and isolation acceptance

Required cases:

- declared and chunked bodies above 6 MiB return 413;
- invalid/negative `Content-Length` returns 400;
- Nginx sustained per-IP API excess returns 429 and respects connection caps;
- login failure threshold returns 429 with `Retry-After`;
- unsupported content types, malformed JSON, invalid Unicode, deep nesting,
  excessive arrays, formula-like spreadsheet cells, and invalid archives fail
  without 5xx or partial writes;
- query pagination and search result caps remain bounded;
- invalid/replayed WebSocket tokens fail closed;
- concurrent users from two tenants cannot read, mutate, search, subscribe to,
  approve, replay, or infer one another's records;
- non-root role administrators cannot add a permission they do not hold,
  assign a pre-existing over-privileged role, or create a user with that role;
- the role editor exposes only permissions delegable by the current non-root
  administrator, while SaaS Root retains the full permission catalog;
- root tenant selection is explicit and audited;
- retries preserve idempotency and optimistic revision conflicts return 409.

Use focused pytest suites plus an authenticated staging DAST scan. DAST must use
non-production data, an approved scan window, and a dedicated account.

## Security release gates

The machine-readable source is `security/acceptance-catalog.json`. CI blocks on:

- Python dependency audit with `pip-audit`;
- frontend production dependency audit with `npm audit`;
- Python SAST with Bandit;
- backend and frontend image scanning with Anchore/Grype;
- redacted Git history/worktree secret scanning with Gitleaks;
- lint, tests, migration graph, clean PostgreSQL migration, Compose, Prometheus,
  Alertmanager, and frontend build gates.

Critical/high findings must be fixed or have a time-bounded risk acceptance signed
by Application Security and the accountable service owner. A risk acceptance
must identify finding, affected artifact/version, exploitability, compensating
control, expiry, owner, and remediation issue. It may not suppress unrelated
future findings.

Authenticated OWASP ZAP or equivalent DAST is a staging release artifact. Store
the report privately because it can expose routes and security posture.

## Evidence and owners

| Artifact | Owner |
|---|---|
| workload profile/result/hash | Performance Engineering |
| PostgreSQL/Redis/worker/queue graphs | Platform Operations |
| pool/capacity worksheet | Database Operations |
| import and idempotency evidence | Application Operations |
| cross-tenant concurrency evidence | Application Security |
| SCA/SAST/image/secret/DAST reports | Application Security |
| controlled failure timeline | Platform Operations |
| final exception/risk decision | Release Manager + accountable owner |

Every artifact must include commit/image digest, environment, UTC timestamps,
effective configuration, dataset description, threshold version, raw output,
result, and owner. Never attach passwords, tokens, cookies, provider credentials,
prompt contents, tenant private data, or full production payloads.

## Exit boundary

Local implementation is complete when the middleware/configuration controls,
contracts, harnesses, validators, CI gates, tests-as-code, and runbook pass static
validation.

PRG-006 remains pending until the target staging environment provides:

- baseline, peak, and soak PASS evidence;
- valid/malformed import and queue/drain evidence;
- WebSocket and cross-tenant concurrent PASS evidence;
- Redis, PostgreSQL, worker, and provider failure/recovery evidence;
- security scan outputs with zero unresolved critical/high findings;
- approved capacity limits and scaling triggers;
- signed Release Manager acceptance.
