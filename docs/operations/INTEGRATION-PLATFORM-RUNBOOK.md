# Production Integration Platform Runbook

## Purpose

This runbook covers the tenant-scoped production integration control plane:

- service accounts and least-privilege API tokens;
- token issue, rotation, suspension, and revocation;
- connector SDK event intake;
- signed outgoing CloudEvents webhooks;
- retry, dead-letter, and replay operations;
- integration health and API access audit.

The older `/integrations` provider registry remains a demo/legacy surface.
Legacy mock credential writes and unauthenticated legacy inbound webhooks are
disabled whenever `DEMO_MODE=false`.

## Standards and security posture

- Events use the
  [CloudEvents 1.0.2 specification](https://github.com/cloudevents/spec/tree/v1.0.2)
  in structured JSON mode.
- API tokens follow bearer-token transport requirements: send them only over
  trusted TLS and never place them in URLs, logs, tickets, or source control.
  See [RFC 6750](https://www.rfc-editor.org/rfc/rfc6750).
- Outbound destinations use an explicit host allowlist, reject redirects,
  reject URL credentials/fragments, bound response reads, and enforce timeouts.
  This follows the allowlist-first guidance in the
  [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html).
- The webhook signature is an SBS versioned HMAC-SHA256 contract. It is not a
  claim of RFC 9421 conformance.
- Tokens are stored only as SHA-256 verifiers. Webhook URLs, webhook signing
  secrets, and queued payloads are AES-GCM encrypted with tenant/resource-bound
  associated data.

## Required configuration

```dotenv
INTEGRATION_PLATFORM_WORKER_BATCH_SIZE=50
INTEGRATION_PLATFORM_MAX_ACTIVE_TOKENS_PER_ACCOUNT=10
INTEGRATION_PLATFORM_REQUEST_LOG_RETENTION_DAYS=90
INTEGRATION_PLATFORM_DELIVERY_RETENTION_DAYS=90
INTEGRATION_OUTBOUND_WEBHOOK_TIMEOUT_SECONDS=15
INTEGRATION_OUTBOUND_WEBHOOK_MAX_PAYLOAD_BYTES=262144
INTEGRATION_OUTBOUND_WEBHOOK_ALLOWED_HOSTS=automation.example.com,events.example.com
```

`INTEGRATION_OUTBOUND_WEBHOOK_ALLOWED_HOSTS` contains exact host names only.
It is not a suffix or wildcard list. An empty list safely disables creation and
delivery to every destination.

Production also requires a non-placeholder `CREDENTIAL_ENCRYPTION_KEY`. Do not
rotate that key without a separately tested data re-encryption procedure:
existing connector secrets and queued encrypted payloads depend on it.

## RBAC

| Permission | Purpose |
|---|---|
| `integration.platform.accounts.read` | View service accounts, scope registry, and SDK contract |
| `integration.platform.accounts.manage` | Create, update, suspend, activate, or revoke accounts |
| `integration.platform.tokens.read` | View token metadata, never plaintext |
| `integration.platform.tokens.issue` | Issue and rotate tokens |
| `integration.platform.tokens.revoke` | Revoke tokens |
| `integration.platform.webhooks.read` | View subscriptions and delivery history |
| `integration.platform.webhooks.manage` | Create, test, rotate, activate, pause, or revoke webhooks |
| `integration.platform.webhooks.replay` | Replay failed/dead-letter deliveries |
| `integration.platform.observability.read` | View dashboard and machine API request audit |

Organization Admin and IT Manager receive full control. IT Agent receives read
and observability access. Security Officer receives account/token metadata,
webhook read, and observability access. SaaS Root must explicitly select a
tenant for mutations.

## Service-account setup

1. Open **Integrations → Production API & Webhooks → Service accounts**.
2. Select the organization when operating as SaaS Root.
3. Choose a purpose-specific name. Do not reuse one account across unrelated
   connectors.
4. Select only the required scopes:
   - `integration.events.write`;
   - `tickets.read`;
   - `assets.read`.
5. Configure exact source CIDRs when the connector has stable egress.
6. Set a rate limit and maximum token TTL appropriate to the connector.
7. Create the account and then issue its first token.
8. Copy the plaintext token immediately into the connector's approved secret
   store. The ITSM database and UI cannot reveal it again.
9. Call `GET /api/v1/integration-platform/sdk/v1/whoami` to prove identity,
   tenant, and effective scopes.

The token format is opaque:

```text
sbs_svc_<lookup-prefix>_<random-secret>
```

Do not parse it except to treat the entire value as a bearer credential.

## Token rotation

1. Select the active token and click **Rotate**.
2. Save the replacement token before dismissing the one-time panel.
3. Update the connector secret atomically.
4. Verify `whoami` and a non-destructive connector operation.
5. Confirm the old token is `REVOKED`.
6. Review **API audit** for unexpected attempts with the old token.

Rotation creates the replacement and revokes the predecessor in one database
transaction. If the transaction fails, the old token remains valid.

For an incident, revoke the token or suspend the entire service account first.
Revoking an account also revokes all active tokens and is irreversible.

## Connector SDK contract

Identity:

```http
GET /api/v1/integration-platform/sdk/v1/whoami
Authorization: Bearer <service-token>
```

Event publish:

```http
POST /api/v1/integration-platform/sdk/v1/events
Authorization: Bearer <service-token>
Content-Type: application/json

{
  "event_type": "monitoring.alert",
  "entity_type": "asset",
  "entity_id": "asset-id",
  "idempotency_key": "provider-event-unique-id",
  "data": {
    "severity": "critical",
    "summary": "API latency is above threshold"
  }
}
```

The idempotency key is scoped to the service account. Concurrent duplicate
publishes are serialized in PostgreSQL and return the existing event.
Secret-like field names such as password, authorization, token, API key, or
client secret are rejected because SDK event payloads become operational
records.

Read endpoints:

```text
GET /api/v1/integration-platform/sdk/v1/tickets/{ticket_id}
GET /api/v1/integration-platform/sdk/v1/assets/{asset_id}
```

Every request checks:

- token verifier and expiry;
- account and token lifecycle;
- effective intersection of account and token scopes;
- source CIDR;
- per-token rolling one-minute rate window;
- tenant boundary.

Allowed and denied authenticated attempts create a secret-safe request log.
Malformed tokens that cannot be associated with an account are intentionally
not persisted.

## Outbound webhook setup

1. Add the destination's exact host to
   `INTEGRATION_OUTBOUND_WEBHOOK_ALLOWED_HOSTS` and restart the API/worker.
2. Create a subscription in **Outgoing webhooks**.
3. Save the one-time signing secret in the receiver's approved secret store.
4. Configure event types. Exact names and a trailing namespace wildcard such
   as `major_incident.*` are supported.
5. Click **Test**.
6. Wait for the test delivery to reach `SUCCEEDED`.
7. Confirm the UI reports the current URL and secret versions as tested.
8. Activate the subscription.

Changing the target or rotating the signing secret pauses an active
subscription and invalidates the test evidence. Pending business deliveries
remain queued while paused. They resume after the current configuration passes
test and is activated.

Revocation is irreversible. It deletes encrypted target/secret material and
cancels still-pending deliveries.

## Webhook request contract

The body is a CloudEvents structured JSON document. Relevant headers:

```text
Content-Type: application/cloudevents+json
X-SBS-Webhook-ID: <subscription-id>
X-SBS-Delivery-ID: <delivery-id>
X-SBS-Timestamp: <unix-seconds>
X-SBS-Signature: v1=<lowercase-hmac-sha256-hex>
Idempotency-Key: <stable-delivery-key>
```

Signature input:

```text
<X-SBS-Timestamp>.<exact raw request body bytes>
```

Receiver requirements:

1. Read and preserve the raw body before JSON parsing.
2. Reject timestamps outside a locally defined replay window, recommended
   maximum five minutes.
3. Compute HMAC-SHA256 with the shared signing secret.
4. Compare `v1=<hex>` using a constant-time function.
5. Deduplicate using `Idempotency-Key`.
6. Return `2xx` only after durable acceptance.
7. Return `429` with integer `Retry-After` for deliberate throttling.

## Retry and dead-letter behavior

Retryable:

- network failures and timeouts;
- HTTP `408`, `425`, `429`;
- HTTP `5xx`.

Non-retryable:

- other HTTP `4xx`;
- redirects;
- response larger than the safety bound;
- missing/decryption/integrity errors;
- revoked or missing subscription.

Backoff is exponential and capped. Integer `Retry-After` is honored up to one
day. A retryable failure becomes `DEAD_LETTER` after the configured maximum
attempts. A permanent failure becomes `FAILED`.

Each attempt records status, bounded provider request ID, latency, safe error,
and the target/signing-secret versions actually used. Response bodies are
drained only to a bounded limit and are not retained.

## Dead-letter triage and replay

1. Filter **Delivery and DLQ** to `DEAD_LETTER` or `FAILED`.
2. Inspect HTTP status, safe error, attempt count, subscription health, and the
   version used.
3. Fix the receiver or subscription configuration.
4. Test and activate the subscription.
5. Click **Replay** and provide an operational reason.
6. Track the new delivery. The original record remains immutable and the new
   record links back through `replay_of_id`.

Replay is allowed only when the subscription is active. It decrypts the
original payload and re-encrypts it with a fresh resource-bound nonce.

## Operational queries

Dashboard:

```text
GET /api/v1/integration-platform/dashboard
```

Delivery queue:

```text
GET /api/v1/integration-platform/deliveries?status=DEAD_LETTER
```

Machine API audit:

```text
GET /api/v1/integration-platform/request-logs?outcome=DENIED
```

Connector contract:

```text
GET /api/v1/integration-platform/connector-contract
```

## Incident response

### Suspected token disclosure

1. Revoke the token; suspend the account if scope is unclear.
2. Search denied/allowed request logs by account and source IP.
3. Review business audit records for operations correlated to those request
   IDs.
4. Issue a narrowly scoped replacement only after containment.
5. Rotate the upstream secret and document the incident.

### Suspected webhook secret disclosure

1. Pause the subscription.
2. Rotate the signing secret.
3. Update the receiver.
4. Run a connection test and verify its signature.
5. Activate only after the current version test succeeds.
6. Review unexpected receiver requests independently; the ITSM system records
   only outbound attempts.

### Queue growth

1. Check worker readiness and logs for
   `outbound_webhook_cycle_failed`.
2. Compare `PENDING`, `RETRY`, and `DEAD_LETTER` dashboard counts.
3. Check receiver health, rate limits, TLS, allowlist, and network path.
4. Pause noisy subscriptions when needed; pending records remain queued.
5. Restore the receiver, test, activate, and monitor drain rate.

## Release acceptance

Before production release:

- apply migration `20260729_0051`;
- confirm a single Alembic head;
- run focused and full backend regression;
- run frontend production build and browser acceptance;
- create two tenants and prove cross-tenant isolation;
- prove token issue/rotate/revoke and one-time reveal;
- prove scope, CIDR, rate-limit, expiry, and account suspension denials;
- prove signed webhook test, activation gate, retry, DLQ, and replay;
- prove a pause preserves pending delivery;
- prove logs and APIs never expose token hashes, encrypted values, plaintext
  secrets, payload ciphertext, or response bodies;
- confirm legacy mock inbound paths return `410` with `DEMO_MODE=false`.
