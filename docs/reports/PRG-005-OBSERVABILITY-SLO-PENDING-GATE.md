# PRG-005 — Observability and operational SLOs

Status: `IMPLEMENTATION_COMPLETE_RUNTIME_GATE_PENDING`  
Date: 2026-07-29

## Outcome

The local implementation now defines and exposes production-shaped telemetry for
the API, PostgreSQL, Redis, database pool, background worker, queues/outbox,
notifications and integrations, AI providers, business SLA, and core ticket
transactions. SLOs, alerts, dashboard panels, ownership, remediation, correlation,
and synthetic evidence are linked by an executable static contract.

This report does not claim live monitoring acceptance. The current environment
cannot supply Docker/runtime, alert destination, browser, or on-call evidence.

## Implemented controls

- HTTP duration is a cumulative Prometheus histogram with p95 recording rules.
- Operational collection is bounded and low-cardinality; it does not label
  tenant, user, ticket, email, prompt, correlation, credential, or token data.
- Dependency collection fails observable: the scrape remains available and
  reports collector/dependency failure rather than returning a false healthy
  snapshot.
- Worker heartbeat uses a TTL in Redis and exposes current readiness/age.
- Queue metrics distinguish ready, scheduled, dead-letter, persisted queued age,
  and unpublished transactional outbox age.
- Delivery metrics cover email, Teams, webhook status, oldest queue age, and
  recent terminal failure windows.
- AI metrics cover governed provider outcome, recent latency, and circuit state
  without exposing prompt contents.
- SLA metrics expose target state and recent breaches; ticket-created/closed
  windows provide core business-transaction evidence.
- `monitoring/slo-catalog.json` defines seven SLO contracts with owner, query,
  objective/window, alert, dashboard, and runbook.
- Prometheus contains three recording rules and 17 alerts. Every alert carries
  severity, owner, service, SLO, and runbook annotations.
- Grafana dashboard `sbs-platform-overview` contains 17 platform, queue,
  integration, AI, and business panels.
- `scripts/synthetic_core_flow.py` supports read-only login/list validation and
  an explicitly enabled create/read/close ticket lifecycle. Output is
  secrets-safe, correlated JSON with deterministic SHA-256 evidence.
- Alertmanager groups by alert/severity and inhibits warnings for the same
  service while a critical alert is active.

## Static evidence completed

- `python scripts/validate_observability_contract.py`
  - expected: seven SLOs, 17 alerts, 17 dashboard panels;
- Ruff for changed backend/tests/scripts;
- JSON parsing for SLO catalog and Grafana dashboard;
- tests-as-code in `test_health.py` and
  `test_observability_contract.py`;
- complete operations runbook with per-alert triage and acceptance boundary.

## Deferred runtime acceptance

Run in the target environment and attach raw, timestamped evidence:

1. `docker compose -f docker-compose.prod.yml --env-file .env.production config`
2. Prometheus `promtool check config /etc/prometheus/prometheus.yml`
3. Alertmanager `amtool check-config /etc/alertmanager/alertmanager.yml`
4. authenticated `/api/v1/metrics` scrape with all collectors successful;
5. Grafana dashboard visual inspection across a six-hour signal window;
6. read-only synthetic login/list check;
7. write-path synthetic ticket lifecycle check;
8. controlled warning and critical alert firing;
9. responsible operator receipt and acknowledgement within 15 minutes;
10. duplicate fingerprint suppression and resolved-event audit evidence;
11. noise review after a representative soak window.

Owners:

- Platform Operations: topology, Prometheus, Alertmanager, Grafana, Redis,
  worker, queue, synthetic scheduling;
- Application Operations: API error/latency and job failure triage;
- Database Operations: PostgreSQL and pool capacity;
- Integration Operations: email, Teams, webhook delivery;
- AI Operations: provider/circuit degradation;
- Service Management: business SLA breach response;
- Release Manager: evidence completeness and final gate decision.

## Exit decision

Local implementation: complete.  
Production exit criteria: pending live runtime, recipient, synthetic, dashboard,
noise, and on-call evidence.
