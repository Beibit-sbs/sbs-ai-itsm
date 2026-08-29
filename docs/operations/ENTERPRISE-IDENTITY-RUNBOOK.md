# ENTERPRISE IDENTITY RUNBOOK

## Provisioning architecture

Authentication and provisioning are separate controls:

- OIDC signs an already governed user into SBS AI ITSM.
- SCIM 2.0 creates, updates, groups, disables, and audits identities.
- A SCIM token is bound to exactly one SBS tenant and one connector.
- The external `externalId` is immutable. Email and display attributes may
  change without changing the identity link.
- Root and superuser accounts can never be created or removed through SCIM.

The administration workspace is available at:

`Administration -> Identity Provisioning`

It exposes connector health and token metadata but never the stored credential.
The bearer token is returned only when a connector is created or rotated. The
database stores only its SHA-256 digest and an eight-character display hint.

## Microsoft Entra provisioning setup

1. In Identity Provisioning, select the organization and create an `ENTRA`
   connector.
2. Select a least-privilege default role and an active fallback owner. The
   fallback owner receives active work when an employee leaves.
3. Copy the one-time bearer token before dismissing it.
4. In the Entra Enterprise Application open `Provisioning`, select `Automatic`,
   and configure:

   - Tenant URL: `https://<itsm-host>/api/v1/scim/v2`
   - Secret Token: the one-time SBS token

5. Run `Test Connection`.
6. Map at minimum:

   - `externalId` from the immutable Entra object ID;
   - `userName` from the approved unique work email;
   - `displayName`, `title`, `department`, `employeeNumber`, and `manager`;
   - `active` from the Entra soft-delete/account-enabled expression.

7. Include approved users and groups in provisioning scope.
8. Start with on-demand provisioning for one test manager, one direct report,
   and one group. Verify the event log and group role mapping before enabling
   the full synchronization cycle.

Generic SCIM clients use the same base URL. Discovery endpoints are
`ServiceProviderConfig`, `ResourceTypes`, and `Schemas`.

## Connector lifecycle

- `DRAFT`: token exists but provisioning requests are rejected.
- `ACTIVE`: SCIM requests are accepted.
- `PAUSED`: requests are rejected while mappings or ownership policy is fixed.
- `REVOKED`: terminal state; the credential cannot be restored.

Rotating a token invalidates the previous token immediately. Update Entra
before the next scheduled synchronization. Use a short planned pause if the
identity provider cannot update the token atomically.

An IP allowlist is optional. It contains CIDR networks and is evaluated against
the direct request peer. When a trusted reverse proxy is used, align this policy
with the proxy topology; do not trust an arbitrary client-supplied forwarding
header.

## Joiner, mover, and leaver behavior

Joiner:

- creates a tenant user with an unguessable, unusable local password;
- marks the authoritative source as `SCIM` or `ENTRA`;
- applies mapped group roles, or the connector default role;
- resolves the manager immediately or when the manager arrives later.

Mover:

- updates approved profile fields and manager hierarchy;
- synchronizes current owner/assignee display references;
- recomputes roles after every group membership or group mapping change;
- rejects direct local profile, password, activation, and role edits for
  provisioned identities to prevent authoritative-source drift.

Leaver:

- disables the account and removes roles;
- revokes all active SBS refresh sessions;
- transfers active assignments, ownership, approvals, assets, direct reports,
  and active major-incident responsibilities to an active same-tenant fallback;
- records a structured transfer summary and tamper-evident audit event.

Use the offboarding preview in the Identity Provisioning workspace before a
manual deprovision. Ordinary Administration deactivation is rejected when work
would be orphaned.

## Failure, retry, and reconciliation

Every mutating SCIM request is keyed by the provider request ID and a canonical
payload hash. Repeating the same ID and payload returns the stored result.
Reusing an ID with another payload is rejected.

Application work runs inside a savepoint. A failed request cannot leave a
partially created user or group. The event is persisted as:

- `APPLIED`;
- `RETRY_SCHEDULED` with exponential backoff; or
- `DEAD_LETTER` for terminal validation/conflict failures.

