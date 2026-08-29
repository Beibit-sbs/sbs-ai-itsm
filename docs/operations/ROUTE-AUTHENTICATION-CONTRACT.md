# Route Authentication Contract

## Purpose

Every SBS AI ITSM API route must establish one of these identities before
processing tenant or platform data:

- an authenticated platform user;
- a tenant-scoped SCIM connector;
- a scoped service-account bearer token;
- an authenticated monitoring/event source;
- a signed or state-bound external callback;
- a dedicated metrics/Alertmanager secret.

Only the small public allowlist in
`scripts/validate_route_authentication.py` may omit those mechanisms.

## Governed public routes

The public surface is limited to:

- shallow health, liveness, and readiness;
- login and MFA challenge exchange;
- OIDC configuration and authorization bootstrap.

Public responses must not include secrets, tenant records, deep diagnostics,
provider credentials, dependency exception text, or user existence details.
OIDC callback, refresh, logout, metrics, SCIM, incoming email, monitoring,
integration service-token, and webhook flows are not public exceptions; each
must prove state, token, signature, cookie/session, or source identity.

## Static gate

Run:

```powershell
python scripts/validate_route_authentication.py
```

The validator parses every FastAPI route decorator under
`backend/app/api/v1/routes`, classifies the function's authentication
mechanism, and fails when:

- a route has no governed protection marker;
- a public route is not explicitly allowlisted;
- a stale public exception no longer maps to a route;
- the route inventory unexpectedly shrinks below its protected baseline.

Current static result:

```text
Route authentication contract valid: 708 endpoints, 701 protected,
7 governed public.
```

## Adding or changing a route

1. Prefer `Depends(get_current_user)` plus the least-privilege permission and
   tenant/object scope.
2. For machine callers, use an existing governed connector/service-token
   mechanism with rotation, revocation, rate limit, and audit.
3. For callbacks, verify signature/state with constant-time comparison,
   timestamp/replay bounds, payload limits, and idempotency.
4. Add positive, unauthenticated, unauthorized, and cross-tenant regression
   cases.
5. Run this contract, the authorization catalog, PRG-006 validator, and the
   full local release gate.

A new public exception requires Application Security review, a concise
non-secret justification in `PUBLIC_ENDPOINTS`, explicit response-data review,
rate limiting, and a negative regression. Do not add broad file, router, path
prefix, or marker-name exceptions.

## Legacy integrations

The legacy demo inbound webhook:

- is hidden from OpenAPI;
- is disabled outside demo mode;
- requires an authenticated user with
  `integrations.webhooks.manage`;
- resolves only an active webhook in the actor's tenant scope;
- supports seeded nested paths through `{path:path}`;
- attributes the resulting event to the authenticated actor.

External production delivery must use the integration-platform service-token
or signed monitoring/email connector flows, not the legacy demo endpoint.

## Runtime acceptance

Against the deployed edge:

1. call every public route without credentials and inspect the minimized
   response;
2. call representative protected user, SCIM, service-token, monitoring,
   metrics, and callback routes without/with invalid credentials;
3. require 401/403/404 and no state change as appropriate;
4. replay signed/state-bound requests and require rejection;
5. verify tenant scoping and audit/correlation evidence for accepted writes;
6. confirm OpenAPI does not expose hidden callback/demo routes.

Any unexpected unauthenticated success is a release blocker.
