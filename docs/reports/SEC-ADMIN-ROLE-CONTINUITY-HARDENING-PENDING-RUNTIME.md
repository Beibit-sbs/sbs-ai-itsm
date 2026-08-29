# Administrative Role Continuity Hardening — Runtime Pending

Date: 2026-07-29

## Outcome

Built-in tenant roles are now protected from accidental non-root mutation, and
every active tenant must retain at least one active
`organization_admin`. These controls prevent a tenant administrator from
locking the organization out of its own administration plane.

## Product behavior

- global roles remain read-only for organization administrators;
- built-in tenant system roles are also read-only for organization
  administrators;
- custom tenant roles remain fully configurable within the actor's delegable
  permission set;
- the administration UI labels protected tenant system roles as read-only and
  disables their name, description, and permission mutations;
- removing `organization_admin` from the last active tenant administrator
  returns 409;
- deactivating the last active tenant administrator returns 409;
- the same continuity guard is shared by direct administration, governed
  identity lifecycle, and automatic SCIM deprovisioning;
- after a replacement administrator is active, the former administrator may
  be reassigned or deactivated through the normal governed flow.

SaaS Root may edit a system-role definition deliberately, but tenant
administrator continuity still requires a replacement identity before the
last active organization administrator is removed.

## Regression

The administration regression proves:

1. a non-root administrator cannot rename a built-in tenant role;
2. a non-root administrator cannot replace its permissions;
3. the protected role remains unchanged after both denied requests;
4. the last administrator cannot remove their own admin role;
5. identity lifecycle cannot deactivate that last administrator;
6. creating a replacement administrator unlocks the governed reassignment.

The release catalog now includes:

- `SEC-SYSTEM-ROLE-INTEGRITY`;
- `SEC-TENANT-ADMIN-CONTINUITY`;
- `AUTH-SYSTEM-ROLE-INTEGRITY-026`;
- `AUTH-TENANT-ADMIN-CONTINUITY-027`.

## Static validation

- Python compilation: PASS
- Ruff: PASS
- authorization catalog: PASS
- PRG-006 contract: PASS
- TypeScript: PASS

Representative PostgreSQL/Redis regression and browser confirmation remain
pending. No runtime result is claimed.
