# INT-MON-001 — Monitoring Connectors Pending Runtime Gate

## Outcome

The local implementation is complete and statically verified. Runtime
acceptance remains part of the accumulated release gate because the current
execution environment cannot run the project test/container runtime.

## Delivered

- tenant-scoped Alertmanager/Prometheus, Grafana, Zabbix, Sentry, and generic
  webhook sources;
- Bearer and HMAC-SHA256 authentication, including the native Grafana signing
  form and provider-issued Sentry secrets;
- bounded streaming payload-size enforcement, replay windows, IP/CIDR
  allowlists, per-source rate limits, and content-type validation;
- encrypted durable receipts, safe retained headers, idempotency and
  conflicting-key rejection;
- provider-specific normalization into the existing Event Operations
  correlation, suppression, incident, recovery, and escalation pipeline;
- asynchronous worker processing, retry/backoff, dead-letter, manual
  reprocessing, retention, and source health counters;
- administration UI for source security policy, one-time secret handling,
  connector health, receipt inspection, and recovery;
- dedicated RBAC permissions, audit events, configuration examples,
  migration `20260729_0049`, tests-as-code, and operations runbook.

## Security decisions

- A source UUID is an address, not a credential.
- HMAC is preferred; Bearer remains available for providers that cannot
  calculate a supported signature.
- Request size is checked during streaming before full buffering.
- Signature/authentication headers and raw secrets are never returned or
  retained in safe receipt metadata.
- Raw receipts are encrypted with tenant/source-bound authenticated
  encryption.
- Network admission, replay, rate, size, signature, tenant, and source-state
  checks happen before an event enters the business workflow.
- Public intake returns a receipt and performs no monitoring-provider network
  calls in the request transaction.

## Static evidence

The stage is required to pass:

- Ruff over the complete backend and relevant tests/scripts;
- Python compileall;
- TypeScript `tsc --noEmit`;
- Alembic single-head inspection through `0049`;
- OpenAPI route inspection;
- development and production Compose parsing;
- `git diff --check`.

Runtime pytest, database migration execution, live worker processing, real
provider delivery, production frontend bundling, and browser acceptance remain
pending and must not be represented as completed.

## Runtime acceptance checklist

- create one source for each supported provider and prove secret
  non-disclosure;
- accept valid Bearer, SBS HMAC, Grafana HMAC, and configured Sentry signature
  requests;
- reject invalid signatures, stale timestamps, forbidden IPs, oversized
  requests, wrong content types, and rate-limit overflow;
- prove same-key/same-body idempotency and same-key/different-body conflict;
- process firing and recovery payloads through correlation and incident
  lifecycle;
- prove suppression, duplicate alerts, mapping overrides, and tenant
  isolation;
- inject malformed and transient-failure payloads and verify retry,
  dead-letter, and audited reprocessing;
- verify encrypted payload storage and retention purge;
- execute focused tests in `backend/tests/test_monitoring_connectors.py`;
- run the full regression suite and browser acceptance.

