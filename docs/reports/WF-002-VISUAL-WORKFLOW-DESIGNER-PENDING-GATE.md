# WF-002 — Visual Workflow Designer

Status: **implementation complete; runtime release gate pending**

Date: 2026-07-29

## Outcome

The versioned engine now has an accessible visual administration surface,
server-authoritative structural diff, optional four-eyes publication review,
and reusable tenant-scoped subflows.

The stage builds on migration `20260729_0052`; it was extended before runtime
application so the repository retains a single linear migration head.

## Delivered

### Accessible visual designer

- Node cards for `CONDITION`, `ACTION`, `WAIT`, `APPROVAL`, `SUBFLOW`, and
  `END`.
- Keyboard-operable add, remove, move, type, branch, and entrypoint controls.
- Type-specific configuration, action catalog, retry/backoff, approval role,
  timeout, self-approval, wait, and subflow controls.
- Quick patterns for condition, approval gate, timer, and reusable subflow.
- Explicit graph-edge summary.
- Synchronized Visual and JSON views with unsaved-edit protection.
- Existing validation, dry-run, publish, rollback, and execution views remain
  available in the same workspace.

### Structural version diff

- Tenant-scoped comparison endpoint for versions of the same workflow.
- Integrity verification before comparison.
- Bounded RFC-6901-style JSON pointer flattening.
- Added, changed, removed, and total summaries.
- Three-column operator presentation for review before publish/rollback.

### Four-eyes publication governance

- Per-workflow `publish_approval_required` policy.
- Draft review state and immutable request/decision evidence.
- Separate read/request/decide RBAC permissions.
- Only a valid, integrity-safe draft can enter review.
- Requester, original author, and last editor cannot decide their own review.
- Any draft edit resets decision evidence.
- Publish fails closed unless the current draft review is approved.
- Review queue and approve/reject interface.
- Every request, decision, governance toggle, and publish is audited.

### Reusable subflows

- `SUBFLOW` is a first-class validated and simulated node.
- Child workflow lookup is tenant-scoped and requires an active published
  target.
- Parent/child submission is transactionally idempotent.
- Parent waits durably in `WAITING_SUBFLOW`.
- Child output and status become step evidence.
- `FAIL` and explicit `CONTINUE` child-failure policies.
- Maximum wait and maximum nesting depth.
- Direct self-invocation denied; indirect recursion bounded.
- Parent cancellation cascades through owned non-terminal descendants.

## Tests as code

The workflow test suite now additionally covers:

- four-eyes publish denial before review;
- self-review denial;
- independent review and governed publish;
- structural diff evidence;
- version-bound child enqueue;
- parent wait and resume after child success.

## Static acceptance completed

- Full backend Ruff passed.
- Full backend compileall passed.
- Frontend TypeScript `tsc --noEmit` passed.
- OpenAPI generation passed: 512 total paths, 24 workflow paths, and 27
  workflow operations.
- Alembic reported one head: `20260729_0052`.
- Development and production Compose configurations parsed successfully.
- `git diff --check` passed; only repository line-ending notices were emitted.

Runtime acceptance remains deferred under the same environment constraint as
WF-001 and must include real PostgreSQL worker concurrency, subflow
parent/child recovery, multi-user review, browser keyboard operation, and
production frontend build.

## Operational reference

See `docs/operations/WORKFLOW-ENGINE-RUNBOOK.md`.
