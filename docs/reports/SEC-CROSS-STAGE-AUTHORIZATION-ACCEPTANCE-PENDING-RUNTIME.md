# Cross-Stage Authorization Acceptance — Runtime Pending

Date: 2026-07-29

## Outcome

Critical authorization boundaries across milestones M2 through M8 now have a
single machine-readable acceptance inventory, validator, tests-as-code,
release-gate integration, and operator runbook.

Current static result:

```text
Authorization acceptance valid: 30 controls, 12 domains, 8 actors,
runtime acceptance pending.
```

## Covered actors

- anonymous;
- requester;
- IT agent;
- IT manager;
- organization administrator;
- security officer;
- SaaS Root;
- scoped service account.

## Covered domains

Identity, administration, security, tenancy, tickets, catalog, search, CMDB,
AI, workflow, configuration, and integrations.

Controls cover 401/403 denials, hidden 404 behavior, empty non-discoverable
results, governed 409 conflicts, general fail-closed flows, and explicit
positive access for the security officer and SaaS Root.

## Product hardening delivered

The audit found and closed an organization-admin privilege-amplification path.
A non-root role manager can now grant and assign only permissions the actor
already holds. The same rule is applied to:

- role permission replacement;
- assigning one or more roles to an existing user;
- creating a user with an initial role.

The non-root role-editor catalog is filtered to delegable permissions. Direct
submission of a hidden permission ID still fails server-side. SaaS Root keeps
full intentional delegation authority.

## Enforcement artifacts

- `security/authorization-acceptance.json`
- `scripts/validate_authorization_acceptance.py`
- `backend/tests/test_authorization_acceptance_contract.py`
- `backend/tests/test_admin_security.py`
- `backend/tests/test_auth.py`
- `docs/operations/AUTHORIZATION-ACCEPTANCE-RUNBOOK.md`

The validator is enforced by CI and by the consolidated local release gate.

## Validation completed

- authorization contract: PASS;
- PRG-006 security contract: PASS with 11 controls;
- Ruff: PASS;
- Python compilation: PASS;
- referenced implementation/regression evidence: present.

Representative PostgreSQL/Redis regression, concurrent cross-tenant execution,
deployed-edge denial checks, and audit/correlation evidence remain pending.
The current environment does not permit that runtime, so no live PASS is
claimed.
