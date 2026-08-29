from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hmac
import secrets
import time
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    AuthUser,
    create_token,
    decode_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.external_identity import ExternalIdentity
from app.models.mfa_login_challenge import MfaLoginChallenge
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_mfa import UserMfa
from app.services.audit import log_audit
from app.services.mfa import (
    build_otpauth_uri,
    consume_recovery_code,
    count_recovery_codes,
    create_challenge_token,
    decrypt_totp_secret,
    encode_recovery_code_hashes,
    encrypt_totp_secret,
    generate_recovery_codes,
    generate_totp_secret,
    hash_challenge_token,
    is_locked,
    verify_totp,
)
from app.services.oidc import OidcClient, OidcError, OidcIdentityClaims, create_pkce_pair
from app.services.password_policy import get_password_minimum_length

router = APIRouter(prefix="/auth")
settings = get_settings()
REFRESH_COOKIE_NAME = "sbs_refresh_token"
OIDC_STATE_COOKIE_NAME = "sbs_oidc_state"
oidc_client = OidcClient(settings)
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=512)


class AuthUserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    tenant_id: str | None
    role: str
    permissions: list[str] = Field(default_factory=list)
    mfa_enabled: bool = False
    mfa_verified: bool = False
    must_change_password: bool = False


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    user: AuthUserResponse


class MfaChallengeResponse(BaseModel):
    mfa_required: bool = True
    challenge_token: str
    expires_in_seconds: int
    methods: list[str] = Field(default_factory=lambda: ["totp", "recovery_code"])


class MfaLoginVerifyRequest(BaseModel):
    challenge_token: str = Field(min_length=32, max_length=256)
    code: str = Field(min_length=6, max_length=64)


class MfaStatusResponse(BaseModel):
    enabled: bool
    verified_at: datetime | None
    recovery_codes_remaining: int
    locked: bool
    policy_enforced: bool
    required_for_role: bool
    current_session_verified: bool


class MfaEnrollmentRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)


class MfaEnrollmentResponse(BaseModel):
    secret: str
    otpauth_uri: str
    issuer: str
    account_name: str


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=64)


class MfaRecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]
    requires_reauthentication: bool = True


class MfaDisableRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    code: str = Field(min_length=6, max_length=64)


class MfaDisableResponse(BaseModel):
    disabled: bool
    sessions_revoked: int


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class AccountResponse(BaseModel):
    id: str
    email: str
    full_name: str
    tenant_id: str | None
    role: str
    identity_source: str
    provisioning_state: str
    local_password_supported: bool
    must_change_password: bool
    last_login_at: datetime | None


class SelfSessionResponse(BaseModel):
    id: str
    created_at: datetime
    refresh_expires_at: datetime
    revoked_at: datetime | None
    replaced_by_id: str | None
    ip_address: str | None
    user_agent: str | None
    auth_method: str | None
    is_active: bool
    is_current: bool


class SelfSessionRevokeResponse(BaseModel):
    session_id: str
    revoked: bool
    current_session_revoked: bool


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=8, max_length=512)


class PasswordChangeResponse(BaseModel):
    changed: bool
    sessions_revoked: int
    reauthentication_required: bool = True


class SsoConfigResponse(BaseModel):
    enabled: bool
    provider_name: str | None = None
    button_label: str | None = None
    login_path: str | None = None


def _to_response(
    user: AuthUser,
    permissions: list[str] | None = None,
    *,
    mfa_enabled: bool = False,
    mfa_verified: bool = False,
) -> AuthUserResponse:
    return AuthUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        tenant_id=user.tenant_id,
        role=user.role,
        permissions=permissions or [],
        mfa_enabled=mfa_enabled,
        mfa_verified=mfa_verified,
        must_change_password=user.must_change_password,
    )


