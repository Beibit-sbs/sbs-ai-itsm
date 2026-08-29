# Asset Discovery Operations Runbook

## Purpose

This runbook operates tenant-scoped discovery from Microsoft Intune, Azure
Resource Graph, Microsoft Configuration Manager AdminService, and Lansweeper
Data API into the governed SBS AI ITSM CMDB.

Discovery does not bypass CMDB controls. Every provider record passes through
the existing source identity, preview, validation, precedence, field ownership,
duplicate detection, and reconciliation history pipeline.

## Operating model

```text
Provider API
  -> bounded authenticated fetch
  -> provider normalization + duplicate external-ID rejection
  -> batches of at most 500 records
  -> governed CMDB reconciliation preview
  -> optional apply of unambiguous and valid batches
  -> complete-snapshot missing/stale evaluation
  -> explicit administrator review before CI retirement
```

The worker executes scheduled and manual runs. It retries transient failures
with exponential backoff, moves exhausted transient failures to
`DEAD_LETTER`, and preserves each reconciliation run ID for investigation.

## Permissions

| Permission | Purpose |
|---|---|
| `asset.discovery.read` | View connectors, runs, health, and stale candidates |
| `asset.discovery.manage` | Create, test, configure, pause, rotate, or revoke |
| `asset.discovery.run` | Queue and retry discovery runs |
| `asset.discovery.review` | Dismiss or retire stale candidates |

SaaS Root can select a tenant. Organization administrators and IT managers
receive the full discovery control set. IT agents receive read access only.

## Provider prerequisites

### Microsoft Intune

1. Create a Microsoft Entra application for the tenant.
2. Grant the application permission
   `DeviceManagementManagedDevices.Read.All`.
3. Grant tenant administrator consent.
4. Create a client secret and record the directory tenant ID and client ID.
5. Do not place any of these values in connector configuration JSON.

The connector calls the Microsoft Graph
`deviceManagement/managedDevices` endpoint and follows only same-origin Graph
pagination links.

References:

