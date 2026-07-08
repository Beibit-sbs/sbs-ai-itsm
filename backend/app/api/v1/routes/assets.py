from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.asset_import_batch import AssetImportBatch
from app.models.asset_import_row import AssetImportRow
from app.models.ticket import Ticket
from app.models.tenant import Tenant
from app.models.user import User
from app.services.asset_import import AssetImportService, FILE_SIZE_LIMIT_BYTES
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
    purchase_date: datetime | None
    accepted_at: datetime | None
    purchase_cost: float | None
    current_cost: float | None
    depreciation_amount: float | None
    residual_value: float | None
    purchase_year: int | None
    verification_status: str | None
    imported_at: datetime | None
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


class AssetListPageResponse(BaseModel):
    items: list[AssetResponse]
    total: int
    page: int
    page_size: int


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


def _ensure_access(current_user: AuthUserResponse) -> None:
    if current_user.role != "saas_root" and current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access required")


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


@router.get("", response_model=AssetListPageResponse)
def list_assets(
    q: str | None = Query(default=None, min_length=1),
    source: str | None = Query(default=None),
    verification_status: str | None = Query(default=None),
    without_location: bool = Query(default=False),
    disposed: bool = Query(default=False),
    assigned_to_name: str | None = Query(default=None),
    purchase_year: int | None = Query(default=None),
    type: str | None = Query(default=None),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssetListPageResponse:
    _ensure_access(current_user)
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
            )
        )
    if source:
        statement = statement.where(Asset.source == source)
    if verification_status:
        statement = statement.where(Asset.verification_status == verification_status)
    if without_location:
        statement = statement.where((Asset.location.is_(None)) | (Asset.location == "") | (Asset.verification_status == "needs_location"))
    if disposed:
        statement = statement.where(Asset.status == "disposed")
    if assigned_to_name:
        statement = statement.where(Asset.assigned_to_name == assigned_to_name)
    if purchase_year is not None:
        statement = statement.where(Asset.purchase_year == purchase_year)
    if type:
        statement = statement.where((Asset.type == type) | (Asset.asset_type == type))

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    sort_map = {
        "asset_tag": Asset.asset_tag,
        "name": Asset.name,
        "status": Asset.status,
        "type": Asset.asset_type,
        "source": Asset.source,
        "purchase_year": Asset.purchase_year,
        "updated_at": Asset.updated_at,
        "created_at": Asset.created_at,
    }
    order_column = sort_map.get(sort_by, Asset.updated_at)
    direction = asc if sort_dir.lower() == "asc" else desc
    rows = db.execute(
        statement.order_by(direction(order_column), Asset.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    items = [
        AssetResponse(
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
            location=asset.location,
            purchase_date=asset.purchase_date,
            accepted_at=asset.accepted_at,
            purchase_cost=asset.purchase_cost,
            current_cost=asset.current_cost,
            depreciation_amount=asset.depreciation_amount,
            residual_value=asset.residual_value,
            purchase_year=asset.purchase_year,
            verification_status=asset.verification_status,
            imported_at=asset.imported_at,
            warranty_until=asset.warranty_until,
            condition=asset.condition,
            description=asset.description,
            tenant_id=asset.tenant_id,
            tenant_name=tenant_name,
            health=calculate_asset_health(asset),
        )
        for asset, tenant_name in rows
    ]
    return AssetListPageResponse(items=items, total=total, page=page, page_size=page_size)


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
        location=asset.location,
        purchase_date=asset.purchase_date,
        accepted_at=asset.accepted_at,
        purchase_cost=asset.purchase_cost,
        current_cost=asset.current_cost,
        depreciation_amount=asset.depreciation_amount,
        residual_value=asset.residual_value,
        purchase_year=asset.purchase_year,
        verification_status=asset.verification_status,
        imported_at=asset.imported_at,
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

    actor = _current_actor(db, current_user)
    log_audit(
        db,
        action="asset_import_preview_generated",
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
            if row.status in {"duplicate", "error"}:
                log_audit(
                    db,
                    action="asset_import_row_skipped",
                    entity_type="asset_import_row",
                    entity_id=row.id,
                    actor_user=actor,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    metadata={"reason": row.error_message, "row_number": row.row_number},
                )
            elif row.status == "updated":
                log_audit(
                    db,
                    action="asset_updated_from_import",
                    entity_type="asset",
                    entity_id=row.asset_id,
                    actor_user=actor,
                    metadata={"batch_id": batch.id, "row_number": row.row_number},
                )
            elif row.status == "imported":
                log_audit(
                    db,
                    action="asset_created_from_import",
                    entity_type="asset",
                    entity_id=row.asset_id,
                    actor_user=actor,
                    metadata={"batch_id": batch.id, "row_number": row.row_number},
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
