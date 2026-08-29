# Guarded AI actions runbook

## Safety rule

An AI response is never an executable command. The platform accepts only one
of four server-defined proposal types:

- `ticket.update`;
- `ticket.classify`;
- `knowledge.draft`;
- `runbook.draft`.

The action type, target type, fields, value constraints, risk, permissions, and
handler are fixed in server code. Tenant policy can reduce this allowlist but
cannot extend it. Unknown tools, extra parameters, prompt-injection markers,
credential-like values, oversized payloads, and malformed citation evidence
fail before a proposal is stored.

## Lifecycle

1. An authorized user or Copilot creates a proposal with an idempotency key,
   rationale, bounded citation metadata, and schema-valid parameters.
2. The server stores canonical parameters and their SHA-256. The original AI
   source query is not stored; only its SHA-256 is retained.
3. Ticket proposals bind to a live tenant-scoped target fingerprint.
4. A human reviewer approves or rejects the proposal. A HIGH-risk proposal
   requires a reviewer other than its creator when four-eyes mode is enabled.
5. An authorized executor starts a fixed server handler.
6. Immediately before execution the server rechecks policy, action allowlist,
   tenant, executor permissions, expiry, parameter integrity, schema, and live
   target fingerprint.
7. The execution records canonical before/after state hashes and a bounded
   result. Audit records contain identifiers, hashes, and decisions, not raw AI
   prompts.
8. Rollback is available only while live state still matches the recorded
   post-execution state.

There is no endpoint that accepts an arbitrary tool name, URL, command, SQL,
module, or handler.

## Initial configuration

1. Apply migration `20260729_0058`.
2. Sign in as Organization Admin or IT Manager.
3. Open **AI Copilot → Guarded AI Actions**.
4. Enable only the action types approved for the tenant.
5. Keep independent approval enabled for HIGH risk.
6. Set the proposal TTL and save the policy.
7. Verify that agents who propose changes do not also hold unnecessary
   approval, execution, or rollback permissions.

No action is available before an explicit tenant policy exists.

## Action behavior

### Ticket update and classification

Only `category` and `priority` are accepted. Target tenant and current ticket
state are verified at proposal and execution time. Each changed field produces
a ticket-history entry. Rollback restores only those protected fields and
refuses if another actor changed the ticket afterward.

### Knowledge draft

Creates an internal article in `draft` state. It does not publish content.
Rollback archives the draft only when its content hash and draft state still
match the execution evidence.

### Runbook draft

Creates an inactive, approval-required runbook. It cannot execute automation.
Rollback keeps it inactive and refuses if its protected content changed or it
was activated.

## Permission separation

- `ai.actions.read`: inspect policy and proposals;
- `ai.actions.propose`: create validated proposals;
- `ai.actions.approve`: review proposals;
- `ai.actions.execute`: execute an approved proposal;
- `ai.actions.rollback`: compensate an eligible execution;
- `ai.actions.manage`: manage tenant policy.

The executor also needs the underlying domain permission, such as
`tickets.update`, `knowledge.create`, or `automation.runbooks.create`.
Permissions and tenant scope are checked again at execution time.

## Idempotency and concurrency

The pair `(tenant_id, idempotency_key)` is unique. Repeating the same request
returns the original proposal; reusing a key with changed action, target, or
parameters returns a conflict. PostgreSQL review and execution paths lock the
proposal row. Each proposal has at most one execution record.

Optimistic revision control protects policy updates. A proposal is not a lease:
expiry, policy removal, permission removal, parameter hash mismatch, or target
drift all stop execution.

## Incident response

- `Action type is not in the server allowlist`: reject the generated output;
  never add an ad hoc handler during an incident.
- `Parameters are not allowlisted`: inspect prompt/evaluation regression and
  regenerate a typed proposal.
- `Independent approval is required`: route to another authorized reviewer.
- `Ticket changed after proposal creation`: create a new proposal from the
  current ticket state.
- `Action is no longer allowed`: review tenant policy; do not bypass it.
- `automatic rollback refused`: freeze further AI actions and perform a normal
  domain-specific recovery after assessing live changes.
- repeated `FAILED` proposals: disable the affected action in tenant policy and
  review audit evidence, prompt version, and provider health.

## Release proof

Before enabling on a server, prove:

1. unknown tools, extra fields, prompt injection, and credential-like content
   are rejected;
2. cross-tenant target IDs are indistinguishable from missing targets;
3. idempotent retry returns the original proposal and conflicting reuse fails;
4. HIGH-risk self-approval fails;
5. policy, permissions, expiry, hashes, and target fingerprint are all
   revalidated immediately before execution;
6. ticket, article, and runbook actions cannot exceed their fixed handlers;
7. rollback succeeds for unchanged state and refuses after live drift;
8. audit and action tables contain no raw source query or credential material.

