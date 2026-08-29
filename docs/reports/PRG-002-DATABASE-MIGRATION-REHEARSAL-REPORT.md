# PRG-002 — Database Migration Rehearsal

## Result

Status: `COMPLETED_LOCAL`

Date: 2026-07-28

An isolated PostgreSQL copy was restored, populated with balanced tenant data,
downgraded to the previous Alembic revision, upgraded to the current head,
started as a complete production-like stack, and verified without changing the
primary local staging database.

## Isolation

- Source project: `sbs-itsm-staging`.
- Rehearsal project: `sbs-itsm-rehearsal`.
- Rehearsal env: `.env.rehearsal.local` (git-ignored).
- Rehearsal secrets: `secrets.rehearsal/` (git-ignored and distinct).
- Rehearsal application: `127.0.0.1:18080`.
- Rehearsal Grafana: `127.0.0.1:13000`.
- Rehearsal Alertmanager: `127.0.0.1:19093`.
- PostgreSQL, Redis, backend, worker, and Prometheus are not published to the
  host.

## Snapshot evidence

- Format: PostgreSQL custom archive.
- Size: `273145` bytes.
- SHA-256:
  `acf317329cc729c7453afcc10eb6376f41e137b03b237bdad3b024dc7173a60b`.
- Local artifact: `backups/db/prg002_source_head.dump` (git-ignored).
- Restore into the isolated project: passed.
- Restore without `--confirm-restore`: blocked with exit code `1`.

## Production-like fixture

The restored copy was extended only inside the rehearsal project:

- tenants: `2`;
- users: `3` including the copied local root;
- tickets: `50`;
- Tenant A tickets: `25`;
- Tenant B tickets: `25`;
- orphaned ticket tenant references: `0`;
- cross-tenant requester relationships: `0`.

The fixture is idempotent and stored in
`scripts/sql/migration-rehearsal-fixture.sql`.

## Migration evidence

Rehearsed path:

```text
20260727_0028 (head)
        ↓ controlled downgrade
20260720_0027
        ↓ application readiness = 503, migrations=out_of_date
20260727_0028 (head)
```

- Controlled downgrade: passed.
- Downgrade duration including container startup/build check: `5627 ms`.
- Upgrade `0027 → 0028`: passed in `1274 ms`.
- Idempotent second `upgrade head`: passed in `1209 ms`.
- Migration service after full stack launch: `Exited (0)`.
- Post-migration backend and frontend: healthy.
- Authenticated production smoke: passed.
- Actual error-level runtime log lines: `0`.

## Data and schema integrity

Pre/post migration counts were identical:

- tenants: `2 → 2`;
- users: `3 → 3`;
- tickets: `50 → 50`;
- per-tenant split: `25/25 → 25/25`.

Post-migration schema checks:

- current revision: `20260727_0028`;
- MFA tables created: `2`;
- indexes on MFA tables: `8`;
- invalid/not-ready indexes: `0`;
- unvalidated constraints: `0`;
- waiting locks after migration: `0`;
- duplicate ticket numbers: `0`;
- unknown user tenant references: `0`;
- unknown ticket tenant references: `0`.

Deployment/rehearsal tooling tests: `6 passed`.
The immediately preceding full backend regression remained
`504 passed, 16 skipped`.

## Compatibility behavior

Before upgrade, the current backend started but returned:

```text
HTTP 503
migrations=out_of_date
```

This is the required fail-closed behavior. After upgrade, readiness returned
200 and the complete login/identity/logout, frontend, metrics, Grafana, and
Alertmanager smoke journey passed.

## Lock and maintenance assessment

Migration `0028` creates two new MFA tables and their indexes. It does not
rewrite the 50 existing tickets or tenant/user rows. No waiting lock remained
after migration, and the measured local upgrade completed in 1.274 seconds.

Operational decision:

- use a short maintenance/restart window for this release;
- stop application traffic before migration;
- require the migration container to exit successfully before backend/worker;
- do not approve zero-downtime assumptions from this small dataset;
- measure large-table migrations separately under PRG-006.

## Rollback and forward-fix decision

- Default after new application traffic: forward-fix.
- Downgrade is allowed only before new-version traffic and only with a verified
  snapshot.
- The `0028` downgrade drops `user_mfa` and `mfa_login_challenges`. It is
  prohibited after MFA enrollment because it would destroy factor/challenge
  data.
- If the safe downgrade boundary is passed, restore the verified snapshot into
  a new isolated project and cut over after validation.

## Gate decision

PRG-002 local gate: `GO`.

Next stage: `PRG-003-BACKUP-RESTORE-DISASTER-RECOVERY`.