def _issue_tokens(
    db: Session,
    user: AuthUser,
    permissions: list[str] | None = None,
    *,
    replaced_session: AuthSession | None = None,
    mfa_verified: bool = False,
    auth_method: str = "pwd",
    request: Request | None = None,
) -> TokenPair:
    session_id = str(uuid.uuid4())
    subject = {
        "sub": user.id,
        "email": user.email,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "sid": session_id,
        "amr": [auth_method, *(["mfa"] if mfa_verified else [])],
        "mfa": mfa_verified,
    }
    access_token = create_token(subject, expires_in_seconds=settings.access_token_ttl_minutes * 60, token_type="access")
    refresh_token = create_token(subject, expires_in_seconds=settings.refresh_token_ttl_minutes * 60, token_type="refresh")
    db.add(
        AuthSession(
            id=session_id,
            user_id=user.id,
            refresh_expires_at=int(time.time()) + settings.refresh_token_ttl_minutes * 60,
            ip_address=(request.client.host[:64] if request and request.client else None),
            user_agent=(request.headers.get("user-agent") or "")[:2048] or None
            if request
            else None,
            auth_method=auth_method[:32],
        )
    )
    if replaced_session is not None:
        replaced_session.revoked_at = datetime.now(UTC)
        replaced_session.replaced_by_id = session_id
    mfa_config = db.scalar(
        select(UserMfa).where(UserMfa.user_id == user.id, UserMfa.enabled.is_(True))
    )
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_to_response(
            user,
            permissions,
            mfa_enabled=mfa_config is not None,
            mfa_verified=mfa_verified,
        ),
    )


def _active_session(db: Session, payload: dict) -> AuthSession:
    session_id = str(payload.get("sid") or "")
    session = db.get(AuthSession, session_id) if session_id else None
    if (
        session is None
        or session.user_id != str(payload.get("sub"))
        or session.revoked_at is not None
        or session.refresh_expires_at <= int(time.time())
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")
    return session


def _locked_refresh_session(db: Session, payload: dict) -> AuthSession:
    session_id = str(payload.get("sid") or "")
    session = db.scalar(
        select(AuthSession)
        .where(AuthSession.id == session_id)
        .with_for_update()
    ) if session_id else None
    if session is None or session.user_id != str(payload.get("sub")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or revoked",
        )
    return session


def _revoke_replacement_chain(db: Session, session: AuthSession) -> int:
    revoked = 0
    next_id = session.replaced_by_id
    visited = {session.id}
    revoked_at = datetime.now(UTC)
    while next_id and next_id not in visited and len(visited) <= 100:
        visited.add(next_id)
        replacement = db.get(AuthSession, next_id)
        if replacement is None:
            break
        if replacement.revoked_at is None:
            replacement.revoked_at = revoked_at
            revoked += 1
        next_id = replacement.replaced_by_id
    return revoked


def _current_session_id(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(
        authorization.removeprefix("Bearer ").strip(),
        expected_type="access",
    )
    return str(payload.get("sid") or "") or None


def _delete_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=f"{settings.api_v1_prefix}/auth",
        secure=settings.app_env.lower() == "production",
        httponly=True,
        samesite="lax",
    )


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.refresh_token_ttl_minutes * 60,
        httponly=True,
        secure=settings.app_env.lower() == "production",
        samesite="lax",
        path=f"{settings.api_v1_prefix}/auth",
    )


def _safe_return_to(value: str | None) -> str:
    candidate = (value or "/dashboard").strip()
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or len(candidate) > 500
    ):
        return "/dashboard"
    return candidate