- [List managed devices](https://learn.microsoft.com/en-us/graph/api/intune-devices-manageddevice-list?view=graph-rest-1.0)
- [Configure Microsoft Graph access for Intune](https://learn.microsoft.com/en-us/intune/developer/configure-graph-api-access)

### Azure Resource Graph

1. Create a Microsoft Entra application.
2. Grant its service principal `Reader` or a narrower custom read role on the
   subscriptions or management groups in scope.
3. Record the directory tenant ID, client ID, and client secret.
4. Choose explicit subscription IDs where possible.
5. Review the Resource Graph query before enabling automatic apply.

The connector uses REST API version `2024-04-01` and preserves `$skipToken`
pagination without accepting provider-controlled origin changes.

References:

- [Azure Resource Graph overview and permissions](https://learn.microsoft.com/en-us/azure/governance/resource-graph/overview)
- [Resources REST operation](https://learn.microsoft.com/en-us/rest/api/azureresourcegraph/resourcegraph/resources/resources?view=rest-azureresourcegraph-resourcegraph-2024-04-01)

### Microsoft Configuration Manager

1. Enable and validate AdminService in the Configuration Manager environment.
2. Expose it only through trusted internal TLS.
3. Add its exact hostname to
   `ASSET_DISCOVERY_SCCM_ALLOWED_HOSTS`; wildcards and suffix matching are not
   supported.
4. Prefer a trusted gateway that converts the organization's Windows
   Integrated authentication into a short-lived Bearer credential. Direct
   Basic authentication is available only where the deployment policy permits
   it.
5. Keep the configured path under `/AdminService/`.

References:

- [AdminService usage](https://learn.microsoft.com/en-us/intune/configmgr/develop/adminservice/usage)
- [AdminService release notes and device route](https://learn.microsoft.com/en-us/intune/configmgr/develop/adminservice/release-notes)

### Lansweeper Data API

1. Obtain a Personal Access Token or OAuth access token with access to the
   intended site.
2. Record the site ID.
3. Start with a conservative page size and confirm the returned field set.
4. Account for the documented request and response restrictions when choosing
   the discovery schedule.

PAT requests use `Authorization: Token`; OAuth access tokens use Bearer.
Pagination uses `FIRST`/`NEXT` and the provider cursor. Responses are bounded
locally to 5 MiB.

References:

- [Data API quickstart](https://developer.lansweeper.com/docs/data-api/get-started/quickstart)
- [Getting data and pagination](https://developer.lansweeper.com/docs/data-api/guides/getting-data)
- [Data API types](https://developer.lansweeper.com/docs/data-api/reference/types)
- [Data API restrictions](https://developer.lansweeper.com/docs/data-api/get-started/restrictions)

## Runtime configuration

Set these values in the local `.env` or deployment secret manager:

```dotenv
ASSET_DISCOVERY_WORKER_BATCH_SIZE=10
ASSET_DISCOVERY_REQUEST_TIMEOUT_SECONDS=30
ASSET_DISCOVERY_SCCM_ALLOWED_HOSTS=sccm-admin.example.internal
CREDENTIAL_ENCRYPTION_KEY=<at-least-32-random-characters>
```

Use exact SCCM hostnames separated by commas. The fixed Microsoft and
Lansweeper endpoints are not configurable from the UI.

## Create and activate a connector

1. Sign in as Organization Admin, IT Manager, or SaaS Root.
2. Open **Активы и CMDB → Asset Discovery**.
3. For SaaS Root, select the organization.
4. Select the provider.
5. Create a new governed `DISCOVERY` CMDB source or select an unbound active
   source.
6. When creating a source, select a published CI class.
7. Enter the provider-specific configuration and credential.
8. Choose:
   - schedule, minimum 5 minutes;
   - maximum records, up to 50,000;
   - complete scans required before stale review;
   - `PREVIEW` or `AUTO APPLY`.
9. Create the connector. It starts as `DRAFT`.
10. Press **Проверить**.
11. Confirm that the UI shows the current credential version as `проверен`.
12. Press **Активировать**.

Activation fails closed unless the currently stored credential version has
passed a connection test. A secret is encrypted with AES-GCM and bound to both
tenant and connector. The plaintext is never returned by the API.

## Reconciliation policy

Use `PREVIEW` for the first runs of every provider. Inspect the linked CMDB
reconciliation batches for:

- invalid class attributes;
- ambiguous matches;
- provider duplicate identifiers;
- blocked fields caused by a higher-priority owner;
- unexpected create volume.

`AUTO APPLY` applies only batches with no invalid or ambiguous records. It does
not weaken schema validation, field ownership, source priority, or tenant
isolation.

A provider returning the same `external_id` twice fails the discovery run
instead of silently overwriting data.

## Complete snapshots and stale-device safety

Missing state advances only after a fully consumed provider snapshot.

- A scan truncated by `max_records` is marked incomplete and cannot make an
  existing CI missing or stale.
- A pagination loop is rejected and cannot make an existing CI stale.
- A transient, failed, cancelled, or dead-letter run cannot make a CI stale.
- A complete scan increments `missing_run_count` for identities not observed.
- At `missing_threshold_runs`, the system creates an `OPEN` stale candidate.
- No CI is automatically deleted or retired.

An authorized reviewer must enter a reason and choose:

- **Оставить** — dismiss the current missing episode;
- **Retire CI** — set lifecycle to `RETIRED`, status to inactive, preserve the
  identity, and append immutable asset history and audit evidence.

If a dismissed asset reappears, its candidate becomes `RECOVERED`. A later
missing episode can open the candidate again. A human retirement is sticky:
later discovery may refresh technical facts but cannot silently restore
`lifecycle_status` or `verification_status`.

## Credential rotation and revocation

Rotation:

1. Open the connector details.
2. Enter the complete replacement credential.
3. Press **Rotate credential**.
4. The connector is automatically paused.
5. Test the new credential.
6. Reactivate only after the test succeeds.

Revocation is permanent for that connector:

- encrypted credential and hint are cleared;
- due queued/retry runs are cancelled;
- scheduling stops;
- the connector cannot be reactivated.

Create a replacement connector and source binding when a revoked integration
must be restored.

## Failure handling

| State | Operator action |
|---|---|
| `RETRY` | Wait for bounded backoff; inspect `last_error` if repeated |
| `FAILED` | Correct non-transient credential/config/data error, then retry |
| `DEAD_LETTER` | Correct the root cause and use the explicit retry action |
| `COMPLETED_WITH_ERRORS` | Review invalid/ambiguous reconciliation records |
| `CANCELLED` | Activate the correct connector and retry if still required |

HTTP 408, 425, 429, and 5xx failures are retryable. `Retry-After` is honored
within a one-day cap. Redirects, changed pagination origins, oversized
responses, unsupported provider shapes, and duplicate external IDs fail
closed.

## Security controls

- Credentials are stored only in encrypted connector fields.
- Nested configuration keys containing secret/password/token/credential/API
  key markers are rejected.
- Microsoft and Lansweeper hosts are fixed.
- SCCM requires HTTPS, an exact hostname allowlist, and an AdminService path.
- Redirects are disabled.
- Response streams are bounded before aggregation.
- Provider error bodies are not persisted or reflected to clients.
- Tenant scoping applies to connector, run, stale-review, and dashboard APIs.
- Connector lifecycle, credential rotation, run queue/retry, and stale
  decisions are audited.
- PostgreSQL workers use row locks with `SKIP LOCKED` to avoid duplicate
  processing across worker replicas.

## Local migration and later server cutover

Local development:

```powershell
cd backend
alembic upgrade head
```

Migration `20260729_0050` is additive. Before server cutover:

1. Back up the target database.
2. Configure production encryption and SCCM allowlist secrets.
3. Apply Alembic through `20260729_0050`.
4. Start API and worker from the same release.
5. Verify `/api/v1/health/readiness`.
6. Create each production connector as `DRAFT`.
7. Test it, run in `PREVIEW`, inspect reconciliation, then activate.
8. Enable `AUTO APPLY` only after source matching and ownership are approved.

Do not copy local provider secrets or encrypted connector rows into a server
whose encryption key differs.

## Acceptance checklist

- [ ] Current migration head is `20260729_0050`.
- [ ] Every provider has a least-privilege identity.
- [ ] SCCM hostname is explicitly allowlisted.
- [ ] Credential plaintext is absent from API responses, logs, and audit.
- [ ] DRAFT cannot activate before current-credential test success.
- [ ] Rotation pauses the connector and requires a new test.
- [ ] Concurrent pending runs are rejected.
- [ ] Incomplete scans do not increment missing state.
- [ ] Stale retirement requires a reason and creates history/audit.
- [ ] Retired CI cannot be silently reactivated by discovery.
- [ ] Retry and dead-letter recovery are exercised in the target runtime.
- [ ] Cross-tenant access is denied.

