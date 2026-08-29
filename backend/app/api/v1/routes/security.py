from __future__ import annotations

from datetime import UTC, datetime, timedelta
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.models.user_mfa import UserMfa
from app.services.audit import log_audit, parse_metadata, summarize_security
from app.services.mfa import count_recovery_codes, is_locked
from app.services.rbac import is_saas_root, require_permissions

router = APIRouter(prefix="/security")
settings = get_settings()


class LoginEventResponse(BaseModel):
    id: str
    actor_email: str
    action: str
    ip_address: str | None
    user_agent: str | None
    metadata: dict[str, object]
    created_at: datetime


class SessionOverviewResponse(BaseModel):
    active_users: int
    logged_in_last_24h: int
    inactive_users: int
    session_timeout_minutes: int
    active_sessions: int
    revoked_sessions: int
    expired_sessions: int
    refresh_ttl_minutes: int


class SecuritySessionResponse(BaseModel):
    id: str
    user_id: str
    user_email: str
    user_name: str
    tenant_id: str | None
    created_at: datetime
    refresh_expires_at: datetime
    revoked_at: datetime | None
    replaced_by_id: str | None
    ip_address: str | None
    user_agent: str | None
    auth_method: str | None
    is_active: bool
    is_current: bool


class SessionRevokeResponse(BaseModel):
    session_id: str
    revoked: bool


class UserSessionsRevokeResponse(BaseModel):
    user_id: str
    sessions_revoked: int


class SecurityRiskSummaryResponse(BaseModel):
    failed_logins_24h: int
    success_logins_24h: int
    active_users: int
    risk_level: str
    recent_security_events: list[dict[str, object]]


class MfaUserStatusResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str
    active: bool
    required: bool
    enabled: bool
    verified_at: datetime | None
    recovery_codes_remaining: int
    locked: bool


class MfaOverviewResponse(BaseModel):
    enforcement_enabled: bool
    required_role_codes: list[str]
    total_users: int
    enrolled_users: int
    required_users: int
    required_users_without_mfa: int
    current_session_verified: bool
    users: list[MfaUserStatusResponse]


class MfaAdminResetResponse(BaseModel):
    user_id: str
    reset: bool
    sessions_revoked: int


