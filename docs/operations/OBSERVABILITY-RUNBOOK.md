# Observability and SLO runbook

## Purpose

This runbook is the operating contract for SBS AI ITSM telemetry, service-level
objectives, alerts, synthetic checks, ownership, and evidence. It deliberately
uses low-cardinality, tenant-aggregated metrics: tenant IDs, user IDs, ticket IDs,
email addresses, prompts, tokens, and secrets must never be Prometheus labels.

The machine-readable SLO source is
`monitoring/slo-catalog.json`. Validate the whole contract with:

```powershell
python scripts/validate_observability_contract.py
```

## Components and access

- Prometheus `3.13.1` scrapes every backend replica every 15 seconds through
  Docker DNS discovery.
- Alertmanager `0.33.1` groups, deduplicates, inhibits, and resolves alerts
  before sending them to the authenticated SBS monitoring webhook.
- Grafana `13.1.0` provisions dashboard UID `sbs-platform-overview`.
- `/api/v1/metrics` requires the bearer token from
  `secrets/metrics_auth_token`.
- Prometheus retains 30 days in `prometheus_data`.
- Alertmanager retains grouping state in `alertmanager_data`; its UI and Grafana
  bind to loopback by default.
- Publish operations interfaces only through an approved TLS reverse proxy or
  private operations network. Anonymous Grafana access and self-registration
  remain disabled.

## SLO contract

| Service | SLI | Objective / window | Primary alert | Owner |
|---|---|---|---|---|
| API | successful requests / all requests | 99.9% / 30d | `SbsBackendTargetDown` | Platform Operations |
| API | HTTP 5xx ratio | at most 1% / 30d | `SbsHighHttpErrorRate` | Application Operations |
| API | HTTP p95 latency | at most 1s / 30d | `SbsHighP95Latency` | Application Operations |
| Jobs | oldest queued job | 99% evaluations at most 300s / 30d | `SbsJobQueueLagHigh` | Platform Operations |
| Delivery | terminal email, Teams, webhook outcomes | at least 99% success / 30d | `SbsRecentDeliveryFailures` | Integration Operations |
| AI | governed provider outcomes | at least 99% success / 30d | `SbsAiProviderErrorRateHigh` | AI Operations |
| SLA engine | targets met before breach | at least 99.5% / 30d | `SbsRecentSlaBreaches` | Service Management |

The production acceptance owner may tighten thresholds after baseline and soak
tests. Loosening an objective requires a reviewed change record, evidence, and
an explicit risk acceptance; editing only an alert expression is not sufficient.

## Metric coverage

The backend exports:

- HTTP count, in-progress requests, and true duration histograms;
- PostgreSQL/Redis readiness and probe duration;
- database pool checked-in, checked-out, overflow, and configured size;
- jobs-worker heartbeat, Redis ready/scheduled/dead-letter depth, persisted queue
  age, and transactional outbox age;
- outbound email, Teams, and webhook delivery state, queue age, and recent
  terminal failures;
- AI provider outcomes, recent latency, and circuit-breaker state;
- current SLA target state and recent breaches;
- core ticket-created and ticket-closed transaction windows;
- WebSocket connections, dashboard event publication, transport readiness, and
  authenticated Alertmanager receipts.

Metrics are process-local where appropriate and aggregated in PromQL across
replicas. Database-derived snapshots are gauges. If a dependency probe fails,
the scrape remains available and reports `sbs_dependency_ready = 0` plus
`sbs_operational_snapshot_success = 0`.

## Dashboard

The provisioned platform overview contains 17 panels covering:

- availability, request rate, 5xx ratio, p95 latency and route p95;
- WebSocket and dashboard-event activity;
- dependency and worker readiness;
- queue depth, queue age, dead letters, and outbox symptoms;
- delivery lag and recent terminal delivery failures;
- AI provider outcomes;
- recent business SLA breaches.

An operations dashboard is evidence, not a substitute for an alert. Every
critical service must have an SLI, an SLO catalog entry, at least one dashboard
panel, an actionable alert, an owner, and a runbook section.

## Correlation

- Inbound requests receive or propagate a bounded `X-Request-ID`.
- JSON application logs emit `correlation_id`.
- job runs and lifecycle events persist `correlation_id`;
- audit, integration request, webhook, AI ledger, and synthetic evidence carry
  either the same correlation value or a one-way correlation hash where raw
  identifiers would expose tenant data.
- Search by correlation before searching by user-controlled free text.
- Never add authorization headers, cookies, credentials, tokens, secrets, prompt
  bodies, notification bodies, or ticket descriptions to logs or metric labels.

