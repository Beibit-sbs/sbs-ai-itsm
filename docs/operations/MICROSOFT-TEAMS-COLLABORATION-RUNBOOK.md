# Microsoft Teams Collaboration Runbook

## Scope

This runbook covers the tenant-scoped Microsoft Teams Workflow integration,
Adaptive Card notifications, secure ITSM actions, delivery recovery, and Major
Incident collaboration rooms introduced by `INT-COLLAB-001`.

The platform intentionally does not use Microsoft Graph application permission
to post ordinary channel messages. Microsoft documents the application-only
`Teamwork.Migrate.All` permission for migration scenarios, not normal
notifications. SBS AI ITSM uses a Teams Workflow webhook for supported
channel delivery and keeps every state-changing action inside the authenticated
ITSM application.

## Required server configuration

- `CREDENTIAL_ENCRYPTION_KEY`: unique production secret used to encrypt webhook
  URLs with tenant- and connector-bound AES-256-GCM additional data.
- `TEAMS_PUBLIC_BASE_URL`: externally reachable HTTPS origin of SBS AI ITSM.
  Adaptive Card actions are generated only for this exact origin.
- `TEAMS_WEBHOOK_ALLOWED_HOSTS`: comma-separated Microsoft webhook hostname
  suffix allowlist. Keep the defaults unless Microsoft assigns a documented
  regional hostname that must be added.
- `TEAMS_REQUEST_TIMEOUT_SECONDS`: outbound request timeout.
- `TEAMS_WORKER_BATCH_SIZE`: maximum due deliveries per worker cycle.

Never put a Workflow webhook URL in `.env`, logs, screenshots, tickets, or
documentation. Enter it in the Teams administration workspace; the API returns
only `webhook_configured`.

## Create a Teams Workflow

1. Open the target Teams channel and select **Workflows**.
2. Create **Post to a channel when a webhook request is received**.
3. Assign at least two operational owners so the Workflow is not orphaned.
4. Select the target Team and channel.
5. Copy the generated HTTPS webhook URL.
6. In SBS AI ITSM open **Microsoft Teams → Подключение**.
7. Create a separate destination for each audience:
   `DEFAULT`, `APPROVALS`, `MAJOR_INCIDENT`, or `SECURITY`.
8. Run **Проверить**, confirm the Adaptive Card arrived, and activate the
   connector.

For `MAJOR_INCIDENT`, also configure the Teams channel deep link and, if the
organization uses a persistent bridge, the meeting deep link.

## Delivery semantics

- Business transactions create a `QUEUED` outbox record in the same database
  transaction; no network call occurs in the request path.
- The worker sends due records and records `SENT`, `RETRY`, `FAILED`,
  `DEAD_LETTER`, or `CANCELLED`.
- HTTP `429`, selected transient HTTP statuses, timeouts, and server errors use
  `Retry-After` or exponential backoff.
- Permanent client errors fail without an unsafe infinite retry.
- The queue uses connector-bound idempotency keys and a short duplicate window
  to prevent fan-out duplicates from recipient-specific in-app notifications.
- A paused or revoked connector cancels due sends rather than leaking them to a
  stale destination.

## Secure actions and approvals

Workflow Webhooks do not provide authenticated `Action.Execute` callbacks.
Cards therefore use `Action.OpenUrl` to the exact `TEAMS_PUBLIC_BASE_URL`.
Approvers must authenticate in SBS AI ITSM, after which the normal tenant,
object-state, optimistic-lock, and RBAC checks run. Approval decisions and
comments are written by the existing domain API and audit trail.

Do not add unsigned query-string decision endpoints or accept identity claims
from a card payload.

## Major Incident operation

- Declaring a SEV1/SEV2 automatically opens a collaboration-room record when an
  active `MAJOR_INCIDENT` destination exists.
- Declare, update, and transition events enqueue dedicated critical/warning
  cards.
- Cards include the ITSM record, configured channel, and meeting actions.
- When the incident becomes `CLOSED` or `CANCELLED`, the collaboration-room
  record is closed. Teams channel lifecycle remains under Microsoft 365
  governance; SBS AI ITSM does not delete Teams content.

## Failure recovery

1. Open **Microsoft Teams → Доставка**.
2. Inspect HTTP status, last error, attempt count, and next attempt time.
3. For `401/403/404`, verify the Workflow still exists and its owners retain
   access. Rotate the webhook, run a test, then activate the connector.
4. For `429`, leave the item in `RETRY`; the worker honors `Retry-After`.
5. For `FAILED`, `DEAD_LETTER`, or `CANCELLED`, correct the connector and use
   **Повторить**. Manual retry resets the attempt budget and is audited.
6. If a URL may have leaked, revoke the connector immediately, delete/disable
   the Teams Workflow, create a new Workflow, and rotate the webhook.

## Health and audit

Monitor:

- active connector count;
- queue and retry depth;
- failed/dead-letter count;
- sends during the last 24 hours;
- connector success/failure counters and last error;
- open Major Incident room count.

Security-sensitive operations emit audit events for connector creation/update,
webhook rotation, test, activation/pause/revoke, manual retry, and Major
Incident room lifecycle. Secret values are never included in audit metadata.

## Local-to-server cutover

Local development can use a `MOCK` connector only while `DEMO_MODE=true`.
Before server activation:

1. apply Alembic through `20260729_0048`;
2. configure unique production secrets and `TEAMS_PUBLIC_BASE_URL`;
3. confirm the public origin and TLS certificate;
4. create production Teams Workflows and enter their URLs through the UI;
5. test each destination;
6. activate connectors;
7. verify the worker is running and queue depth returns to zero.

