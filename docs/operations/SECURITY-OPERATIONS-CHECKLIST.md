# SECURITY OPERATIONS CHECKLIST

## Secrets And Credentials
- Rotate `JWT_SECRET_KEY` to a strong random value.
- Rotate `POSTGRES_PASSWORD` and verify app connectivity after rotation.
- Confirm no default demo passwords remain in production env files.
- Keep `.env.production` outside git tracking.

## Runtime Hardening
- Confirm `DEMO_MODE=false`.
- Confirm `RUN_STARTUP_DDL=false`.
- Confirm CORS origins are explicit production domains (no wildcard).
- Confirm admin/root accounts are reviewed and RBAC scope is minimal.

## Data Protection
- Verify DB backup execution (`bash scripts/backup-db.sh`).
- Verify backup artifact retention policy and storage permissions.
- Run periodic restore drills in a safe environment.
- Never run `docker compose down -v` in production operations without an approved data-loss plan.

## Network And Edge
- Enforce HTTPS/reverse proxy for external traffic.
- Restrict exposed ports with firewall/security groups.
- Ensure only required ports are reachable from untrusted networks.

## Monitoring And Audit
- Check backend/frontend/container logs regularly.
- Confirm health/readiness/liveness endpoints are reachable.
- Verify deep diagnostics are accessible only for privileged users.
- Validate external integration providers are mock-safe or explicitly disabled for non-approved environments.
