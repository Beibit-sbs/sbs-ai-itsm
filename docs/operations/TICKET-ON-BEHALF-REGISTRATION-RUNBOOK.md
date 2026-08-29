# Ticket on-behalf registration runbook

## Purpose

The workflow lets an authorized service-desk employee register a ticket for an
active user in the same organization without impersonating that user. The
system preserves both identities and the business reason in the audit trail.

## Authorization

- Permission: `tickets.create.on_behalf`.
- Standard roles: SaaS root, organization admin, IT manager and IT agent.
- Requester does not receive this permission and cannot access the requester
  directory or override their own identity.
- Candidate lookup and ticket creation are tenant-scoped and active-user only.

## Operator procedure

1. Open **Tickets** and select **Create ticket**.
2. In **Requester**, keep **For myself** for a self-created ticket or select an
   active organization user.
3. Verify requester contact, department and location populated from the user
   profile; correct ticket-specific values when necessary.
4. For another requester, enter a factual reason of at least three characters.
   Do not place passwords, tokens, medical data or unrelated personal data in
   the reason.
5. Complete category, priority, description and optional asset/assignee, then
   submit.
6. In the ticket overview verify **Registered by** and registration channel.
   The protected audit entry contains the submitted reason.

## Stored evidence

- `requester_id`, requester name/email snapshot and requester contact;
- `created_by_id` and creator name snapshot;
- `creation_channel`: `SELF_SERVICE`, `ON_BEHALF` or `LEGACY`;
- `on_behalf_reason` for an on-behalf record;
- ticket history event `created_on_behalf` without exposing the reason;
- tamper-evident audit action `ticket_created_on_behalf` with actor, requester
  and reason.

## Failure handling

- HTTP 403: confirm the operator has `tickets.create.on_behalf`; never grant it
  to the requester role as a workaround.
- HTTP 400 unknown/inactive requester: reactivate through the approved identity
  lifecycle or select the correct tenant user; do not bypass tenant scope.
- HTTP 422 reason required: enter a real business reason.
- Directory load failure: check `/api/v1/health/readiness`, current migration
  and operator session permissions before retrying.
- Suspected misuse: preserve ticket/audit IDs, revoke the operator session if
  necessary and follow the security incident process. Do not edit audit rows.

## Release verification

1. `alembic current` reports `20260814_0080 (head)` or a later connected head.
2. Readiness is HTTP 200 and migration check is `ok`.
3. Permission exists only on approved roles.
4. Requester candidate directory rejects the requester role.
5. Cross-tenant and inactive requester IDs are rejected.
6. On-behalf creation without a reason is rejected.
7. Successful creation returns different requester/creator IDs and
   `creation_channel=ON_BEHALF`.
8. History and audit evidence exist, while the reason is absent from requester
   history and notification content.

