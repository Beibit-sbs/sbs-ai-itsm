# Multi-Role Assignment Hardening — Runtime Pending

Date: 2026-07-29

## Outcome

The administration console and user-creation API now support an exact ordered
multi-role set. Administrators can create or update a user with several roles
and see the resulting deduplicated permission union before saving.

## Previous gap

The API accepted `role_ids`, but the UI used a single-select control and sent
only one role. Saving from the console therefore replaced the complete role
set with one role, even when the user previously had several assignments.

## Delivered behavior

- the assignment dialog loads and preselects all current roles;
- the create-user dialog uses the same multi-role model and permission preview;
- roles are selected through an accessible checkbox list;
- system/custom role type and role description are visible;
- the dialog calculates the unique effective permission union;
- the save action submits the complete role-ID set atomically;
- the first selected role is retained deterministically as the primary role
  used for role identity and MFA policy, while authorization uses the union;
- an empty selection is blocked in the UI;
- the replacement semantics and last-administrator continuity rule are
  explicit;
- backend scope, bounded delegation, system-role integrity, and tenant-admin
  continuity checks still apply to every selected role.

## Regression

`test_multiple_roles_produce_an_effective_permission_union` reassigns requester
and IT-agent roles together, reloads the exact saved set, signs in as the
target user, and verifies effective permissions contributed by both roles.

`test_create_user_with_multiple_roles_preserves_primary_order` performs the
same proof atomically during user creation and verifies that the first role
remains the primary role after a fresh login.

Machine-readable controls:

- `SEC-MULTI-ROLE-EFFECTIVE-UNION`;
- `AUTH-MULTI-ROLE-UNION-028`.

## Validation

- frontend TypeScript no-emit: PASS;
- accessibility source audit: PASS;
- Ruff and Python compilation: PASS;
- PRG-006 and authorization contracts: PASS.

Browser interaction and PostgreSQL-backed regression remain pending in the
representative runtime environment.
