# Account and session security runbook

## Purpose

This runbook governs local password changes, browser-session visibility,
session revocation, refresh-token rotation, and refresh-token replay response.
It applies to every SBS AI ITSM user, not only administrators.

## Identity-source boundary

- `LOCAL` users authenticate with a platform password and may change it in
  **My account**.
- `OIDC`, `SCIM`, and `ENTRA` identities cannot use the local password login or
  password-change flow. Their credential lifecycle remains authoritative in
  the external identity provider.
- An existing local user linked to OIDC remains `LOCAL` and keeps the
  explicitly governed break-glass/local login path.

Never convert an externally managed identity to local merely to work around an
IdP incident. Use the approved break-glass account and identity runbook.

## Credential-abuse boundary

Password login applies two rolling-window limits before credential issuance:

- five failed attempts for one normalized email address in five minutes;
- 25 failed attempts from one sanitized client IP in five minutes, even when
  the attacker rotates email addresses.

The values are controlled by `LOGIN_RATE_LIMIT_ATTEMPTS`,
`LOGIN_IP_RATE_LIMIT_ATTEMPTS`, and `LOGIN_RATE_LIMIT_WINDOW_SECONDS`.
The IP threshold must not be lower than the account threshold. Configuration
validation rejects non-positive, inverted, or excessively large windows and
thresholds.

Unknown and externally managed accounts run password verification against a
per-process dummy hash. This keeps the expensive credential-verification step
present without revealing whether the submitted local identity exists through
the obvious fast-fail timing difference. Email and password input lengths are
bounded before that work begins.

Both rolling queries use dedicated `action/email/time` and `action/IP/time`
indexes. The IP is trustworthy only behind the edge identity chain defined in
the edge trust runbook. A `429` includes `Retry-After`; do not increase limits
to hide an attack. Inspect `login_failed` events and proxy/HTTP 429 metrics,
identify distributed sources, and escalate credential-stuffing indicators.

## User self-service

Every authenticated user can open `/account` to:

1. inspect identity source, role, organization, provisioning state, and last
   login;
2. change a local password after proving the current password;
3. enroll, inspect, regenerate recovery codes for, or disable local MFA;
4. view up to 100 own session records with state, issue time, IP address,
   user-agent, and authentication method;
5. revoke an own remote session or terminate the current session.

Session ownership is enforced in the database query. A session belonging to
another user is returned as not found.

## Password-change behavior

The new password is evaluated against the effective tenant/global password
policy and must differ from the current password. On success:

- the password hash is replaced using the current hardened work factor;
- every active session for the user is revoked;
- the HttpOnly refresh cookie is removed;
- the UI clears its session and requires a new login;
- audit action `self_password_changed` records only the session count and
  request context. Password values never enter logs, responses, or metadata.

## Administrator-issued temporary passwords

Passwords set during local-user creation or an administrative reset are always
temporary. The platform sets `must_change_password`, revokes every existing
session during reset, and does not permit an administrator to disable that
revocation.

After a successful login with a temporary password, both enforcement layers
activate:

- the browser redirects the user to **My account** and displays the required
  action;
- the API returns `403` for every protected business resource until the
  password is changed.

Only `/auth/me`, `/auth/account`, own-session inspection/revocation, and
`/auth/password/change` remain available. This server-side restriction means a
user cannot bypass the requirement by calling the API outside the browser.
MFA enrollment remains hidden until the password has been replaced. Successful
self-service change clears the flag, revokes the temporary session, removes the
refresh cookie, and requires a fresh login.

Administrative reset is disabled for `OIDC`, `SCIM`, and `ENTRA` identities;
their password lifecycle remains with the authoritative provider.

## Refresh-token rotation and replay containment

The refresh endpoint locks the session row before rotation. This prevents two
parallel requests from successfully rotating the same refresh token.

Each successful rotation revokes the previous session and links it to the new
session. If a replaced refresh token is presented again, the platform:

1. classifies the event as token reuse;
2. walks the bounded replacement chain;
3. revokes every still-active descendant;
4. writes `refresh_token_reuse_detected` with the number of descendants;
5. returns `401`, forcing reauthentication on the legitimate browser too.

This fail-closed response intentionally prioritizes account containment over
session continuity.

## Operator response

For `refresh_token_reuse_detected`:

1. confirm the user, tenant, source IP, user-agent, and event timestamp;
2. verify all descendant sessions are revoked;
3. contact the user through an approved channel;
4. require password rotation for local identities or IdP credential response
   for external identities;
5. inspect adjacent login, MFA, administration, and integration activity;
6. open a security incident if the client context is unrecognized.

Administrators may inspect tenant-scoped session context and revoke an
individual or all user sessions from Administration > Security. SaaS Root may
operate across tenants; organization administrators remain tenant scoped.

## Acceptance

Run the static contract:

```powershell
python scripts/validate_session_security.py
```

Runtime acceptance must additionally prove:

- invalid known and unknown accounts have comparable password-verification
  behavior without exposing account existence;
- one account and one source IP are independently throttled at their configured
  thresholds, including email rotation from the same IP;
- simultaneous refresh attempts produce exactly one successful rotation;
- replay of the previous token invalidates the newly issued access/session
  pair;
- cross-user and cross-tenant session revocation returns no resource;
- local password change revokes all sessions and the old password;
- administrator-issued passwords cannot reach business APIs until changed;
- administrative reset cannot retain an existing session;
- successful required change clears the restriction only after re-login;
- external identities cannot use either local password endpoint;
- session IP, user-agent, and auth method match the sanitized edge context;
- audit output contains no password or token material.
