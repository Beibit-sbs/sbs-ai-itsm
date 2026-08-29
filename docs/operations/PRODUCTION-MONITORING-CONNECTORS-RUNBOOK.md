# Production Monitoring Connectors Runbook

## Scope

This runbook covers the tenant-scoped monitoring intake introduced by
`INT-MON-001`. It accepts Alertmanager/Prometheus, Grafana, Zabbix, Sentry,
and generic webhook events, normalizes them into Event Operations, and then
uses the existing correlation, suppression, escalation, incident creation,
and recovery policies.

The intake endpoint is:

```text
POST /api/v1/event-operations/webhooks/{source_id}
```

The source identifier is not a credential. Every enabled source must also pass
its configured Bearer or HMAC authentication, IP/CIDR policy, payload-size
limit, rate limit, and tenant/source validation.

## Source setup

Open **Event Operations → Sources** and create one source per external
monitoring destination. Do not reuse a source between tenants or between
production and non-production environments.

Configure:

- provider type: `ALERTMANAGER`, `PROMETHEUS`, `GRAFANA`, `ZABBIX`, `SENTRY`,
  or `GENERIC`;
- authentication mode: `HMAC_SHA256` is preferred; use `BEARER` only when the
  sender cannot calculate a supported signature;
- replay window for timestamped HMAC requests;
- requests-per-minute limit based on expected peak alert bursts;
- maximum request size;
- optional trusted proxy or provider egress IP/CIDR allowlist;
- provider-specific field mappings, tags, correlation policy, and incident
  policy in Event Operations.

The generated credential is displayed once. Store it in the provider's secret
store. The API and administration UI never return the encrypted credential.

## Authentication contracts

### SBS HMAC contract

Generic and Zabbix senders calculate:

```text
hex(HMAC-SHA256(secret, timestamp + "." + exact_raw_request_body))
```

Required headers:

```text
Content-Type: application/json
X-SBS-Timestamp: <Unix epoch seconds>
X-SBS-Signature: <lowercase or uppercase hexadecimal digest>
X-Idempotency-Key: <stable provider event or batch identifier>
```

The body must be signed byte-for-byte as transmitted. The timestamp must fall
inside the configured replay window. A repeated idempotency key with the same
body returns the original receipt and does not repeat business side effects. A
reused key with a different body is rejected as a conflict.

### Grafana native HMAC

Configure Grafana's webhook HMAC secret with:

```text
X-Grafana-Alerting-Signature
```

and configure the timestamp header as:

```text
X-Grafana-Alerting-Timestamp
```

The platform validates Grafana's documented message:

```text
hex(HMAC-SHA256(secret, timestamp + ":" + exact_raw_request_body))
```

