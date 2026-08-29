# MFA and privileged-access runbook

## Scope

The platform supports time-based one-time passwords (TOTP), one-time recovery
codes, MFA-verified access/refresh sessions, replay protection, temporary
lockout, tenant-scoped coverage reporting, and audited administrative reset.
SSO accounts continue to use the upstream Identity Provider MFA policy.

## Security model

- TOTP secrets are encrypted at rest with AES-256-GCM.
- `mfa_encryption_key` is a dedicated Docker secret and must not be reused as
  the JWT, database, Redis, metrics, or webhook credential.
- Recovery codes are never stored in plaintext. The server stores keyed HMAC
  digests and removes a digest after its first successful use.
- A TOTP time step cannot be reused for authentication.
- Password success does not create a platform session when MFA is already
  enabled. It creates a short-lived, attempt-limited MFA challenge.
- Administrative reset requires `security.mfa.manage` and an MFA-verified
  administrator session. Reset revokes every active session of the target user.
- All enrollment, verification failure, recovery-code rotation, disable, and
  reset operations are written to the audit trail.

## First production rollout

Do not enable enforcement before privileged users have registered a factor,
otherwise those accounts cannot complete their first enrollment.

1. Generate production secrets with `scripts/init-production-secrets.py`.
2. Keep `MFA_ENFORCEMENT_ENABLED=false` for the initial deployment.
3. Deploy and run all migrations, including `20260727_0028`.
4. Each SaaS Root, Organization Admin, and Security Officer opens
   `Администрирование → Security → Защита моей учётной записи`.
5. The user enters the current local password, imports the TOTP secret into an
   authenticator, confirms one code, and stores the displayed recovery codes in
   an approved password vault.
6. In `Security → Покрытие MFA`, verify `Privileged gap = 0`.
7. Set `MFA_ENFORCEMENT_ENABLED=true` and redeploy backend, worker, and migrate
   services with the same `mfa_encryption_key`.
8. Run `scripts/check-production-env.sh`; MFA enforcement must report enabled.
9. Test a new login for one account from each required role.

Never rotate `mfa_encryption_key` directly. Existing TOTP secrets would become
undecryptable. A key-rotation procedure must decrypt with the previous key,
re-encrypt with the new key, verify, and only then remove the previous key.

## User enrollment

1. Open `Администрирование → Security`.
2. Under `Защита моей учётной записи`, enter the current password.
3. Add the displayed secret as a time-based/TOTP key in the authenticator.
4. Enter the current six-digit code.
5. Copy all recovery codes to an approved offline/password-vault location.
6. Sign out and sign in again. The Security page must show
   `Текущая сессия: MFA verified`.

Recovery codes are displayed only after enrollment or regeneration.

## Recovery-code rotation

The user enters a fresh TOTP code under `Обновить recovery-коды`. Issuing a new
set immediately invalidates every previous recovery code. Audit action:
`mfa_recovery_codes_regenerated`.

## Lost authenticator

Preferred path: the user signs in with one unused recovery code and registers a
replacement factor.

Administrative path:

1. Verify the requester's identity using the approved service-desk procedure.
2. A different administrator signs in through MFA.
3. Open `Security → Покрытие MFA` or the user's details.
4. Select `Сбросить MFA`, confirm the target, and record the linked incident.
5. Confirm audit action `mfa_admin_reset` and session revocation count.
6. The user signs in with the password and immediately performs enrollment.

An administrator cannot use this operation on their own account.

## Incident response

- Repeated `login_mfa_failed` events contribute to the failed-login risk score.
- A locked factor clears after `MFA_LOCKOUT_SECONDS`; do not bypass the lock by
  editing database rows.
- For suspected factor compromise, reset MFA, revoke sessions, rotate the local
  password, inspect login/audit events, and preserve incident evidence.
- For suspected `mfa_encryption_key` exposure, treat every local TOTP factor as
  compromised and run a coordinated factor re-enrollment.

## Verification

Expected controls:

- privileged gap is zero before enforcement;
- MFA enforcement is enabled after rollout;
- administrative reset is disabled for non-MFA sessions;
- recovery-code count decreases after use;
- old recovery codes fail after regeneration;
- TOTP replay and consumed login challenges fail;
- audit events include actor, target, timestamp, IP, user agent, and action.

