# SBS AI ITSM — isolated production rehearsal

Date: 2026-08-14 12:14 +05:00  
Project: `sbs-itsm-rehearsal`  
Result: `PASS_LOCAL_PRODUCTION_LIKE`

## Isolation and safety

- The rehearsal used `.env.rehearsal.local`, `secrets.rehearsal/`, dedicated
  Docker networks, volumes and loopback ports.
- The primary local SQLite database was not modified.
- No production, staging or local-development volume was removed.
- Secret values were neither printed nor copied into evidence. Existing
  rehearsal credentials were preserved; only missing independently rotatable
  secrets were generated.

## Confirmed runtime

- Production configuration preflight: `66 OK / 2 WARN / 0 FAIL`.
- Current backend, worker, migration and frontend images built successfully.
- PostgreSQL 17 and Redis 8 are healthy.
- Alembic migration service exited `0`; the current database revision is
  `20260814_0080 (head)`.
- Backend and frontend healthchecks are healthy.
- Prometheus, Grafana and Alertmanager are running in the isolated stack.
- Fresh runtime log scan found `0` error/critical/exception signatures.
- Final backend/frontend images have `0` High/Critical CVE; current dependency,
  SAST, history/worktree secret scans and SBOM generation pass. Passive OWASP
  ZAP has `0 FAIL`, `4 WARN` rule IDs and `63 PASS`.

## Authenticated production smoke

The smoke journey passed all required checks:

1. liveness;
2. readiness including PostgreSQL, Redis, migrations and runtime;
3. frontend HTML through the reverse proxy;
4. anonymous access rejection on a protected API;
5. authenticated Prometheus metrics;
6. Grafana health;
7. Alertmanager readiness;
8. login, authenticated identity and logout.

A dedicated active `requester` smoke account was provisioned through an
operator-only, rehearsal-confirmed command. It is not root and not superuser.
Its password remains only in the ignored rehearsal secrets directory.

## Defects found and fixed

1. The rehearsal configuration had 25 preflight failures. Missing trusted
   proxy/network identity, Prometheus, CloudWatch namespace, demo-seed safety
   and additive secret settings were corrected.
2. The production frontend restart-looped because the read-only filesystem
   prevented nginx template rendering. A bounded tmpfs with unprivileged
   ownership is now used only for `/etc/nginx/conf.d`.
3. The smoke client could not test a strict public `Host` while connecting to
   loopback. It now supports a validated public Host header without weakening
   `TrustedHostMiddleware`.
4. Restored tenants could lack standard roles. The production system seed now
   creates missing system roles idempotently for existing tenants while leaving
   custom roles untouched. The rehearsal now has 12 standard roles for two
   tenants.
5. Existing secret directories had no safe additive upgrade path. The secret
   initializer now adds only missing independently rotatable files and never
   overwrites existing credentials.
6. Periodic work previously shared the queue worker process. A separate
   leader-elected scheduler now owns periodic cycles through a renewable Redis
   lease and publishes readiness/heartbeat metrics.
7. Prometheus could not scrape horizontally scaled backend replicas because
   strict Host validation rejected Docker DNS targets. The metrics endpoint now
   permits that Host only with the exact metrics bearer token; all other routes
   remain strict.
8. The dead-letter list contained duplicated acceptance failures. Three exact
   jobs were acknowledged through the governed API, all Redis occurrences were
   removed, and the database lifecycle rows plus audit evidence were retained.
9. Software Asset Management was absent. Migration `0078` adds tenant-scoped
   products, licenses and installations; the API/UI now provide compliance,
   prohibited/unauthorized software, renewals and cost-at-risk reconciliation.
10. Tickets had no governed participant/watcher workflow and the Notification
    Center was tenant-scoped instead of recipient-scoped. Migration `0079`
    adds participant roles and preferences; notification list/count/read
    operations are now personal by default and tenant-wide access requires
    `notifications.manage`.
11. Ticket creation stored the requester but not the actual registrar, accepted
    requester contact without persisting it and had no governed on-behalf
    workflow. Migration `0080` adds creator/contact/channel/reason fields; a
    dedicated permission, tenant user directory, mandatory reason,
    anti-impersonation checks, history and tamper-evident audit now protect the
    workflow.

## Continuation acceptance — scheduler, observability, SAM and participants

- Three backend replicas are healthy and Prometheus reports `3/3` scrape
  targets healthy.
- The scheduler owns one live Redis lease; readiness is `1` and the worker does
  not execute duplicate periodic cycles.
- The observability catalog contains 8 SLOs, 21 alerts and 20 Grafana panels.
- Controlled Alertmanager correlation
  `codex-observability-20260814-scheduler-v2` produced exactly one firing and
  one resolved audit event after duplicate delivery.
- The governed dead-letter queue is `0`; three historical failure rows and
  three acknowledgement audit events remain preserved.
- Clean Docker builds of backend, migration and frontend passed. The frontend
  build includes the lazy `SoftwareAssetsPage` production chunk.
- PostgreSQL upgraded transactionally through `0079` to `0080`; `alembic
  current` reports `20260814_0080 (head)`.
- All three SAM tables are protected by tenant foreign keys, constraints,
  indexes, optimistic versions, RBAC and tamper-evident audit actions.
- Latest focused SAM/migration/authentication acceptance: 10 passed, 0 failed.
- Existing system roles were backfilled idempotently: organization admin and IT
  manager receive all SAM permissions, IT agent receives read access, requester
  remains denied (`HTTP 403`).
- All three backend replicas, worker, scheduler and frontend were rebuilt from
  the same source revision after migration `0080`; readiness reports PostgreSQL,
  Redis, migrations, runtime and websocket transport as ready.
- Requester browser smoke confirms the participant tab, self-watch event scope
  and channel controls. RU/KK/EN labels render, and browser console errors are
  zero. Focused participants/notifications/auth/migration/localization tests:
  26 passed, 0 failed.
- On-behalf runtime acceptance confirms the five new PostgreSQL columns and
  permission assignment only to root, organization admin, IT manager and IT
  agent. The live stack has three healthy backend replicas, healthy frontend,
  worker and scheduler; readiness is HTTP 200 with PostgreSQL, Redis,
  migrations, runtime and websocket transport ready. Seventy-three focused
  test executions, TypeScript, Vite production build, accessibility and
  interactive-control audits passed. The 769-test monolithic regression hit a
  20-minute process timeout without reporting a failed test and is therefore
  not represented as a full-suite PASS.

## Evidence

Machine-readable evidence:
`docs/audit/evidence/P0-PRODUCTION-REHEARSAL-2026-08-14.json`, SHA-256
`6dbb04223dd363e9c5c0dd27a893ea8587912b536b5b8b80a289587ac4114c85`.

Security evidence:
`docs/audit/evidence/P0-SECURITY-GATE-2026-08-14.json`, SHA-256
`b6b01b57adfc4bec18a1ab5c41851dd17819545fc7f9d91a6c2aceeb057b4b42`.

## Remaining boundary

This is a strong local production-like acceptance, not permission to expose the
system publicly. Server DNS/TLS and active scan, real IdP/MFA enrollment,
external providers, production discovery/license inventory feeds, server-sized
load/soak and golden clean-tenant E2E remain separate release conditions.
