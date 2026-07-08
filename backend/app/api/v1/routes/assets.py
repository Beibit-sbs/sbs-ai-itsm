from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.asset_history import AssetHistory
from app.models.asset_import_batch import AssetImportBatch
from app.models.asset_import_row import AssetImportRow
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.user import User
from app.services.asset_import import FILE_SIZE_LIMIT_BYTES, AssetImportService
from app.services.asset_sla import calculate_asset_health
from app.services.audit import log_audit
from app.services.rbac import ensure_same_tenant_or_root, require_permissions

router = APIRouter(prefix="/assets")
import_service = AssetImportService()


class AssetResponse(BaseModel):
    id: str
    asset_tag: str
    name: str
    type: str | None
    asset_type: str
    original_type: str | None
    serial_number: str | None
    inventory_number: str | None
    source: str | None
    source_batch_id: str | None
    manufacturer: str | None
    model: str | None
    status: str
    owner_name: str
    assigned_to_name: str | None
    assigned_to_email: str | None
    department: str | None
    location: str
    building: str | None
    floor: str | None
    room: str | None
    location_label: str | None
    location_verified_at: datetime | None
    responsible_person_name: str | None
    responsible_person_position: str | None
    responsible_department: str | None
    mol_name: str | None
    mol_department: str | None
    purchase_date: datetime | None
    accepted_at: datetime | None
    purchase_cost: float | None
    current_cost: float | None
    initial_cost: float | None
    depreciation_amount: float | None
    residual_cost: float | None
    residual_value: float | None
    purchase_year: int | None
    writeoff_date: datetime | None
    writeoff_reason: str | None
    verification_status: str | None
    imported_at: datetime | None
    assigned_at: datetime | None
    moved_at: datetime | None
    disposed_at: datetime | None
    last_inventory_at: datetime | None
    last_verified_at: datetime | None
    warranty_until: datetime | None
    condition: str
    description: str | None
    notes: str | None
    tenant_id: str | None
    tenant_name: str | None
    health: str
    created_at: datetime
    updated_at: datetime


class LinkedTicketSummary(BaseModel):
    id: str
    ticket_number: str | None
    title: str
    status: str
    priority: str
    updated_at: datetime


class AssetHistoryResponse(BaseModel):
    id: str
    asset_id: str
    actor_id: str | None
    action: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    comment: str | None
    created_at: datetime


class AssetHistoryFeedItem(AssetHistoryResponse):
    asset_name: str | None = None
    inventory_number: str | None = None
    actor_email: str | None = None


class AssetDetailResponse(AssetResponse):
    linked_tickets_summary: list[LinkedTicketSummary]
    latest_history: list[AssetHistoryResponse]


class AssetListPageResponse(BaseModel):
    items: list[AssetResponse]
    total: int
    page: int
    page_size: int


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


class AssetPatchRequest(BaseModel):
    name: str | None = None
    asset_type: str | None = None
    status: str | None = None
    source: str | None = None
    verification_status: str | None = None
    building: str | None = None
    floor: str | None = None
    room: str | None = None
    location_label: str | None = None
    responsible_person_name: str | None = None
    responsible_person_position: str | None = None
    responsible_department: str | None = None
    mol_name: str | None = None
    mol_department: str | None = None
    purchase_date: datetime | None = None
    purchase_year: int | None = None
    initial_cost: float | None = None
    depreciation_amount: float | None = None
    residual_cost: float | None = None
    writeoff_date: datetime | None = None
    writeoff_reason: str | None = None
    serial_number: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    notes: str | None = None
    description: str | None = None


class AssetAssignRequest(BaseModel):
    responsible_person_name: str
    responsible_department: str | None = None
    mol_name: str | None = None
    mol_department: str | None = None
    comment: str | None = None


class AssetMoveRequest(BaseModel):
    building: str | None = None
    floor: str | None = None
    room: str | None = None
    location_label: str | None = None
    comment: str | None = None


class AssetVerifyRequest(BaseModel):
    verification_status: str = Field(default="verified")
    comment: str | None = None


class AssetDisposeRequest(BaseModel):
    writeoff_reason: str
    comment: str | None = None


class AssetRestoreRequest(BaseModel):
    comment: str | None = None


class ImportPreviewRequest(BaseModel):
    batch_id: str
    dry_run: bool = True


