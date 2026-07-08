# FOUNDATION-002 — Tenant, User, Role and Permission Foundation

## Goal

Implement the security and data-isolation foundation before any ticket functionality.

## In scope

- Tenant model and lifecycle status.
- User model with tenant membership.
- SaaS Root identity separated from tenant users.
- Role, Permission and role-permission mappings.
- Password hashing and JWT access/refresh foundation.
- Permission dependency for FastAPI routes.
- Audit events for sign-in and administrative changes.
- Seed data for one SaaS Root and one demo tenant.
- Automated tests proving cross-tenant access is denied.

## Out of scope

- Tickets, SLA, assets and AI.
- LDAP/Active Directory integration.
- Production SSO.

## Exit criteria

- Database migrations pass.
- Login and token refresh work.
- SaaS Root can list tenants.
- Organization Admin can access only its own tenant.
- Cross-tenant API tests pass.
- Frontend has real login session handling.
