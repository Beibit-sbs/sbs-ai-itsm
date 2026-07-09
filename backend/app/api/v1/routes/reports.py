from __future__ import annotations

import csv
import json
import io
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
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
from app.services.automation import trigger_automation_event
from app.services.notifications import create_domain_event_notification
from app.services.rbac import require_permissions

router = APIRouter(prefix="/reports")


class SavedReportResponse(BaseModel):
    id: str
    tenant_id: str | None
    name: str
    report_type: str
    filters_json: dict[str, Any]
    visibility: str
    schedule_enabled: bool
    created_by_id: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class CreateSavedReportRequest(BaseModel):
    name: str
    report_type: str
    filters_json: dict[str, Any] = Field(default_factory=dict)
    visibility: str = "tenant"
    schedule_enabled: bool = False


class ReportSnapshotResponse(BaseModel):
    id: str
    tenant_id: str | None
    saved_report_id: str | None
    report_type: str
    period_from: datetime | None
    period_to: datetime | None
    filters_json: dict[str, Any]
    payload_json: dict[str, Any]
    generated_by_id: str | None
    generated_at: datetime
    created_at: datetime
    created_by: str


class CreateSnapshotRequest(BaseModel):
    report_type: str | None = None
    saved_report_id: str | None = None
    filters_json: dict[str, Any] = Field(default_factory=dict)
    period_from: datetime | None = None
    period_to: datetime | None = None


class ExportReportRequest(BaseModel):
    report_type: str
    format: str = Field(default="json", pattern="^(json|csv)$")
    filters_json: dict[str, Any] = Field(default_factory=dict)


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
        visibility=item.visibility,
        schedule_enabled=item.schedule_enabled,
        created_by_id=item.created_by_id,
        created_by=item.created_by,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _snapshot_response(item: ReportSnapshot) -> ReportSnapshotResponse:
    return ReportSnapshotResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        saved_report_id=item.saved_report_id,
        report_type=item.report_type,
        period_from=item.period_from,
        period_to=item.period_to,
        filters_json=_parse_json(item.filters_json),
        payload_json=_parse_json(item.payload_json),
        generated_by_id=item.generated_by_id,
        generated_at=item.generated_at,
        created_at=item.created_at,
        created_by=item.created_by,
    )


def _saved_report_query(current_user: AuthUserResponse):
    tenant_id = _tenant_scope(current_user)
    statement = select(SavedReport).order_by(SavedReport.updated_at.desc())
    if tenant_id is not None:
        statement = statement.where(SavedReport.tenant_id == tenant_id)
    return statement


def _snapshot_query(current_user: AuthUserResponse):
    tenant_id = _tenant_scope(current_user)
    statement = select(ReportSnapshot).order_by(ReportSnapshot.created_at.desc())
    if tenant_id is not None:
        statement = statement.where(ReportSnapshot.tenant_id == tenant_id)
    return statement


