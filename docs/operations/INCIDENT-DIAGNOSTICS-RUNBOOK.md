# INCIDENT DIAGNOSTICS RUNBOOK

## Frontend Does Not Open
1. Check containers: `docker compose ps`.
2. Check frontend logs: `make logs-frontend`.
3. Validate frontend endpoint: `curl -I http://localhost:5173/`.

## Backend Returns 500
1. Check backend logs: `make logs-backend`.
2. Check basic health: `curl -sS http://localhost:8000/api/v1/health`.
3. Check readiness: `curl -sS http://localhost:8000/api/v1/health/readiness`.

## Postgres Down
1. Verify postgres service state in `docker compose ps`.
2. Check health probe inside container:
   - `docker compose exec postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"`
3. Validate `DATABASE_URL` and credentials in `.env.production`.

## Alembic Missing Column / Schema Drift
1. Compare revisions:
   - `make db-current`
   - `make db-head`
2. Apply migration:
   - `make db-upgrade`
3. Re-run health/readiness checks.

## Login Not Working
1. Verify backend auth endpoint is reachable.
2. Check backend logs for `login_failed` patterns.
3. Confirm DB connectivity and seed/account state.

## Assets/Tickets Not Loading
1. Verify `/api/v1/health/readiness`.
2. Verify backend logs for DB exceptions.
3. Confirm alembic state (`make db-current`, `make db-head`).

## Migration Failed
1. Stop repeated migration attempts.
2. Take backup immediately (`bash scripts/backup-db.sh`) before manual fixes.
3. Investigate migration error and apply controlled correction.

## Container Unhealthy
1. Inspect container-specific logs.
2. Check dependency chain (postgres/redis/backend/frontend).
3. Restart only affected services first.

## Disk Full
1. Check host disk usage.
2. Remove stale local artifacts safely (old backups/logs), keep retention policy.
3. Re-run health checks after cleanup.

## Redis Unavailable
1. Verify redis container state.
2. Test ping:
   - `docker compose exec redis redis-cli ping`
3. Validate `REDIS_URL` and network/service names.
