# SAM-001 — Software Asset Management

Date: 2026-08-14  
Status: `IMPLEMENTED_LOCAL / EXTERNAL_DISCOVERY_PENDING`

## Delivered

- migration `20260814_0078` with `software_products`, `software_licenses` and
  `software_installations`;
- tenant foreign keys, unique catalog/install keys, check constraints, renewal
  and compliance indexes;
- products, entitlements, license types, quantities, supplier/contract,
  expiration, renewal, prohibited policy, installations and authorization;
- reconciliation and compliance positions with multi-currency purchase cost
  and cost-at-risk;
- optimistic locking, role permissions, system-role upgrade backfill and
  tamper-evident audit actions;
- `/software-assets` RU/KK/EN interface with catalog, licenses, installations,
  compliance, renewal dashboard and violation actions.

## Verified

- Ruff and Python compile: PASS.
- Focused SAM tests: 5 passed.
- SAM plus migration graph and route-auth contracts: 10 passed.
- Current collection: 760 tests.
- TypeScript: PASS.
- Clean Linux Docker frontend build: PASS; `SoftwareAssetsPage` emitted as a
  production lazy chunk.
- PostgreSQL rehearsal migration `0077 -> 0078`: PASS.
- Three backend replicas and frontend: healthy.
- Existing system-role backfill: organization admin/IT manager/IT agent PASS;
  requester negative authorization: HTTP 403.

## Honest remaining boundary

- real Intune/SCCM/Lansweeper installation inventory feed;
- governed bulk software import with preview/commit;
- end-to-end renewal notification delivery;
- golden browser flow with a disposable tenant.

These are tracked as `PARTIAL/BLOCKED_EXTERNAL`; no simulation is reported as a
provider-confirmed discovery success.
