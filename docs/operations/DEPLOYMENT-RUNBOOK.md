# DEPLOYMENT RUNBOOK

## Prerequisites
- Docker and Docker Compose are installed.
- `.env.production` is configured locally and not tracked by git.
- Production secrets are rotated (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`).
- Backups are enabled and tested.

## First Deploy
1. Prepare env:
   - `cp .env.production.example .env.production`
   - Update production values.
2. Validate env:
   - `bash scripts/check-production-env.sh`
3. Validate compose:
   - `docker compose -f docker-compose.prod.yml config`
4. Start stack:
   - `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`
5. Run migration explicitly:
   - `make db-upgrade`
6. Verify runtime:
   - `make health`
   - `make smoke`

## Update Deploy
1. Pull latest code.
2. Run pre-update backup:
   - `bash scripts/backup-db.sh`
3. Build and restart:
   - `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`
4. Apply migration:
   - `make db-upgrade`
5. Post-deploy checks:
   - `make health`
   - `make smoke`

## Migration Procedure
- Use explicit migration command only (`make db-upgrade`).
- Verify migration state:
  - `make db-current`
  - `make db-head`
- Do not rely on startup DDL in production.

## Backup Before Update
- Always run:
  - `bash scripts/backup-db.sh`
  - `bash scripts/backup-data.sh`

## Rollback Procedure
1. Roll application images to previous known-good tag/commit.
2. Restart services with previous image set.
3. If schema rollback is required, apply controlled downgrade plan only after approval.
4. If needed, use DB restore runbook.

## Restore Procedure
- See `docs/operations/BACKUP-RESTORE-RUNBOOK.md`.

## Smoke-Check After Deploy
- `curl -sS http://localhost:8000/api/v1/health`
- `curl -sS http://localhost:8000/api/v1/health/liveness`
- `curl -sS http://localhost:8000/api/v1/health/readiness`
- Open frontend and key routes.

## Troubleshooting
- Containers unhealthy: `docker compose ps`, `make logs-backend`, `make logs-frontend`.
- Migration mismatch: `make db-current`, `make db-head`.
- Startup failures: inspect backend health and DB/Redis connectivity.
