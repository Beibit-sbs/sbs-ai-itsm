from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.analytics import (
    collect_ai_metrics,
    collect_asset_metrics,
    collect_executive_summary,
    collect_knowledge_metrics,
    collect_notification_metrics,
    collect_overview,
    collect_security_metrics,
    collect_sla_metrics,
    collect_ticket_metrics,
)
from app.services.audit import log_audit
from app.services.rbac import require_permissions

router = APIRouter(prefix="/analytics")


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.get(User, current_user.id)


def _tenant_scope(current_user: AuthUserResponse) -> str | None:
    return None if current_user.role == "saas_root" else current_user.tenant_id


def _audit_view(db: Session, request: Request, current_user: AuthUserResponse, analytics_type: str) -> None:
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="analytics_viewed",
        entity_type="analytics",
        entity_id=analytics_type,
        actor_user=actor,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"analytics_type": analytics_type},
    )
    db.commit()


@router.get("/overview")
def get_analytics_overview(
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read")
    _audit_view(db, request, current_user, "overview")
    return collect_overview(db, _tenant_scope(current_user))


@router.get("/tickets")
def get_ticket_analytics(
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read")
    _audit_view(db, request, current_user, "tickets")
    return collect_ticket_metrics(db, _tenant_scope(current_user))


@router.get("/sla")
def get_sla_analytics(
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read")
    _audit_view(db, request, current_user, "sla")
    return collect_sla_metrics(db, _tenant_scope(current_user))


@router.get("/assets")
def get_asset_analytics(
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read")
    _audit_view(db, request, current_user, "assets")
    return collect_asset_metrics(db, _tenant_scope(current_user))


@router.get("/ai")
def get_ai_analytics(
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read")
    _audit_view(db, request, current_user, "ai")
    return collect_ai_metrics(db, _tenant_scope(current_user))


@router.get("/knowledge")
def get_knowledge_analytics(
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read")
    _audit_view(db, request, current_user, "knowledge")
    return collect_knowledge_metrics(db, _tenant_scope(current_user))


@router.get("/notifications")
def get_notification_analytics(
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read")
    _audit_view(db, request, current_user, "notifications")
    return collect_notification_metrics(db, _tenant_scope(current_user))


@router.get("/security")
def get_security_analytics(
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read")
    _audit_view(db, request, current_user, "security")
    return collect_security_metrics(db, _tenant_scope(current_user))


@router.get("/executive-summary")
def get_executive_summary(
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read")
    _audit_view(db, request, current_user, "executive-summary")
    return collect_executive_summary(db, _tenant_scope(current_user))
