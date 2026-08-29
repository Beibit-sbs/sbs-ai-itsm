# WF-001 — Versioned Workflow Engine

Status: **implementation complete; runtime release gate pending**

Date: 2026-07-29

## Outcome

The platform now has a production-oriented workflow engine alongside the
legacy Automation Rules implementation. The new engine adds governed
versioning, deterministic simulation, durable runtime state, role-bound
approvals, bounded retry/compensation, replay, and tamper-evident execution
history.

No runtime-completion claim is made. The local environment currently blocks
the privileged pytest/Docker and native production frontend-build gates. The
implementation continued with all available non-privileged static gates.

## Delivered

### Data and lifecycle

- Additive Alembic migration `20260729_0052`.
- Tenant-scoped definitions with `ACTIVE`, `PAUSED`, and `ARCHIVED` lifecycle.
- Single editable draft and immutable `PUBLISHED`/`RETIRED` versions.
- Definition SHA-256, validation result, change summary, author, publisher, and
  rollback lineage.
- Optimistic revisions for workflow, draft, and approval mutation.
- Rollback creates a new published version instead of rewriting history.

### Definition engine

- Conditions with explicit operators and deterministic branching.
- Allowlisted actions for ticket, notification, integration, variable, and
  controlled-failure use cases.
- Durable waits and approvals with separate approved/rejected/timeout paths.
- Bounded DAG validation, reachability, terminal-node and cycle checks.
- Template resolution from context, variables, and previous step output.
- Secret-like field rejection, nesting limits, context size limit, and
  allowlisted node/action types.
- Side-effect-free simulation trace.

### Runtime

- Execution binding to the exact immutable workflow version.
- Tenant/workflow idempotency and PostgreSQL transaction advisory locking.
- Active-execution backpressure and `ALLOW`/`SERIALIZE` concurrency policy.
- Per-step bounded retry and exponential backoff.
- Optional reverse-order compensation for completed actions.
- Timer/approval resume, cancellation, dead-letter, and replay.
- Unexpected worker errors now have bounded attempts and dead-letter
  termination.
- PostgreSQL `FOR UPDATE SKIP LOCKED` worker claiming.
- Terminal execution retention cleanup.
- Legacy event hook preserved and production workflow enqueue isolated in
  savepoints so automation cannot break the source ITSM transaction.

### Security and evidence

- Nine granular workflow RBAC permissions.
- Explicit tenant scope for SaaS Root.
- Role-bound approvals, self-approval protection, and controlled override.
- Tenant-constrained ticket actions.
- No arbitrary shell, SQL, URL, or code execution.
- Per-execution ordered SHA-256 event chain and verification endpoint.
- Audit events for create, update, draft save, publish, rollback, manual run,
  cancel, replay, approval decision, success, and failure.

### API and UI

- 20 workflow OpenAPI paths after integrity verification was added.
- Catalog, dashboard, definition/version lifecycle, validate/simulate,
  execution/recovery, event history, and approval endpoints.
- **Automation → Production Workflows** is the default automation workspace.
- Admin interface includes metrics, tenant selection for SaaS Root, workflow
  creation, JSON draft editor, validation, dry-run, publish, rollback, status
  controls, execution step detail, cancel/replay, and approval queue.
- Legacy Overview, Rules, Executions, Runbooks, Approvals, and Templates remain
  available for transition.

## Tests as code

`backend/tests/test_workflow_engine.py` covers:

- malformed retry values failing closed without crashing validation;
- cycle rejection;
- secret-like field rejection;
- deterministic condition simulation;
- immutable published versions;
- idempotent execution submission;
- successful version-bound execution;
- ordered hash-chain linkage;
- valid chain verification and tamper detection.

## Static acceptance completed

- Ruff passed for the full backend after implementation.
- Python compileall passed.
- TypeScript `tsc --noEmit` passed.
- OpenAPI generation succeeded and exposed the workflow control plane.
- Alembic reported exactly one head: `20260729_0052`.

The complete static gate is rerun and recorded in the execution ledger before
the next stage is marked ready.

## Deferred runtime gate

Still required when the local runtime is available:

1. Apply migration `0052` to PostgreSQL and rehearse downgrade/upgrade.
2. Run focused workflow tests and the full backend suite.
3. Run the production frontend build.
4. Start API, worker, PostgreSQL, and Redis from the target release.
5. Prove duplicate concurrent submission, worker replica ownership, retry,
   wait, approval, timeout, compensation, dead-letter, replay, and retention.
6. Prove cross-tenant denial and role/self-approval controls.
7. Perform browser acceptance of the Production Workflows workspace.

## Operational reference

See `docs/operations/WORKFLOW-ENGINE-RUNBOOK.md`.
