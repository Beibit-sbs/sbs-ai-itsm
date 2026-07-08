from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit import parse_metadata, summarize_security
from app.services.rbac import is_saas_root, require_permissions

router = APIRouter(prefix="/security")


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


class SecurityRiskSummaryResponse(BaseModel):
    failed_logins_24h: int
    success_logins_24h: int
    active_users: int
    risk_level: str
    recent_security_events: list[dict[str, object]]


@router.get("/login-events", response_model=list[LoginEventResponse])
def get_login_events(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[LoginEventResponse]:
    require_permissions(current_user, "security.login_events.read")
    statement = select(AuditLog).where(AuditLog.action.in_(["login_success", "login_failed"]))
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
    now = datetime.now(UTC)
    logged_in_last_24h = sum(1 for item in users if item.last_login_at and item.last_login_at >= now - timedelta(hours=24))
    return SessionOverviewResponse(
        active_users=sum(1 for item in users if item.is_active),
        logged_in_last_24h=logged_in_last_24h,
        inactive_users=sum(1 for item in users if not item.is_active),
        session_timeout_minutes=60,
    )


@router.get("/risk-summary", response_model=SecurityRiskSummaryResponse)
def get_risk_summary(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> SecurityRiskSummaryResponse:
    require_permissions(current_user, "security.audit.read")
    summary = summarize_security(db)
    if not is_saas_root(current_user):
        failed = int(
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "login_failed",
                    AuditLog.tenant_id == current_user.tenant_id,
                    AuditLog.created_at >= datetime.now(UTC) - timedelta(hours=24),
                )
            )
            or 0
        )
        summary["failed_logins_24h"] = failed
    return SecurityRiskSummaryResponse(**summary)
