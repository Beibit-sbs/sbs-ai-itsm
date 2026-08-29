# Major Incident Management Runbook

## Purpose

This runbook defines the operating procedure for SEV1/SEV2 incidents in the
SBS AI ITSM Major Incident Command Center.

## Roles

- Incident Commander owns priorities, decisions, lifecycle transitions, and
  the war-room rhythm.
- Communications Lead owns stakeholder/public updates and communication
  cadence.
- Technical Lead coordinates diagnosis and mitigation.
- Scribe maintains the authoritative timeline.
- SMEs and stakeholders participate without replacing the named commander.

Every named internal responder must be an active user in the incident tenant.
External participants may be recorded with a display name and contact.

## Declaration

1. Open `Major Incidents` and select `Объявить Major Incident`.
2. Select the authoritative P1/P2 parent Ticket.
3. Choose SEV1 or SEV2, Incident Commander, and Communications Lead.
4. Record confirmed executive summary, impact statement, affected service,
   customer impact, and war-room URL.
5. Declare the incident. The system creates an immutable milestone, sets the
   communication deadline, and records an audit event.
6. Add related Tickets as children. A child Ticket can belong to only one
   Major Incident.

Default communication cadence is 30 minutes for SEV1 and 60 minutes for SEV2.
The command center flags overdue communication.

## Active response

1. Add Technical Lead, SME, Scribe, and stakeholder participants.
2. Move the incident from `DECLARED` to `MITIGATING`.
3. Publish only confirmed facts. Choose audience, delivery channel, and
   current service status.
4. Use `INTERNAL` for technical facts that must not leave the response team.
   `STAKEHOLDERS` and `PUBLIC` updates require a channel.
5. Recalculate CMDB impact when the CI graph or parent Ticket changes.
6. Record technical events, decisions, milestones, and stakeholder updates in
   the authoritative timeline.
7. Assign corrective actions with owner and future due date.

Allowed service states are `MAJOR_OUTAGE`, `PARTIAL_OUTAGE`, `DEGRADED`,
`OPERATIONAL`, and `UNKNOWN`.

## Resolution and closure

1. Enter `MONITORING` after mitigation is stable.
2. Return to `MITIGATING` if symptoms recur.
3. Resolve only after service validation. Resolution sets service state to
   `OPERATIONAL`.
4. Prepare the Post-Incident Review with summary, root cause, contributing
   factors, lessons learned, and prevention plan.
5. A different authorized user must approve the PIR. The preparer cannot
   self-approve it.
6. Close only after the PIR is approved. Approved PIR content is immutable.
7. Complete actions with verifiable completion evidence; overdue actions
   remain visible after incident closure.

## Control and audit expectations

- Major Incident reads and mutations use the Ticket permission boundary.
- Tenant isolation is enforced for parent/child Tickets, responders, actions,
  and all detail reads.
- Lifecycle, communications, team, child-link, PIR, and action mutations are
  audited.
- Incident, PIR, and action updates use optimistic versions where concurrent
  edits would be unsafe.
- The timeline is append-only through the product API.

## Operational checks

- Active SEV1 count has a named commander and communications lead.
- `Comms overdue` is zero or has an explicitly owned recovery action.
- Every resolved incident has a complete PIR in progress.
- Every closed incident has an independently approved PIR.
- Overdue corrective actions are reviewed at least daily.
- CMDB impact is recalculated when its saved assessment is stale.