The worker polls due retry events every 15 seconds. Administrators may use
`Retry` after correcting the source data or connector mapping. Do not repeatedly
retry a dead-letter event without addressing its recorded cause.

Recommended daily checks:

- no unexpected `DEAD_LETTER` events;
- connector success time is within the Entra cycle;
- no connector has a growing failure counter;
- fallback owners remain active and appropriately privileged;
- deprovisioned users have no active sessions or owned work.

## Supported flow

- OpenID Connect Authorization Code flow with PKCE (`S256`).
- Stateless, signed `state` cookie so callbacks may reach any backend replica.
- ID token signature, `iss`, `aud`, `exp`, `iat`, `state`, `nonce` and verified email validation.
- Asymmetric signing algorithms only; `RS256` is the default allowlist.
- Local SBS access/refresh sessions are still rotated and revocable after SSO login.

## Identity provider registration

Register SBS as a confidential web client and configure the exact callback:

`https://<itsm-host>/api/v1/auth/sso/callback`

Enable Authorization Code flow and PKCE. The ID token must contain `sub`, `email`,
`email_verified`, and preferably `name`.

## Production configuration

1. Replace `secrets/oidc_client_secret` with the value issued by the identity provider.
2. Set `OIDC_ENABLED=true` in `.env.production`.
3. Configure `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_REDIRECT_URI`,
   `OIDC_ALLOWED_EMAIL_DOMAINS`, and the provider label.
   Set `OIDC_CLIENT_AUTH_METHOD` to `client_secret_basic` or `client_secret_post`
   according to provider metadata.
4. Keep `OIDC_ALLOW_EMAIL_LINKING=false` and `OIDC_AUTO_PROVISION=false` for the
   initial rollout.
5. Run `make env-check`, redeploy, and verify `/api/v1/auth/sso/config`.

## Administrative readiness console

Sign in as Organization Admin or SaaS Root and open:

`Администрирование -> Identity & SSO`

The console reads `GET /api/v1/admin/identity-provider` and intentionally exposes
only safe configuration metadata. Client ID and client secret are represented by
boolean `configured` flags; their values are never returned to the browser.

Use `Проверить OIDC discovery` after deployment. The backend forces a fresh metadata
lookup, validates the existing OIDC trust policy, records
`identity_provider_tested` in audit, and returns only issuer and endpoint hostnames.
Do not use this control as a substitute for an end-to-end test login.

## Safe account linking

The default mode never links an existing SBS account based only on a matching email.
An administrator pre-links the immutable IdP subject through:

- `POST /api/v1/admin/users/{user_id}/external-identities`
- body: `{"subject":"<provider-subject>"}`

Use `GET` on the same path to audit links and `DELETE` with the identity ID to revoke one.
All link/unlink actions are added to the tamper-evident audit chain.

The same operations are available in:

`Администрирование -> Пользователи -> Детали -> Enterprise Identity`

Always copy the immutable `sub` claim from the IdP administration console. Do not
use email, display name, or another mutable attribute as the subject.

## Controlled provisioning

Only enable `OIDC_AUTO_PROVISION=true` after setting an approved
`OIDC_DEFAULT_TENANT_ID`, a least-privilege `OIDC_DEFAULT_ROLE_CODE`, and a strict
`OIDC_ALLOWED_EMAIL_DOMAINS` list. Auto-provisioning never creates root or superuser
accounts. `OIDC_ALLOW_EMAIL_LINKING=true` is separate and should remain disabled unless
the organization has verified account ownership and lifecycle procedures.

## Recovery and rotation

- Preserve one locally authenticated break-glass root account in the approved secret manager.
- Rotate the IdP secret by replacing `secrets/oidc_client_secret` and recreating backend,
  worker, and migrate containers.
- A failed OIDC request is recorded as `oidc_login_failed`; successful requests use
  `oidc_login_success`.
- Local logout revokes the SBS session. Provider-wide logout must follow the IdP's own
  session policy.