class ImportCommitRequest(BaseModel):
    dry_run: bool = False


class AssetImportBatchResponse(BaseModel):
    id: str
    tenant_id: str | None
    file_name: str
    original_file_name: str
    status: str
    total_rows: int
    valid_rows: int
    imported_rows: int
    skipped_rows: int
    error_rows: int
    created_by: str | None
    created_at: datetime
    completed_at: datetime | None
    summary: dict[str, Any]


class AssetImportRowResponse(BaseModel):
    id: str
    row_number: int
    raw: dict[str, Any]
    normalized: dict[str, Any]
    status: str
    error_message: str | None
    asset_id: str | None
    created_at: datetime


class ImportSummaryResponse(BaseModel):
    total_batches: int
    preview_ready_batches: int
    committed_batches: int
    total_rows: int
    total_imported_rows: int
    total_error_rows: int


def _history_feed_response(item: AssetHistory, asset: Asset | None, actor: User | None) -> AssetHistoryFeedItem:
    return AssetHistoryFeedItem(
        id=item.id,
        asset_id=item.asset_id,
        actor_id=item.actor_id,
        action=item.action,
        old_value=item.old_value,
        new_value=item.new_value,
        comment=item.comment,
        created_at=item.created_at,
        asset_name=asset.name if asset else None,
        inventory_number=asset.inventory_number if asset else None,
        actor_email=actor.email if actor else None,
    )


def _ensure_access(current_user: AuthUserResponse) -> None:
    if current_user.role != "saas_root" and current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access required")


def _require_asset_read(current_user: AuthUserResponse) -> None:
    if current_user.role == "requester":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester cannot access assets registry")
    require_permissions(current_user, "assets.read")


def _can_manage_assets(current_user: AuthUserResponse) -> bool:
    return current_user.role in {"saas_root", "organization_admin", "it_manager"}


def _allow_agent_limited_update(current_user: AuthUserResponse) -> bool:
    return current_user.role == "it_agent"


def _asset_query(current_user: AuthUserResponse):
    statement = select(Asset, Tenant.name).join(Tenant, Tenant.id == Asset.tenant_id, isouter=True)
    if current_user.role != "saas_root":
        statement = statement.where(Asset.tenant_id == current_user.tenant_id)
    return statement


def _parse_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _to_batch_response(batch: AssetImportBatch) -> AssetImportBatchResponse:
    return AssetImportBatchResponse(
        id=batch.id,
        tenant_id=batch.tenant_id,
        file_name=batch.file_name,
        original_file_name=batch.original_file_name,
        status=batch.status,
        total_rows=batch.total_rows,
        valid_rows=batch.valid_rows,
        imported_rows=batch.imported_rows,
        skipped_rows=batch.skipped_rows,
        error_rows=batch.error_rows,
        created_by=batch.created_by,
        created_at=batch.created_at,
        completed_at=batch.completed_at,
        summary=_parse_json(batch.summary_json),
    )


def _to_row_response(row: AssetImportRow) -> AssetImportRowResponse:
    return AssetImportRowResponse(
        id=row.id,
        row_number=row.row_number,
        raw=_parse_json(row.raw_json),
        normalized=_parse_json(row.normalized_json),
        status=row.status,
        error_message=row.error_message,
        asset_id=row.asset_id,
        created_at=row.created_at,
    )


def _current_actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.get(User, current_user.id)


