from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.report_snapshot import ReportSnapshot
from app.models.saved_report import SavedReport
from app.models.user import User
from app.services.analytics import report_payload_for_type
from app.services.audit import log_audit
from app.services.rbac import require_permissions

router = APIRouter(prefix="/reports")


class SavedReportResponse(BaseModel):
    id: str
    tenant_id: str | None
    name: str
    report_type: str
    filters_json: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime


class CreateSavedReportRequest(BaseModel):
    name: str
    report_type: str
    filters_json: dict[str, Any] = Field(default_factory=dict)


class ReportSnapshotResponse(BaseModel):
    id: str
    tenant_id: str | None
    report_type: str
    period_from: datetime | None
    period_to: datetime | None
    payload_json: dict[str, Any]
    created_at: datetime
    created_by: str


class CreateSnapshotRequest(BaseModel):
    report_type: str
    period_from: datetime | None = None
    period_to: datetime | None = None


class DemoExportResponse(BaseModel):
    report_type: str
    format: str
    generated_at: datetime
    headers: list[str]
    rows: list[dict[str, Any]]
    payload: dict[str, Any]


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.get(User, current_user.id)


def _tenant_scope(current_user: AuthUserResponse) -> str | None:
    return None if current_user.role == "saas_root" else current_user.tenant_id


def _parse_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _saved_report_response(item: SavedReport) -> SavedReportResponse:
    return SavedReportResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        name=item.name,
        report_type=item.report_type,
        filters_json=_parse_json(item.filters_json),
        created_by=item.created_by,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _snapshot_response(item: ReportSnapshot) -> ReportSnapshotResponse:
    return ReportSnapshotResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        report_type=item.report_type,
        period_from=item.period_from,
        period_to=item.period_to,
        payload_json=_parse_json(item.payload_json),
        created_at=item.created_at,
        created_by=item.created_by,
    )


@router.get("/saved", response_model=list[SavedReportResponse])
def list_saved_reports(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SavedReportResponse]:
    require_permissions(current_user, "reports.read")
    tenant_id = _tenant_scope(current_user)
    statement = select(SavedReport).order_by(SavedReport.updated_at.desc())
    if tenant_id is not None:
        statement = statement.where(SavedReport.tenant_id == tenant_id)
    return [_saved_report_response(item) for item in db.scalars(statement).all()]


@router.post("/saved", response_model=SavedReportResponse, status_code=status.HTTP_201_CREATED)
def create_saved_report(
    request: CreateSavedReportRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedReportResponse:
    require_permissions(current_user, "reports.create")
    now = datetime.now(UTC)
    item = SavedReport(
        id=str(uuid.uuid4()),
        tenant_id=_tenant_scope(current_user),
        name=request.name,
        report_type=request.report_type,
        filters_json=json.dumps(request.filters_json, ensure_ascii=False),
        created_by=current_user.email,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    log_audit(
        db,
        action="saved_report_created",
        entity_type="saved_report",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"report_type": request.report_type, "name": request.name},
    )
    db.commit()
    db.refresh(item)
    return _saved_report_response(item)


@router.get("/snapshots", response_model=list[ReportSnapshotResponse])
def list_snapshots(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ReportSnapshotResponse]:
    require_permissions(current_user, "reports.read")
    tenant_id = _tenant_scope(current_user)
    statement = select(ReportSnapshot).order_by(ReportSnapshot.created_at.desc())
    if tenant_id is not None:
        statement = statement.where(ReportSnapshot.tenant_id == tenant_id)
    return [_snapshot_response(item) for item in db.scalars(statement).all()]


@router.post("/snapshots", response_model=ReportSnapshotResponse, status_code=status.HTTP_201_CREATED)
def create_snapshot(
    request: CreateSnapshotRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportSnapshotResponse:
    require_permissions(current_user, "reports.create")
    tenant_id = _tenant_scope(current_user)
    payload = report_payload_for_type(db, request.report_type, tenant_id)
    item = ReportSnapshot(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        report_type=request.report_type,
        period_from=request.period_from,
        period_to=request.period_to or datetime.now(UTC),
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
        created_at=datetime.now(UTC),
        created_by=current_user.email,
    )
    db.add(item)
    log_audit(
        db,
        action="report_snapshot_created",
        entity_type="report_snapshot",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"report_type": request.report_type},
    )
    db.commit()
    db.refresh(item)
    return _snapshot_response(item)


@router.get("/export-demo", response_model=DemoExportResponse)
def export_demo_report(
    report_type: str = Query(default="overview"),
    format: str = Query(default="json"),
    http_request: Request = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DemoExportResponse:
    require_permissions(current_user, "reports.export")
    tenant_id = _tenant_scope(current_user)
    payload = report_payload_for_type(db, report_type, tenant_id)
    rows = [{"metric": key, "value": value} for key, value in payload.items()]
    log_audit(
        db,
        action="demo_export_requested",
        entity_type="report_export",
        entity_id=report_type,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"report_type": report_type, "format": format},
    )
    db.commit()
    return DemoExportResponse(
        report_type=report_type,
        format=format,
        generated_at=datetime.now(UTC),
        headers=["metric", "value"],
        rows=rows,
        payload=payload,
    )
