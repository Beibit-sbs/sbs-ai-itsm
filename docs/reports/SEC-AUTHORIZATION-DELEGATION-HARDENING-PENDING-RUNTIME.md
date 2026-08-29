# Authorization Delegation Hardening — Runtime Regression Pending

Date: 2026-07-29

## Outcome

A tenant role administrator can no longer amplify privileges by adding a
permission they do not hold and then assigning the resulting role to a user.
The server now applies the same bounded-delegation rule to all relevant
administrative paths.

## Enforcement

- editing a tenant role rejects any permission absent from the acting
  administrator's effective permission set;
- assigning one or more roles rejects a role whose permissions exceed the
  acting administrator's effective set;
- creating a user with an over-privileged role is rejected;
- SaaS Root remains authorized to grant the complete platform permission set;
- the non-root permission catalog is filtered to permissions the actor can
  actually delegate, preventing unusable or dangerous choices in the role
  editor;
- tenant and global role-scope checks remain unchanged and additive.

The denial is evaluated before a role or user mutation is committed and
returns HTTP 403.

## Regression contract

`test_organization_admin_cannot_amplify_or_delegate_privileges` exercises:

1. a tenant administrator cannot see `tenant.manage` in the delegable catalog;
2. a direct permission-ID submission still fails with 403;
3. SaaS Root can deliberately place that permission on a tenant role;
4. the tenant administrator cannot assign that over-privileged role;
5. the tenant administrator cannot create a user with that role.

`SEC-PRIVILEGE-DELEGATION` is now a machine-readable release control in
`security/acceptance-catalog.json`. The PRG-006 validator checks the control,
all three mutation paths, permission-catalog filtering, and the regression
test.

## Validation completed

- Ruff: PASS
- Python compilation: PASS
- PRG-006 contract: PASS with 11 security controls
- diff integrity: PASS

Runtime pytest remains pending because the current execution environment does
not permit the representative PostgreSQL/Redis test runtime. No runtime result
is fabricated.