def _email_domain_allowed(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in settings.oidc_allowed_email_domains


def _resolve_oidc_user(db: Session, claims: OidcIdentityClaims) -> tuple[User, ExternalIdentity, str]:
    identity = db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == claims.issuer,
            ExternalIdentity.subject == claims.subject,
        )
    )
    if identity is not None:
        user = db.get(User, identity.user_id)
        if user is None:
            raise OidcError("OIDC identity is linked to an unknown account")
        return user, identity, "existing_identity"

    if not _email_domain_allowed(claims.email):
        raise OidcError("OIDC email domain is not allowed")

    user = _load_user(db, claims.email)
    link_mode = "email_link"
    if user is not None:
        if not settings.oidc_allow_email_linking:
            raise OidcError("OIDC account requires an administrator-created identity link")
    else:
        if not settings.oidc_auto_provision or not settings.oidc_default_tenant_id:
            raise OidcError("OIDC account is not provisioned")
        tenant = db.get(Tenant, settings.oidc_default_tenant_id)
        if tenant is None or not tenant.is_active:
            raise OidcError("OIDC default tenant is unavailable")
        role = db.scalar(
            select(Role).where(
                Role.tenant_id == tenant.id,
                Role.code == settings.oidc_default_role_code,
            )
        )
        if role is None:
            raise OidcError("OIDC default role is unavailable")
        user = User(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            role_id=role.id,
            email=claims.email,
            full_name=claims.full_name,
            identity_source="OIDC",
            provisioning_state="ACTIVE",
            password_hash="external_identity_only",
            is_active=True,
            is_superuser=False,
            is_root=False,
        )
        db.add(user)
        db.flush()
        link_mode = "auto_provision"

    identity = ExternalIdentity(
        id=str(uuid.uuid4()),
        user_id=user.id,
        provider_name=settings.oidc_provider_name,
        issuer=claims.issuer,
        subject=claims.subject,
        email_at_link=claims.email,
    )
    db.add(identity)
    return user, identity, link_mode


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthUserResponse:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    payload = decode_token(authorization.removeprefix("Bearer ").strip(), expected_type="access")
    _active_session(db, payload)
    user_id = str(payload.get("sub"))
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown account")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    password_change_paths = {
        f"{settings.api_v1_prefix}/auth/me",
        f"{settings.api_v1_prefix}/auth/account",
        f"{settings.api_v1_prefix}/auth/password/change",
        f"{settings.api_v1_prefix}/auth/sessions",
    }
    if (
        user.must_change_password
        and request.url.path not in password_change_paths
        and not request.url.path.startswith(
            f"{settings.api_v1_prefix}/auth/sessions/"
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required before accessing this resource",
        )

    mfa_config = db.scalar(
        select(UserMfa).where(UserMfa.user_id == user.id, UserMfa.enabled.is_(True))
    )
    return _to_response(
        _auth_user(user),
        _permission_codes(user),
        mfa_enabled=mfa_config is not None,
        mfa_verified=bool(payload.get("mfa")),
    )


def _load_user(db: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    return db.scalar(statement)


def _permission_codes(user: User) -> list[str]:
    permission_codes = set()
    if user.role is not None:
        permission_codes.update(permission.code for permission in user.role.permissions)
    for role in user.roles:
        permission_codes.update(permission.code for permission in role.permissions)
    return sorted(permission_codes)


def _auth_user(user: User) -> AuthUser:
    return AuthUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        tenant_id=user.tenant_id,
        role=user.role.code if user.role is not None else "member",
        must_change_password=user.must_change_password,
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _mfa_config(db: Session, user_id: str) -> UserMfa | None:
    return db.scalar(select(UserMfa).where(UserMfa.user_id == user_id))


def _role_requires_mfa(user: User) -> bool:
    role_code = user.role.code if user.role is not None else "member"
    return role_code in settings.mfa_required_role_codes


def _create_mfa_login_challenge(db: Session, user: User) -> MfaChallengeResponse:
    now = datetime.now(UTC)
    db.execute(
        delete(MfaLoginChallenge).where(
            MfaLoginChallenge.expires_at <= now,
        )
    )
    raw_token, token_hash = create_challenge_token()
    db.add(
        MfaLoginChallenge(
            id=str(uuid.uuid4()),
            token_hash=token_hash,
            user_id=user.id,
            expires_at=now + timedelta(seconds=settings.mfa_challenge_ttl_seconds),
        )
    )
    return MfaChallengeResponse(
        challenge_token=raw_token,
        expires_in_seconds=settings.mfa_challenge_ttl_seconds,
    )


def _load_mfa_login_challenge(
    db: Session,
    raw_token: str,
) -> tuple[MfaLoginChallenge, User]:
    challenge = db.scalar(
        select(MfaLoginChallenge).where(
            MfaLoginChallenge.token_hash == hash_challenge_token(raw_token)
        )
    )
    if (
        challenge is None
        or challenge.consumed_at is not None
        or _as_utc(challenge.expires_at) <= datetime.now(UTC)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired MFA challenge",
        )
    user = db.get(User, challenge.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired MFA challenge",
        )
    return challenge, user


def _verify_mfa_code(config: UserMfa, code: str) -> str | None:
    if is_locked(config.locked_until):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="MFA is temporarily locked after repeated failures",
        )
    secret = decrypt_totp_secret(config.secret_ciphertext)
    used_step = verify_totp(secret, code, last_used_step=config.last_used_step)
    if used_step is not None:
        config.last_used_step = used_step
        config.failed_attempts = 0
        config.locked_until = None
        return "totp"
    recovery_valid, updated_hashes = consume_recovery_code(
        config.recovery_code_hashes_json,
        code,
    )
    if recovery_valid:
        config.recovery_code_hashes_json = updated_hashes
        config.failed_attempts = 0
        config.locked_until = None
        return "recovery_code"
    return None


def _record_mfa_failure(config: UserMfa) -> None:
    config.failed_attempts += 1
    if config.failed_attempts >= settings.mfa_max_attempts:
        config.failed_attempts = 0
        config.locked_until = datetime.now(UTC) + timedelta(seconds=settings.mfa_lockout_seconds)


@router.get("/sso/config", response_model=SsoConfigResponse)
def sso_config() -> SsoConfigResponse:
    if not settings.oidc_enabled:
        return SsoConfigResponse(enabled=False)
    return SsoConfigResponse(
        enabled=True,
        provider_name=settings.oidc_provider_name,
        button_label=settings.oidc_button_label,
        login_path=f"{settings.api_v1_prefix}/auth/sso/login",
    )


@router.get("/sso/login")
async def sso_login(return_to: str = "/dashboard") -> RedirectResponse:
    if not settings.oidc_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO is not enabled")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier, code_challenge = create_pkce_pair()
    state_cookie = create_token(
        {
            "sub": "oidc-state",
            "email": "oidc-state@sbs.local",
            "state": state,
            "nonce": nonce,
            "code_verifier": code_verifier,
            "return_to": _safe_return_to(return_to),
        },
        expires_in_seconds=settings.oidc_state_ttl_seconds,
        token_type="oidc_state",
    )
    try:
        authorization_url = await oidc_client.authorization_url(
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
        )
    except OidcError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSO provider is unavailable",
        ) from exc
    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        OIDC_STATE_COOKIE_NAME,
        state_cookie,
        max_age=settings.oidc_state_ttl_seconds,
        httponly=True,
        secure=settings.app_env.lower() == "production",
        samesite="lax",
        path=f"{settings.api_v1_prefix}/auth/sso",
    )
    return response