Grafana documents the webhook structure and HMAC options in its
[webhook notifier documentation](https://grafana.com/docs/grafana-cloud/alerting-and-irm/alerting/configure-notifications/manage-contact-points/integrations/webhook-notifier/).

### Sentry service hook

Create the Sentry hook first and copy its provider-issued secret into
**Source → Intake policy → Provider secret**. The platform accepts
`Sentry-Hook-Signature` as a body HMAC and relies on receipt idempotency to
prevent duplicate side effects. Always send a stable event identifier.

Sentry's project service-hook registration is documented in the
[Sentry API reference](https://docs.sentry.io/api/projects/register-a-new-service-hook/).
Confirm the active Sentry integration's signing behavior during server
acceptance before enabling incident automation.

### Bearer mode

Send:

```text
Authorization: Bearer <one-time source token>
Content-Type: application/json
X-Idempotency-Key: <stable provider event or batch identifier>
```

Use this mode for Alertmanager when the chosen delivery path cannot calculate
HMAC. Prometheus documents Alertmanager's webhook batch shape in the
[Alertmanager configuration reference](https://prometheus.io/docs/alerting/latest/configuration/).

## Provider payloads

- Alertmanager/Prometheus: the standard `alerts[]` webhook batch is expanded
  into individual normalized events.
- Grafana: modern unified-alerting and legacy webhook shapes are supported.
- Zabbix: configure a webhook media type that sends JSON fields for event ID,
  host, trigger/problem, severity, status, timestamp, and tags. Zabbix's
  webhook media-type model is documented in the
  [Zabbix webhook documentation](https://www.zabbix.com/documentation/current/en/manual/config/notifications/media/webhook).
- Sentry: issue/error and service-hook envelopes are normalized using the
  provider event/project identifiers.
- Generic: send one object, an `events[]` array, or an `alerts[]` array.
  Stable `external_event_id`, `title`, `severity`, `status`, `occurred_at`,
  `resource`, `service`, `description`, and `labels` fields produce the best
  result.

Unknown payload fields are not copied blindly into tickets. Normalization,
redaction, field mappings, and Event Operations policy decide what becomes
operational data.

## Receipt queue and recovery

The public endpoint validates and durably stores an encrypted receipt, then
returns HTTP `202`. A worker performs normalization and event processing
outside the webhook request.

Receipt states:

- `RECEIVED` / `RETRY`: waiting for worker processing;
- `PROCESSING`: claimed by a worker;
- `PROCESSED`: normalization and Event Operations processing succeeded;
- `FAILED`: a processing error remains eligible for operator inspection;
- `DEAD_LETTER`: malformed or retry-exhausted payload requiring correction;
- `REJECTED`: intake controls rejected the request;
- `DUPLICATE`: duplicate evidence where applicable.

Open **Event Operations → Receipts** to filter by source/state, inspect safe
metadata, see created/correlated/suppressed results, and reprocess a failed or
dead-letter receipt. Manual reprocessing resets the retry budget and is
audited. Raw payloads stay encrypted and are never exposed through the normal
administration API.

Processed receipt evidence is purged after
`MONITORING_RECEIPT_RETENTION_DAYS`; active retry/dead-letter evidence is kept
for operator action.

## Safety and capacity

- Payload size is enforced while streaming, before the body is fully buffered.
- The global maximum is `MONITORING_GLOBAL_MAX_PAYLOAD_BYTES`; a source can
  only set a lower effective limit.
- Per-source rate limiting is enforced before receipt creation.
- IP allowlists use explicit IPv4/IPv6 addresses or CIDRs. When deployed behind
  a reverse proxy, trust forwarded client-IP headers only at the proxy boundary
  and pass a sanitized address to the application.
- Signature, authorization, cookie, and secret headers are never retained in
  receipt metadata.
- Receipt payloads use the platform credential-encryption key and
  tenant/source-bound authenticated encryption.
- Do not include credentials, personal data, access tokens, or unrestricted
  stack dumps in alert labels or annotations.

## Health monitoring

For every source watch:

- last success and failure timestamps;
- success, failure, and dead-letter counters;
- receipt depth by state and age;
- repeated authentication, replay, size, or rate-limit rejections;
- event correlation/suppression ratios;
- incidents opened, recovered, and escalated from monitoring.

An enabled source with no recent success must be investigated against the
provider's expected send frequency. Test alerts should use a distinct tag and
be closed/recovered after acceptance.

## Local-to-server cutover

1. Apply Alembic through `20260729_0049`.
2. Configure a unique `CREDENTIAL_ENCRYPTION_KEY`.
3. Set the monitoring worker batch, receipt retention, and global payload
   limit for the server capacity.
4. Put the webhook endpoint behind HTTPS and the production reverse proxy.
5. Configure proxy request-size limits consistently with the application.
6. Create separate production sources and store their one-time credentials in
   each provider.
7. Send signed firing and recovery test events for every source.
8. Prove duplicate, stale timestamp, bad signature, rate-limit, oversized
   payload, malformed payload, retry, dead-letter, and manual recovery paths.
9. Verify tenant isolation, audit evidence, correlation, suppression, incident
   creation, escalation, and recovery.
10. Observe worker queue depth and source health before enabling automatic
    incident creation for all alerts.

