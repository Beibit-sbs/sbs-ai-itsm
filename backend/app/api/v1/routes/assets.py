from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.ticket import Ticket
from app.models.tenant import Tenant
from app.services.asset_sla import calculate_asset_health

router = APIRouter(prefix="/assets")


class AssetResponse(BaseModel):
    id: str
    asset_tag: str
    name: str
    type: str | None
    asset_type: str
    serial_number: str | None
    inventory_number: str | None
    manufacturer: str | None
    model: str | None
    status: str
    owner_name: str
    assigned_to_name: str | None
    assigned_to_email: str | None
    department: str | None
    location: str
    purchase_date: datetime | None
    warranty_until: datetime | None
    condition: str
    description: str | None
    tenant_id: str | None
    tenant_name: str | None
    health: str


class AssetTicketResponse(BaseModel):
    id: str
    ticket_number: str | None
    title: str
    priority: str
    status: str
    assignee_name: str | None
    sla_status: str | None
    created_at: datetime
    updated_at: datetime


def _ensure_access(current_user: AuthUserResponse) -> None:
    if current_user.role != "saas_root" and current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access required")


def _asset_query(current_user: AuthUserResponse):
    statement = select(Asset, Tenant.name).join(Tenant, Tenant.id == Asset.tenant_id, isouter=True)
    if current_user.role != "saas_root":
        statement = statement.where(Asset.tenant_id == current_user.tenant_id)
    return statement.order_by(Asset.updated_at.desc(), Asset.created_at.desc())


@router.get("", response_model=list[AssetResponse])
def list_assets(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AssetResponse]:
    _ensure_access(current_user)
    rows = db.execute(_asset_query(current_user)).all()
    return [
        AssetResponse(
            id=asset.id,
            asset_tag=asset.asset_tag,
            name=asset.name,
            type=asset.type or asset.asset_type,
            asset_type=asset.asset_type,
            serial_number=asset.serial_number,
            inventory_number=asset.inventory_number,
            manufacturer=asset.manufacturer,
            model=asset.model,
            status=asset.status,
            owner_name=asset.owner_name,
            assigned_to_name=asset.assigned_to_name,
            assigned_to_email=asset.assigned_to_email,
            department=asset.department,
            location=asset.location,
            purchase_date=asset.purchase_date,
            warranty_until=asset.warranty_until,
            condition=asset.condition,
            description=asset.description,
            tenant_id=asset.tenant_id,
            tenant_name=tenant_name,
            health=calculate_asset_health(asset),
        )
        for asset, tenant_name in rows
    ]


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> AssetResponse:
    _ensure_access(current_user)
    row = db.execute(select(Asset, Tenant.name).join(Tenant, Tenant.id == Asset.tenant_id, isouter=True).where(Asset.id == asset_id)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    asset, tenant_name = row
    if current_user.role != "saas_root" and asset.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    return AssetResponse(
        id=asset.id,
        asset_tag=asset.asset_tag,
        name=asset.name,
        type=asset.type or asset.asset_type,
        asset_type=asset.asset_type,
        serial_number=asset.serial_number,
        inventory_number=asset.inventory_number,
        manufacturer=asset.manufacturer,
        model=asset.model,
        status=asset.status,
        owner_name=asset.owner_name,
        assigned_to_name=asset.assigned_to_name,
        assigned_to_email=asset.assigned_to_email,
        department=asset.department,
        location=asset.location,
        purchase_date=asset.purchase_date,
        warranty_until=asset.warranty_until,
        condition=asset.condition,
        description=asset.description,
        tenant_id=asset.tenant_id,
        tenant_name=tenant_name,
        health=calculate_asset_health(asset),
    )


@router.get("/{asset_id}/tickets", response_model=list[AssetTicketResponse])
def get_asset_tickets(asset_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AssetTicketResponse]:
    _ensure_access(current_user)
    asset = db.scalar(select(Asset).where(Asset.id == asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if current_user.role != "saas_root" and asset.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    tickets = db.scalars(
        select(Ticket).where(Ticket.asset_id == asset.id).order_by(Ticket.updated_at.desc(), Ticket.created_at.desc())
    ).all()
    return [
        AssetTicketResponse(
            id=ticket.id,
            ticket_number=ticket.ticket_number,
            title=ticket.title,
            priority=ticket.priority,
            status=ticket.status,
            assignee_name=ticket.assignee_name,
            sla_status=ticket.sla_status,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )
        for ticket in tickets
    ]