def _decimal_to_float(value: float | Decimal | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _compose_location(asset: Asset) -> str:
    if asset.location and asset.location.strip():
        return asset.location
    parts = [item for item in [asset.building, asset.floor, asset.room] if item]
    if parts:
        return " / ".join(parts)
    if asset.location_label:
        return asset.location_label
    return "Location unknown"


def _asset_response(asset: Asset, tenant_name: str | None) -> AssetResponse:
    return AssetResponse(
        id=asset.id,
        asset_tag=asset.asset_tag,
        name=asset.name,
        type=asset.type or asset.asset_type,
        asset_type=asset.asset_type,
        original_type=asset.original_type,
        serial_number=asset.serial_number,
        inventory_number=asset.inventory_number,
        source=asset.source,
        source_batch_id=asset.source_batch_id,
        manufacturer=asset.manufacturer,
        model=asset.model,
        status=asset.status,
        owner_name=asset.owner_name,
        assigned_to_name=asset.assigned_to_name,
        assigned_to_email=asset.assigned_to_email,
        department=asset.department,
        location=_compose_location(asset),
        building=asset.building,
        floor=asset.floor,
        room=asset.room,
        location_label=asset.location_label,
        location_verified_at=asset.location_verified_at,
        responsible_person_name=asset.responsible_person_name,
        responsible_person_position=asset.responsible_person_position,
        responsible_department=asset.responsible_department,
        mol_name=asset.mol_name,
        mol_department=asset.mol_department,
        purchase_date=asset.purchase_date,
        accepted_at=asset.accepted_at,
        purchase_cost=_decimal_to_float(asset.purchase_cost),
        current_cost=_decimal_to_float(asset.current_cost),
        initial_cost=_decimal_to_float(asset.initial_cost),
        depreciation_amount=_decimal_to_float(asset.depreciation_amount),
        residual_cost=_decimal_to_float(asset.residual_cost),
        residual_value=_decimal_to_float(asset.residual_value),
        purchase_year=asset.purchase_year,
        writeoff_date=asset.writeoff_date,
        writeoff_reason=asset.writeoff_reason,
        verification_status=asset.verification_status,
        imported_at=asset.imported_at,
        assigned_at=asset.assigned_at,
        moved_at=asset.moved_at,
        disposed_at=asset.disposed_at,
        last_inventory_at=asset.last_inventory_at,
        last_verified_at=asset.last_verified_at,
        warranty_until=asset.warranty_until,
        condition=asset.condition,
        description=asset.description,
        notes=asset.notes,
        tenant_id=asset.tenant_id,
        tenant_name=tenant_name,
        health=calculate_asset_health(asset),
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def _ticket_summary(ticket: Ticket) -> LinkedTicketSummary:
    return LinkedTicketSummary(
        id=ticket.id,
        ticket_number=ticket.ticket_number,
        title=ticket.title,
        status=ticket.status,
        priority=ticket.priority,
        updated_at=ticket.updated_at,
    )


def _history_response(item: AssetHistory) -> AssetHistoryResponse:
    return AssetHistoryResponse(
        id=item.id,
        asset_id=item.asset_id,
        actor_id=item.actor_id,
        action=item.action,
        old_value=item.old_value,
        new_value=item.new_value,
        comment=item.comment,
        created_at=item.created_at,
    )


def _write_history(
    db: Session,
    *,
    asset_id: str,
    actor_id: str | None,
    action: str,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
    comment: str | None,
) -> None:
    db.add(
        AssetHistory(
            id=str(uuid.uuid4()),
            asset_id=asset_id,
            actor_id=actor_id,
            action=action,
            old_value=_json_safe(old_value),
            new_value=_json_safe(new_value),
            comment=comment,
            created_at=datetime.now(UTC),
        )
    )


def _asset_or_404(db: Session, current_user: AuthUserResponse, asset_id: str) -> Asset:
    asset = db.scalar(select(Asset).where(Asset.id == asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if current_user.role != "saas_root" and asset.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@router.get("", response_model=AssetListPageResponse)
def list_assets(
    q: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    source: str | None = Query(default=None),
    verification_status: str | None = Query(default=None),
    room: str | None = Query(default=None),
    building: str | None = Query(default=None),
    responsible_person_name: str | None = Query(default=None),
    mol_name: str | None = Query(default=None),
    purchase_year: int | None = Query(default=None),
    missing_location: bool = Query(default=False),
    disposed: bool = Query(default=False),
    needs_verification: bool = Query(default=False),
    without_location: bool = Query(default=False),
    assigned_to_name: str | None = Query(default=None),
    type: str | None = Query(default=None),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssetListPageResponse:
    _ensure_access(current_user)
    _require_asset_read(current_user)

    statement = _asset_query(current_user)

    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Asset.asset_tag.ilike(pattern),
                Asset.name.ilike(pattern),
                Asset.serial_number.ilike(pattern),
                Asset.inventory_number.ilike(pattern),
                Asset.manufacturer.ilike(pattern),
                Asset.model.ilike(pattern),
                Asset.assigned_to_name.ilike(pattern),
                Asset.department.ilike(pattern),
                Asset.location.ilike(pattern),
                Asset.room.ilike(pattern),
                Asset.responsible_person_name.ilike(pattern),
                Asset.mol_name.ilike(pattern),
            )
        )

    effective_type = asset_type or type
    if effective_type and effective_type != "ALL":
        statement = statement.where(or_(Asset.asset_type == effective_type, Asset.type == effective_type))
    if status_filter and status_filter != "ALL":
        statement = statement.where(Asset.status == status_filter)
    if source and source != "ALL":
        statement = statement.where(Asset.source == source)
    if verification_status and verification_status != "ALL":
        statement = statement.where(Asset.verification_status == verification_status)
    if room:
        statement = statement.where(Asset.room == room)
    if building:
        statement = statement.where(Asset.building == building)
    if responsible_person_name:
        statement = statement.where(Asset.responsible_person_name == responsible_person_name)
    if mol_name:
        statement = statement.where(Asset.mol_name == mol_name)
    if purchase_year is not None:
        statement = statement.where(Asset.purchase_year == purchase_year)
    if missing_location or without_location:
        statement = statement.where(
            or_(
                Asset.room.is_(None),
                func.length(func.trim(func.coalesce(Asset.room, ""))) == 0,
                Asset.location.is_(None),
                func.length(func.trim(func.coalesce(Asset.location, ""))) == 0,
                Asset.location == "Location unknown",
                Asset.verification_status == "needs_location",
            )
        )
    if disposed:
        statement = statement.where(Asset.status == "disposed")
    if needs_verification:
        statement = statement.where(Asset.verification_status.in_(["needs_location", "pending", "unknown"]))
    if assigned_to_name and assigned_to_name != "ALL":
        statement = statement.where(Asset.assigned_to_name == assigned_to_name)

    sort_map = {
        "name": Asset.name,
        "inventory_number": Asset.inventory_number,
        "asset_type": Asset.asset_type,
        "room": Asset.room,
        "responsible_person_name": Asset.responsible_person_name,
        "purchase_year": Asset.purchase_year,
        "residual_cost": Asset.residual_cost,
        "created_at": Asset.created_at,
        "updated_at": Asset.updated_at,
        "asset_tag": Asset.asset_tag,
        "status": Asset.status,
        "source": Asset.source,
        "type": Asset.asset_type,
    }
    order_column = sort_map.get(sort_by, Asset.updated_at)
    direction = asc if sort_dir.lower() == "asc" else desc

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.execute(
        statement.order_by(direction(order_column), Asset.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    return AssetListPageResponse(
        items=[_asset_response(asset, tenant_name) for asset, tenant_name in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/history", response_model=list[AssetHistoryFeedItem])
def list_assets_history(
    action: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    asset_q: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AssetHistoryFeedItem]:
    _ensure_access(current_user)
    _require_asset_read(current_user)
    require_permissions(current_user, "assets.history.read")

    statement = (
        select(AssetHistory, Asset, User)
        .join(Asset, Asset.id == AssetHistory.asset_id)
        .join(User, User.id == AssetHistory.actor_id, isouter=True)
    )
    if current_user.role != "saas_root":
        statement = statement.where(Asset.tenant_id == current_user.tenant_id)
    if action:
        statement = statement.where(AssetHistory.action == action)
    if actor:
        statement = statement.where(
            or_(
                User.email.ilike(f"%{actor}%"),
                User.full_name.ilike(f"%{actor}%"),
            )
        )
    if asset_q:
        pattern = f"%{asset_q}%"
        statement = statement.where(or_(Asset.name.ilike(pattern), Asset.inventory_number.ilike(pattern), Asset.asset_tag.ilike(pattern)))
    if date_from:
        statement = statement.where(AssetHistory.created_at >= date_from)
    if date_to:
        statement = statement.where(AssetHistory.created_at <= date_to)

    rows = db.execute(statement.order_by(AssetHistory.created_at.desc()).limit(limit)).all()
    return [_history_feed_response(item, asset, actor_user) for item, asset, actor_user in rows]


@router.get("/{asset_id}", response_model=AssetDetailResponse)
def get_asset(asset_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> AssetDetailResponse:
    _ensure_access(current_user)
    _require_asset_read(current_user)

    row = db.execute(select(Asset, Tenant.name).join(Tenant, Tenant.id == Asset.tenant_id, isouter=True).where(Asset.id == asset_id)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    asset, tenant_name = row
    if current_user.role != "saas_root" and asset.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    linked_tickets = db.scalars(
        select(Ticket).where(Ticket.asset_id == asset.id).order_by(Ticket.updated_at.desc()).limit(20)
    ).all()
    latest_history = db.scalars(
        select(AssetHistory).where(AssetHistory.asset_id == asset.id).order_by(AssetHistory.created_at.desc()).limit(30)
    ).all()

    payload = _asset_response(asset, tenant_name)
    return AssetDetailResponse(
        **payload.model_dump(),
        linked_tickets_summary=[_ticket_summary(ticket) for ticket in linked_tickets],
        latest_history=[_history_response(item) for item in latest_history],
    )


@router.patch("/{asset_id}", response_model=AssetDetailResponse)
def patch_asset(
    asset_id: str,
    request: AssetPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssetDetailResponse:
    _ensure_access(current_user)
    _require_asset_read(current_user)
    asset = _asset_or_404(db, current_user, asset_id)

    updates = request.model_dump(exclude_unset=True)
    if not updates:
        return get_asset(asset.id, current_user, db)

    if _can_manage_assets(current_user):
        require_permissions(current_user, "assets.update")
    elif _allow_agent_limited_update(current_user):
        allowed = {"building", "floor", "room", "location_label", "verification_status", "notes", "description"}
        if any(field not in allowed for field in updates):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent can only update location/notes/verification")
        if "verification_status" in updates:
            require_permissions(current_user, "assets.verify")
        else:
            require_permissions(current_user, "assets.update")
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Asset update is not allowed")

    before = {field: getattr(asset, field) for field in updates.keys()}
    for field, value in updates.items():
        setattr(asset, field, value)

    if any(field in updates for field in {"building", "floor", "room", "location_label"}):
        asset.location = " / ".join([item for item in [asset.building, asset.floor, asset.room] if item]) or (asset.location_label or asset.location)
        asset.location_verified_at = datetime.now(UTC)

    if "verification_status" in updates:
        asset.last_verified_at = datetime.now(UTC)

    asset.updated_at = datetime.now(UTC)

    actor = _current_actor(db, current_user)
    _write_history(
        db,
        asset_id=asset.id,
        actor_id=current_user.id,
        action="asset_updated",
        old_value=before,
        new_value={field: getattr(asset, field) for field in updates.keys()},
        comment="Asset card updated",
    )
    log_audit(
        db,
        action="asset_updated",
        entity_type="asset",
        entity_id=asset.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"updated_fields": sorted(updates.keys())},
    )

    db.commit()
    return get_asset(asset.id, current_user, db)


@router.post("/{asset_id}/assign", response_model=AssetDetailResponse)
def assign_asset(
    asset_id: str,
    request: AssetAssignRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssetDetailResponse:
    _ensure_access(current_user)
    _require_asset_read(current_user)
    require_permissions(current_user, "assets.assign")
    if not _can_manage_assets(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only manager/admin/root can assign assets")

    asset = _asset_or_404(db, current_user, asset_id)
    before = {
        "responsible_person_name": asset.responsible_person_name,
        "responsible_department": asset.responsible_department,
        "mol_name": asset.mol_name,
        "mol_department": asset.mol_department,
    }

    asset.responsible_person_name = request.responsible_person_name
    asset.responsible_department = request.responsible_department
    asset.mol_name = request.mol_name
    asset.mol_department = request.mol_department
    asset.assigned_to_name = request.responsible_person_name
    asset.department = request.responsible_department
    asset.assigned_at = datetime.now(UTC)
    asset.updated_at = datetime.now(UTC)

    actor = _current_actor(db, current_user)
    _write_history(
        db,
        asset_id=asset.id,
        actor_id=current_user.id,
        action="asset_assigned",
        old_value=before,
        new_value={
            "responsible_person_name": asset.responsible_person_name,
            "responsible_department": asset.responsible_department,
            "mol_name": asset.mol_name,
            "mol_department": asset.mol_department,
        },
        comment=request.comment,
    )
    log_audit(
        db,
        action="asset_assigned",
        entity_type="asset",
        entity_id=asset.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"responsible_person_name": request.responsible_person_name, "mol_name": request.mol_name},
    )
    db.commit()
    return get_asset(asset.id, current_user, db)


@router.post("/{asset_id}/move", response_model=AssetDetailResponse)
def move_asset(
    asset_id: str,
    request: AssetMoveRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssetDetailResponse:
    _ensure_access(current_user)
    _require_asset_read(current_user)
    require_permissions(current_user, "assets.move")
    if not _can_manage_assets(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only manager/admin/root can move assets")

    asset = _asset_or_404(db, current_user, asset_id)
    before = {
        "building": asset.building,
        "floor": asset.floor,
        "room": asset.room,
        "location_label": asset.location_label,
        "location": asset.location,
    }

    asset.building = request.building
    asset.floor = request.floor
    asset.room = request.room
    asset.location_label = request.location_label
    asset.location = " / ".join([item for item in [asset.building, asset.floor, asset.room] if item]) or (asset.location_label or "Location unknown")
    asset.location_verified_at = datetime.now(UTC)
    asset.moved_at = datetime.now(UTC)
    asset.updated_at = datetime.now(UTC)

    actor = _current_actor(db, current_user)
    _write_history(
        db,
        asset_id=asset.id,
        actor_id=current_user.id,
        action="asset_moved",
        old_value=before,
        new_value={
            "building": asset.building,
            "floor": asset.floor,
            "room": asset.room,
            "location_label": asset.location_label,
            "location": asset.location,
        },
        comment=request.comment,
    )
    log_audit(
        db,
        action="asset_moved",
        entity_type="asset",
        entity_id=asset.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"room": asset.room, "building": asset.building},
    )
    db.commit()
    return get_asset(asset.id, current_user, db)


@router.post("/{asset_id}/verify", response_model=AssetDetailResponse)
def verify_asset(
    asset_id: str,
    request: AssetVerifyRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssetDetailResponse:
    _ensure_access(current_user)
    _require_asset_read(current_user)
    require_permissions(current_user, "assets.verify")

    asset = _asset_or_404(db, current_user, asset_id)
    before = {"verification_status": asset.verification_status}

    asset.verification_status = request.verification_status
    asset.last_verified_at = datetime.now(UTC)
    asset.last_inventory_at = datetime.now(UTC)
    asset.updated_at = datetime.now(UTC)

    actor = _current_actor(db, current_user)
    _write_history(
        db,
        asset_id=asset.id,
        actor_id=current_user.id,
        action="asset_verified",
        old_value=before,
        new_value={"verification_status": asset.verification_status},
        comment=request.comment,
    )
    log_audit(
        db,
        action="asset_verified",
        entity_type="asset",
        entity_id=asset.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"verification_status": asset.verification_status},
    )
    db.commit()
    return get_asset(asset.id, current_user, db)


@router.post("/{asset_id}/dispose", response_model=AssetDetailResponse)
def dispose_asset(
    asset_id: str,
    request: AssetDisposeRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssetDetailResponse:
    _ensure_access(current_user)
    _require_asset_read(current_user)
    require_permissions(current_user, "assets.dispose")
    if not _can_manage_assets(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only manager/admin/root can dispose assets")

    asset = _asset_or_404(db, current_user, asset_id)
    before = {
        "status": asset.status,
        "disposed_at": asset.disposed_at,
        "writeoff_date": asset.writeoff_date,
        "writeoff_reason": asset.writeoff_reason,
    }

    now = datetime.now(UTC)
    asset.status = "disposed"
    asset.disposed_at = now
    asset.writeoff_date = now
    asset.writeoff_reason = request.writeoff_reason
    asset.updated_at = now

    actor = _current_actor(db, current_user)
    _write_history(
        db,
        asset_id=asset.id,
        actor_id=current_user.id,
        action="asset_disposed",
        old_value=before,
        new_value={
            "status": asset.status,
            "disposed_at": asset.disposed_at.isoformat(),
            "writeoff_date": asset.writeoff_date.isoformat(),
            "writeoff_reason": asset.writeoff_reason,
        },
        comment=request.comment,
    )
    log_audit(
        db,
        action="asset_disposed",
        entity_type="asset",
        entity_id=asset.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"writeoff_reason": request.writeoff_reason},
    )
    db.commit()
    return get_asset(asset.id, current_user, db)


@router.post("/{asset_id}/restore", response_model=AssetDetailResponse)
def restore_asset(
    asset_id: str,
    request: AssetRestoreRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssetDetailResponse:
    _ensure_access(current_user)
    _require_asset_read(current_user)
    require_permissions(current_user, "assets.restore")
    if not _can_manage_assets(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only manager/admin/root can restore assets")

    asset = _asset_or_404(db, current_user, asset_id)
    before = {"status": asset.status, "disposed_at": asset.disposed_at}

    asset.status = "active"
    asset.disposed_at = None
    asset.updated_at = datetime.now(UTC)

    actor = _current_actor(db, current_user)
    _write_history(
        db,
        asset_id=asset.id,
        actor_id=current_user.id,
        action="asset_restored",
        old_value=before,
        new_value={"status": asset.status, "disposed_at": None},
        comment=request.comment,
    )
    log_audit(
        db,
        action="asset_restored",
        entity_type="asset",
        entity_id=asset.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"restored": True},
    )
    db.commit()
    return get_asset(asset.id, current_user, db)


@router.get("/{asset_id}/history", response_model=list[AssetHistoryResponse])
def get_asset_history(asset_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AssetHistoryResponse]:
    _ensure_access(current_user)
    _require_asset_read(current_user)
    require_permissions(current_user, "assets.history.read")
    asset = _asset_or_404(db, current_user, asset_id)

    rows = db.scalars(select(AssetHistory).where(AssetHistory.asset_id == asset.id).order_by(AssetHistory.created_at.desc())).all()
    return [_history_response(item) for item in rows]


@router.get("/{asset_id}/tickets", response_model=list[AssetTicketResponse])
def get_asset_tickets(asset_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AssetTicketResponse]:
    _ensure_access(current_user)
    _require_asset_read(current_user)
    asset = _asset_or_404(db, current_user, asset_id)

    tickets = db.scalars(select(Ticket).where(Ticket.asset_id == asset.id).order_by(Ticket.updated_at.desc(), Ticket.created_at.desc())).all()
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


@router.post("/import/upload", response_model=AssetImportBatchResponse, status_code=status.HTTP_201_CREATED)
def upload_asset_import(
    request: Request,
    file: UploadFile = File(...),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssetImportBatchResponse:
    _ensure_access(current_user)
    require_permissions(current_user, "assets.import")

    filename = file.filename or "assets.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .xlsx files are supported")

    payload = file.file.read(FILE_SIZE_LIMIT_BYTES + 1)
    if len(payload) > FILE_SIZE_LIMIT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large")

    batch = AssetImportBatch(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        file_name=f"asset-import-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}.xlsx",
        original_file_name=filename,
        status="uploaded",
        total_rows=0,
        valid_rows=0,
        imported_rows=0,
        skipped_rows=0,
        error_rows=0,
        created_by=current_user.email,
        summary_json=json.dumps({"uploaded_file_b64": base64.b64encode(payload).decode("utf-8")}, ensure_ascii=False),
    )
    db.add(batch)

    actor = _current_actor(db, current_user)
    log_audit(
        db,
        action="asset_import_uploaded",
        entity_type="asset_import_batch",
        entity_id=batch.id,
        actor_user=actor,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"file_name": filename, "size_bytes": len(payload)},
    )
    db.commit()
    db.refresh(batch)
    return _to_batch_response(batch)


@router.post("/import/preview")
def preview_asset_import(
    payload: ImportPreviewRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_access(current_user)
    require_permissions(current_user, "assets.import.preview")

    batch = db.get(AssetImportBatch, payload.batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found")
    ensure_same_tenant_or_root(current_user, batch.tenant_id)

    try:
        summary = import_service.preview_import(db, batch=batch, dry_run=payload.dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or corrupted .xlsx file") from exc

    actor = _current_actor(db, current_user)
    log_audit(
        db,
        action="asset_import_previewed",
        entity_type="asset_import_batch",
        entity_id=batch.id,
        actor_user=actor,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=summary,
    )
    db.commit()
    return summary


@router.post("/import/{batch_id}/commit")
def commit_asset_import(
    batch_id: str,
    payload: ImportCommitRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_access(current_user)
    require_permissions(current_user, "assets.import.commit")

    batch = db.get(AssetImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found")
    ensure_same_tenant_or_root(current_user, batch.tenant_id)

    if batch.status not in {"preview_ready", "committed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Preview must be generated before commit")

    summary = import_service.commit_import(db, batch=batch, dry_run=payload.dry_run)
    actor = _current_actor(db, current_user)

    if not payload.dry_run:
        rows = db.scalars(select(AssetImportRow).where(AssetImportRow.batch_id == batch.id)).all()
        for row in rows:
            if row.status in {"updated", "imported"} and row.asset_id:
                _write_history(
                    db,
                    asset_id=row.asset_id,
                    actor_id=current_user.id,
                    action="asset_imported",
                    old_value=None,
                    new_value={"batch_id": batch.id, "row_number": row.row_number, "row_status": row.status},
                    comment="Asset imported from Excel",
                )

        log_audit(
            db,
            action="asset_import_committed",
            entity_type="asset_import_batch",
            entity_id=batch.id,
            actor_user=actor,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            metadata=summary,
        )
        db.commit()

    return summary


@router.get("/import/batches", response_model=list[AssetImportBatchResponse])
def list_asset_import_batches(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AssetImportBatchResponse]:
    _ensure_access(current_user)
    require_permissions(current_user, "assets.import.read_batches")

    statement = select(AssetImportBatch)
    if current_user.role != "saas_root":
        statement = statement.where(AssetImportBatch.tenant_id == current_user.tenant_id)
    rows = db.scalars(statement.order_by(AssetImportBatch.created_at.desc())).all()
    return [_to_batch_response(item) for item in rows]


@router.get("/import/batches/{batch_id}", response_model=AssetImportBatchResponse)
def get_asset_import_batch(batch_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> AssetImportBatchResponse:
    _ensure_access(current_user)
    require_permissions(current_user, "assets.import.read_batches")

    batch = db.get(AssetImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found")
    ensure_same_tenant_or_root(current_user, batch.tenant_id)
    return _to_batch_response(batch)


@router.get("/import/batches/{batch_id}/rows", response_model=list[AssetImportRowResponse])
def list_asset_import_batch_rows(
    batch_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AssetImportRowResponse]:
    _ensure_access(current_user)
    require_permissions(current_user, "assets.import.read_batches")

    batch = db.get(AssetImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found")
    ensure_same_tenant_or_root(current_user, batch.tenant_id)

    statement = select(AssetImportRow).where(AssetImportRow.batch_id == batch_id)
    if status_filter:
        statement = statement.where(AssetImportRow.status == status_filter)
    rows = db.scalars(statement.order_by(AssetImportRow.row_number.asc())).all()
    return [_to_row_response(item) for item in rows]


@router.get("/import/template")
def get_asset_import_template(current_user: AuthUserResponse = Depends(get_current_user)) -> dict[str, Any]:
    _ensure_access(current_user)
    require_permissions(current_user, "assets.import.preview")
    return {
        "sheet": "Лист_1",
        "header_row_hint": 7,
        "data_row_hint": 8,
        "columns": {
            "A": "Наименование",
            "B": "Дата принятия к учету",
            "C": "Инвентарный номер",
            "G": "Первоначальная стоимость",
            "I": "Стоимость на конец периода",
            "J": "Амортизация на конец периода",
            "K": "Остаточная стоимость",
            "L": "МОЛ",
            "M/O": "Статус",
            "P": "ТЕХНИКА",
            "R": "КАБИНЕТ",
            "S": "Год",
        },
        "notes": [
            "Upload -> preview -> commit workflow is required",
            "Rows without inventory number are marked as error",
            "Duplicate inventory numbers are not auto-created",
        ],
    }


@router.get("/import/summary", response_model=ImportSummaryResponse)
def get_asset_import_summary(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> ImportSummaryResponse:
    _ensure_access(current_user)
    require_permissions(current_user, "assets.import.read_batches")

    statement = select(AssetImportBatch)
    if current_user.role != "saas_root":
        statement = statement.where(AssetImportBatch.tenant_id == current_user.tenant_id)
    batches = db.scalars(statement).all()

    return ImportSummaryResponse(
        total_batches=len(batches),
        preview_ready_batches=sum(1 for item in batches if item.status == "preview_ready"),
        committed_batches=sum(1 for item in batches if item.status == "committed"),
        total_rows=sum(item.total_rows for item in batches),
        total_imported_rows=sum(item.imported_rows for item in batches),
        total_error_rows=sum(item.error_rows for item in batches),
    )
