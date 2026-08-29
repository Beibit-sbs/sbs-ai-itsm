# Production Workflow Engine Runbook

## Purpose

This runbook covers the tenant-scoped, versioned workflow engine introduced by
`WF-001`. It is separate from the legacy Automation Rules and Runbooks screens.
Both engines can consume the same domain event while workflow adoption is
phased.

The production engine provides:

- draft, publish, retire, and rollback lifecycle;
- optional four-eyes review before publication;
- immutable execution binding to a published version and SHA-256 definition;
- conditions, actions, waits, approvals, branches, retry, compensation, and
  terminal nodes;
- reusable, version-bound child workflows through `SUBFLOW` nodes;
- idempotent automatic/manual/replay execution;
- tenant-scoped action execution and approval authorization;
- durable worker recovery and dead-letter handling;
- tamper-evident per-execution event history;
- operator UI under **Automation → Production Workflows**.

## Components

| Component | Responsibility |
| --- | --- |
| `workflow_definitions` | Mutable workflow identity, status, trigger and concurrency policy |
| `workflow_versions` | Draft and immutable published/retired definitions |
| `workflow_executions` | Durable runtime state, context, cursor, retry and replay lineage |
| `workflow_step_executions` | Per-node attempts, output, wait and compensation state |
| `workflow_approvals` | Role-bound approval task with optimistic version |
| `workflow_execution_events` | Ordered SHA-256 hash chain for runtime evidence |
| jobs worker | Claims due executions, resumes waits and approvals, applies retry policy |

Migration: `20260729_0052_workflow_engine.py`.

## Access model

Permissions are intentionally separated:

- `workflows.read`
- `workflows.design`
- `workflows.publish`
- `workflows.execute`
- `workflows.executions.read`
- `workflows.executions.manage`
- `workflows.approvals.read`
- `workflows.approvals.decide`
- `workflows.approvals.override`
- `workflows.reviews.read`
- `workflows.reviews.request`
- `workflows.reviews.decide`

Organization Administrators receive all controls. IT Managers can design,
publish, execute, recover, and decide tasks assigned to their role. IT Agents
can read, execute, and decide tasks assigned to `it_agent`. Security Officers
have read-only evidence access. SaaS Root bypasses permission checks but must
provide an explicit tenant scope.

An approval can be decided only by its configured `approver_role`, unless the
actor has `workflows.approvals.override`. Self-approval is denied by default.

When **Four-eyes review** is enabled for a workflow, a valid draft must be
submitted for review before publication. The requester, original author, and
last editor cannot approve it. Any draft edit or governance toggle invalidates
the previous review evidence.

## Definition lifecycle

1. Create the workflow. It starts `PAUSED` with draft version 1.
2. Edit only the draft. Published and retired rows are never edited.
3. Save the draft and resolve every validation error.
4. Run a dry-run with representative, non-secret context.
5. If four-eyes governance is enabled, submit the draft and have a different
   authorized user approve it.
6. Inspect the structural diff against the currently published version.
7. Publish with a change-ticket/comment. The previous published version becomes
   `RETIRED`; the new version becomes `PUBLISHED`.
8. Activate or pause the workflow separately when required.
9. Rollback selects an older published/retired definition and creates a new
   immutable published version. History is never rewritten.

Concurrent edits use `revision` fields. HTTP `409` means the operator must
reload current state before retrying.

## Minimal definition

```json
{
  "schema_version": "1.0",
  "trigger": {"type": "ticket_created"},
  "entrypoint": "priority_gate",
  "on_failure": "COMPENSATE",
  "nodes": [
    {
      "key": "priority_gate",
      "type": "CONDITION",
      "name": "Critical priority?",
      "config": {
        "path": "context.ticket.priority",
        "operator": "eq",
        "value": "CRITICAL"
      },
      "next": {"true": "manager_approval", "false": "end"}
    },
    {
      "key": "manager_approval",
      "type": "APPROVAL",
      "name": "Manager approval",
      "config": {
        "approver_role": "it_manager",
        "timeout_minutes": 60,
        "allow_self_approval": false
      },
      "next": {
        "approved": "notify",
        "rejected": "end",
        "timeout": "end"
      }
    },
    {
      "key": "notify",
      "type": "ACTION",
      "name": "Notify operations",
      "config": {
        "action": "notification.create",
        "recipient_email": "ops@example.test",
        "title": "Critical ticket ${context.ticket.id}",
        "message": "Approved for response"
      },
      "retry": {"max_attempts": 3, "backoff_seconds": 30},
      "next": "end"
    },
    {
      "key": "end",
      "type": "END",
      "name": "Complete",
      "config": {}
    }
  ]
}
```

Templates can read `context`, `variables`, and completed `steps`. Definitions
and execution context reject secret-like field names. Tokens, passwords,
private keys and provider credentials must remain in governed connector
configuration, never in workflow JSON.

## Safe actions

The initial action catalog is intentionally allowlisted:

