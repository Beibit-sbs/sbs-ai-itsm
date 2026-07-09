from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.analytics import (
    collect_overview,
    get_ai_analytics as svc_get_ai_analytics,
    get_asset_analytics as svc_get_asset_analytics,
    get_automation_analytics as svc_get_automation_analytics,
    get_executive_analytics as svc_get_executive_analytics,
    get_knowledge_analytics as svc_get_knowledge_analytics,
    get_security_analytics as svc_get_security_analytics,
    get_sla_analytics as svc_get_sla_analytics,
    get_ticket_analytics as svc_get_ticket_analytics,
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


def _analytics_filters(
    date_from: datetime | None,
    date_to: datetime | None,
    group_by: str | None,
    category: str | None,
    priority: str | None,
    assignee_id: str | None,
    status: str | None,
) -> dict[str, object]:
    return {
        "date_from": date_from,
        "date_to": date_to,
        "group_by": group_by,
        "category": category,
        "priority": priority,
        "assignee_id": assignee_id,
        "status": status,
    }


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
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    group_by: str = Query(default="day", pattern="^(day|week|month)$"),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read", "analytics.tickets.read")
    _audit_view(db, request, current_user, "tickets")
    return svc_get_ticket_analytics(
        db,
        _analytics_filters(date_from, date_to, group_by, category, priority, assignee_id, status),
        current_user,
    )


@router.get("/sla")
def get_sla_analytics(
    request: Request,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    group_by: str = Query(default="day", pattern="^(day|week|month)$"),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read", "analytics.sla.read")
    _audit_view(db, request, current_user, "sla")
    return svc_get_sla_analytics(
        db,
        _analytics_filters(date_from, date_to, group_by, category, priority, assignee_id, status),
        current_user,
    )


@router.get("/assets")
def get_asset_analytics(
    request: Request,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    group_by: str = Query(default="month", pattern="^(day|week|month)$"),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read", "analytics.assets.read")
    _audit_view(db, request, current_user, "assets")
    return svc_get_asset_analytics(
        db,
        _analytics_filters(date_from, date_to, group_by, category, priority, assignee_id, status),
        current_user,
    )


@router.get("/ai")
def get_ai_analytics(
    request: Request,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    group_by: str = Query(default="day", pattern="^(day|week|month)$"),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read", "analytics.ai.read")
    _audit_view(db, request, current_user, "ai")
    return svc_get_ai_analytics(
        db,
        _analytics_filters(date_from, date_to, group_by, category, priority, assignee_id, status),
        current_user,
    )


@router.get("/knowledge")
def get_knowledge_analytics(
    request: Request,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    group_by: str = Query(default="day", pattern="^(day|week|month)$"),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read", "analytics.knowledge.read")
    _audit_view(db, request, current_user, "knowledge")
    return svc_get_knowledge_analytics(
        db,
        _analytics_filters(date_from, date_to, group_by, category, priority, assignee_id, status),
        current_user,
    )


@router.get("/security")
def get_security_analytics(
    request: Request,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    group_by: str = Query(default="day", pattern="^(day|week|month)$"),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read", "analytics.security.read")
    _audit_view(db, request, current_user, "security")
    return svc_get_security_analytics(
        db,
        _analytics_filters(date_from, date_to, group_by, category, priority, assignee_id, status),
        current_user,
    )


@router.get("/automation")
def get_automation_analytics(
    request: Request,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    group_by: str = Query(default="day", pattern="^(day|week|month)$"),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read", "analytics.automation.read")
    _audit_view(db, request, current_user, "automation")
    return svc_get_automation_analytics(
        db,
        _analytics_filters(date_from, date_to, group_by, category, priority, assignee_id, status),
        current_user,
    )


@router.get("/executive")
def get_executive_analytics_endpoint(
    request: Request,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    group_by: str = Query(default="day", pattern="^(day|week|month)$"),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "analytics.read", "analytics.executive.read")
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="executive_analytics_viewed",
        entity_type="analytics",
        entity_id="executive",
        actor_user=actor,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={
            "analytics_type": "executive",
            "user_id": current_user.id,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    db.commit()
    return svc_get_executive_analytics(
        db,
        current_user,
        _analytics_filters(date_from, date_to, group_by, category, priority, assignee_id, status),
    )


@router.get("/executive-summary")
def get_executive_summary_legacy(
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_executive_analytics_endpoint(request=request, current_user=current_user, db=db)