@router.get("/sso/callback")
async def sso_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not settings.oidc_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO is not enabled")
    state_cookie = request.cookies.get(OIDC_STATE_COOKIE_NAME)
    if not state_cookie or not state:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid SSO state")
    try:
        state_payload = decode_token(state_cookie, expected_type="oidc_state")
    except HTTPException as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid SSO state") from exc
    expected_state = str(state_payload.get("state") or "")
    if not expected_state or not hmac.compare_digest(expected_state, state):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid SSO state")

    return_to = _safe_return_to(str(state_payload.get("return_to") or "/dashboard"))
    response: RedirectResponse
    try:
        if error or not code:
            raise OidcError("OIDC provider returned an authorization error")
        token_payload = await oidc_client.exchange_code(
            code=code,
            code_verifier=str(state_payload.get("code_verifier") or ""),
        )
        claims = await oidc_client.validate_id_token(
            str(token_payload["id_token"]),
            expected_nonce=str(state_payload.get("nonce") or ""),
        )
        user, identity, link_mode = _resolve_oidc_user(db, claims)
        if not user.is_active:
            raise OidcError("OIDC account is deactivated")

        now = datetime.now(UTC)
        user.last_login_at = now
        identity.last_login_at = now
        identity.email_at_link = claims.email
        auth_user = _auth_user(user)
        log_audit(
            db,
            action="oidc_login_success",
            entity_type="auth",
            entity_id=user.id,
            actor_user=user,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            metadata={
                "provider": settings.oidc_provider_name,
                "issuer": claims.issuer,
                "link_mode": link_mode,
            },
        )
        token_pair = _issue_tokens(
            db,
            auth_user,
            _permission_codes(user),
            auth_method="sso",
            request=request,
        )
        db.commit()
        query = urlencode({"sso": "success", "return_to": return_to})
        response = RedirectResponse(f"/login?{query}", status_code=status.HTTP_302_FOUND)
        _set_refresh_cookie(response, token_pair.refresh_token or "")
    except (OidcError, IntegrityError) as exc:
        db.rollback()
        reason = str(exc) if isinstance(exc, OidcError) else "identity_link_conflict"
        log_audit(
            db,
            action="oidc_login_failed",
            entity_type="auth",
            entity_id=None,
            actor_email="oidc-user@sbs.local",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            metadata={"provider": settings.oidc_provider_name, "reason": reason},
        )
        db.commit()
        response = RedirectResponse(
            "/login?sso=error", status_code=status.HTTP_302_FOUND
        )
    response.delete_cookie(
        OIDC_STATE_COOKIE_NAME,
        path=f"{settings.api_v1_prefix}/auth/sso",
        secure=settings.app_env.lower() == "production",
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/login", response_model=TokenPair | MfaChallengeResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenPair | MfaChallengeResponse:
    normalized_email = payload.email.strip().lower()
    client_ip = request.client.host if request.client else None
    db.execute(delete(AuthSession).where(AuthSession.refresh_expires_at <= int(time.time())))
    window_start = datetime.now(UTC) - timedelta(seconds=settings.login_rate_limit_window_seconds)
    recent_failures = int(
        db.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.actor_email == normalized_email,
                AuditLog.action == "login_failed",
                AuditLog.created_at >= window_start,
            )
        )
        or 0
    )
    recent_ip_failures = (
        int(
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.ip_address == client_ip,
                    AuditLog.action == "login_failed",
                    AuditLog.created_at >= window_start,
                )
            )
            or 0
        )
        if client_ip
        else 0
    )
    if (
        recent_failures >= settings.login_rate_limit_attempts
        or recent_ip_failures >= settings.login_ip_rate_limit_attempts
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts; try again later",
            headers={"Retry-After": str(settings.login_rate_limit_window_seconds)},
        )

    user = _load_user(db, normalized_email)
    is_local_user = user is not None and user.identity_source == "LOCAL"
    candidate_hash = user.password_hash if is_local_user else DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, candidate_hash)
    if not is_local_user or not password_valid:
        log_audit(
            db,
            action="login_failed",
            entity_type="auth",
            entity_id=None,
            actor_email=normalized_email,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            metadata={"reason": "invalid_credentials"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        log_audit(
            db,
            action="login_failed",
            entity_type="auth",
            entity_id=user.id,
            actor_user=user,
            metadata={"reason": "inactive_user"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    mfa_config = _mfa_config(db, user.id)
    mfa_enabled = bool(mfa_config and mfa_config.enabled)
    if settings.mfa_enforcement_enabled and _role_requires_mfa(user) and not mfa_enabled:
        log_audit(
            db,
            action="login_failed",
            entity_type="auth",
            entity_id=user.id,
            actor_user=user,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            metadata={"reason": "mfa_enrollment_required"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA enrollment is required for this privileged role",
        )

    if mfa_enabled:
        challenge = _create_mfa_login_challenge(db, user)
        log_audit(
            db,
            action="login_mfa_challenge",
            entity_type="auth",
            entity_id=user.id,
            actor_user=user,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            metadata={"methods": challenge.methods},
        )
        db.commit()
        return challenge

    user.last_login_at = datetime.now(UTC)
    auth_user = _auth_user(user)
    log_audit(
        db,
        action="login_success",
        entity_type="auth",
        entity_id=user.id,
        actor_user=user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"role": auth_user.role},
    )
    db.commit()
    result = _issue_tokens(
        db,
        auth_user,
        _permission_codes(user),
        request=request,
    )
    db.commit()
    _set_refresh_cookie(response, result.refresh_token or "")
    return result.model_copy(update={"refresh_token": None})


@router.post("/mfa/verify-login", response_model=TokenPair)
def verify_mfa_login(
    payload: MfaLoginVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenPair:
    challenge, user = _load_mfa_login_challenge(db, payload.challenge_token)
    config = _mfa_config(db, user.id)
    if config is None or not config.enabled:
        challenge.consumed_at = datetime.now(UTC)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA is not enabled for this account",
        )
    if challenge.attempts >= settings.mfa_max_attempts:
        challenge.consumed_at = datetime.now(UTC)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="MFA challenge attempt limit exceeded",
        )

    method = _verify_mfa_code(config, payload.code)
    if method is None:
        challenge.attempts += 1
        _record_mfa_failure(config)
        if challenge.attempts >= settings.mfa_max_attempts:
            challenge.consumed_at = datetime.now(UTC)
        log_audit(
            db,
            action="login_mfa_failed",
            entity_type="auth",
            entity_id=user.id,
            actor_user=user,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            metadata={"challenge_attempt": challenge.attempts},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")

    challenge.consumed_at = datetime.now(UTC)
    user.last_login_at = datetime.now(UTC)
    log_audit(
        db,
        action="login_success",
        entity_type="auth",
        entity_id=user.id,
        actor_user=user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"role": _auth_user(user).role, "mfa_method": method},
    )
    result = _issue_tokens(
        db,
        _auth_user(user),
        _permission_codes(user),
        mfa_verified=True,
        auth_method="pwd",
        request=request,
    )
    db.commit()
    _set_refresh_cookie(response, result.refresh_token or "")
    return result.model_copy(update={"refresh_token": None})


@router.post("/refresh", response_model=TokenPair)
def refresh(
    response: Response,
    http_request: Request,
    request: RefreshRequest | None = None,
    db: Session = Depends(get_db),
) -> TokenPair:
    refresh_token = (request.refresh_token if request else None) or http_request.cookies.get(
        REFRESH_COOKIE_NAME
    )
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    payload = decode_token(refresh_token, expected_type="refresh")
    session = _locked_refresh_session(db, payload)
    if session.revoked_at is not None:
        user = db.get(User, session.user_id)
        descendants_revoked = _revoke_replacement_chain(db, session)
        log_audit(
            db,
            action="refresh_token_reuse_detected",
            entity_type="auth_session",
            entity_id=session.id,
            actor_user=user,
            actor_email=user.email if user is not None else str(payload.get("email")),
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
            metadata={"descendant_sessions_revoked": descendants_revoked},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected; session family revoked",
        )
    if session.refresh_expires_at <= int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or revoked",
        )
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown account")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    auth_methods = payload.get("amr") if isinstance(payload.get("amr"), list) else []
    result = _issue_tokens(
        db,
        _auth_user(user),
        _permission_codes(user),
        replaced_session=session,
        mfa_verified=bool(payload.get("mfa")),
        auth_method="sso" if "sso" in auth_methods else "pwd",
        request=http_request,
    )
    db.commit()
    _set_refresh_cookie(response, result.refresh_token or "")
    return result.model_copy(update={"refresh_token": None})


@router.get("/me", response_model=AuthUserResponse)
def me(current_user: AuthUserResponse = Depends(get_current_user)) -> AuthUserResponse:
    return current_user


@router.get("/account", response_model=AccountResponse)
def get_account(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountResponse:
    user = db.get(User, current_user.id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown account",
        )
    return AccountResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        tenant_id=user.tenant_id,
        role=current_user.role,
        identity_source=user.identity_source,
        provisioning_state=user.provisioning_state,
        local_password_supported=user.identity_source == "LOCAL",
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
    )


@router.get("/sessions", response_model=list[SelfSessionResponse])
def list_my_sessions(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[SelfSessionResponse]:
    current_session_id = _current_session_id(authorization)
    now_epoch = int(time.time())
    sessions = db.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == current_user.id)
        .order_by(AuthSession.created_at.desc())
        .limit(100)
    ).all()
    return [
        SelfSessionResponse(
            id=session.id,
            created_at=session.created_at,
            refresh_expires_at=datetime.fromtimestamp(
                session.refresh_expires_at,
                tz=UTC,
            ),
            revoked_at=session.revoked_at,
            replaced_by_id=session.replaced_by_id,
            ip_address=session.ip_address,
            user_agent=session.user_agent,
            auth_method=session.auth_method,
            is_active=(
                session.revoked_at is None
                and session.refresh_expires_at > now_epoch
            ),
            is_current=session.id == current_session_id,
        )
        for session in sessions
    ]


@router.post(
    "/sessions/{session_id}/revoke",
    response_model=SelfSessionRevokeResponse,
)
def revoke_my_session(
    session_id: str,
    response: Response,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> SelfSessionRevokeResponse:
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == current_user.id,
        )
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    current_session_revoked = session.id == _current_session_id(authorization)
    if session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
    actor = db.get(User, current_user.id)
    log_audit(
        db,
        action="self_session_revoked",
        entity_type="auth_session",
        entity_id=session.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"current_session_revoked": current_session_revoked},
    )
    db.commit()
    if current_session_revoked:
        _delete_refresh_cookie(response)
    return SelfSessionRevokeResponse(
        session_id=session.id,
        revoked=True,
        current_session_revoked=current_session_revoked,
    )