- add ticket comment;
- set ticket priority;
- assign a ticket;
- transition ticket status;
- create an in-app notification;
- emit an event to governed outgoing webhook subscriptions;
- set an execution variable;
- explicitly fail a workflow for controlled testing.

Each ticket lookup includes the execution tenant. Arbitrary code, shell, SQL,
URL, and credential actions are not supported.

## Visual designer and reusable subflows

The administration workspace offers three synchronized definition views:

- **Visual** — accessible form controls for nodes, configuration, retries,
  branches, entrypoint, and failure policy;
- **JSON** — exact schema representation for advanced changes and review;
- **Diff** — server-generated JSON-pointer comparison between immutable
  versions.

Changing visual fields updates the same JSON definition. An `UNSAVED` marker
protects local edits from polling refreshes. Reordering cards changes visual
organization only; graph routing is defined by explicit branch selectors.

A `SUBFLOW` node invokes another active workflow in the same tenant:

```json
{
  "key": "shared_notification",
  "type": "SUBFLOW",
  "name": "Shared notification policy",
  "config": {
    "workflow_code": "shared_notification",
    "context": {
      "entity_type": "${context.entity_type}",
      "entity_id": "${context.entity_id}"
    },
    "max_wait_seconds": 86400,
    "failure_policy": "FAIL"
  },
  "next": "end"
}
```

The parent waits durably for the version-bound child. Subflow depth is limited
to five, direct self-invocation is denied, child context is secret-scanned, and
parent cancellation cascades to its owned non-terminal child. `CONTINUE`
accepts a failed child as an explicit branch policy; `FAIL` fails the parent.

## Execution semantics

- Automatic triggers match only `ACTIVE` workflows with a published version.
- Manual execution may run a published paused workflow for controlled testing.
- The tuple `(workflow_id, idempotency_key)` is unique.
- PostgreSQL advisory locks serialize concurrent submissions of the same key.
- Each execution stores its exact version ID, version number, and context.
- `max_active_executions` applies backpressure; overflow becomes `DROPPED`.
- `SERIALIZE` defers a workflow while another non-terminal execution is active.
- Action retry is bounded to 10 attempts and exponential backoff is capped.
- Unexpected worker failures are bounded by execution `max_attempts`; exhausted
  executions become `DEAD_LETTER`.
- Replay creates a new execution bound to the original immutable version.
- Waits and approvals are durable and resume through `next_run_at`.
- Subflows are durable and resume through `WAITING_SUBFLOW`.
- Cancellation and every privileged control action are audited.

## Worker operation

The standard jobs worker runs the workflow cycle approximately once per second.
It claims due rows with PostgreSQL `FOR UPDATE SKIP LOCKED`, allowing multiple
replicas without duplicate ownership.

Configuration:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `WORKFLOW_WORKER_BATCH_SIZE` | `50` | Due executions claimed per cycle |
| `WORKFLOW_MAX_CONTEXT_BYTES` | `262144` | Maximum serialized context |
| `WORKFLOW_EXECUTION_RETENTION_DAYS` | `180` | Terminal execution retention |

The hourly cleanup deletes only terminal executions older than retention.
Versions and definitions are not removed by this cleanup.

## Incident response

### Execution remains queued

1. Confirm the jobs worker is running.
2. Check application logs for `workflow_cycle_failed`.
3. Inspect `next_run_at`, `status`, `attempts`, and `last_error`.
4. Verify migration head `20260729_0052`.
5. Restart only the worker process after the underlying dependency is healthy.

### Execution is in dead letter

1. Open the execution and inspect step failures.
2. Confirm whether the failing action produced any business-side effect.
3. Correct connector, data, or workflow configuration.
4. Use **Replay**. The replay uses the original version by design.
5. If behavior must use a new definition, publish a new version and start a new
   execution instead of replay.

### Approval is not visible

1. Verify the task is `PENDING` and not expired.
2. Verify the signed-in user role equals `approver_role`.
3. Use override permission only for an authorized break-glass procedure.
4. Confirm tenant scope and self-approval policy.

### Integrity verification fails

1. Stop deleting or editing workflow evidence.
2. Call `GET /api/v1/workflows/executions/{id}/events/verify`.
3. Preserve the database snapshot and application logs.
4. Escalate as a security incident. Do not “repair” hashes in place.
5. Restore from trusted evidence only after investigation.

## Deployment and rollback

Before migration:

1. Take a database backup using the deployment procedure.
2. Confirm exactly one Alembic head.
3. Deploy backend and worker from the same release.
4. Apply migration `0052`.
5. Deploy frontend.

Release acceptance must prove:

- migration upgrade and downgrade rehearsal;
- workflow validation and dry-run;
- publish immutability and rollback-as-new-version;
- idempotent submission and tenant isolation;
- action retry, timer resume, approval decision and timeout;
- dead-letter and replay;
- event-chain verification;
- worker replica claim safety;
- browser acceptance for designer, history, and approvals.

If the application must be rolled back before any workflow data is used, revert
the application and downgrade migration `0052`. Once workflows are in use,
prefer an application forward-fix; a database downgrade destroys workflow
definitions and execution evidence.
