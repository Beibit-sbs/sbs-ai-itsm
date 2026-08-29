# Advanced Change Governance Runbook

## Purpose

This runbook governs the advanced Change Management controls exposed at
`/change-calendar` and `/api/v1/change-governance`. It supplements the core RFC
process in `CHANGE-MANAGEMENT-RUNBOOK.md`.

The control objectives are:

- prevent work during blackouts and detect competing change windows;
- keep Standard Changes inside a reviewed, preauthorized scope;
- preserve CAB/ECAB agenda, decision, and evidence;
- require implementation and validation evidence before closure;
- require an independently approved PIR for high-risk outcomes;
- measure change success, failure, emergency rate, and delivery lead time.

## Roles and segregation of duties

| Activity | Change operator | Change approver | SaaS Root |
|---|---:|---:|---:|
| Read calendar, readiness, tasks, PIR, analytics | Yes | Yes | Yes |
| Create/update RFC tasks | Yes | Yes | Yes |
| Create maintenance or blackout windows | No | Yes | Yes |
| Author Standard Change models | No | Yes | Yes |
| Run CAB/ECAB and record decisions | No | Yes | Yes |
| Submit PIR | Yes | Yes | Yes |
| Approve PIR authored by another operator | No | Yes | Yes |

An operator cannot approve their own PIR. Existing RFC requester self-approval
protection also remains active.

## Maintenance and blackout calendar

1. Select the organization when acting as SaaS Root.
2. Create a `MAINTENANCE` window for an approved service period or a `BLACKOUT`
   window for a prohibited period.
3. Define the time zone, concrete start/end, and optional service,
   environment, or asset scope.
4. Confirm the window appears on the 42-day calendar.
5. Before scheduling an RFC, review its window assessment and readiness score.

Scheduling is blocked when:

- the RFC overlaps an applicable active blackout;
- another scheduled or implementing RFC overlaps on the same service,
  environment, or linked asset;
- the implementation window is invalid.

Only an `EMERGENCY` change can override a blackout. The scheduling transition
must carry an explicit justification. The platform records the actor, time,
reason, transition history, and audit event. The override is an exception, not
a way to convert normal work into an emergency.

## Standard Change lifecycle

1. Create a versioned model with a unique code, complete implementation,
   testing, rollback, and validation plans.
2. Define task templates as `IMPLEMENTATION`, `VALIDATION`, or `ROLLBACK`.
3. Define the approved scope, including `maximum_assets` where applicable.
4. Set both governance review and preauthorization expiry dates.
5. Instantiate an RFC from the model instead of copying an old RFC.

Instantiation is rejected if the model is inactive, expired, due for review,
or the selected asset count exceeds its approved scope. Model-created RFCs
retain the model identifier and receive fresh executable tasks. They do not
share task state with the template.

After every closed, failed, or rolled-back model-based change, the model
reliability counters are updated. Disable and review a model when its failure
pattern no longer supports preauthorization.

## CAB and ECAB

1. Create a meeting and assign a chair and participants.
2. Add assessed RFCs to the agenda with a recommendation and presenter.
3. Publish the agenda before the meeting.
4. Start the meeting and record each decision.
5. Attach decision evidence, including quorum confirmation, rollback review,
   and collision review where applicable.
6. Record minutes and complete the meeting.

Agenda decisions are append-only evidence: the decision, actor, timestamp,
comment, and evidence object remain tied to the meeting and RFC.

Use ECAB only for time-critical emergency decisions. ECAB does not waive
rollback, evidence, blackout-override, or PIR controls.

## Implementation, validation, and rollback tasks

- Required `IMPLEMENTATION` tasks must be completed with evidence before the
  RFC can move from `IMPLEMENTING` to review.
- Required `VALIDATION` tasks must be completed with evidence before closure.
- `FAILED` and `SKIPPED` required tasks do not satisfy a gate.
- Rollback tasks document the approved recovery sequence and its evidence.
- Optimistic versions protect tasks from stale concurrent updates.

The readiness panel is the pre-flight checklist. A score is informational; any
failed blocking check still prevents the governed transition.

## Post-implementation review

A PIR is required for:

- emergency changes;
- high or critical risk changes;
- changes that required an outage;
- failed or rolled-back outcomes.

The author records outcome, objective attainment, actual impact/outage,
incidents caused, lessons learned, and follow-up actions. After submission, a
different authorized operator reviews and approves it. Required PIR approval
must exist before the RFC can close.

## Operational monitoring

Review the Analytics tab at least weekly:

- change success rate;
- change failure rate;
- emergency change rate;
- average lead time;
- average implementation duration;
- open execution tasks;
- overdue Standard Change reviews.

Investigate declining success or rising emergency rate by service, model,
owner, and window. Correct the model or operating process before restoring
preauthorization.

## Recovery and troubleshooting

- HTTP 409 means stale version, active collision, invalid state, or expired
  governance authority. Refresh the record and reassess; do not retry blindly.
- HTTP 422 means missing evidence, invalid scope, incomplete readiness, or an
  invalid transition request.
- HTTP 404 for a SaaS Root organization view usually means the selected tenant
  no longer exists or the record belongs to another tenant.
- Do not update governance tables directly. Correct records through the API so
  history and audit evidence stay consistent.