@router.post("/password/change", response_model=PasswordChangeResponse)
def change_my_password(
    payload: PasswordChangeRequest,
    response: Response,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PasswordChangeResponse:
    user = db.get(User, current_user.id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown account",
        )
    if user.identity_source != "LOCAL":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Password is managed by the external identity provider",
        )
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is invalid",
        )
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current password",
        )
    password_error = validate_password_strength(
        payload.new_password,
        minimum_length=get_password_minimum_length(db, user.tenant_id),
        demo_mode=settings.demo_mode,
    )
    if password_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=password_error,
        )

    sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    revoked_at = datetime.now(UTC)
    for session in sessions:
        session.revoked_at = revoked_at
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.updated_at = revoked_at
    log_audit(
        db,
        action="self_password_changed",
        entity_type="user",
        entity_id=user.id,
        actor_user=user,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"sessions_revoked": len(sessions)},
    )
    db.commit()
    _delete_refresh_cookie(response)
    return PasswordChangeResponse(
        changed=True,
        sessions_revoked=len(sessions),
    )


@router.get("/mfa/status", response_model=MfaStatusResponse)
def get_mfa_status(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaStatusResponse:
    config = _mfa_config(db, current_user.id)
    return MfaStatusResponse(
        enabled=bool(config and config.enabled),
        verified_at=config.verified_at if config and config.enabled else None,
        recovery_codes_remaining=count_recovery_codes(config.recovery_code_hashes_json)
        if config and config.enabled
        else 0,
        locked=bool(config and is_locked(config.locked_until)),
        policy_enforced=settings.mfa_enforcement_enabled,
        required_for_role=current_user.role in settings.mfa_required_role_codes,
        current_session_verified=current_user.mfa_verified,
    )


@router.post("/mfa/enroll", response_model=MfaEnrollmentResponse)
def enroll_mfa(
    payload: MfaEnrollmentRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaEnrollmentResponse:
    user = db.get(User, current_user.id)
    if user is None or not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is invalid",
        )
    config = _mfa_config(db, user.id)
    if config is not None and config.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MFA is already enabled")

    secret = generate_totp_secret()
    if config is None:
        config = UserMfa(
            id=str(uuid.uuid4()),
            user_id=user.id,
            secret_ciphertext=encrypt_totp_secret(secret),
        )
        db.add(config)
    else:
        config.secret_ciphertext = encrypt_totp_secret(secret)
        config.recovery_code_hashes_json = "[]"
        config.last_used_step = None
        config.failed_attempts = 0
        config.locked_until = None
        config.verified_at = None
    log_audit(
        db,
        action="mfa_enrollment_started",
        entity_type="user",
        entity_id=user.id,
        actor_user=user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"method": "totp"},
    )
    db.commit()
    return MfaEnrollmentResponse(
        secret=secret,
        otpauth_uri=build_otpauth_uri(secret, user.email, settings.mfa_issuer_name),
        issuer=settings.mfa_issuer_name,
        account_name=user.email,
    )