def _current_session_id(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(
        authorization.removeprefix("Bearer ").strip(),
        expected_type="access",
    )
    return str(payload.get("sid") or "") or None


def _session_timeout_minutes(db: Session, tenant_id: str | None) -> int:
    statement = select(SystemSetting).where(SystemSetting.key == "session_timeout_minutes")
    candidate = (
        db.scalar(statement.where(SystemSetting.tenant_id == tenant_id))
        if tenant_id
        else None
    )
    if candidate is None:
        candidate = db.scalar(statement.where(SystemSetting.tenant_id.is_(None)))
    try:
        return int(candidate.value) if candidate is not None else settings.access_token_ttl_minutes
    except (TypeError, ValueError):
        return settings.access_token_ttl_minutes


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _scoped_sessions_statement(current_user: AuthUserResponse):
    statement = select(AuthSession, User).join(User, User.id == AuthSession.user_id)
    if not is_saas_root(current_user):
        statement = statement.where(User.tenant_id == current_user.tenant_id)
    return statement


def _scoped_users_statement(current_user: AuthUserResponse):
    statement = select(User)
    if not is_saas_root(current_user):
        statement = statement.where(User.tenant_id == current_user.tenant_id)
    return statement


def _session_target(
    db: Session,
    current_user: AuthUserResponse,
    session_id: str,
) -> tuple[AuthSession, User]:
    row = db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(AuthSession.id == session_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    auth_session, user = row
    if not is_saas_root(current_user) and user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return auth_session, user


@router.get("/login-events", response_model=list[LoginEventResponse])
def get_login_events(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[LoginEventResponse]:
    require_permissions(current_user, "security.login_events.read")
    statement = select(AuditLog).where(
        AuditLog.action.in_(
            ["login_success", "login_failed", "login_mfa_challenge", "login_mfa_failed"]
        )
    )
    if not is_saas_root(current_user):
        statement = statement.where(AuditLog.tenant_id == current_user.tenant_id)
    rows = db.scalars(statement.order_by(AuditLog.created_at.desc()).limit(200)).all()
    return [
        LoginEventResponse(
            id=item.id,
            actor_email=item.actor_email,
            action=item.action,
            ip_address=item.ip_address,
            user_agent=item.user_agent,
            metadata=parse_metadata(item.metadata_json),
            created_at=item.created_at,
        )
        for item in rows
    ]


@router.get("/session-overview", response_model=SessionOverviewResponse)
def get_session_overview(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> SessionOverviewResponse:
    require_permissions(current_user, "security.sessions.read")
    users_stmt = select(User)
    if not is_saas_root(current_user):
        users_stmt = users_stmt.where(User.tenant_id == current_user.tenant_id)
    users = db.scalars(users_stmt).all()
    session_rows = db.execute(_scoped_sessions_statement(current_user)).all()
    now_epoch = int(time.time())
    now = datetime.now(UTC)
    logged_in_last_24h = sum(
        1
        for item in users
        if item.last_login_at
        and _as_utc(item.last_login_at) >= now - timedelta(hours=24)
    )
    return SessionOverviewResponse(
        active_users=sum(1 for item in users if item.is_active),
        logged_in_last_24h=logged_in_last_24h,
        inactive_users=sum(1 for item in users if not item.is_active),
        session_timeout_minutes=_session_timeout_minutes(db, current_user.tenant_id),
        active_sessions=sum(
            1
            for auth_session, user in session_rows
            if user.is_active
            and auth_session.revoked_at is None
            and auth_session.refresh_expires_at > now_epoch
        ),
        revoked_sessions=sum(
            1 for auth_session, _user in session_rows if auth_session.revoked_at is not None
        ),
        expired_sessions=sum(
            1
            for auth_session, _user in session_rows
            if auth_session.revoked_at is None and auth_session.refresh_expires_at <= now_epoch
        ),
        refresh_ttl_minutes=settings.refresh_token_ttl_minutes,
    )


@router.get("/sessions", response_model=list[SecuritySessionResponse])
def list_sessions(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[SecuritySessionResponse]:
    require_permissions(current_user, "security.sessions.read")
    current_session_id = _current_session_id(authorization)
    now_epoch = int(time.time())
    rows = db.execute(
        _scoped_sessions_statement(current_user).order_by(AuthSession.created_at.desc()).limit(500)
    ).all()
    return [
        SecuritySessionResponse(
            id=auth_session.id,
            user_id=user.id,
            user_email=user.email,
            user_name=user.full_name,
            tenant_id=user.tenant_id,
            created_at=auth_session.created_at,
            refresh_expires_at=datetime.fromtimestamp(auth_session.refresh_expires_at, tz=UTC),
            revoked_at=auth_session.revoked_at,
            replaced_by_id=auth_session.replaced_by_id,
            ip_address=auth_session.ip_address,
            user_agent=auth_session.user_agent,
            auth_method=auth_session.auth_method,
            is_active=user.is_active
            and auth_session.revoked_at is None
            and auth_session.refresh_expires_at > now_epoch,
            is_current=auth_session.id == current_session_id,
        )
        for auth_session, user in rows
    ]


@router.post("/sessions/{session_id}/revoke", response_model=SessionRevokeResponse)
def revoke_session(
    session_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionRevokeResponse:
    require_permissions(current_user, "security.sessions.manage")
    auth_session, user = _session_target(db, current_user, session_id)
    changed = auth_session.revoked_at is None
    if changed:
        auth_session.revoked_at = datetime.now(UTC)
    actor = db.get(User, current_user.id)
    log_audit(
        db,
        action="session_revoked",
        entity_type="auth_session",
        entity_id=auth_session.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"target_user_id": user.id, "already_revoked": not changed},
    )
    db.commit()
    return SessionRevokeResponse(session_id=auth_session.id, revoked=True)


@router.post("/users/{user_id}/revoke-sessions", response_model=UserSessionsRevokeResponse)
def revoke_user_sessions(
    user_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserSessionsRevokeResponse:
    require_permissions(current_user, "security.sessions.manage")
    user = db.get(User, user_id)
    if user is None or (
        not is_saas_root(current_user) and user.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    active_sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    revoked_at = datetime.now(UTC)
    for auth_session in active_sessions:
        auth_session.revoked_at = revoked_at
    actor = db.get(User, current_user.id)
    log_audit(
        db,
        action="user_sessions_revoked",
        entity_type="user",
        entity_id=user.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"sessions_revoked": len(active_sessions)},
    )
    db.commit()
    return UserSessionsRevokeResponse(user_id=user.id, sessions_revoked=len(active_sessions))


@router.get("/risk-summary", response_model=SecurityRiskSummaryResponse)
def get_risk_summary(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> SecurityRiskSummaryResponse:
    require_permissions(current_user, "security.audit.read")
    summary = summarize_security(db)
    if not is_saas_root(current_user):
        failed = int(
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action.in_(["login_failed", "login_mfa_failed"]),
                    AuditLog.tenant_id == current_user.tenant_id,
                    AuditLog.created_at >= datetime.now(UTC) - timedelta(hours=24),
                )
            )
            or 0
        )
        summary["failed_logins_24h"] = failed
    return SecurityRiskSummaryResponse(**summary)


@router.get("/mfa/overview", response_model=MfaOverviewResponse)
def get_mfa_overview(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaOverviewResponse:
    require_permissions(current_user, "security.mfa.read")
    users = db.scalars(_scoped_users_statement(current_user).order_by(User.email.asc())).all()
    configs = {
        item.user_id: item
        for item in db.scalars(
            select(UserMfa).where(UserMfa.user_id.in_([user.id for user in users]))
        ).all()
    } if users else {}
    rows: list[MfaUserStatusResponse] = []
    for user in users:
        config = configs.get(user.id)
        role_code = user.role.code if user.role is not None else "member"
        enabled = bool(config and config.enabled)
        rows.append(
            MfaUserStatusResponse(
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=role_code,
                active=user.is_active,
                required=role_code in settings.mfa_required_role_codes,
                enabled=enabled,
                verified_at=config.verified_at if enabled and config else None,
                recovery_codes_remaining=count_recovery_codes(
                    config.recovery_code_hashes_json
                )
                if enabled and config
                else 0,
                locked=bool(config and is_locked(config.locked_until)),
            )
        )
    required_rows = [row for row in rows if row.active and row.required]
    return MfaOverviewResponse(
        enforcement_enabled=settings.mfa_enforcement_enabled,
        required_role_codes=list(settings.mfa_required_role_codes),
        total_users=len(rows),
        enrolled_users=sum(1 for row in rows if row.enabled),
        required_users=len(required_rows),
        required_users_without_mfa=sum(1 for row in required_rows if not row.enabled),
        current_session_verified=current_user.mfa_verified,
        users=rows,
    )


@router.post("/users/{user_id}/mfa/reset", response_model=MfaAdminResetResponse)
def reset_user_mfa(
    user_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaAdminResetResponse:
    require_permissions(current_user, "security.mfa.manage")
    if not current_user.mfa_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An MFA-verified session is required to reset another user's MFA",
        )
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use the self-service MFA disable flow for your own account",
        )
    user = db.get(User, user_id)
    if user is None or (
        not is_saas_root(current_user) and user.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    config = db.scalar(select(UserMfa).where(UserMfa.user_id == user.id))
    if config is None:
        return MfaAdminResetResponse(user_id=user.id, reset=False, sessions_revoked=0)

    active_sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    revoked_at = datetime.now(UTC)
    for auth_session in active_sessions:
        auth_session.revoked_at = revoked_at
    db.delete(config)
    actor = db.get(User, current_user.id)
    log_audit(
        db,
        action="mfa_admin_reset",
        entity_type="user",
        entity_id=user.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"sessions_revoked": len(active_sessions)},
    )
    db.commit()
    return MfaAdminResetResponse(
        user_id=user.id,
        reset=True,
        sessions_revoked=len(active_sessions),
    )
