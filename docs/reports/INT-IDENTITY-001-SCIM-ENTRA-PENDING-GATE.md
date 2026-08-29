# INT-IDENTITY-001 SCIM / Entra Provisioning — Pending Runtime Gate

**Date:** 2026-07-29  
**Status:** implementation complete; runtime acceptance pending  
**Migration head:** `20260729_0046`

## Delivered

- tenant-scoped Entra and generic SCIM connectors with lifecycle, rotating
  one-time bearer credentials, digest-only storage, optional CIDR allowlist,
  safe defaults, counters, versioning, RBAC, and audit;
- SCIM 2.0 discovery, User and Group CRUD/PATCH, supported filters, pagination,
  ETag concurrency, RFC-shaped error responses, and immutable external IDs;
- request-id/payload idempotency with replay-safe stored results;
- joiner/mover/leaver user lifecycle, manager hierarchy, approved profile
  mapping, group-to-role mapping, authoritative-source drift protection,
  reactivation, deactivation, session revocation, and audit;
- atomic offboarding with ownership reassignment for operational ITSM work,
  approvals, assets, direct reports, and major-incident responsibilities;
- persisted provisioning event log, savepoint rollback, exponential retry,
  dead-letter, worker processing, manual replay, and transfer history;
- dedicated administration workspace for setup, connectors, one-time secrets,
  identities, offboarding preview, groups/roles, events, and transfers;
- focused acceptance tests for discovery/security, idempotent joiner, mover,
  ETag, manager resolution, group role mapping, Entra member removal, leaver
  reassignment, transaction rollback, dead-letter, and tenant isolation;
- additive migration and expanded enterprise identity runbook.

## Static acceptance evidence

- Ruff and Python compile checks passed.
- TypeScript `tsc --noEmit` passed.
- OpenAPI exposes the SCIM and Identity Provisioning administration surfaces.
- Alembic has one head: `20260729_0046`.
- `git diff --check` passed.

## Pending runtime gate

Privileged runtime execution remains unavailable until 2026-08-04 and the
native production frontend bundle remains sandbox-blocked by `EPERM`. Run
`test_identity_provisioning.py`, the full backend regression, migration
upgrade/downgrade rehearsal on PostgreSQL, production frontend build, worker
retry exercise, Entra on-demand provisioning, browser acceptance, readiness,
and smoke suites when the gate is available.

No runtime completion claim is made.