@router.post("/mfa/confirm", response_model=MfaRecoveryCodesResponse)
def confirm_mfa_enrollment(
    payload: MfaCodeRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaRecoveryCodesResponse:
    user = db.get(User, current_user.id)
    config = _mfa_config(db, current_user.id)
    if user is None or config is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MFA enrollment was not started")
    if config.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MFA is already enabled")
    secret = decrypt_totp_secret(config.secret_ciphertext)
    if verify_totp(secret, payload.code) is None:
        _record_mfa_failure(config)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    recovery_codes = generate_recovery_codes()
    config.enabled = True
    # Enrollment proof is not an authentication event. Allow the same current
    # TOTP window to be used once for the user's first MFA login.
    config.last_used_step = None
    config.recovery_code_hashes_json = encode_recovery_code_hashes(recovery_codes)
    config.failed_attempts = 0
    config.locked_until = None
    config.verified_at = datetime.now(UTC)
    log_audit(
        db,
        action="mfa_enabled",
        entity_type="user",
        entity_id=user.id,
        actor_user=user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"method": "totp", "recovery_code_count": len(recovery_codes)},
    )
    db.commit()
    return MfaRecoveryCodesResponse(recovery_codes=recovery_codes)


@router.post("/mfa/recovery-codes/regenerate", response_model=MfaRecoveryCodesResponse)
def regenerate_mfa_recovery_codes(
    payload: MfaCodeRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaRecoveryCodesResponse:
    user = db.get(User, current_user.id)
    config = _mfa_config(db, current_user.id)
    if user is None or config is None or not config.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MFA is not enabled")
    if is_locked(config.locked_until):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="MFA is temporarily locked")
    secret = decrypt_totp_secret(config.secret_ciphertext)
    used_step = verify_totp(secret, payload.code, last_used_step=config.last_used_step)
    if used_step is None:
        _record_mfa_failure(config)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    recovery_codes = generate_recovery_codes()
    config.last_used_step = used_step
    config.recovery_code_hashes_json = encode_recovery_code_hashes(recovery_codes)
    config.failed_attempts = 0
    config.locked_until = None
    log_audit(
        db,
        action="mfa_recovery_codes_regenerated",
        entity_type="user",
        entity_id=user.id,
        actor_user=user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"recovery_code_count": len(recovery_codes)},
    )
    db.commit()
    return MfaRecoveryCodesResponse(recovery_codes=recovery_codes)


