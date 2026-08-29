# PRG-006 — Performance, resilience, and security acceptance

Status: `IMPLEMENTATION_COMPLETE_RUNTIME_GATE_PENDING`  
Date: 2026-07-29

## Outcome

The repository now contains bounded production capacity controls, layered abuse
protection, reproducible API/WebSocket workloads, guarded dependency-failure
automation, security release gates, and exact acceptance criteria. No runtime
performance, recovery, DAST, or vulnerability result is claimed by this report.

## Implemented controls

- `RequestBodyLimitMiddleware` rejects invalid `Content-Length`, declared
  oversize, and streamed oversize bodies even if Nginx is bypassed.
- Nginx limits client body to 6 MiB, per-IP API rate to 20 requests/second with
  bounded burst, and concurrent connections to 40.
- SQLAlchemy PostgreSQL pool defaults to size 10, overflow 5, 30-second checkout,
  1,800-second recycle, and pre-ping, all validated/configurable.
- Redis is capped with `noeviction`; production services have CPU/memory ceilings
  and common 10 MiB x five-file log rotation.
- `performance/workload-profile.json` defines baseline, peak, and soak load plus
  p95/p99/error/WebSocket thresholds.
- `scripts/run_performance_acceptance.py` executes the read mix, approved
  create/close ticket business flow, and one-time-token WebSockets. Write load
  requires explicit confirmation; output is secrets-safe SHA-256 evidence.
- `scripts/run_resilience_acceptance.py` temporarily stops/restarts Redis and
  PostgreSQL only in explicitly selected local/staging environments. It does not
  remove containers or volumes.
- `security/acceptance-catalog.json` defines 30 owned
  SCA/SAST/image/secret/abuse/isolation/authorization/edge/DAST controls.
- The edge trust chain now uses explicit Host allowlisting, one exact trusted
  TLS gateway, one statically addressed Nginx proxy, sanitized forwarded
  identity, and production configuration validation.
- CI blocks on `pip-audit`, Bandit, production `npm audit`, backend/frontend
  Anchore image scans, and redacted Gitleaks scanning.
- A manually approved `staging-security` workflow runs ZAP only against the
  governed credential-free HTTPS repository variable `STAGING_DAST_URL`.
- Capacity formula, scaling triggers, malformed import, notification/queue,
  idempotency, cross-tenant concurrency, and evidence requirements are documented
  in the PRG-006 runbook.

## Static evidence completed

- Ruff: latest execution blocked by Windows Application Control before linting;
  the release gate records this as a failure pending execution by a trusted
  Ruff binary or CI runner.
- Compileall: pass for backend and scripts.
- TypeScript `--noEmit`: pass.
- Accessibility source audit: pass.
- OpenAPI import: 591 paths.
- Alembic: single head `20260814_0073`.
- Production Compose and bootstrap overlay parsing: pass.
- Workflow YAML parsing: pass.
- Observability contract: seven SLOs, 17 alerts, 17 panels.
- PRG-006 contract: three workload profiles, 30 security controls.
- Edge contract: two trusted hosts, one TLS gateway, and one frontend proxy
  identity.
- Session contract: five lifecycle controls, four self-service routes, and
  refresh-family replay containment.
- Canary evidence contract: simulated production metrics removed, evidence
  mutation root-only, stage decisions fail closed, and backend destinations
  deployment-owned.
- Legacy integration boundary: 23 authorized demo mutation paths, no simulated
  success evidence or webhook side effects, production-only control-plane UI,
  and historical evidence invalidation.
- Automation execution integrity: tenant-scoped rule, ticket, and runbook
  execution; fail-closed conditions; honest simulated/skipped/partial outcomes;
  no mock-email delivery evidence; and historical evidence invalidation.
- Email delivery integrity: production-disabled mock transport, explicit
  simulation without transport IDs/timestamps/success counters, Graph-only
  synchronization, honest dashboard health, and historical evidence
  invalidation.
- Teams delivery integrity: production-disabled mock connector, explicit
  simulation without HTTP/reference/timestamp/success counters, production-only
  Workflow and major-incident routing, honest dashboard health, and historical
  evidence invalidation.
- AI provider evidence integrity: local simulation, missing-credential fallback,
  malformed external responses, connection tests, result APIs, usage ledgers,
  classification and grounded-RAG interfaces preserve requested/effective
  provider evidence without claiming external success.
- Permission-aware UI: custom and multi-role effective permissions drive the
  shared navigation/direct-route registry plus Dashboard queries, metrics, and
  actions; backend authorization remains authoritative.
- Grafana/SLO/workload/security JSON parsing: pass.
- `git diff --check`: pass (line-ending warnings only).
- Tests-as-code:
  - declared and streamed request-body limits;
  - capacity setting bounds;
  - workload/security catalog completeness;
  - layered proxy/application controls;
  - CI/DAST gates;
  - Compose resource/log/Redis memory bounds.

## Deferred runtime commands and acceptance

Performance Engineering:

```powershell
python scripts/run_performance_acceptance.py --profile baseline --base-url https://staging.example.com/api/v1 --email performance-operator@example.com --password-file .\secrets\performance_operator_password
python scripts/run_performance_acceptance.py --profile peak --base-url https://staging.example.com/api/v1 --email performance-operator@example.com --password-file .\secrets\performance_operator_password --confirm-write-load
python scripts/run_performance_acceptance.py --profile soak --base-url https://staging.example.com/api/v1 --email performance-operator@example.com --password-file .\secrets\performance_operator_password --confirm-write-load
```

Platform Operations:

```powershell
python scripts/run_resilience_acceptance.py --environment staging --compose-file .\docker-compose.prod.yml --env-file .\.env.production --readiness-url https://staging.example.com/api/v1/health/readiness --confirm-controlled-failure
```

Application Security:

- run focused/full regression including concurrent cross-tenant suites;
- execute CI SCA/SAST/image/secret jobs;
- dispatch the governed staging DAST workflow;
- require zero unresolved critical/high findings or a signed, expiring risk
  acceptance.

Release acceptance also requires:

- valid and malformed 5,000-row import evidence;
- peak notification, queue, outbox drain, idempotency, and dead-letter evidence;
- WebSocket isolation/reconnection evidence;
- Redis/PostgreSQL/worker/provider failure and recovery timelines;
- stable connection, memory, Redis, and storage graphs after soak;
- approved capacity worksheet and scaling triggers;
- Release Manager sign-off.

## Exit decision

Local implementation: complete.  
Production exit criteria: pending real load, soak, resilience, concurrency,
security-scan, capacity, and signed staging evidence.
