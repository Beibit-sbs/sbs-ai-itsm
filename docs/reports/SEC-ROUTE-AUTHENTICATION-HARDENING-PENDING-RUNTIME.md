# Route Authentication Hardening — Runtime Pending

Date: 2026-07-29

## Outcome

All 708 FastAPI route decorators are now covered by a static authentication
contract: 701 routes establish a governed user/integration identity and seven
minimal routes are explicitly public.

The audit found and fixed a real unauthenticated write path in the legacy demo
integration surface.

## Defect closed

`POST /integrations/inbound/{path}` previously:

- required only `DEMO_MODE`;
- accepted a payload without user, token, or signature;
- queried webhook paths without tenant scope;
- was visible in OpenAPI;
- could not match seeded nested `/hooks/...` paths because the path parameter
  captured only one segment.

It now:

- requires an authenticated platform user;
- requires `integrations.webhooks.manage`;
- applies tenant filtering;
- records the authenticated actor;
- is hidden from OpenAPI;
- remains disabled outside demo mode;
- correctly accepts nested seeded paths using `{path:path}`.

Production external webhook delivery remains on the governed service-token or
signed connector platforms.

## Preventive control

`scripts/validate_route_authentication.py` parses every route function and
fails CI/local release gating if a route lacks a recognized authentication
mechanism and is absent from the exact public allowlist.

Added controls:

- `SEC-ROUTE-AUTHENTICATION-CONTRACT`;
- `AUTH-LEGACY-WEBHOOK-ANON-029`;
- `AUTH-LEGACY-WEBHOOK-RBAC-030`.

## Validation

- route contract: PASS — 708 total, 701 protected, seven public;
- Ruff: PASS;
- Python compilation: PASS;
- PRG-006 and authorization catalogs: PASS;
- OpenAPI construction remains above the release threshold.

Deployed-edge negative requests, replay tests, rate-limit evidence, and full
PostgreSQL regression remain pending.
