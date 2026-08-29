# Event-to-Incident Operations Runbook

## Purpose

This runbook defines how monitoring events enter SBS AI ITSM, how noise is
suppressed and correlated, when a Ticket is created, and how acknowledgment
and escalation are operated.

## Create a source

1. Open `Event Operations` → `Sources & Suppression`.
2. Select the organization when operating as SaaS Root.
3. Create a source with a unique code and correct type.
4. Copy the one-time ingest token immediately. Only its final hint remains
   visible after the dialog is closed.
5. Store the token in the monitoring system's secret store. Do not place it in
   source control, screenshots, logs, or URL parameters.
6. Configure:

   - header `Authorization: Bearer <one-time-token>`;
   - header `X-Event-Source: <source UUID>`;
   - generic endpoint `/api/v1/event-operations/ingest`; or
   - Alertmanager endpoint
     `/api/v1/event-operations/ingest/alertmanager`.

Rotate a token after suspected exposure or as required by policy. Rotation
invalidates the previous token immediately.

## Generic normalized event contract

Required fields:

- `idempotency_key`: stable key for retries of the same source event;
- `external_id` and `fingerprint`;
- `state`: `FIRING` or `RESOLVED`;
- `severity`: `INFO`, `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`;
- `summary` and `occurred_at`.

Optional normalized context includes description, service, resource,
environment, labels, and annotations. Labels/annotations are bounded before
storage. Every accepted event stores a SHA-256 payload hash.

Retry the same event with the same idempotency key. It is counted as a
duplicate and never creates another correlation occurrence or Ticket.

## Correlation policy

Policies are evaluated by ascending priority. The first matching active policy
wins.

1. Define bounded matchers using `EQUALS`, `NOT_EQUALS`, `CONTAINS`, `PREFIX`,
   or `EXISTS`.
2. Define stable group fields such as `service,resource` or
   `label.alertname,resource`.
3. Choose the correlation window and occurrence threshold.
4. Select one mode:

   - `CREATE_UPDATE`: create a Ticket at threshold and append subsequent
     events as evidence;
   - `CORRELATE_ONLY`: maintain a command group without creating a Ticket;
   - `IGNORE`: retain normalized evidence but take no operational action.

5. Choose severity-derived or fixed Ticket priority, category, title template,
   and trusted recovery behavior.
6. Assign primary and fallback responders plus acknowledgment deadlines.

Policy changes use optimistic versions. Existing event/group evidence is not
rewritten when a policy changes.

## Suppression

Use a suppression only for an approved maintenance or a documented noisy
condition.

1. Record a specific matcher, owner-readable reason, start, and end.
2. Verify the time zone before activation.
3. Confirm `Suppressed / 24h` after the window begins.
4. Disable the rule when maintenance ends early.

Only firing events are suppressed. Recovery events remain eligible to resolve
an existing open group, preventing a maintenance rule from leaving incidents
permanently open.

## Triage and escalation

1. Work from `Command Queue`.
2. Review normalized evidence, payload hash, source, correlation key, and
   generated Ticket before acknowledging.
3. Acknowledge with an ownership/action note.
4. The worker checks overdue acknowledgment every 30 seconds.
5. An overdue group is reassigned to the fallback responder and creates an
   in-app notification plus Ticket/activity history. A second reminder is
   scheduled from the policy's fallback interval.
6. The manual `Проверить просроченные escalation` control is an operational
   recovery action; normal operation does not depend on it.

## Recovery behavior

The trusted `RESOLVED` source event closes the correlation group. Per-policy
Ticket behavior is:

- `NONE`: leave Ticket state under operator control;
- `RESOLVE`: set Ticket to `RESOLVED`;
- `CLOSE`: set Ticket to `CLOSED` only for a source whose recovery semantics
  are explicitly trusted.

The recovery state change is retained in the group timeline and Ticket
history.

## Noise and effectiveness review

Review at least weekly:

- source receipt, duplicate, and suppression counters;
- events, firing events, groups, and incidents for the last 24 hours;
- acknowledgment overdue and MTTA;
- noise reduction percentage;
- unmatched/ignored events;
- policies that create too many one-event incidents;
- suppressions that are broad, long-running, or never used.

Never optimize the noise metric by hiding actionable events. Changes require a
specific hypothesis and post-change review.

## Security and tenant isolation

- Source tokens are high-entropy, stored only as SHA-256 hashes, and shown
  once.
- Source UUID plus bearer token is required for ingress.
- Every source, policy, suppression, event, group, responder, and Ticket is
  tenant-bound.
- Configuration requires integration-management permissions.
- Queue reads and acknowledgment use Ticket permissions.
- Source/policy/suppression, acknowledgment, and escalation actions are
  audited.

