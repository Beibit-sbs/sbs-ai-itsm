# PRG-001 — Staging Production Topology

## Result

Status: `COMPLETED_LOCAL`

Date: 2026-07-28

The complete production Compose topology was built and verified in the
isolated local project `sbs-itsm-staging`. The local acceptance gate is green.
By explicit roadmap decision, server hosting, DNS, and trusted TLS are deferred
until the local platform implementation is complete.

## Topology

- PostgreSQL 17 with a persistent data volume.
- Redis 8 with authentication and persistence.
- One-shot Alembic migration service.
- FastAPI backend and separate Redis worker.
- Nginx frontend.
- Prometheus, Alertmanager, and Grafana.
- Internal `data` network for database, queue, metrics, and worker traffic.
- Loopback-only host publication:
  - application: `127.0.0.1:8080`;
  - Grafana: `127.0.0.1:3000`;
  - Alertmanager: `127.0.0.1:9093`.
- Backend, PostgreSQL, Redis, worker, and Prometheus have no host-published
  ports.

The local proof intentionally did not issue public DNS or a trusted
certificate. `BACKEND_CORS_ORIGINS` is already restricted to the planned HTTPS
staging origin.

## Configuration and secret posture

- Runtime env: `.env.staging.local` (git-ignored).
- Runtime secrets: `secrets/` (git-ignored).
- `APP_ENV=production`.
- `DEMO_MODE=false`.
- `RUN_STARTUP_DDL=false`.
- Redis is used for jobs and realtime dashboard transport.
- All required credentials are distinct, non-placeholder Docker secret files.
- No inline secret is present in the runtime env.
- The first-deploy root password was rotated.
- `BOOTSTRAP_ROOT_EMAIL` was removed.
- The bootstrap secret mount was removed from backend.
- The obsolete `bootstrap_root_password` file was deleted.
- The rotated local root credential is stored in the ignored
  `secrets/root_admin_password` file pending migration to an approved secret
  manager.
- OIDC is intentionally disabled until the enterprise provider is selected.
- Privileged MFA is in monitor-only mode pending enrollment.

## Reproducible commands

Preflight:

```powershell
python scripts/check-production-env.py --env-file .env.staging.local
```

First-deploy build and launch:

```powershell
docker compose --project-name sbs-itsm-staging `
  -f docker-compose.prod.yml `
  -f docker-compose.bootstrap.yml `
  --env-file .env.staging.local `
  up -d --build
```

Bootstrap rotation:

```powershell
python scripts/rotate-bootstrap-root.py `
  --env-file .env.staging.local `
  --base-url http://127.0.0.1:8080
```

Normal runtime after removing `BOOTSTRAP_ROOT_EMAIL`:

```powershell
docker compose --project-name sbs-itsm-staging `
  -f docker-compose.prod.yml `
  --env-file .env.staging.local `
  up -d --force-recreate
```

Authenticated smoke:

```powershell
$env:SMOKE_EMAIL = "root@staging.local"
$env:SMOKE_PASSWORD = (Get-Content -Raw secrets/root_admin_password).Trim()
python scripts/smoke-production.py `
  --env-file .env.staging.local `
  --base-url http://127.0.0.1:8080 `
  --grafana-url http://127.0.0.1:3000 `
  --alertmanager-url http://127.0.0.1:9093
Remove-Item Env:SMOKE_PASSWORD
Remove-Item Env:SMOKE_EMAIL
```

## Acceptance evidence

### Preflight and Compose

- Production preflight: `39 OK`, `1 WARN`, `0 FAIL`.
- The single warning is the deliberate monitor-only MFA posture.
- Compose configuration: valid.
- Python deployment utilities: syntax validation passed.
- Deployment-tooling tests: `4 passed`.
- Full backend regression: `504 passed`, `16 skipped`.
- Frontend and backend images: built successfully.

### Database and runtime

- Migration service: `Exited (0)`.
- Alembic current revision: `20260727_0028 (head)`.
- PostgreSQL: healthy.
- Redis: healthy.
- Backend: healthy.
- Frontend: healthy.
- Worker: running.
- Prometheus: running.
- Alertmanager: running and ready.
- Grafana: running with database health `ok`.
- Current runtime error/fatal/panic/traceback log scan: `0` matches.

### Smoke and observability

The production smoke utility passed:

- liveness;
- readiness with database, Redis, Alembic, and runtime checks;
- frontend delivery;
- anonymous denial for protected APIs;
- anonymous denial and token-authenticated access for metrics;
- Grafana health;
- Alertmanager readiness;
- root login, identity, and logout after password rotation.

Prometheus evidence:

- active targets: `1`;
- healthy targets: `1`;
- unhealthy targets: `0`;
- `promtool check config`: success;
- alert rules loaded: `5`.

### Container security

Backend, worker, frontend, Prometheus, Alertmanager, and Grafana were verified
with:

- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- writable paths restricted to declared volumes or tmpfs.

Only frontend, Grafana, and Alertmanager are published to the host, and all
three bind to `127.0.0.1`.

## Defects found and remediated

1. Production Compose hard-coded `.env.production` inside services even when
   another `--env-file` was supplied.
   - Added `APP_ENV_FILE` and validated that it matches the preflight target.
2. Bootstrap email could leak into migrate and worker service environments.
   - Explicitly disabled bootstrap in base services; only the bootstrap overlay
     can enable it for backend.
3. Frontend Docker context included local `node_modules` and broke image
   assembly.
   - Added frontend and backend `.dockerignore` files.
4. Secret generation on Windows wrote CRLF. Redis treated the remaining
   carriage return as part of its password.
   - Changed generation to byte-level LF output and added safe normalization
     for existing secrets.
5. Alertmanager v0.33 returns `200 OK` with body `OK`, while smoke expected the
   word `ready`.
   - Accepted both valid readiness response forms.
6. Grafana attempted plugin background installation on a read-only root
   filesystem and logged missing provisioning directories.
   - Disabled preinstall/update behavior and added the provisioning
     directories.
7. Frontend healthcheck used `localhost`, which resolved to an unbound IPv6
   address in the container.
   - Switched the check to `127.0.0.1`; frontend is now healthy.

## Gate decision

- Local production-topology acceptance: `GO`.
- Local preparation for PRG-002 migration rehearsal: `GO`.
- PRG-001 local-first completion: `GO`.
- Server cutover: deliberately deferred and not treated as a blocker for
  PRG-002.

## Remaining action

Proceed to PRG-002 using isolated local PostgreSQL copies. Before eventual
server go-live, repeat the same preflight, Compose, migration, smoke,
observability, and security evidence through trusted HTTPS.
