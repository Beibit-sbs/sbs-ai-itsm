# Production Email Channel Runbook

## Purpose

This runbook covers the tenant-scoped SBS AI ITSM email channel for Microsoft
365 / Exchange Online. The channel supports:

- inbound email to incident or service request;
- safe reply threading;
- sender, auto-reply, loop, and DMARC checks;
- attachment allowlists, size limits, SHA-256, quarantine, and ClamAV;
- outbound queueing through Microsoft Graph;
- retry with exponential backoff and `Retry-After`;
- bounce evidence and delivery-event history;
- delta polling plus optional Microsoft Graph webhooks.

The administration workspace is `/email-operations`.

## Security model

- The Microsoft Entra client secret is AES-256-GCM encrypted before it is
  stored. The API returns only `client_secret_configured`.
- Encryption is tenant- and purpose-bound. Ciphertext from one tenant or
  field cannot be decrypted under another tenant or purpose.
- `CREDENTIAL_ENCRYPTION_KEY` is a dedicated production secret. Do not reuse
  the JWT, MFA, database, Redis, OIDC, or Microsoft Graph secrets.
- The webhook `clientState`, loop token, and Graph delta link are encrypted.
- Only one channel can be active per tenant.
- Revocation is irreversible: the saved Graph secret, webhook state, delta
  token, and subscription identifiers are removed.
- Every configuration, retry, reprocessing, and attachment decision is
  audited.

Never rotate `CREDENTIAL_ENCRYPTION_KEY` by replacing the value in place.
Existing encrypted channel material would become unreadable. A production key
rotation requires an application-supported decrypt/re-encrypt migration while
both keys are available.

## Microsoft Entra application

1. Create a single-tenant App registration.
2. Add Microsoft Graph **Application** permissions:
   - `Mail.Read`
   - `Mail.Send`
3. Grant tenant admin consent.
4. In Exchange Online, use RBAC for Applications to restrict the application
   to the dedicated service mailbox. Do not grant unrestricted organization
   mailbox access.
5. Create a client secret and immediately copy its **Value**, not its Secret
   ID.
6. Record the Directory (tenant) ID, Application (client) ID, mailbox address,
   and optional mailbox object ID/UPN.

The connection test reads the Inbox folder with `Mail.Read`; it does not
require broad directory read permissions.

## Local configuration

Development works without a public callback:

```dotenv
EMAIL_ATTACHMENT_STORAGE_PATH=./data/email-attachments
EMAIL_POLL_INTERVAL_SECONDS=30
EMAIL_GRAPH_TIMEOUT_SECONDS=20
EMAIL_WORKER_BATCH_SIZE=50
EMAIL_PUBLIC_BASE_URL=
EMAIL_CLAMAV_HOST=
EMAIL_CLAMAV_PORT=3310
```

Without `EMAIL_PUBLIC_BASE_URL`, the worker uses Microsoft Graph delta polling.
Without ClamAV, allowed files are stored in quarantine and require a manual,
audited release. Executable extensions are always blocked.

The backend and worker must share `EMAIL_ATTACHMENT_STORAGE_PATH`. Docker
Compose uses the `email_attachment_data` volume for both services.

## Create and activate a channel

1. Open **Admin & Security → Почтовый канал**.
2. For SaaS Root, select the organization.
3. Open **Подключение Microsoft 365**.
4. Enter:
   - channel name;
   - service mailbox;
   - Directory ID;
   - Application ID;
   - client secret Value;
   - new-message target: incident or service request;
   - optional allowed sender domains;
   - allowed attachment extensions and maximum size.
5. Create the channel. It starts in `DRAFT`.
6. Select **Проверить соединение**.
7. Select **Активировать**.
8. Select **Синхронизировать сейчас** to establish the initial delta
   checkpoint.
9. Send a test message and confirm the outbound status in **Исходящие**.

Changing mailbox, Directory ID, Application ID, or mailbox object ID pauses an
active channel and requires a fresh connection test and activation.

## Server webhook configuration

