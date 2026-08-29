# Service catalog and request fulfillment runbook

## Scope

This runbook covers catalog categories, services, offerings, catalog items,
versioned forms, entitlements, publication, request submission, approvals,
fulfillment tasks, rework, cancellation, cost visibility, and SLA handling.

## Roles

- Catalog Owner: owns service/item content and lifecycle.
- Business Owner: approves entitlement, cost, and business outcome.
- Fulfillment Manager: owns assignment, capacity, and task completion.
- Approver: decides only requests within assigned scope.
- Requester: sees only entitled published items and their own requests.
- Organization Admin: configures tenant catalog controls but does not bypass
  four-eyes or immutable history.

## Publish a catalog item

1. Create or update the draft service, offering, item, and form version.
2. Define requester eligibility, role/group/department rules, price/currency,
   expected delivery, SLA/OLA references, support group, and owner.
3. Validate form keys, types, required fields, conditional logic, defaults,
   attachment limits, and sensitive-field behavior.
4. Preview as at least one entitled and one non-entitled user.
5. Submit for review; reviewer must not be the latest author where four-eyes is
   required.
6. Publish the approved version. Do not mutate a published version in place.
7. Run one non-production request through approval and fulfillment.
8. Attach item/form versions, reviewer, decision, and smoke request to evidence.

Safe default: draft or incomplete items are not orderable.

## Request lifecycle

Normal flow:

```text
submitted -> approval (if required) -> fulfillment -> completed
```

Alternative governed outcomes:

- rejected: approver records a bounded reason;
- rework: fulfillment returns a specific item/task with explanation;
- cancelled: requester/manager uses an allowed state transition;
- failed: operator triages durable activity/audit evidence and retries only
  idempotent work.

Every write request must carry a unique idempotency key where the API contract
requires one. Reusing the same key and payload returns the same durable request;
reusing a key with a different payload fails closed.

## Approval and fulfillment operations

1. Verify approver scope, request state, request/form version, cost, and SLA.
2. Reject self-approval or cross-tenant access.
3. Record approval decision and reason; never edit historical decisions.
4. Assign fulfillment tasks to an eligible user/group.
5. Complete tasks only after required outputs are present.
6. If rework is needed, identify the exact item/field/task and preserve prior
   activity.
7. Complete the request only when all required items/tasks are terminal.

## Troubleshooting

Item is not visible:

- confirm item and parent service/offering are published;
- confirm effective dates, entitlement rules, tenant scope, and user status;
- confirm the published form version is valid;
- inspect denial evidence without exposing another tenant's catalog.

Request cannot submit:

- compare submitted form version and schema hash with the published version;
- inspect required/conditional fields and attachment limits;
- verify idempotency key behavior and entitlement at submission time;
- do not bypass validation with direct database edits.

Approval is missing:

- verify approval policy snapshot, assigned approver/group, and current state;
- inspect notification delivery/queue metrics;
- reassign only through an audited administrative action.

Fulfillment is stalled:

- inspect unassigned/overdue tasks, owner availability, SLA target, queue/worker
  readiness, and recent activity;
- use governed rework/reassignment; never delete tasks or activities.

## Monitoring and capacity

Track request submission/completion rate, approval age, fulfillment task age,
SLA warnings/breaches, notification failures, queue/outbox age, and repeated
idempotency conflicts. Peak and soak acceptance must include the approved
catalog request mix.

## Archive and rollback

- Retire catalog items to stop new orders while preserving historical requests.
- Roll back by publishing an approved prior configuration as a new version.
- Never delete a version referenced by a request, approval, activity, task,
  audit, cost, or SLA snapshot.

## Evidence

Store tenant, item/service/form version IDs, schema/source hashes, author/reviewer,
entitlement cases, request/approval/task timelines, SLA outcome, audit
correlation, and rollback decision. Do not store secrets or sensitive form values
in release evidence.
