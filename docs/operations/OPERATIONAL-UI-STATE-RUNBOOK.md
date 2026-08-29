# Operational UI state contract

Status: `STATIC_CONTRACT_IMPLEMENTED_RUNTIME_ACCEPTANCE_PENDING`  
Owner: Service Experience  
Control: `UX-OPERATIONAL-UI-STATES`

## Purpose

Production operators must be able to distinguish a genuinely empty queue from
an authorization failure, backend outage, timeout, or partial source failure.
An API error must never be rendered as a valid zero KPI.

## Required states

Every operational query surface has five distinct states:

1. loading — progress is announced with `role="status"` where useful;
2. data — current or safely retained cached records are rendered;
3. empty — shown only after a successful response with no matching records;
4. failed — affected sources are named, values use `—`, and retry is available;
5. denied — the permission-aware route and action boundary remains explicit.

Composite consoles use `QueryFailureNotice` to aggregate independent source
failures without hiding healthy panels. Primary queues keep local diagnostics
next to the affected list or detail panel.

## Static acceptance

Run:

```powershell
python scripts/validate_operational_ui_states.py
```

The validator covers Dashboard, Requests, Catalog, Changes, Problems, Major
Incidents, Event Operations, Automation, Identity Provisioning, Integrations,
Email Operations, Teams Collaboration, Configuration Packages, Release
Management, Problem Governance, Change Governance, Monitoring, Workflow Engine,
Integration Platform, Asset Discovery, AI Governance, CMDB Quality, SLA,
Analytics, Assets & CMDB, Custom Fields, Service Desk, and System Diagnostics.
Nested AI Actions, AI Privacy & FinOps, and Catalog Form Designer queries are
covered by the same contract.

It is also part of `scripts/run_local_release_gate.py`.

## Runtime acceptance

For each representative operator role:

1. load the console with healthy APIs and retain a screenshot;
2. interrupt one read endpoint or inject a controlled `5xx`;
3. verify the affected source is named and no false zero/empty state appears;
4. restore the endpoint and use the visible retry action;
5. verify data returns without a new login and the alert clears;
6. repeat with a forbidden source and confirm the permission boundary stays
   authoritative.

Runtime evidence must include timestamps, role, tenant, endpoint, correlation
ID, screenshots before/after, and the final recovery result. Static validation
does not satisfy this runtime acceptance.