def _get_saved_report_or_404(db: Session, current_user: AuthUserResponse, report_id: str) -> SavedReport:
    statement = _saved_report_query(current_user).where(SavedReport.id == report_id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved report not found")
    return item


def _get_snapshot_or_404(db: Session, current_user: AuthUserResponse, snapshot_id: str) -> ReportSnapshot:
    statement = _snapshot_query(current_user).where(ReportSnapshot.id == snapshot_id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report snapshot not found")
    return item


def _payload_for_saved_report(db: Session, current_user: AuthUserResponse, item: SavedReport) -> dict[str, Any]:
    filters = _parse_json(item.filters_json)
    return report_payload_for_type(db, item.report_type, current_user, filters)


@router.get("", response_model=list[SavedReportResponse])
def list_reports(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SavedReportResponse]:
    require_permissions(current_user, "reports.read")
    statement = _saved_report_query(current_user)
    return [_saved_report_response(item) for item in db.scalars(statement).all()]


@router.post("", response_model=SavedReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(
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
        visibility=request.visibility,
        schedule_enabled=request.schedule_enabled,
        created_by_id=current_user.id,
        created_by=current_user.email,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    log_audit(
        db,
        action="report_created",
        entity_type="report",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "report_type": request.report_type,
            "name": request.name,
            "visibility": request.visibility,
            "schedule_enabled": request.schedule_enabled,
        },
    )
    db.commit()
    db.refresh(item)
    return _saved_report_response(item)


@router.get("/saved", response_model=list[SavedReportResponse])
def list_saved_reports_legacy(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SavedReportResponse]:
    return list_reports(current_user=current_user, db=db)


@router.post("/saved", response_model=SavedReportResponse, status_code=status.HTTP_201_CREATED)
def create_saved_report_legacy(
    request: CreateSavedReportRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedReportResponse:
    return create_report(request=request, http_request=http_request, current_user=current_user, db=db)


@router.get("/snapshots", response_model=list[ReportSnapshotResponse])
def list_snapshots(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ReportSnapshotResponse]:
    require_permissions(current_user, "reports.read")
    statement = _snapshot_query(current_user)
    return [_snapshot_response(item) for item in db.scalars(statement).all()]


@router.get("/snapshots/{snapshot_id}", response_model=ReportSnapshotResponse)
def get_snapshot(snapshot_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> ReportSnapshotResponse:
    require_permissions(current_user, "reports.read")
    item = _get_snapshot_or_404(db, current_user, snapshot_id)
    return _snapshot_response(item)


@router.post("/snapshots", response_model=ReportSnapshotResponse, status_code=status.HTTP_201_CREATED)
def create_snapshot(
    request: CreateSnapshotRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportSnapshotResponse:
    require_permissions(current_user, "reports.create")
    tenant_id = _tenant_scope(current_user)
    report_type = request.report_type or "executive"
    filters_json = request.filters_json
    saved_report_id = request.saved_report_id
    if saved_report_id:
        saved = _get_saved_report_or_404(db, current_user, saved_report_id)
        report_type = saved.report_type
        filters_json = _parse_json(saved.filters_json)

    payload = report_payload_for_type(db, report_type, current_user, filters_json)
    now = datetime.now(UTC)
    item = ReportSnapshot(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        saved_report_id=saved_report_id,
        report_type=report_type,
        period_from=request.period_from,
        period_to=request.period_to or now,
        filters_json=json.dumps(filters_json, ensure_ascii=False),
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
        generated_by_id=current_user.id,
        generated_at=now,
        created_at=now,
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
        metadata={"report_type": report_type, "saved_report_id": saved_report_id},
    )
    db.commit()
    db.refresh(item)
    return _snapshot_response(item)


@router.post("/export")
def export_report(
    request: ExportReportRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    require_permissions(current_user, "reports.export")
    payload = report_payload_for_type(db, request.report_type, current_user, request.filters_json)
    generated_at = datetime.now(UTC)

    if request.format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["metric", "value"])
        for key, value in payload.items():
            writer.writerow([key, json.dumps(value, ensure_ascii=False, default=str)])
        csv_content = buffer.getvalue()
        response = Response(content=csv_content, media_type="text/csv")
        response.headers["Content-Disposition"] = f'attachment; filename="{request.report_type}-report.csv"'
    else:
        response = Response(
            content=json.dumps(
                {
                    "report_type": request.report_type,
                    "format": request.format,
                    "generated_at": generated_at.isoformat(),
                    "payload": payload,
                },
                ensure_ascii=False,
                default=str,
            ),
            media_type="application/json",
        )

    log_audit(
        db,
        action="report_exported",
        entity_type="report_export",
        entity_id=request.report_type,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"report_type": request.report_type, "format": request.format},
    )
    create_domain_event_notification(
        db,
        tenant_id=current_user.tenant_id,
        event_type="report_exported",
        title="Экспорт отчета выполнен",
        message=f"Отчет {request.report_type} экспортирован в формате {request.format}.",
        recipient_name=current_user.full_name,
        recipient_email=current_user.email,
        recipient_user_id=current_user.id,
        severity="info",
        entity_type="report_export",
        entity_id=request.report_type,
        action_url="/analytics",
        metadata={"report_type": request.report_type, "format": request.format},
    )
    trigger_automation_event(
        db,
        tenant_id=current_user.tenant_id,
        trigger_type="report_exported",
        context={"entity_type": "report_export", "entity_id": request.report_type, "report": {"type": request.report_type, "format": request.format}},
        actor_email=current_user.email,
    )
    db.commit()
    return response


@router.get("/export-demo")
def export_demo_report(
    report_type: str = Query(default="executive"),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    http_request: Request = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    return export_report(
        request=ExportReportRequest(report_type=report_type, format=format, filters_json={}),
        http_request=http_request,
        current_user=current_user,
        db=db,
    )


@router.get("/{report_id}", response_model=SavedReportResponse)
def get_report(report_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> SavedReportResponse:
    require_permissions(current_user, "reports.read")
    item = _get_saved_report_or_404(db, current_user, report_id)
    return _saved_report_response(item)


@router.post("/{report_id}/run", response_model=ReportSnapshotResponse, status_code=status.HTTP_201_CREATED)
def run_report(
    report_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportSnapshotResponse:
    require_permissions(current_user, "reports.run")
    saved = _get_saved_report_or_404(db, current_user, report_id)
    payload = _payload_for_saved_report(db, current_user, saved)
    now = datetime.now(UTC)
    snapshot = ReportSnapshot(
        id=str(uuid.uuid4()),
        tenant_id=saved.tenant_id,
        saved_report_id=saved.id,
        report_type=saved.report_type,
        period_from=None,
        period_to=now,
        filters_json=saved.filters_json,
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
        generated_by_id=current_user.id,
        generated_at=now,
        created_at=now,
        created_by=current_user.email,
    )
    db.add(snapshot)
    log_audit(
        db,
        action="report_run",
        entity_type="report",
        entity_id=saved.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"report_type": saved.report_type, "snapshot_id": snapshot.id},
    )
    db.commit()
    db.refresh(snapshot)
    return _snapshot_response(snapshot)
