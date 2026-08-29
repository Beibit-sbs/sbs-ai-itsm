# Authorization Acceptance Runbook

## Purpose

Use this runbook to prove that protected SBS AI ITSM operations are both
allowed and denied correctly for anonymous users, requesters, agents,
managers, organization administrators, security officers, SaaS Root, and
service accounts.

The machine-readable source of truth is
`security/authorization-acceptance.json`.

## Denial semantics

- `401` means no valid authenticated identity or session was established.
- `403` means the identity is known but lacks permission or delegation
  authority.
- `404` hides the existence of an object outside the actor's tenant or object
  scope.
- an empty result hides records the actor is not permitted to discover through
  list or search operations.
- `409` rejects self-approval, stale state, drift, or another governed
  separation-of-duties conflict.
- fail-closed behavior may use more than one of these statuses across a
  multi-step control, but must never leak data or commit a partial mutation.

Do not replace object-hiding `404` or empty-result behavior with a detailed
cross-tenant error that reveals another tenant's identifiers or record
existence.

## Static contract

Run from the workspace root:

```powershell
python scripts/validate_authorization_acceptance.py
python scripts/validate_prg006_contract.py
python scripts/run_local_release_gate.py
```

The validator requires:

- every control ID to be unique and owned;
- all eight actor types to be represented;
- at least 20 high/critical controls across at least 10 domains;
- implementation and regression files to exist;
- the named regression test to remain present;
- runtime acceptance to remain `PENDING` until live evidence exists.

## Runtime preparation

Use an isolated local or staging environment with synthetic data. Create:

- two active tenants, A and B;
- a requester, agent, manager, organization administrator, and security
  officer in each tenant;
- one SaaS Root break-glass test identity;
- one scoped service account for tenant A;
- distinguishable tickets, catalog items, CIs, relationships, search records,
  workflows, AI policies, configuration packages, and integration records in
  both tenants.

Never use production credentials, provider keys, personal data, or customer
payloads. Record only synthetic record IDs and hash sensitive evidence.

## Runtime procedure

1. Run the complete backend regression against PostgreSQL and Redis:

   ```powershell
   cd backend
   pytest
   ```

2. Run the critical authorization suites explicitly:

   ```powershell
   pytest tests/test_auth.py tests/test_admin_security.py tests/test_tickets.py
   pytest tests/test_service_catalog.py tests/test_global_search.py
   pytest tests/test_cmdb_ci_classes.py tests/test_cmdb_relationships.py
   pytest tests/test_cmdb_reconciliation.py tests/test_cmdb_impact.py
   pytest tests/test_ai_retrieval.py tests/test_ai_governance.py
   pytest tests/test_ai_actions.py tests/test_workflow_engine.py
   pytest tests/test_configuration_packages.py
   pytest tests/test_integration_platform.py tests/test_tenant_experience.py
   ```

3. For each catalog control, repeat the request through the deployed edge and
   confirm the expected status or empty result.
4. After each denied mutation, query the target as an authorized actor and
   prove that no state changed.
5. Review audit events. Successful sensitive actions must be attributable;
   denied requests must be visible in edge/security telemetry without storing
   credentials or request secrets.
6. Run the same tenant A and tenant B reads and mutations concurrently to
   detect cache, queue, WebSocket, and transaction scope leakage.

## Privilege-delegation acceptance

For a non-root organization administrator:

1. confirm the permission picker excludes permissions the actor does not hold;
2. submit a hidden permission ID directly and require `403`;
3. have SaaS Root place that permission on a tenant role;
4. attempt to assign the role to an existing user and require `403`;
5. attempt to create a user with the role and require `403`;
6. verify the role and both users are unchanged.

SaaS Root must still be able to perform the same deliberate grant. This is an
explicit platform action and must be audited.

## System-role and tenant-admin continuity

- built-in global and tenant system roles are read-only for non-root
  administrators;
- role editors must direct organization administrators to create a custom
  tenant role instead of modifying a built-in baseline;
- role assignment and every deactivation path must retain at least one active
  `organization_admin` in the tenant;
- manual administration, safe identity deactivation, and automatic SCIM
  deprovisioning must share the same continuity guard;
- a 409 continuity denial must occur before ownership transfer, session
  revocation, role removal, or account mutation;
- to rotate the final administrator, create or assign and verify the
  replacement first, then remove the former administrator.

## Multi-role assignments

- the administration UI must load the exact current role set before editing;
- user creation must accept the same ordered multi-role set atomically;
- saving replaces the complete role set atomically, not only the primary role;
- the first selected role is the deterministic primary role used for role
  identity and MFA policy;
- effective permissions must equal the deduplicated union of all assigned
  roles;
- each selected role must independently pass tenant scope and bounded
  delegation checks;
- an empty role set is blocked in the standard UI; exceptional role removal
  must use an explicitly governed API procedure;
- verify a newly assigned secondary role through `/auth/me` in a fresh
  session, not only through the role administration response.

## Evidence

For every control retain:

- source commit and image digest;
- environment and UTC timestamps;
- actor role and tenant aliases, never passwords or tokens;
- method and route template, without secret query parameters;
- expected and actual status/result;
- before/after record hashes for denied mutations;
- request/correlation ID and relevant audit-event ID;
- PASS/FAIL and accountable reviewer.

Runtime acceptance fails on any unexpected allow, cross-tenant discovery,
partial write, stale self-approval, unscoped service-token action, or missing
critical audit evidence.

## Failure response

1. Stop release promotion.
2. Revoke the affected session or service token if exploitation is possible.
3. Preserve correlation IDs, audit anchors, and redacted logs.
4. Identify whether the defect is permission, role delegation, tenant query
   scope, object ACL, cache key, asynchronous context, or edge/session scope.
5. Add a focused regression before changing the implementation.
6. Re-run the full catalog because authorization helpers are shared.

No high/critical authorization failure may be waived without a time-bounded
risk acceptance signed by Application Security and the accountable service
owner.
