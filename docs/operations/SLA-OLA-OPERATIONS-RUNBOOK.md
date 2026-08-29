# SLA / OLA Operations Runbook

## Purpose

This runbook defines how administrators and service owners configure and
operate enterprise SLA, internal OLA, and supplier obligations in SBS AI ITSM.
It covers local operation now and the same controls after server deployment.

## Operating model

Each matching Ticket receives a versioned SLA instance. The instance stores an
immutable policy and calendar snapshot, so later configuration edits do not
silently rewrite historical commitments. A deliberate recalculation supersedes
the old instance and leaves its timeline intact.

An instance can contain:

- `RESPONSE` — first operational response;
- `RESOLUTION` — Ticket resolution;
- `FULFILLMENT` — delivery or fulfillment;
- `OLA` — an internal support-team obligation;
- `SUPPLIER` — an external supplier obligation.

The engine evaluates live targets every 30 seconds in the jobs worker. It
updates the compatibility fields on the Ticket, emits in-app escalation
notifications, and writes auditable timeline and audit records.

## Initial configuration

1. Open **SLA → Calendars**.
2. Select the organization when operating as SaaS Root.
3. Create a calendar with a valid IANA time zone, for example
   `Asia/Almaty`.
4. Confirm the working intervals for Monday through Friday.
5. Add holidays and exceptional working days.
6. Open **SLA → Policies SLA / OLA**.
7. Create one policy per priority and scope.
8. Add response and resolution targets. Add OLA or supplier targets where
   ownership crosses a team or contract boundary.
9. Set the warning threshold and ordered escalation stages.
10. Verify a newly created Ticket appears in **SLA → Control Center**.

A policy without a calendar uses elapsed 24×7 time. This is intentional and is
displayed explicitly in the UI.

## Policy selection

The engine selects an active policy by:

1. Ticket tenant before a global fallback;
2. exact priority, case-insensitive;
3. lowest `priority_order`;
4. optional exact scope for category, department, and location.

The resulting policy and calendar are snapshotted. Existing instances do not
change when an administrator edits a policy.

## Lifecycle automation

- Ticket creation starts an SLA instance.
- Assignment or entry into active work completes the response target.
- `WAITING_USER` and `WAITING_VENDOR` pause the instance only when permitted
  by its policy.
- Leaving a pause status resumes the instance and extends open deadlines by
  the business minutes consumed during the pause.
- `RESOLVED` or `CLOSED` completes the resolution target.
- `REOPENED` creates a new current instance and preserves the previous one.
- A priority change performs an auditable recalculation.
- `CANCELLED` cancels remaining targets.

Monitoring-created Tickets follow the same lifecycle. A trusted recovery event
can resolve the Ticket and complete its resolution obligation.

## Manual pause

Use a manual pause only for an approved exception:

1. Open the instance in the Control Center.
2. Enter a concrete operational justification.
3. Select **Pause SLA**.
4. Confirm the instance is `PAUSED` and an open pause record exists.
5. Resume it as soon as the exception ends.

The API rejects pause reasons not allowed by the policy. Every pause records
the actor, Ticket status, timestamps, business minutes, and reason.

## Breach response

When a target reaches `WARNING`:

1. Verify ownership and current work evidence.
2. Reassign or escalate the Ticket if the owner cannot meet the target.
3. Confirm that the configured escalation recipient received a notification.
4. Do not hide risk with an unjustified pause.

When a target reaches `BREACHED`:

1. Treat the breach queue as an operational exception queue.
2. Record the recovery action in the Ticket.
3. Complete OLA or supplier targets only with supporting evidence.
4. Review the policy, capacity, routing, and calendar after service recovery.
5. Use the immutable timeline and audit log for service review.

## Calendar safety

- Use IANA zones, not fixed UTC offsets.
- Keep intervals ordered and non-overlapping.
- Model holidays as `HOLIDAY`.
- Model an exceptional working day as `WORKING_DAY` with explicit intervals.
- Existing SLA instances retain their original calendar snapshot.
- Recalculate only when the business has approved changing an active
  commitment.

The calendar engine performs calculations in UTC while deriving interval
boundaries in the configured local zone. This preserves daylight-saving
transitions.

## Health checks

Daily:

- no unexpected growth in `BREACHED` targets;
- no stale `PAUSED` instances;
- jobs worker is running;
- escalations create notifications;
- all P1/P2 Tickets have a current instance.

Weekly:

- review warning-to-breach conversion;
- review pause reasons and durations;
- review OLA and supplier performance;
- confirm upcoming holidays;
- verify policy coverage for every active priority.

## Recovery

If the worker is unavailable, targets remain durable and their deadlines do
not change. After worker recovery, run **Check now** or:

`POST /api/v1/sla/evaluate`

The evaluation is idempotent for unchanged state. Escalation levels advance
only once.

If an incorrect policy was selected, correct the policy scope and use:

`POST /api/v1/sla/tickets/{ticket_id}/recalculate`

Do not edit due timestamps directly.

## Server cutover checks

Before production activation:

1. apply Alembic migration `20260729_0042`;
2. run focused and full backend regression;
3. verify the jobs worker executes the SLA cycle;
4. verify the production frontend bundle;
5. test a DST boundary and a holiday;
6. test pause/resume, priority change, reopen, and cancellation;
7. test tenant isolation as SaaS Root and two organization administrators;
8. confirm audit retention and notification delivery;
9. capture browser acceptance evidence for policies, calendars, queue, and
   breaches.