## Synthetic login and ticket flow

The one-shot synthetic utility validates login plus ticket-list access in
read-only mode. With an explicit flag it also creates, reads, and closes a
low-priority ticket, leaving an auditable closed synthetic transaction.

Use a dedicated least-privilege monitoring user and a protected password file:

```powershell
python scripts/synthetic_core_flow.py `
  --base-url http://127.0.0.1:8080/api/v1 `
  --email synthetic-monitor@example.invalid `
  --password-file .\secrets\synthetic_monitor_password
```

For an approved business-transaction test:

```powershell
python scripts/synthetic_core_flow.py `
  --base-url http://127.0.0.1:8080/api/v1 `
  --email synthetic-monitor@example.invalid `
  --password-file .\secrets\synthetic_monitor_password `
  --exercise-ticket-lifecycle
```

The utility prints secrets-safe JSON containing per-step HTTP status and latency,
one correlation ID, timestamps, the optional synthetic ticket ID, and a
deterministic evidence SHA-256. Store the output with the release evidence. Never
store the password, access token, or password-file contents.

Recommended cadence is every five minutes for the read-only check and once per
release for the write-path check. Three consecutive failures page Platform
Operations. Automated scheduling and external alert delivery remain a deployment
acceptance gate because they require the destination environment and on-call
receiver.

## Alert delivery test

Before go-live and after any Alertmanager routing change:

1. Run the observability contract validator.
2. Validate Prometheus and Alertmanager configuration with pinned container
   tooling.
3. Inject a controlled test alert with `severity=warning`,
   `owner=platform-operations`, and a unique correlation ID.
4. Confirm Alertmanager grouping produces one notification, not one notification
   per replica.
5. Confirm the responsible receiver acknowledges it within 15 minutes.
6. Resolve the alert and confirm `monitoring.alert.resolved` reaches the audit
   stream.
7. Repeat the same fingerprint during the repeat interval and verify it is
   deduplicated.
8. Attach firing, acknowledgement, resolution, recipient, and correlation
   evidence to the release record. Do not attach webhook credentials.

Critical alerts page immediately. Warning alerts notify the owning operations
queue and page only after their `for` duration. Informational restart alerts are
timeline context and must not page.

## Common commands

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker compose -f docker-compose.prod.yml --env-file .env.production logs --tail 200 prometheus alertmanager grafana backend worker
python scripts/validate_observability_contract.py
```

