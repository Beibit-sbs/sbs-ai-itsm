# CFG-002 — Configuration Packages

Status: `IMPLEMENTATION COMPLETE — RUNTIME GATE PENDING`

Date: 2026-07-29

## Delivered

- Tenant-scoped package catalog with optimistic revision and archive lifecycle.
- Immutable draft/sealed/retired versions with canonical manifest SHA-256 and
  HMAC-SHA256 signatures.
- Portable extraction for catalog, SLA, notifications, integrations,
  workflows, and custom fields.
- Automatic dependency closure plus fail-closed dependency, schema, secret,
  identifier, size, count, component-hash, manifest-hash, and signature checks.
- Secret-free integration export and target-side disabled-by-default
  activation posture.
- Version comparison and signed JSON artifact export/import.
- Target dry-run with `CREATE`, `UPDATE`, `NOOP`, `BLOCK`, target fingerprint,
  idempotency protection, and drift detection.
- Independent production approval, transactional apply, durable evidence, and
  non-destructive rollback.
- Ten granular permissions, audit coverage, explicit SaaS Root tenant scope,
  dashboard, and full administrator workspace.
- Production signing-key validation, Docker secret generation/mounting, and
  deployment preflight coverage.
- Alembic migration `20260729_0054_configuration_packages.py`.
- Tests-as-code for tamper/secret/dependency rejection, apply/rollback, and
  target-drift refusal.

## Static acceptance

- Full Ruff over `backend/app`, `backend/tests`, and migrations: passed.
- Full Python compileall over the same scope: passed.
- TypeScript `tsc -p tsconfig.app.json --noEmit`: passed.
- OpenAPI import/generation: passed; 540 total paths, including 14
  configuration-package paths and 17 operations.
- Alembic graph: passed; one head, `20260729_0054`.
- Development and production Compose configuration parsing: passed.
- `git diff --check`: passed; Windows line-ending notices only.

## Runtime acceptance deferred

No runtime completion claim is made. The environment currently cannot execute
the privileged pytest/Docker acceptance gate. The accumulated runtime gate
must later cover:

- migration `0054` upgrade and downgrade rehearsal;
- focused and full backend regression;
- artifact transfer between independently running source and target
  environments using the configured trust key;
- concurrent idempotency and PostgreSQL row-lock behavior;
- production frontend build;
- readiness and worker checks;
- two-user production approval/apply;
- target-drift refusal and rollback;
- browser desktop, narrow viewport, and keyboard acceptance.

## Primary files

- `backend/app/models/configuration_package.py`
- `backend/app/services/configuration_packages.py`
- `backend/app/api/v1/routes/configuration_packages.py`
- `backend/migrations/versions/20260729_0054_configuration_packages.py`
- `backend/tests/test_configuration_packages.py`
- `frontend/src/pages/ConfigurationPackagesPage.tsx`
- `docs/operations/CONFIGURATION-PACKAGES-RUNBOOK.md`
