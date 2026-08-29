# BACKUP, RESTORE, AND DISASTER RECOVERY RUNBOOK

## 1. Service objectives

Local engineering targets:

- RPO: no more than 24 hours;
- RTO: no more than 30 minutes to a healthy application and authenticated
  smoke test;
- backup schedule: every day at 02:00 local time;
- retention: 7 daily, 4 weekly, and 6 monthly recovery points per artifact
  stream.

These targets are accepted for local engineering. The service owner must
approve business RPO/RTO before server cutover.

## 2. Backup set

A recoverable set contains all of the following:

| Component | Artifact | Protection |
|---|---|---|
| PostgreSQL | `*.dump.enc` and manifest | custom-format dump, AES-256-GCM, SHA-256, schema revision |
| Runtime data | `*.tar.gz.enc` and manifest | safe relative paths, AES-256-GCM, per-file SHA-256 |
| Run evidence | `runs/*.json` | timing, project, both artifact manifests, retention result |
| Cryptographic secrets | secret-manager recovery set | separate from backup artifacts; never commit or print |

The PostgreSQL backup does not contain filesystem attachments. A database dump
without its matching runtime-data archive and encryption key is incomplete.

## 3. Daily local schedule

The Windows task `SBS AI ITSM Local Backup` is enabled and runs daily at
02:00 as the interactive local user. It calls:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File C:\projects\sbs-ai-itsm-foundation-001\scripts\run-local-backup.ps1
```

The wrapper backs up project `sbs-itsm-staging`, applies retention only after
both encrypted artifacts and manifests are complete, and reports status to
Alertmanager at `http://127.0.0.1:9093`.

Inspect or run the task:

```powershell
schtasks.exe /Query /TN "SBS AI ITSM Local Backup" /V /FO LIST
schtasks.exe /Run /TN "SBS AI ITSM Local Backup"
```

The local task requires the user session and Docker Desktop to be available.
At server cutover, replace it with a systemd timer or the approved enterprise
scheduler; do not depend on an interactive session.

Portable manual command:

```bash
python3 scripts/run-backup.py \
  --project-name sbs-itsm-production \
  --compose-file docker-compose.prod.yml \
  --env-file .env.production \
  --encryption-key-file secrets/backup_encryption_key \
  --output-root backups/scheduled \
  --alertmanager-url http://127.0.0.1:9093 \
  --apply-retention
```

## 4. Encryption and key recovery

`scripts/backup_crypto.py` uses streaming AES-256-GCM. Authentication failure,
truncation, an incorrect key, or a modified ciphertext blocks restore.

Create the backup key for an existing local secret set:

```bash
python3 scripts/init-production-secrets.py \
  --directory secrets \
  --ensure-backup-encryption-key
```

The key must be:

- readable only by the backup/recovery operator;
- stored separately from copied backup artifacts;
- included in the approved secret-manager recovery procedure;
- restored together with the source `mfa_encryption_key`,
  `credential_encryption_key`, and other application secrets when rehearsing a
  full environment recovery;
- paired with a point-in-time-consistent backup of the
  `email_attachment_data` volume whenever the production email channel is in
  use.

Losing `backup_encryption_key` permanently loses the encrypted recovery set.

## 5. Retention and copy policy

`scripts/backup-retention.py` implements grandfather-father-son retention
separately for database and runtime-data streams. It is dry-run by default.
Deletion requires `--apply`.

```bash
python3 scripts/backup-retention.py \
  --root backups/scheduled \
  --daily 7 --weekly 4 --monthly 6
```

Local-first phase:

- artifacts remain under the Git-ignored `backups/` directory;
- access is limited to the local platform owner;
- the encryption key remains under the Git-ignored secret directory;
- the daily task is the authoritative local schedule.

Server go-live policy:

- keep at least three copies on two storage types with one copy outside the
  server trust boundary;
- use immutable/versioned object storage or an approved backup appliance;
- copy only encrypted artifacts and manifests;
- keep encryption keys in the approved secret manager, not in the same backup
  bucket;
- monitor copy completion and test restore from the off-site copy.

External/off-site storage is intentionally deferred by the local-first
decision. Server cutover is blocked until its destination, access roles,
immutability, and deletion policy are configured.

## 6. Isolated database restore

Never perform the first restore into an active environment.