On the target server:

```dotenv
EMAIL_PUBLIC_BASE_URL=https://itsm.example.com
```

Requirements:

- public HTTPS;
- a trusted TLS certificate;
- reverse-proxy routing to the backend API;
- no authentication middleware in front of the Microsoft Graph callback;
- normal platform rate limiting and request-size limits still apply.

After deployment, select **Настроить webhook**. The callback is:

```text
https://itsm.example.com/api/v1/email/webhooks/microsoft-graph/{channel_id}
```

The endpoint:

- echoes Graph `validationToken` as plain text;
- validates encrypted `clientState` with constant-time comparison;
- validates the subscription ID;
- persists an idempotent event and returns `202` quickly;
- lets the worker fetch and process the message.

Subscriptions are automatically renewed before expiry. Delta polling remains
enabled as a recovery path.

## Inbound processing

Processing order:

1. deduplicate by channel and provider message ID;
2. reject the service mailbox itself;
3. reject platform loop headers;
4. reject auto-submitted and bulk/list messages;
5. apply the optional sender-domain allowlist;
6. quarantine DMARC failures;
7. locate the thread by the protected SBS marker, Graph conversation ID, or
   message references;
8. require the original requester or an active tenant user for an existing
   thread;
9. create an incident/request or append a public comment;
10. download, validate, hash, scan, and quarantine attachments;
11. persist the outcome and audit trail.

Untrusted HTML is not rendered. The platform extracts plain text and creates a
safe escaped preview.

## Attachment handling

Always-blocked types include executable, script, installer, registry, shortcut,
and disk-image extensions. Filename path components are removed.

Attachment states:

- `STORED`: scanner returned clean;
- `QUARANTINED`: scan is pending or unavailable;
- `BLOCKED`: type, size, content, or malware check failed;
- `RELEASED`: an authorized operator explicitly released the file.

For server deployment, configure a reachable ClamAV daemon:

```dotenv
EMAIL_CLAMAV_HOST=clamav.internal
EMAIL_CLAMAV_PORT=3310
```

Monitor the quarantine count. A growing count with `scan_status=ERROR` usually
means the scanner is unavailable.

## Outbound status semantics

- `QUEUED`: ready for the worker;
- `RETRY`: a temporary error occurred; `next_retry_at` is set;
- `ACCEPTED`: Microsoft Graph returned `202`; delivery is not yet asserted;
- `DELIVERED`: a separate provider delivery signal confirmed delivery;
- `BOUNCED`: an NDR was correlated with the outbound log;
- `FAILED`: permanent failure or retry exhaustion;
- `SENT`: local mock provider only.

Manual retry never fabricates `SENT`. Accepted/delivered messages cannot be
retried.

## Troubleshooting

### Connection test returns 401 or 403

- confirm the client secret Value has not expired;
- confirm Application permissions, not Delegated permissions;
- confirm admin consent;
- confirm Exchange application scope includes the service mailbox;
- rotate the saved secret, test, and reactivate.

### Inbound messages are not appearing

- confirm the channel is `ACTIVE` and inbound is enabled;
- run **Синхронизировать сейчас**;
- inspect `last_error` and the webhook dead-letter count;
- confirm the worker is running;
- if a delta token is invalidated by Graph, pause/reactivate and perform a
  controlled checkpoint reset through an approved maintenance change.

### Messages remain in RETRY

- inspect HTTP status and Graph request ID in the error;
- 429 and transient 5xx responses are retried automatically;
- confirm worker access to Microsoft identity and Graph endpoints;
- confirm system time is correct.

### Safe shutdown

Pause the channel before planned Microsoft 365 or mailbox maintenance. Queued
messages remain persisted. Reactivate after a successful connection test.

## Backup and restore

Back up:

- PostgreSQL email channel, conversation, message, and audit tables;
- the shared attachment volume;
- the original `credential_encryption_key`.

Database and attachment storage must be restored to the same point-in-time.
Losing the encryption key makes saved Graph credentials and checkpoints
unrecoverable.
