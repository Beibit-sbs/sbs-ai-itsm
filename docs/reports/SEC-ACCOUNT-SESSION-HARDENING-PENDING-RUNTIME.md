# Account and session hardening — runtime acceptance pending

## Outcome

Session lifecycle is now a complete user-facing security capability. Every role
has a reachable account page for profile, local password, MFA, and own-session
management. Administrative session inspection now includes IP address,
user-agent, and authentication method.

Refresh rotation now locks its database row. Reuse of a replaced refresh token
revokes the bounded descendant chain and emits an auditable security event,
instead of merely rejecting the stale token while leaving its child active.

Administrator-issued passwords are now explicitly temporary. User creation and
password reset set a persistent required-change state; reset always revokes
existing sessions. The API, not only the UI, restricts the account to profile,
own-session, and password-change operations until the user replaces the
temporary credential.

Password login now bounds input, performs dummy-hash verification for unknown
or externally managed identities, and enforces independent rolling limits by
normalized email and sanitized client IP. Additive audit-window indexes keep
these controls bounded as audit history grows.

## Implemented evidence

- additive migrations `20260729_0065` through `20260729_0067`;
- four authenticated self-service account/session/password routes;
- external identity local-login and password-change denial;
- policy-aware password change with all-session revocation;
- exact own-session query scope and current-session cookie cleanup;
- session IP, user-agent, and authentication-method persistence;
- refresh row lock, replacement-chain containment, and audit;
- requester-accessible responsive UI plus administrative context;
- mandatory temporary-password replacement with server-side route restriction,
  browser redirect, and post-change reauthentication;
- constant-work unknown-account handling, bounded login input, indexed
  email/IP abuse windows, and independent account/source throttling;
- backend regressions, static contract, CI/local gate integration target,
  security controls, and operator runbook.

Static lint, compilation, TypeScript, accessibility, route-authentication, and
migration-head checks pass. Database concurrency, browser cookie behavior,
real edge identity, and full regression remain explicitly pending runtime
acceptance.
