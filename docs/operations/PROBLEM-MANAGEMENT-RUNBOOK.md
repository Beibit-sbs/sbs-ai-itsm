# Problem Management / KEDB Runbook

## Purpose

This runbook governs reactive and proactive Problem records, root-cause analysis (RCA),
Known Error publication, corrective action, effectiveness validation, and closure.

The module is not a replacement for Incident Management:

- incidents restore service and communicate with affected users;
- problems remove or control the underlying cause of recurring incidents;
- Known Errors publish a verified workaround while permanent correction is pending;
- Change Requests control production implementation of corrective actions.

## Roles and permissions

- IT agents can read, create, update, and investigate Problems.
- IT managers and organization administrators can publish Known Errors, resolve, close,
  reopen, and retire workarounds.
- Security officers have read-only access for assurance and investigation.
- Knowledge managers can read Problems and publish or retire KEDB entries.
- Requesters cannot access internal Problem or KEDB records.

Every mutation is tenant-scoped, permission-checked, version-checked, written to the
Problem history, and added to the tamper-evident audit chain.

## Lifecycle

| Status | Meaning | Allowed next states |
| --- | --- | --- |
| `NEW` | Candidate accepted into Problem Management | `INVESTIGATING`, `CANCELLED` |
| `INVESTIGATING` | Evidence collection and RCA are active | `ROOT_CAUSE_IDENTIFIED`, `CANCELLED` |
| `ROOT_CAUSE_IDENTIFIED` | Root cause has evidence | `KNOWN_ERROR`, `RESOLVED` |
| `KNOWN_ERROR` | Root cause and actionable workaround are published | `KNOWN_ERROR`, `RESOLVED` |
| `RESOLVED` | Permanent correction applied; validation pending | `CLOSED`, `INVESTIGATING` |
| `CLOSED` | Effectiveness validated | `INVESTIGATING` |
| `CANCELLED` | Candidate was invalid or duplicated | terminal |

Publishing an updated workaround keeps the record in `KNOWN_ERROR`. A Known Error remains
searchable after the Problem is resolved or closed until an authorized operator retires it.

## Intake and prioritization

Create a reactive Problem when multiple incidents indicate a shared underlying cause.
Create a proactive Problem from monitoring trends, capacity review, vendor advisories,
security analysis, or failure prediction before material incidents occur.

Required intake evidence:

- clear title, description, and observed symptoms;
- reactive or proactive classification;
- impact and urgency;
- service/category and detection source when known;
- affected incident, asset, and corrective RFC relationships when available;
- target resolution date for time-sensitive risk.

Priority is calculated by the backend from impact × urgency:

- `P1`: score 12–16;
- `P2`: score 8–11;
- `P3`: score 4–7;
- `P4`: score 1–3.

Three or more linked incidents classify the record as recurring for summary analytics.

## RCA control

1. Move `NEW` to `INVESTIGATING` when an owner accepts the analysis.
2. Correlate incident timelines, affected CIs, telemetry, deployments, and environmental
   changes.
3. Reproduce the failure where safe and test competing hypotheses.
4. Use `IDENTIFY_ROOT_CAUSE` only when the causal explanation is supported by evidence.
5. Keep investigation notes in the evidence field and immutable lifecycle history; do not
   overwrite audit data.

The API rejects root-cause evidence shorter than the minimum evidence threshold and rejects
publication before RCA is complete.

## Known Error publication

Use `PUBLISH_KNOWN_ERROR` when the root cause is known and an operationally safe workaround
has been verified. Publication requires:

- a searchable Known Error title;
- documented root cause;
- an actionable workaround with enough detail for a Service Desk agent;
- manager, organization administrator, or Knowledge Manager authorization.

Agents see active KEDB entries in the Service Desk ticket card and can open the full KEDB
search at `/problems`. Do not publish destructive recovery steps, credentials, secrets, or
unverified vendor commands.

## Correction, validation, and closure

1. Link corrective RFCs before production implementation where a controlled change is
   required.
2. Use `RESOLVE` only after the permanent correction is implemented and resolution evidence
   is recorded.
3. Observe a validation period appropriate to the failure frequency and business impact.
4. Use `CLOSE` only with evidence that recurrence and service KPIs were checked.
5. Use `REOPEN` with a reason if the symptoms recur; resolution and closure evidence are
   cleared from the active record but preserved in history.
6. Retire an active workaround only after resolution/closure and with an explicit reason.

## Concurrency and relationship safety

All patch and transition requests carry `expected_version`. HTTP 409 means another operator
updated the record; reload it, review the new history, and reapply the intended decision.

Ticket, Asset, and Change links are validated against the Problem tenant. Missing or
cross-tenant records return HTTP 422 and no partial mutation is committed.

## API operations

- `GET /api/v1/problems` — filtered Problem register.
- `GET /api/v1/problems/summary` — aging, recurrence, KEDB, and critical metrics.
- `GET /api/v1/problems/known-errors` — active searchable Known Error Database.
- `GET /api/v1/problems/{id}` — RCA evidence, relationships, and immutable history.
- `POST /api/v1/problems` — create Problem record.
- `PATCH /api/v1/problems/{id}` — update assessment and relationships.
- `POST /api/v1/problems/{id}/transitions` — controlled lifecycle action.

## Operational review

Review at least weekly:

- open and overdue Problems;
- P1/P2 aging and owner coverage;
- Problems with three or more related incidents;
- Known Errors without corrective RFCs;
- workarounds that remain published after closure;
- reopen rate and incidents recurring after closure;
- evidence quality for RCA, resolution, and effectiveness validation.
