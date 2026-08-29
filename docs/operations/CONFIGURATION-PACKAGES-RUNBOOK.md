# Configuration Packages Runbook

## Purpose

Configuration packages move governed platform configuration from a local or
development environment to staging and production without copying database
rows or secrets. The control plane provides:

- immutable package versions with SHA-256 component and manifest integrity;
- HMAC-SHA256 artifact authentication;
- dependency closure and fail-closed validation;
- target-state dry-run with `CREATE`, `UPDATE`, `NOOP`, and `BLOCK` evidence;
- independent production approval;
- target drift detection immediately before apply;
- before-snapshot, result hashes, audit events, and non-destructive rollback.

The feature is available at `/admin/configuration-packages`. Its API prefix is
`/api/v1/configuration-packages`.

## Supported configuration

The current portable component contract covers:

| Component | Stable identity | Notes |
| --- | --- | --- |
| Catalog category | `catalog_category:<code>` | Owner/runtime history excluded |
| Catalog service | `catalog_service:<code>` | Depends on category |
| Service offering | `catalog_offering:<code>` | Depends on service and category |
| Catalog item | `catalog_item:<code>` | Includes policy JSON, excludes owner user ID |
| SLA calendar | `sla_calendar:<name>` | Includes weekly hours and exceptions |
| SLA policy | `sla_policy:<name>:<priority>` | Depends on its calendar |
| Notification template | `notification_template:<code>` | Tenant ownership checked |
| External system | `external_system:<code>` | Secrets removed; imported disabled |
| Integration mapping | composite stable key | Imported inactive |
| Webhook endpoint | composite stable key | Secret reference removed; imported inactive |
| Workflow | `workflow:<code>` | Published version only; subflow closure enforced |
| Custom-field set | `custom_field_set:<code>` | Published schema only |

Selecting a dependent type automatically adds its prerequisite types. The
validator still verifies every declared dependency so a manually edited or
incomplete artifact cannot be sealed or imported.

## Trust and secret model

`CONFIGURATION_PACKAGE_SIGNING_KEY` is an independent secret of at least 32
characters. Production refuses to start if it is absent, a placeholder, or
reused as another platform credential.

The source and target environments must share the same package trust key if
the target is expected to accept source-signed artifacts. Distribute that key
through the approved secret manager, not inside the artifact or Git.

For a local-to-server workflow:

1. Generate an independent high-entropy key.
2. Put it in the local `.env` as
   `CONFIGURATION_PACKAGE_SIGNING_KEY=<value>`.
3. Put the same value in the server Docker secret file
   `configuration_package_signing_key`.
4. Restart the local API after changing `.env`.
5. Never copy `credential_encryption_key`, integration credentials, or API
   tokens through a package.

The production secret generator creates this secret automatically:

```powershell
python scripts/init-production-secrets.py --directory secrets
```

The preflight checks its presence, length, placeholder status, and separation:

```powershell
python scripts/check-production-env.py --env-file .env.production
```

## RBAC

Permissions are intentionally split:

- `configuration.packages.read`
- `configuration.packages.build`
- `configuration.packages.seal`
- `configuration.packages.export`
- `configuration.packages.import`
- `configuration.deployments.read`
- `configuration.deployments.plan`
- `configuration.deployments.approve`
- `configuration.deployments.apply`
- `configuration.deployments.rollback`

Organization Admin and IT Manager receive the full control set by default.
Security Officer receives read-only package and deployment evidence. SaaS Root
must always select an explicit tenant and cannot use an implicit global scope.

For production deployments, the requester cannot approve their own request.
Application is blocked until a different authorized user approves it.

## Standard local-to-server procedure

### 1. Build

1. Open **Admin & Security → Пакеты конфигурации**.
2. Select the organization if operating as SaaS Root.
3. Create a stable package, for example `service-desk-core`.
4. Select component domains.
5. Use source environment `local`.
6. Enter a meaningful change summary and build the version.

The server captures current published configuration only. Runtime records,
history, user IDs, health counters, and credentials are excluded.

### 2. Validate and seal

Review:

- component and dependency counts;
- validation errors and warnings;
- manifest integrity indicator;
- selected configuration scope.

Choose **Проверить и запечатать**. A sealed version is immutable and gains a
manifest signature. If a draft is invalid, fix the source configuration and
build a new version; do not modify a signed artifact.

### 3. Export

Download the `.sbs-config.json` artifact. Move it through an approved,
integrity-preserving channel. The artifact is not confidential by design, but
it remains controlled operational configuration.

### 4. Import on the target

1. Open the target server control plane.
2. Select the target tenant.
3. Paste the complete artifact JSON into **Импорт артефакта**.
4. Enter the import reason.
5. Import.

The server rejects an unsupported format, oversized package, invalid
component hash, invalid HMAC signature, missing dependency, forbidden secret
field, embedded credential-like URL, database identifier, or invalid domain
definition.

### 5. Dry-run

Create a deployment for `staging` or `production`. Store and review:

- operation counts and per-component actions;
- plan SHA-256;
- target-state fingerprint;
- validation output;
- package version and target environment.

`NOOP` means the portable state already matches. No deletes are planned.

### 6. Approval and apply

For production:

1. Request approval.
2. A different user with `configuration.deployments.approve` reviews and
   approves.
3. An authorized operator applies the deployment.

For development, test, and staging, a validated plan may be applied directly
or sent through the same approval flow.

Immediately before writing, the server rebuilds the target fingerprint. Any
intervening configuration edit causes a drift error and a new dry-run is
required. Application is transactional. A domain failure rolls back writes and
records a failed-deployment result.

External systems, mappings, and webhooks are always imported disabled. Bind
target credentials, validate connectivity, and activate them through the
integration administration workflow after deployment.

## Rollback

Rollback is available only for an applied deployment with a valid before
snapshot.

- Updated workflows and custom-field sets are restored as new immutable
  published versions.
- Updated mutable configuration is restored to its captured portable state.
- Newly created objects are archived, retired, made inactive, or disabled.
- Objects are never destructively deleted by package rollback.

Review `snapshot_before_sha256`, the resulting `result_sha256`, and audit
events after rollback. A rollback is itself durable evidence and cannot be
re-applied from the same deployment record.

## Failure response

| Symptom | Expected response |
| --- | --- |
| Invalid signature | Verify both environments use the approved trust key; do not bypass validation |
| Missing dependency | Rebuild the source package with dependency closure |
| Forbidden secret field | Remove the secret from source metadata and rotate it if it was exposed |
| Local draft conflict | Publish, discard, or otherwise resolve the target draft before promotion |
| Target drift | Review the intervening change and create a new dry-run |
| Global legacy code conflict | Rename/migrate the legacy notification or external-system code |
| Apply failed | Inspect failure evidence; no partial transaction is accepted |
| Integration imported inactive | Bind target credentials, test, then activate separately |

## Evidence retained

Each deployment retains:

- immutable package version reference;
- idempotency key;
- target environment;
- dry-run plan and hash;
- target-state fingerprint;
- requester, reviewer, applier, and rollback actors;
- timestamps, reasons, review comment, and error;
- before-snapshot hash;
- apply/rollback result and hash;
- audit events for every governance transition.

Runtime acceptance remains part of the accumulated release gate: migration,
database regression, multi-user four-eyes scenario, readiness, and browser
acceptance must be executed when the privileged runtime is available.