@router.post("/mfa/disable", response_model=MfaDisableResponse)
def disable_mfa(
    payload: MfaDisableRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaDisableResponse:
    user = db.get(User, current_user.id)
    config = _mfa_config(db, current_user.id)
    if user is None or config is None or not config.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MFA is not enabled")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Current password is invalid")
    method = _verify_mfa_code(config, payload.code)
    if method is None:
        _record_mfa_failure(config)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code")

    active_sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    revoked_at = datetime.now(UTC)
    for auth_session in active_sessions:
        auth_session.revoked_at = revoked_at
    log_audit(
        db,
        action="mfa_disabled",
        entity_type="user",
        entity_id=user.id,
        actor_user=user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"verification_method": method, "sessions_revoked": len(active_sessions)},
    )
    db.delete(config)
    db.commit()
    return MfaDisableResponse(disabled=True, sessions_revoked=len(active_sessions))


@router.post("/logout")
def logout(
    request: LogoutRequest,
    response: Response,
    http_request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    actor: User | None = None
    actor_email = "unknown@sbs.local"

    if authorization and authorization.startswith("Bearer "):
        try:
            payload = decode_token(authorization.removeprefix("Bearer ").strip(), expected_type="access")
            actor = db.scalar(select(User).where(User.id == str(payload.get("sub"))))
        except HTTPException:
            actor = None

    if actor is not None:
        actor_email = actor.email

    refresh_jti = None
    session_id = None
    refresh_token = request.refresh_token or http_request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token:
        try:
            refresh_payload = decode_token(refresh_token, expected_type="refresh")
            refresh_jti = str(refresh_payload.get("jti"))
            session_id = str(refresh_payload.get("sid") or "")
            if actor is None:
                actor = _load_user(db, str(refresh_payload.get("email")))
                if actor is not None:
                    actor_email = actor.email
        except HTTPException:
            refresh_jti = None

    if session_id is None and authorization and authorization.startswith("Bearer "):
        try:
            access_payload = decode_token(
                authorization.removeprefix("Bearer ").strip(), expected_type="access"
            )
            session_id = str(access_payload.get("sid") or "")
        except HTTPException:
            session_id = None

    session = db.get(AuthSession, session_id) if session_id else None
    if session is not None:
        session.revoked_at = datetime.now(UTC)

    log_audit(
        db,
        action="logout_success",
        entity_type="auth",
        entity_id=actor.id if actor is not None else None,
        actor_user=actor,
        actor_email=actor_email,
        metadata={"refresh_jti": refresh_jti},
    )
    db.commit()
    _delete_refresh_cookie(response)
    return {"ok": True}
