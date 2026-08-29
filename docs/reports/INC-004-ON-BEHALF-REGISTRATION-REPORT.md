# INC-004 — audited on-behalf ticket registration

Date: 2026-08-14  
Status: `COMPLETE_LOCAL`

## Delivered

- migration `20260814_0080` with creator, contact, channel and reason fields;
- explicit `tickets.create.on_behalf` RBAC permission;
- active, tenant-scoped requester candidate directory;
- requester anti-impersonation and cross-tenant/inactive-user rejection;
- mandatory on-behalf reason and authoritative user-profile snapshots;
- creator/requester separation in API and ticket overview;
- ticket history plus tamper-evident audit evidence;
- RU/KK/EN labels and operator guidance;
- IT agent ticket creation permission required for normal service-desk intake.

## Acceptance evidence

- backend collection: 769 tests in 87 files;
- 73 focused test executions passed after compatibility fixtures were updated;
- Ruff and Python compileall: PASS;
- TypeScript: PASS;
- Docker Vite production build: PASS, 142 modules;
- accessibility audit: PASS, 77 files / 16 dialogs;
- interactive controls: PASS, 673 buttons / 39 links;
- route authentication: 742 endpoints / 735 protected / 7 governed public;
- OpenAPI: 734 operations / 617 paths;
- PostgreSQL: `20260814_0080 (head)`;
- runtime: 3/3 backend healthy, frontend healthy, worker/scheduler running,
  readiness HTTP 200.

The monolithic 769-test run reached a 20-minute process timeout without a
reported failed test. It is not counted as a full regression PASS. The last
complete regression remains 723 passed / 16 skipped; stable four-shard CI is a
separate quality-platform action.

## Security boundary

Only SaaS root, organization admin, IT manager and IT agent receive the new
permission. Requesters cannot enumerate users or create for another identity.
Linked requesters must be active and belong to the ticket tenant. Audit stores
the business reason, while normal ticket history does not disclose it.

## Remaining external gate

Public server deployment still requires real TLS/edge acceptance, production
identity lifecycle and independent security review. Those external gates do
not invalidate the completed local workflow.

