# Advanced Problem Management Runbook

## Purpose

Use `/problem-governance` with the core `/problems` register to detect recurring
incidents, prove root cause, govern corrective actions, and measure KEDB value.

## Proactive trend workflow

1. Select the organization and scan the last 30 days.
2. Review cluster signature, baseline/current volume, growth, score, priority,
   and member incidents.
3. Acknowledge a credible signal, dismiss only with evidence, or convert it.
4. Conversion creates a tenant-safe proactive Problem and links every cluster
   incident as immutable investigation scope.

Trend signatures normalize category and stable title terms. A dismissed signal
reopens if a later scan finds the recurrence again.

## Structured RCA

Choose Five Whys, Ishikawa, Fault Tree, or a custom evidence structure.

- Five Whys requires at least three answered steps.
- Ishikawa requires at least three populated cause categories.
- Fault Tree requires a structured tree.
- Every method requires a problem statement, evidence, contributing factors,
  and a defensible conclusion.

Submit the RCA for independent review. The author cannot approve it. Approval
copies the governed conclusion to the Problem root cause and records history
and audit evidence.

## Corrective and preventive actions

Each action has a type, accountable owner, due date, required flag, and
measurable effectiveness criterion.

```text
OPEN -> IN_PROGRESS -> IMPLEMENTED -> VERIFIED
                                  \-> INEFFECTIVE
```

Implementation requires evidence. Effectiveness review requires a 0–100 score,
observation evidence, and a reviewer other than the owner. Required actions
must be `VERIFIED` before the Problem can close.

An ineffective action returns the investigation to improvement planning; do
not mark it verified merely to clear the closure gate.

## KEDB value

When a Known Error is viewed or applied, record usage and optionally the linked
Ticket, minutes saved, avoided escalation, and helpful/not-helpful feedback.
Review views, applications, helpfulness, time saved, and avoided escalations.
Low value means the workaround needs correction, discoverability improvement,
or retirement.

## Operating controls

- Refresh records after HTTP 409 optimistic-version conflicts.
- Treat HTTP 422 as missing governance evidence, not a retry condition.
- SaaS Root must select a tenant before running a trend scan.
- Never update RCA, action, trend, or usage tables directly.
- Review overdue actions and open high-score trends weekly.

