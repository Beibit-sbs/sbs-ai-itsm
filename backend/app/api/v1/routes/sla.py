from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.sla import SlaPolicy
from app.models.ticket import Ticket
from app.models.tenant import Tenant
from app.services.asset_sla import summarize_sla_overview

router = APIRouter(prefix="/sla")


class SlaPolicyResponse(BaseModel):
    id: str
    name: str
    priority: str
    target_response_minutes: int
    target_resolution_minutes: int
    response_minutes: int | None
    resolution_minutes: int | None
    is_active: bool | None
    status: str
    breach_count: int
    description: str | None
    tenant_id: str | None
    tenant_name: str | None


class SlaOverviewResponse(BaseModel):
    total_tickets: int
    breached_tickets: int
    warning_tickets: int
    problematic_assets: int
    warranty_expiring: int


class SlaBreachResponse(BaseModel):
    ticket_id: str
    ticket_number: str | None
    title: str
    priority: str
    status: str
    sla_status: str | None
    response_due_at: datetime | None
    resolution_due_at: datetime | None
    tenant_name: str | None


def _ensure_access(current_user: AuthUserResponse) -> None:
    if current_user.role != "saas_root" and current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access required")


def _policy_query(current_user: AuthUserResponse):
    statement = select(SlaPolicy, Tenant.name).join(Tenant, Tenant.id == SlaPolicy.tenant_id, isouter=True)
    if current_user.role != "saas_root":
        statement = statement.where(SlaPolicy.tenant_id == current_user.tenant_id)
    return statement.order_by(SlaPolicy.priority.asc(), SlaPolicy.target_resolution_minutes.asc())


@router.get("", response_model=list[SlaPolicyResponse])
@router.get("/policies", response_model=list[SlaPolicyResponse])
def list_sla_policies(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SlaPolicyResponse]:
    _ensure_access(current_user)
    rows = db.execute(_policy_query(current_user)).all()
    return [
        SlaPolicyResponse(
            id=policy.id,
            name=policy.name,
            priority=policy.priority,
            target_response_minutes=policy.target_response_minutes,
            target_resolution_minutes=policy.target_resolution_minutes,
            response_minutes=policy.response_minutes,
            resolution_minutes=policy.resolution_minutes,
            is_active=policy.is_active,
            status=policy.status,
            breach_count=policy.breach_count,
            description=policy.description,
            tenant_id=policy.tenant_id,
            tenant_name=tenant_name,
        )
        for policy, tenant_name in rows
    ]


@router.get("/overview", response_model=SlaOverviewResponse)
def get_sla_overview(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> SlaOverviewResponse:
    _ensure_access(current_user)
    overview = summarize_sla_overview(db)
    return SlaOverviewResponse(**overview)


@router.get("/breaches", response_model=list[SlaBreachResponse])
def list_sla_breaches(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SlaBreachResponse]:
    _ensure_access(current_user)
    statement = select(Ticket, Tenant.name).join(Tenant, Tenant.id == Ticket.tenant_id, isouter=True)
    if current_user.role != "saas_root":
        statement = statement.where(Ticket.tenant_id == current_user.tenant_id)
    statement = statement.where(Ticket.sla_status == "BREACHED").order_by(Ticket.updated_at.desc(), Ticket.created_at.desc())
    rows = db.execute(statement).all()
    return [
        SlaBreachResponse(
            ticket_id=ticket.id,
            ticket_number=ticket.ticket_number,
            title=ticket.title,
            priority=ticket.priority,
            status=ticket.status,
            sla_status=ticket.sla_status,
            response_due_at=ticket.response_due_at,
            resolution_due_at=ticket.resolution_due_at,
            tenant_name=tenant_name,
        )
        for ticket, tenant_name in rows
    ]