Validate rules inside the pinned images:

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm --no-deps prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm --no-deps alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
```

## Backend or dependency unavailable

1. Identify whether `up`, `sbs_dependency_ready`, readiness, or all three failed.
2. Check `/api/v1/health/readiness`; do not use deep-health output as a public
   endpoint.
3. For PostgreSQL inspect availability, connection limits, locks, disk, and
   migration state.
4. For Redis inspect persistence, memory policy, authentication, connectivity,
   and Pub/Sub readiness.
5. Stop rollout automation while a required dependency is unavailable.
6. Verify dependency recovery, backend readiness, alert resolution, and the
   original business transaction before closing the incident.

## HTTP error rate

1. Break down 5xx by route and replica.
2. Correlate the first error with application logs and the latest deployment or
   configuration change.
3. Check dependency, pool, worker, and queue signals before restarting anything.
4. If a release introduced the regression, use the governed rollback procedure.
5. Confirm the 5xx ratio remains below 1% for at least 15 minutes after recovery.

## HTTP latency

1. Inspect p95 by route; do not rely on average latency.
2. Compare database pool pressure, dependency probe time, queue lag, and request
   concurrency.
3. Look for a single expensive route, tenant-agnostic background contention, or
   an external provider call on the request path.
4. Apply a bounded mitigation, then verify p95 below one second for 15 minutes.
5. Open a performance problem record when the same route breaches twice in seven
   days.

## Database pool saturation

1. Confirm checked-out connections exceed 80% of configured pool size for ten
   minutes.
2. Check slow queries, idle-in-transaction sessions, locks, and dependency
   latency.
3. Do not increase the pool until PostgreSQL `max_connections`, replica count,
   and connection budget have been recalculated together.
4. Capture before/after pool utilization and p95 latency as evidence.

## Worker or queue lag

1. Confirm worker heartbeat, Redis ready/scheduled/dead-letter depth, persisted
   queued-job age, and outbox age.
2. Check the worker log by job correlation ID and task name.
3. Triage dead-letter items before replay; replay must keep idempotency controls.
4. Never clear Redis queues manually. If a failure is intentionally non-retryable
   or came from an approved acceptance test, use the governed dead-letter
   acknowledgement endpoint with a resolution code and reason; the database
   history remains `dead_letter` and an immutable audit event is written.
5. Confirm ready/scheduled depth stabilizes, oldest age falls below threshold,
   and outbox age returns below two minutes.

## Scheduler unavailable

1. Confirm that the `scheduler` container is running and inspect its structured
   logs for `scheduler_lease_acquisition_failed`, `scheduler_lease_lost`, or a
   failing periodic cycle name.
2. Verify Redis connectivity and inspect `sbs:jobs:scheduler:lease`,
   `sbs:jobs:scheduler:heartbeat`, and `sbs:jobs:scheduler:metadata`. Never edit
   the lease while a scheduler container is healthy.
3. Confirm that the regular `worker` has `JOBS_PERIODIC_CYCLES_ENABLED=false`.
   Queue workers must not duplicate the SLA, integration, workflow, or cleanup
   cycles owned by the scheduler.
4. Restart only the scheduler service. A replacement acquires the expiring
   Redis lease automatically; verify `sbs_scheduler_ready == 1` before closing
   the incident.

## Authentication failure spike

1. Compare password, MFA, and OIDC failure counts in the Security login-events
   view and the `Authentication failures` dashboard panel.
2. Check whether failures are concentrated behind one trusted proxy or tenant,
   without placing email addresses, IPs, or tenant identifiers in Prometheus.
3. Preserve the immutable audit events, apply account/IP controls, and escalate
   to the security owner if the activity is not an expected acceptance test.
4. Confirm the five-minute failure window returns below threshold before
   resolving the alert.

## Attachment scanner error or backlog

1. Keep every `PENDING`, `ERROR`, or `INFECTED` attachment quarantined. Do not
   use manual release unless the approved emergency procedure explicitly
   permits it.
2. Check ClamAV connectivity, signature freshness, scanner timeouts, storage
   permissions, and worker/scheduler logs without downloading suspicious data.
3. Reprocess only after the scanner is healthy. Confirm `ERROR` reaches zero
   and the oldest quarantine age falls below 300 seconds.
4. Preserve hashes, scan findings, reviewer identity, and audit records for any
   infected or manually handled item.

## Delivery failure or lag

1. Select the affected `channel` label: email, Teams, or webhook.
2. Check channel configuration readiness without exposing credentials.
3. Separate retryable provider throttling/outage from permanent validation,
   destination, or policy errors.
4. Requeue only through governed replay endpoints; preserve idempotency keys.
5. Confirm queue age below five minutes and no new terminal failure in two
   consecutive windows.

## AI provider degradation

1. Check provider status, tenant allowlist/region policy, budget, and circuit
   state.
2. Compare `SUCCESS`, `FALLBACK`, `BLOCKED`, and `ERROR`; policy blocks are not
   provider outages.
3. Preserve the safe local fallback and PII-redaction policy.
4. Never paste prompts, credentials, or provider responses into the incident.
5. Restore external calls only after a connection test and circuit recovery.

## SLA breach

1. Identify new breached targets in the SLA operations queue.
2. Confirm the worker and SLA evaluation cycle are current.
3. Distinguish a true service breach from a calendar, pause, ownership, or policy
   configuration defect.
4. Notify Service Management and attach the ticket/SLA audit timeline.
5. Open a problem record for repeated systemic breaches.

## Telemetry collector failure

1. Determine whether only the database or Redis collector failed.
2. Check the corresponding dependency metric and backend log.
3. A successful HTTP scrape with a failed collector is degraded telemetry, not
   proof that the dependency is healthy.
4. Repair collection and verify two consecutive complete scrapes.

## Unexpected process restart

1. Correlate the process start time with Compose events, health-check failures,
   deployment activity, and host resource pressure.
2. Confirm there is no restart loop and no active request/queue regression.
3. Record the reason if the restart was not an approved deployment action.

## Acceptance boundary

Local static acceptance includes application lint/compile, the observability
contract validator, JSON parsing, Compose parsing, and tests-as-code. Production
acceptance additionally requires:

- live Prometheus and Alertmanager config validation;
- metrics scrape and dashboard visual inspection;
- read-only and write-path synthetic evidence;
- controlled alert firing, acknowledgement, deduplication, and resolution;
- at least one baseline/peak/soak performance run before final threshold approval.

Do not mark PRG-005 complete until those environment-dependent artifacts exist.
