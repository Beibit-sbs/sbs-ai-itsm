# BACKUP AND RESTORE RUNBOOK

## Database Backup
1. Ensure containers are running.
2. Run:
   - `bash scripts/backup-db.sh`
3. Backup artifact will be created in:
   - `backups/db/YYYYMMDD_HHMMSS_sbs_itsm.sql.gz`
4. Verify file exists and is non-empty.

## Data Backup (Uploads/Static)
1. Run:
   - `bash scripts/backup-data.sh`
2. If runtime directories are present, archive is created in `backups/data/`.
3. If no directories are found, script prints guidance and exits safely.

## Backup Verification
- Check backup size:
  - `ls -lh backups/db`
- Optional SQL sanity check:
  - `gzip -t backups/db/<file>.sql.gz`

## Restore Procedure
1. Confirm restore intent explicitly:
   - `CONFIRM_RESTORE=yes bash scripts/restore-db.sh backups/db/<file>.sql.gz`
2. Script blocks restore if confirmation flag is missing.
3. Script restores via `psql` into running postgres container.

## Data Safety Rules
- Never restore without a recent backup snapshot.
- Do not run `docker compose down -v` as part of routine backup/restore.
- Perform restore drills in non-production first when possible.

## Post-Restore Validation
- Run health checks:
  - `make health`
- Run smoke checks:
  - `make smoke`
- Validate key modules in browser (`/tickets`, `/assets`, `/knowledge`, `/analytics`, `/integrations`).

## Prohibited Actions
- `docker compose down -v` without explicit approved data-loss decision.
- Unverified restore from unknown or corrupted backup files.
