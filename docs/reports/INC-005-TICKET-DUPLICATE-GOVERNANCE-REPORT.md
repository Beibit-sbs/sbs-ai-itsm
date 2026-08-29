# INC-005 — ticket duplicate, merge, and split governance

Date: 2026-08-29  
Status: `COMPLETE_LOCAL`

## Delivered

- migration `20260829_0081` connected to `20260814_0080`;
- ticket parent/merge relationship, merge actor/reason/time and optimistic
  governance version;
- immutable `ticket_governance_actions` evidence with tenant/action/idempotency
  uniqueness and source/target/pair indexes;
- explainable candidate scoring with tenant, normal visibility and active-state
  filtering;
- governed false-positive dismissal with pair suppression;
- manager/admin soft merge that preserves the complete source record;
- agent/manager/admin child-ticket split with new ticket number and SLA;
- stable row-lock order, stale-version rejection and idempotent retries;
- ticket history, tamper-evident audit, SLA, notification and automation hooks;
- explicit RBAC separation for read, dismiss, merge and split;
- RU/KK/EN ticket-detail controls, merge warning/banner and relationship fields.

## Acceptance evidence

- current backend collection: 775 tests;
- new governance suite: 6/6 passed;
- migration/on-behalf compatibility preflight: 6/6 passed;
- expanded tickets/on-behalf/participants/governance regression: 33/33 passed;
- Ruff and Python compileall: PASS;
- TypeScript project build: PASS;
- local and Docker Vite production builds: PASS, 142 modules;
- accessibility baseline: PASS, 77 files / 16 dialogs;
- interactive controls: PASS, 681 buttons / 39 links;
- route authentication: 746 endpoints / 739 protected / 7 governed public;
- OpenAPI: 738 operations / 621 paths;
- PostgreSQL: `20260829_0081 (head)`;
- runtime: 3/3 backend replicas healthy, frontend healthy, worker/scheduler
  running and readiness HTTP 200.

The last complete whole-suite baseline remains 723 passed / 16 skipped. This
stage does not relabel a previous timed-out monolithic run as a full PASS; its
scope is covered by targeted regression and live PostgreSQL acceptance.

## Safety properties

- no automatic merge based on score;
- no hard delete or transfer of source comments/history;
- requesters cannot enumerate candidates or perform governance actions;
- all reads retain tenant and ticket visibility boundaries;
- merge is restricted to root/admin/manager;
- reasons, versions and stable idempotency keys are mandatory;
- every decision has immutable operational and tamper-evident audit evidence.

## Remaining external gate

Public server deployment still requires real TLS/edge acceptance, production
identity lifecycle and independent security review. Those external gates do
not invalidate the completed local workflow.