1. Prepare a new Compose project, environment file, and recovered secret set.
2. Start only its PostgreSQL service.
3. Restore the encrypted artifact with explicit confirmation.
4. Start the complete stack and wait for health checks.
5. Restore runtime data into an empty isolated path.
6. Run smoke, data, audit, and integrity checks.

Example:

```bash
docker compose \
  --project-name sbs-itsm-drill \
  -f docker-compose.prod.yml \
  --env-file .env.drill.local \
  up -d --wait postgres

python3 scripts/postgres-snapshot.py restore \
  --project-name sbs-itsm-drill \
  --compose-file docker-compose.prod.yml \
  --env-file .env.drill.local \
  --snapshot backups/db/<snapshot>.dump.enc \
  --encryption-key-file secrets.drill/backup_encryption_key \
  --confirm-restore

docker compose \
  --project-name sbs-itsm-drill \
  -f docker-compose.prod.yml \
  --env-file .env.drill.local \
  up -d --build --wait

python3 scripts/runtime-data-backup.py restore \
  --archive backups/data/<runtime-data>.tar.gz.enc \
  --target-root backups/runtime-restore \
  --encryption-key-file secrets.drill/backup_encryption_key \
  --confirm-restore
```

Restore safeguards:

- manifest SHA-256 is verified before database changes;
- AES-GCM authenticates the complete ciphertext;
- database restore uses `--single-transaction` and `--exit-on-error`;
- runtime restore rejects absolute paths, traversal, links, and device files;
- a non-empty runtime target is rejected;
- active production must never be the first restore target.

## 7. Recovery validation

Required acceptance checks:

- Alembic revision equals application head;
- critical table counts match the recovery point;
- tenant distribution is unchanged;
- no orphan tenant-scoped records;
- no invalid PostgreSQL indexes or unvalidated constraints;
- restored attachment hashes match their manifest;
- liveness, readiness, frontend, metrics, Grafana, and Alertmanager pass;
- privileged login, identity lookup, and logout pass;
- audit-chain integrity returns `valid=true` with no failures;
- backend, worker, and migration logs have no error-level events.

Do not compare mutable audit totals after smoke literally: login/logout adds new
valid audit events. Compare the snapshot baseline, required alert events, and
the chain-integrity result.

## 8. Backup failure alert

`scripts/run-backup.py` submits `SbsDatabaseBackupFailed` with severity
`critical`, project, diagnostic, and this runbook to the Alertmanager API if
database backup, runtime-data backup, manifest creation, retention, or
notification fails. It resolves the alert only after the whole backup set is
complete.

Operator response:

1. Acknowledge within 15 minutes.
2. Preserve the last known-good recovery set.
3. Check Docker/PostgreSQL health, free disk, permissions, key availability,
   and Alertmanager connectivity.
4. Re-run without deleting the failed partial evidence.
5. Verify both manifests and close only after a successful run.
6. Escalate to the Platform Owner after two consecutive failures or when the
   RPO target is at risk.

## 9. Ownership and recovery decisions

| Responsibility | Local owner | Server-cutover owner |
|---|---|---|
| Incident commander / go-no-go | Platform Owner | Service Owner |
| Database restore | Platform Owner | Platform/Database Operations |
| Secret recovery and access review | Platform Owner | Security Operations |
| ITSM functional validation | Platform Owner | ITSM Process Owner |
| Off-site storage and retention | deferred | Infrastructure/Backup Operations |

Decision points:

- If the source is healthy and only schema deployment failed, prefer a
  forward-fix.
- If corruption or destructive change is suspected, stop writes and restore
  into a new project.
- If the snapshot or key fails authentication, reject it and select an earlier
  verified recovery point.
- If restored counts, tenant boundaries, attachment hashes, or audit integrity
  fail, recovery is `NO-GO`.
- Cut over traffic only after technical and functional validation and an
  explicit incident-commander decision.

## 10. Prohibited actions

- Restoring directly into the active environment as the first test.
- Passing `--confirm-restore` without resolving the exact target project.
- Keeping the only encryption key beside the only backup copy.
- Running retention with `--apply` against a path outside `backups/`.
- Treating successful `pg_dump` as a complete backup without attachments,
  manifests, and a restore drill.
- Running `docker compose down -v` as a routine recovery step.
