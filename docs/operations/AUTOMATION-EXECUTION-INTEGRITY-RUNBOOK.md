# Automation execution integrity

## Purpose

This runbook governs the classic automation rules, action logs, retries,
approvals, and manual runbooks under `/api/v1/automation`. The production
workflow engine remains the preferred orchestration control plane. Classic
automation must nevertheless preserve tenant isolation and honest execution
evidence.

An automation run is successful only when every action performed a confirmed
internal side effect. Logging a preview, requesting an unavailable action, or
starting a manual checklist is not completion evidence.

## Status semantics

Action status:

- `success`: a governed internal database side effect was created or updated;
- `simulated`: a preview/log record was created, but no external delivery or
  export occurred;
- `skipped`: the action was unavailable, unsupported, lacked tenant-scoped
  context, or required approval;
- `failed`: the action raised an execution error;
- `dry_run`: the action was planned but not executed.

Run status is derived from its action logs:

- all confirmed internal actions: `success`;
- confirmed plus simulated/skipped actions: `partial`;
- simulated actions without confirmed effects: `simulated`;
- only skipped actions or no actions: `skipped`;
- any failed action: `failed`;
- an explicit preview: `dry_run`.

The success-rate dashboard counts only `success`/`completed`, never
`partial`, `simulated`, `skipped`, `manual_pending`, or `dry_run`.

## Email and report previews

`send_mock_email` and `create_mock_email_log` create a local
`EmailMessageLog` with:

- `provider=mock_automation`;
- `status=SIMULATED`;
- `sent_at`, `accepted_at`, and `delivered_at` unset;
- `delivery_confirmed=false`;
- an explicit error/message stating that no external email was sent.

`export_report_mock` returns `exported=false`. Use the production email channel
or integration platform when remote delivery is required. Never convert a mock
log to `SENT`, `ACCEPTED`, or `DELIVERED`.

## Tenant isolation

- Ticket lookup includes the effective execution tenant.
- Non-root users cannot execute another tenant's rule or runbook.
- Non-root users cannot retry another tenant's execution.
- Route-level reads use tenant filters before invoking the service.
- A tenant/global rule executed for a tenant stores that effective tenant on
  the run, action logs, notifications, approvals, and audit records.
- A runbook and linked ticket must resolve to the same tenant.

Cross-tenant resource identifiers return not found and must not change target
records.

## Conditions and action definitions

Malformed condition documents, non-list condition collections, non-object
conditions, and missing condition paths fail closed. Empty valid conditions
mean an unconditional rule.

Rule actions must be a list of at most 50 objects. Runbooks contain at most 100
steps. Text, timeout/cooldown, priority, step, and checklist inputs are bounded.
Unknown or unimplemented action types are skipped; there is no successful
no-op fallback.

## Manual runbooks

Starting a runbook through the classic run route creates `manual_pending` with
`completion_confirmed=false`. Starting a governed checklist requires at least
one step. The current step cannot exceed the stored checklist, completion is
rejected until the final step is reached, and terminal executions are
immutable.

Operator confirmation is evidence that the documented steps were performed; it
does not prove an external system action unless a separate production connector
record confirms it.

## Historical evidence

Migration `20260729_0070`:

- reclassifies `mock_automation` email delivery as `SIMULATED` and clears all
  delivery timestamps;
- reclassifies known mock/no-op action logs;
- recalculates affected run statuses as simulated, skipped, or partial;
- changes falsely completed classic runbooks to `manual_pending`;
- invalidates generated demo run and runbook-completion evidence.

Downgrade cannot recreate invalidated delivery or completion evidence.

## Verification

Run:

```powershell
python scripts/validate_automation_execution_integrity.py
python scripts/run_local_release_gate.py
```

In staging, retain evidence for:

1. successful internal notification/comment/assignment actions;
2. mock email with no transport timestamps;
3. unsupported action producing `skipped`;
4. mixed actions producing `partial`;
5. malformed conditions not matching;
6. cross-tenant rule, runbook, ticket, and retry attempts returning not found;
7. early runbook completion returning conflict;
8. representative PostgreSQL upgrade through `20260729_0070`.

Any mock email marked sent/delivered, successful no-op, cross-tenant mutation,
or checklist completed before its final step is a release-blocking integrity
incident.
