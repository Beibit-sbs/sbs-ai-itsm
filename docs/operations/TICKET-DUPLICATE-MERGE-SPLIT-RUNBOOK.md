# Ticket duplicate, merge, and split runbook

## Purpose

This workflow helps the service desk identify likely duplicate tickets, record
false positives, merge a duplicate without losing evidence, and split
independent work into a child ticket. Similarity is decision support only; the
platform never merges tickets automatically.

## Authorization

| Operation | Permission | Default roles |
|---|---|---|
| View candidates | `tickets.duplicates.read` | root, organization admin, IT manager, IT agent |
| Dismiss candidate | `tickets.duplicates.manage` | root, organization admin, IT manager, IT agent |
| Merge current ticket | `tickets.merge` | root, organization admin, IT manager |
| Split child ticket | `tickets.split` | root, organization admin, IT manager, IT agent |

Normal ticket visibility still applies. A permission never reveals a ticket
outside the current tenant or the operator's queue scope. Requesters receive
none of these permissions.

## Similarity score

The candidate endpoint evaluates at most 500 recent visible, active and
unmerged tenant tickets, ranks them, and returns at most 20 by default. The
score is capped at 100 and is explainable through signal codes:

- title similarity: up to 50 points;
- same requester email: 20 points;
- same category: 15 points;
- same asset: 10 points;
- description similarity: up to 10 points;
- creation within 24 hours: 10 points; within 7 days: 5 points.

Previously dismissed or merged pairs are suppressed. Operators must compare
the actual symptoms, requester, affected service/asset and timestamps before a
decision.

## Dismiss a false positive

1. Open **Tickets**, open a ticket and select **Duplicates & split**.
2. Review the score and every visible signal.
3. Enter a factual reason of at least three characters.
4. Select **Not a duplicate**.
5. Confirm the candidate disappears after refresh and both ticket histories
   contain `duplicate_candidate_dismissed`.

The action increments both governance versions and stores score, signals,
actor, reason, pair and idempotency key in immutable evidence.

## Merge a duplicate

1. Decide which record is the primary ticket. Open the duplicate that should
   become the source.
2. In **Duplicates & split**, enter the verified reason.
3. On the primary candidate select **Merge current into this** and confirm the
   warning.
4. Verify the source shows the merged banner and link to the primary ticket.
5. Verify the primary ticket history contains the received source reference.

Merge is intentionally non-destructive:

- the source ticket remains queryable and becomes `CANCELLED`;
- `merged_into_id`, reason, actor and timestamp are saved on the source;
- comments, history, requester evidence and attachments are never deleted or
  moved;
- the target lifecycle/status is unchanged;
- both governance versions increment in one transaction;
- SLA close processing and requester status notification use the normal
  governed paths.

Only an active, unmerged source can be merged. A cancelled or already merged
ticket cannot be a target.

## Split independent work

1. Open the mixed-scope ticket and select **Duplicates & split**.
2. Enter a clear child title, optional description and split reason.
3. Select **Create child ticket**.
4. Open the resulting child and verify `parent_ticket_id` points to the source.

The child inherits tenant, requester/contact, department, location, category,
priority and asset unless the API request explicitly changes category or
priority. It receives a new atomic ticket number, independent SLA and normal
creation notification/automation. The source remains open and its governance
version increments.

## Concurrency and retry

- Every write sends expected governance versions. HTTP 409 means another
  operator changed one of the tickets; refresh and review again.
- Every write sends an idempotency key. Retrying the same operation with the
  same key returns the original evidence and does not repeat side effects.
- Reusing a key for another pair fails with HTTP 409.
- PostgreSQL row locks are acquired in stable ticket-ID order for two-ticket
  operations to reduce deadlock risk.

## Failure handling

- HTTP 403: do not broaden the role as a workaround; confirm the specific
  permission and the operator's job responsibility.
- HTTP 404: the ticket is absent or intentionally hidden by tenant/queue scope.
- HTTP 409 stale version: refresh both records and repeat the human review.
- Empty candidate list: reduce `min_score` only for investigation; never treat
  no candidate as evidence that no duplicate exists.
- Wrong merge: preserve both ticket/action/audit IDs and escalate to the ITSM
  owner. Do not edit database rows or delete history; corrective action must be
  implemented as a new governed workflow.

## Release verification

1. `alembic current` reports `20260829_0081 (head)` or a later connected head.
2. Readiness is HTTP 200 with migrations `ok`.
3. Requester candidate access fails with HTTP 403.
4. Cross-tenant candidate and merge targets remain hidden.
5. Dismissal suppresses only the reviewed pair and is idempotent.
6. Merge preserves source comments/history and is idempotent.
7. Stale governance versions fail with HTTP 409.
8. Split produces exactly one child for repeated idempotent requests.
9. Ticket histories and tamper-evident audit entries exist for every action.
10. RU/KK/EN controls, keyboard focus, TypeScript and production build pass.
