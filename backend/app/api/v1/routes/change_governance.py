from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.api.v1.routes.changes import (
    ChangeDetailResponse,
    _audit_request,
    _detail_response,
    _get_change,
    _record_history,
    _replace_links,
    _risk_score,
    _validate_linked_records,
)
from app.db.session import get_db
from app.models.change_approval import ChangeApproval
from app.models.change_governance import (
    CABAgendaItem,
    CABMeeting,
    ChangeImplementationTask,
    ChangePostImplementationReview,
    ChangeWindow,
    StandardChangeModel,
)
from app.models.change_request import ChangeRequest
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.change_governance import (
    aware,
    assess_change_window,
    change_metrics,
    create_tasks_from_standard_model,
    now_utc,
    pir_for_change,
    readiness_assessment,
    update_standard_model_outcome,
    validate_user,
)
from app.services.enterprise_sla import validate_timezone
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/change-governance")


class WindowCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)
    window_type: Literal["MAINTENANCE", "BLACKOUT"]
    starts_at: datetime
    ends_at: datetime
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    services: list[str] = Field(default_factory=list, max_length=100)
    asset_ids: list[str] = Field(default_factory=list, max_length=500)
    environments: list[str] = Field(default_factory=list, max_length=20)
    recurrence: dict[str, object] | None = None
    is_active: bool = True


class WindowUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    services: list[str] | None = Field(default=None, max_length=100)
    asset_ids: list[str] | None = Field(default=None, max_length=500)
    environments: list[str] | None = Field(default=None, max_length=20)
    recurrence: dict[str, object] | None = None
    is_active: bool | None = None


class StandardModelCreate(BaseModel):
    tenant_id: str | None = None
    code: str = Field(
        min_length=2,
        max_length=80,
        pattern=r"^[A-Z0-9][A-Z0-9_-]+$",
    )
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=10_000)
    service_name: str | None = Field(default=None, max_length=200)
    environment: str = Field(default="PRODUCTION", min_length=2, max_length=80)
    default_duration_minutes: int = Field(default=60, ge=5, le=10_080)
    implementation_plan: str = Field(min_length=10, max_length=20_000)
    test_plan: str = Field(min_length=10, max_length=20_000)
    rollback_plan: str = Field(min_length=10, max_length=20_000)
    validation_plan: str = Field(min_length=10, max_length=20_000)
    task_templates: list[dict[str, object]] = Field(
        default_factory=list,
        max_length=100,
    )
    scope: dict[str, object] = Field(default_factory=dict)
    preauthorized_until: datetime
    review_due_at: datetime
    is_active: bool = True


class StandardModelUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=10, max_length=10_000)
    service_name: str | None = Field(default=None, max_length=200)
    environment: str | None = Field(default=None, min_length=2, max_length=80)
    default_duration_minutes: int | None = Field(default=None, ge=5, le=10_080)
    implementation_plan: str | None = Field(default=None, min_length=10, max_length=20_000)
    test_plan: str | None = Field(default=None, min_length=10, max_length=20_000)
    rollback_plan: str | None = Field(default=None, min_length=10, max_length=20_000)
    validation_plan: str | None = Field(default=None, min_length=10, max_length=20_000)
    task_templates: list[dict[str, object]] | None = Field(default=None, max_length=100)
    scope: dict[str, object] | None = None
    preauthorized_until: datetime | None = None
    review_due_at: datetime | None = None
    is_active: bool | None = None


class InstantiateStandardModel(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = Field(default=None, min_length=10, max_length=20_000)
    planned_start_at: datetime | None = None
    owner_id: str | None = None
    asset_ids: list[str] = Field(default_factory=list, max_length=100)
    ticket_ids: list[str] = Field(default_factory=list, max_length=100)


class TaskCreate(BaseModel):
    task_type: Literal["IMPLEMENTATION", "VALIDATION", "ROLLBACK"]
    title: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    sequence: int | None = Field(default=None, ge=1, le=1_000)
    is_required: bool = True
    owner_id: str | None = None
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    status: Literal[
        "PENDING",
        "IN_PROGRESS",
        "COMPLETED",
        "FAILED",
        "SKIPPED",
    ]
    evidence: str | None = Field(default=None, max_length=10_000)


class PIRUpsert(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    outcome: Literal["SUCCESS", "PARTIAL", "FAILED", "ROLLED_BACK"]
    objectives_met: bool
    actual_impact: str = Field(min_length=3, max_length=20_000)
    actual_outage_minutes: int = Field(default=0, ge=0, le=100_800)
    incidents_caused: int = Field(default=0, ge=0, le=10_000)
    lessons_learned: str = Field(min_length=3, max_length=20_000)
    follow_up_actions: list[dict[str, object]] = Field(
        default_factory=list,
        max_length=100,
    )


class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class PIRApprovalRequest(VersionRequest):
    comment: str = Field(min_length=3, max_length=5_000)


class MeetingCreate(BaseModel):
    tenant_id: str | None = None
    title: str = Field(min_length=3, max_length=200)
    meeting_type: Literal["CAB", "ECAB"] = "CAB"
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=10, le=1_440)
    location_or_url: str | None = Field(default=None, max_length=500)
    chair_user_id: str | None = None
    participant_user_ids: list[str] = Field(default_factory=list, max_length=100)


class MeetingUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    status: Literal[
        "DRAFT",
        "PUBLISHED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    ] | None = None
    minutes: str | None = Field(default=None, max_length=20_000)


class AgendaAdd(BaseModel):
    change_id: str
    presenter_user_id: str | None = None
    recommendation: str | None = Field(default=None, max_length=10_000)


class AgendaDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED", "DEFERRED", "MORE_INFO"]
    comment: str = Field(min_length=3, max_length=10_000)
    evidence: dict[str, object] = Field(default_factory=dict)


def _tenant_id(
    db: Session,
    current_user: AuthUserResponse,
    requested: str | None = None,
    *,
    required_for_root: bool = False,
) -> str | None:
    if is_saas_root(current_user):
        if required_for_root and not requested:
            raise HTTPException(status_code=422, detail="tenant_id is required")
        if requested and db.get(Tenant, requested) is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return requested
    if requested and requested != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not current_user.tenant_id:
        raise HTTPException(status_code=422, detail="Tenant context is required")
    return current_user.tenant_id


def _actor(db: Session, current_user: AuthUserResponse) -> User:
    actor = db.get(User, current_user.id)
    if actor is None:
        raise HTTPException(status_code=403, detail="User account not found")
    return actor


def _version(current: int, expected: int, entity: str) -> None:
    if current != expected:
        raise HTTPException(
            status_code=409,
            detail=f"{entity} version conflict; current version is {current}",
        )


def _validate_standard_model_controls(
    task_templates: list[dict[str, object]],
    scope: dict[str, object],
) -> None:
    allowed_types = {"IMPLEMENTATION", "VALIDATION", "ROLLBACK"}
    for index, template in enumerate(task_templates, start=1):
        task_type = str(template.get("type") or "IMPLEMENTATION").upper()
        title = str(template.get("title") or "").strip()
        if task_type not in allowed_types:
            raise HTTPException(
                status_code=422,
                detail=f"Task template {index} has an unsupported type",
            )
        if len(title) < 3:
            raise HTTPException(
                status_code=422,
                detail=f"Task template {index} requires a descriptive title",
            )
    maximum_assets = scope.get("maximum_assets")
    if maximum_assets is not None:
        if isinstance(maximum_assets, bool):
            raise HTTPException(
                status_code=422,
                detail="scope.maximum_assets must be a positive integer",
            )
        try:
            maximum_assets_value = int(maximum_assets)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="scope.maximum_assets must be a positive integer",
            ) from exc
        if maximum_assets_value < 1 or maximum_assets_value > 100:
            raise HTTPException(
                status_code=422,
                detail="scope.maximum_assets must be between 1 and 100",
            )


def _audit(
    db: Session,
    request: Request,
    current_user: AuthUserResponse,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    tenant_id: str,
    metadata: dict[str, object],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user=db.get(User, current_user.id),
        actor_email=current_user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _commit(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc


def _window_response(item: ChangeWindow) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "name": item.name,
        "description": item.description,
        "window_type": item.window_type,
        "starts_at": item.starts_at,
        "ends_at": item.ends_at,
        "timezone": item.timezone,
        "services": item.services_json,
        "asset_ids": item.asset_ids_json,
        "environments": item.environments_json,
        "recurrence": item.recurrence_json,
        "is_active": item.is_active,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _standard_response(item: StandardChangeModel) -> dict[str, Any]:
    reliability = round(
        item.success_count * 100 / max(1, item.success_count + item.failure_count),
        1,
    )
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "service_name": item.service_name,
        "environment": item.environment,
        "default_duration_minutes": item.default_duration_minutes,
        "implementation_plan": item.implementation_plan,
        "test_plan": item.test_plan,
        "rollback_plan": item.rollback_plan,
        "validation_plan": item.validation_plan,
        "task_templates": item.task_templates_json,
        "scope": item.scope_json,
        "preauthorized_until": item.preauthorized_until,
        "review_due_at": item.review_due_at,
        "is_active": item.is_active,
        "usage_count": item.usage_count,
        "success_count": item.success_count,
        "failure_count": item.failure_count,
        "reliability_percent": reliability,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _task_response(item: ChangeImplementationTask) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "change_id": item.change_id,
        "task_type": item.task_type,
        "sequence": item.sequence,
        "title": item.title,
        "description": item.description,
        "status": item.status,
        "is_required": item.is_required,
        "owner_id": item.owner_id,
        "owner_name": item.owner_name,
        "due_at": item.due_at,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "evidence": item.evidence,
        "version": item.version,
    }


def _pir_response(
    db: Session,
    item: ChangePostImplementationReview,
) -> dict[str, Any]:
    prepared = db.get(User, item.prepared_by_id) if item.prepared_by_id else None
    approved = db.get(User, item.approved_by_id) if item.approved_by_id else None
    return {
        "id": item.id,
        "change_id": item.change_id,
        "status": item.status,
        "outcome": item.outcome,
        "objectives_met": item.objectives_met,
        "actual_impact": item.actual_impact,
        "actual_outage_minutes": item.actual_outage_minutes,
        "incidents_caused": item.incidents_caused,
        "lessons_learned": item.lessons_learned,
        "follow_up_actions": item.follow_up_actions_json,
        "prepared_by_id": item.prepared_by_id,
        "prepared_by_name": prepared.full_name if prepared else None,
        "submitted_at": item.submitted_at,
        "approved_by_id": item.approved_by_id,
        "approved_by_name": approved.full_name if approved else None,
        "approved_at": item.approved_at,
        "approval_comment": item.approval_comment,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _meeting_response(db: Session, item: CABMeeting) -> dict[str, Any]:
    chair = db.get(User, item.chair_user_id) if item.chair_user_id else None
    agenda = db.scalars(
        select(CABAgendaItem)
        .where(CABAgendaItem.meeting_id == item.id)
        .order_by(CABAgendaItem.sequence)
    ).all()
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "title": item.title,
        "meeting_type": item.meeting_type,
        "status": item.status,
        "scheduled_at": item.scheduled_at,
        "duration_minutes": item.duration_minutes,
        "location_or_url": item.location_or_url,
        "chair_user_id": item.chair_user_id,
        "chair_user_name": chair.full_name if chair else None,
        "participant_user_ids": item.participant_user_ids_json,
        "minutes": item.minutes,
        "version": item.version,
        "agenda": [
            {
                "id": agenda_item.id,
                "change_id": agenda_item.change_id,
                "change_number": (
                    db.get(ChangeRequest, agenda_item.change_id).change_number
                    if db.get(ChangeRequest, agenda_item.change_id)
                    else None
                ),
                "sequence": agenda_item.sequence,
                "presenter_user_id": agenda_item.presenter_user_id,
                "recommendation": agenda_item.recommendation,
                "decision": agenda_item.decision,
                "decision_comment": agenda_item.decision_comment,
                "evidence": agenda_item.evidence_json,
                "decided_by_id": agenda_item.decided_by_id,
                "decided_at": agenda_item.decided_at,
            }
            for agenda_item in agenda
        ],
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/windows")
def list_windows(
    tenant_id: str | None = Query(default=None),
    starts_at: datetime | None = Query(default=None),
    ends_at: datetime | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "changes.read")
    resolved = _tenant_id(db, current_user, tenant_id)
    statement = select(ChangeWindow)
    if resolved:
        statement = statement.where(ChangeWindow.tenant_id == resolved)
    if starts_at:
        statement = statement.where(ChangeWindow.ends_at > starts_at)
    if ends_at:
        statement = statement.where(ChangeWindow.starts_at < ends_at)
    rows = db.scalars(statement.order_by(ChangeWindow.starts_at)).all()
    return [_window_response(item) for item in rows]


@router.post("/windows", status_code=status.HTTP_201_CREATED)
def create_window(
    payload: WindowCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.schedule")
    tenant_id = _tenant_id(
        db,
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    assert tenant_id is not None
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=422, detail="Window end must be after start")
    try:
        timezone = validate_timezone(payload.timezone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _validate_linked_records(db, tenant_id, payload.asset_ids, [])
    item = ChangeWindow(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        window_type=payload.window_type,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        timezone=timezone,
        services_json=list(dict.fromkeys(payload.services)),
        asset_ids_json=list(dict.fromkeys(payload.asset_ids)),
        environments_json=[
            value.upper() for value in dict.fromkeys(payload.environments)
        ],
        recurrence_json=payload.recurrence,
        is_active=payload.is_active,
        version=1,
        created_by_id=current_user.id,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        request,
        current_user,
        action="change.window_created",
        entity_type="change_window",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"window_type": item.window_type, "name": item.name},
    )
    _commit(db, "A change window with this name and start already exists")
    db.refresh(item)
    return _window_response(item)


@router.patch("/windows/{window_id}")
def update_window(
    window_id: str,
    payload: WindowUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.schedule")
    tenant_id = _tenant_id(db, current_user)
    item = db.get(ChangeWindow, window_id)
    if item is None or (tenant_id and item.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="Change window not found")
    _version(item.version, payload.expected_version, "Change window")
    updates = payload.model_dump(
        exclude_unset=True,
        exclude={"expected_version"},
    )
    for source, target in {
        "services": "services_json",
        "asset_ids": "asset_ids_json",
        "environments": "environments_json",
        "recurrence": "recurrence_json",
    }.items():
        if source in updates:
            updates[target] = updates.pop(source)
    start = updates.get("starts_at", item.starts_at)
    end = updates.get("ends_at", item.ends_at)
    if end <= start:
        raise HTTPException(status_code=422, detail="Window end must be after start")
    if "timezone" in updates:
        try:
            updates["timezone"] = validate_timezone(str(updates["timezone"]))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "asset_ids_json" in updates:
        _validate_linked_records(db, item.tenant_id, updates["asset_ids_json"], [])
    for field, value in updates.items():
        setattr(item, field, value)
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="change.window_updated",
        entity_type="change_window",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"version": item.version},
    )
    _commit(db, "Change window update conflicts with existing data")
    db.refresh(item)
    return _window_response(item)


@router.get("/calendar")
def change_calendar(
    starts_at: datetime,
    ends_at: datetime,
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.read")
    resolved = _tenant_id(db, current_user, tenant_id)
    change_statement = select(ChangeRequest).where(
        ChangeRequest.planned_start_at < ends_at,
        ChangeRequest.planned_end_at > starts_at,
    )
    window_statement = select(ChangeWindow).where(
        ChangeWindow.starts_at < ends_at,
        ChangeWindow.ends_at > starts_at,
        ChangeWindow.is_active.is_(True),
    )
    if resolved:
        change_statement = change_statement.where(
            ChangeRequest.tenant_id == resolved
        )
        window_statement = window_statement.where(
            ChangeWindow.tenant_id == resolved
        )
    changes = db.scalars(
        change_statement.order_by(ChangeRequest.planned_start_at)
    ).all()
    windows = db.scalars(
        window_statement.order_by(ChangeWindow.starts_at)
    ).all()
    return {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "changes": [
            {
                "id": item.id,
                "tenant_id": item.tenant_id,
                "change_number": item.change_number,
                "title": item.title,
                "change_type": item.change_type,
                "status": item.status,
                "risk_level": item.risk_level,
                "service_name": item.service_name,
                "environment": item.environment,
                "planned_start_at": item.planned_start_at,
                "planned_end_at": item.planned_end_at,
                "outage_required": item.outage_required,
            }
            for item in changes
        ],
        "windows": [_window_response(item) for item in windows],
    }


@router.get("/changes/{change_id}/window-assessment")
def get_window_assessment(
    change_id: str,
    starts_at: datetime | None = Query(default=None),
    ends_at: datetime | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.read")
    change = _get_change(db, change_id, current_user)
    return assess_change_window(
        db,
        change,
        starts_at=starts_at,
        ends_at=ends_at,
    )


@router.get("/changes/{change_id}/readiness")
def get_readiness(
    change_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.read")
    return readiness_assessment(
        db,
        _get_change(db, change_id, current_user),
    )


@router.get("/standard-models")
def list_standard_models(
    tenant_id: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "changes.read")
    resolved = _tenant_id(db, current_user, tenant_id)
    statement = select(StandardChangeModel)
    if resolved:
        statement = statement.where(StandardChangeModel.tenant_id == resolved)
    if not include_inactive:
        statement = statement.where(StandardChangeModel.is_active.is_(True))
    rows = db.scalars(
        statement.order_by(StandardChangeModel.name)
    ).all()
    return [_standard_response(item) for item in rows]


@router.post("/standard-models", status_code=status.HTTP_201_CREATED)
def create_standard_model(
    payload: StandardModelCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    tenant_id = _tenant_id(
        db,
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    assert tenant_id is not None
    preauthorized_until = aware(payload.preauthorized_until)
    review_due_at = aware(payload.review_due_at)
    if preauthorized_until <= now_utc():
        raise HTTPException(status_code=422, detail="Preauthorization must be in the future")
    if review_due_at > preauthorized_until:
        raise HTTPException(
            status_code=422,
            detail="Review must be due no later than preauthorization expiry",
        )
    _validate_standard_model_controls(payload.task_templates, payload.scope)
    item = StandardChangeModel(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        service_name=payload.service_name,
        environment=payload.environment.upper(),
        default_duration_minutes=payload.default_duration_minutes,
        outage_required=False,
        outage_minutes=0,
        implementation_plan=payload.implementation_plan,
        test_plan=payload.test_plan,
        rollback_plan=payload.rollback_plan,
        validation_plan=payload.validation_plan,
        task_templates_json=payload.task_templates,
        scope_json=payload.scope,
        preauthorized_until=preauthorized_until,
        review_due_at=review_due_at,
        is_active=payload.is_active,
        usage_count=0,
        success_count=0,
        failure_count=0,
        version=1,
        approved_by_id=current_user.id,
        created_by_id=current_user.id,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        request,
        current_user,
        action="change.standard_model_created",
        entity_type="standard_change_model",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"code": item.code},
    )
    _commit(db, "Standard change model code already exists")
    db.refresh(item)
    return _standard_response(item)


@router.patch("/standard-models/{model_id}")
def update_standard_model(
    model_id: str,
    payload: StandardModelUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    tenant_id = _tenant_id(db, current_user)
    item = db.get(StandardChangeModel, model_id)
    if item is None or (tenant_id and item.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="Standard change model not found")
    _version(item.version, payload.expected_version, "Standard change model")
    updates = payload.model_dump(
        exclude_unset=True,
        exclude={"expected_version"},
    )
    _validate_standard_model_controls(
        updates.get("task_templates", item.task_templates_json),
        updates.get("scope", item.scope_json),
    )
    for source, target in {
        "task_templates": "task_templates_json",
        "scope": "scope_json",
    }.items():
        if source in updates:
            updates[target] = updates.pop(source)
    for field in ("preauthorized_until", "review_due_at"):
        if field in updates:
            updates[field] = aware(updates[field])
    for field, value in updates.items():
        setattr(item, field, value)
    if aware(item.review_due_at) > aware(item.preauthorized_until):
        raise HTTPException(
            status_code=422,
            detail="Review must be due no later than preauthorization expiry",
        )
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="change.standard_model_updated",
        entity_type="standard_change_model",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"version": item.version},
    )
    _commit(db, "Standard change model update conflicts with existing data")
    db.refresh(item)
    return _standard_response(item)


@router.post(
    "/standard-models/{model_id}/instantiate",
    response_model=ChangeDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def instantiate_standard_model(
    model_id: str,
    payload: InstantiateStandardModel,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChangeDetailResponse:
    require_permissions(current_user, "changes.create")
    tenant_id = _tenant_id(db, current_user)
    item = db.get(StandardChangeModel, model_id)
    if item is None or (tenant_id and item.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="Standard change model not found")
    instant = now_utc()
    if not item.is_active or aware(item.preauthorized_until) <= instant:
        raise HTTPException(
            status_code=409,
            detail="Standard change model is inactive or preauthorization expired",
        )
    if aware(item.review_due_at) <= instant:
        raise HTTPException(
            status_code=409,
            detail="Standard change model requires governance review",
        )
    _validate_linked_records(
        db,
        item.tenant_id,
        payload.asset_ids,
        payload.ticket_ids,
    )
    maximum_assets = item.scope_json.get("maximum_assets")
    if maximum_assets is not None and len(set(payload.asset_ids)) > int(maximum_assets):
        raise HTTPException(
            status_code=422,
            detail=(
                "Selected assets exceed the preauthorized standard model scope "
                f"({maximum_assets})"
            ),
        )
    owner = (
        validate_user(db, payload.owner_id, item.tenant_id)
        if payload.owner_id
        else _actor(db, current_user)
    )
    planned_end = (
        payload.planned_start_at
        + timedelta(minutes=item.default_duration_minutes)
        if payload.planned_start_at
        else None
    )
    score, risk_level, cab_required = _risk_score(
        impact_level="LOW",
        likelihood=1,
        outage_required=False,
        change_type="STANDARD",
        asset_count=len(payload.asset_ids),
    )
    if cab_required:
        raise HTTPException(
            status_code=422,
            detail="Selected scope exceeds the preauthorized standard risk",
        )
    change = ChangeRequest(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        change_number=f"CHG-{instant.year}-{uuid.uuid4().hex[:8].upper()}",
        title=payload.title or item.name,
        description=payload.description or item.description,
        change_type="STANDARD",
        status="DRAFT",
        service_name=item.service_name,
        environment=item.environment,
        standard_model_id=item.id,
        impact_level="LOW",
        likelihood=1,
        risk_score=score,
        risk_level=risk_level,
        business_justification=f"Preauthorized standard model {item.code}.",
        implementation_plan=item.implementation_plan,
        test_plan=item.test_plan,
        rollback_plan=item.rollback_plan,
        validation_plan=item.validation_plan,
        requested_by_id=current_user.id,
        requested_by_name=current_user.full_name,
        requested_by_email=current_user.email,
        owner_id=owner.id,
        owner_name=owner.full_name,
        cab_required=False,
        approval_status="NOT_REQUIRED",
        planned_start_at=payload.planned_start_at,
        planned_end_at=planned_end,
        outage_required=False,
        outage_minutes=0,
        validation_status="NOT_STARTED",
        pir_status="NOT_REQUIRED",
        version=1,
    )
    db.add(change)
    db.flush()
    _replace_links(
        db,
        change,
        asset_ids=list(dict.fromkeys(payload.asset_ids)),
        ticket_ids=list(dict.fromkeys(payload.ticket_ids)),
    )
    create_tasks_from_standard_model(db, change, item)
    item.usage_count += 1
    _record_history(
        db,
        change,
        current_user,
        event_type="STANDARD_MODEL_INSTANTIATED",
        message=f"Change created from preauthorized model {item.code}",
        to_status="DRAFT",
        metadata={
            "standard_model_id": item.id,
            "standard_model_version": item.version,
        },
    )
    _audit_request(
        db,
        request,
        change,
        current_user,
        "changes.standard_model_instantiate",
        {"standard_model_id": item.id},
    )
    db.commit()
    db.refresh(change)
    return _detail_response(db, change)


@router.get("/changes/{change_id}/tasks")
def list_tasks(
    change_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "changes.read")
    change = _get_change(db, change_id, current_user)
    rows = db.scalars(
        select(ChangeImplementationTask)
        .where(ChangeImplementationTask.change_id == change.id)
        .order_by(
            ChangeImplementationTask.task_type,
            ChangeImplementationTask.sequence,
        )
    ).all()
    return [_task_response(item) for item in rows]


@router.post(
    "/changes/{change_id}/tasks",
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    change_id: str,
    payload: TaskCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.update")
    change = _get_change(db, change_id, current_user)
    if change.status not in {
        "DRAFT",
        "ASSESSMENT",
        "APPROVED",
        "SCHEDULED",
        "IMPLEMENTING",
        "REVIEW",
        "FAILED",
    }:
        raise HTTPException(status_code=409, detail="Tasks cannot be added now")
    owner = validate_user(db, payload.owner_id, change.tenant_id)
    sequence = payload.sequence or (
        int(
            db.scalar(
                select(func.max(ChangeImplementationTask.sequence)).where(
                    ChangeImplementationTask.change_id == change.id,
                    ChangeImplementationTask.task_type == payload.task_type,
                )
            )
            or 0
        )
        + 1
    )
    item = ChangeImplementationTask(
        id=str(uuid.uuid4()),
        tenant_id=change.tenant_id,
        change_id=change.id,
        task_type=payload.task_type,
        sequence=sequence,
        title=payload.title,
        description=payload.description,
        status="PENDING",
        is_required=payload.is_required,
        owner_id=owner.id if owner else change.owner_id,
        owner_name=owner.full_name if owner else change.owner_name,
        due_at=payload.due_at,
        version=1,
    )
    db.add(item)
    db.flush()
    change.version += 1
    _record_history(
        db,
        change,
        current_user,
        event_type="TASK_CREATED",
        message=f"{payload.task_type} task created: {payload.title}",
        metadata={"task_id": item.id},
    )
    _audit_request(db, request, change, current_user, "changes.task_created")
    _commit(db, "Task sequence already exists")
    db.refresh(item)
    return _task_response(item)


@router.patch("/changes/{change_id}/tasks/{task_id}")
def update_task(
    change_id: str,
    task_id: str,
    payload: TaskUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.execute")
    change = _get_change(db, change_id, current_user)
    item = db.get(ChangeImplementationTask, task_id)
    if item is None or item.change_id != change.id:
        raise HTTPException(status_code=404, detail="Change task not found")
    _version(item.version, payload.expected_version, "Change task")
    allowed = {
        "PENDING": {"IN_PROGRESS", "COMPLETED", "SKIPPED"},
        "IN_PROGRESS": {"COMPLETED", "FAILED"},
        "FAILED": {"IN_PROGRESS"},
        "COMPLETED": set(),
        "SKIPPED": set(),
    }
    if payload.status != item.status and payload.status not in allowed[item.status]:
        raise HTTPException(status_code=409, detail="Invalid task transition")
    if payload.status == "SKIPPED" and item.is_required:
        raise HTTPException(status_code=422, detail="Required task cannot be skipped")
    if payload.status in {"COMPLETED", "FAILED", "SKIPPED"} and not (
        payload.evidence or ""
    ).strip():
        raise HTTPException(status_code=422, detail="Task evidence is required")
    instant = now_utc()
    if payload.status == "IN_PROGRESS" and item.started_at is None:
        item.started_at = instant
    if payload.status in {"COMPLETED", "FAILED", "SKIPPED"}:
        item.completed_at = instant
    item.status = payload.status
    item.evidence = payload.evidence
    item.version += 1
    if item.task_type == "VALIDATION":
        validation_tasks = db.scalars(
            select(ChangeImplementationTask).where(
                ChangeImplementationTask.change_id == change.id,
                ChangeImplementationTask.task_type == "VALIDATION",
                ChangeImplementationTask.is_required.is_(True),
            )
        ).all()
        if any(task.status == "FAILED" for task in validation_tasks):
            change.validation_status = "FAILED"
        elif validation_tasks and all(
            task.status == "COMPLETED" for task in validation_tasks
        ):
            change.validation_status = "PASSED"
        else:
            change.validation_status = "IN_PROGRESS"
    change.version += 1
    _record_history(
        db,
        change,
        current_user,
        event_type="TASK_UPDATED",
        message=f"{item.task_type} task {item.title}: {item.status}",
        metadata={"task_id": item.id, "evidence": item.evidence or ""},
    )
    _audit_request(db, request, change, current_user, "changes.task_updated")
    db.commit()
    db.refresh(item)
    return _task_response(item)


@router.get("/changes/{change_id}/pir")
def get_pir(
    change_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.read")
    change = _get_change(db, change_id, current_user)
    item = pir_for_change(db, change.id)
    if item is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    return _pir_response(db, item)


@router.put("/changes/{change_id}/pir")
def upsert_pir(
    change_id: str,
    payload: PIRUpsert,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.execute")
    change = _get_change(db, change_id, current_user)
    if change.status not in {"REVIEW", "FAILED", "ROLLED_BACK", "COMPLETED"}:
        raise HTTPException(status_code=409, detail="PIR is not available yet")
    item = pir_for_change(db, change.id)
    if item is None:
        if payload.expected_version is not None:
            raise HTTPException(status_code=409, detail="PIR does not exist")
        item = ChangePostImplementationReview(
            id=str(uuid.uuid4()),
            tenant_id=change.tenant_id,
            change_id=change.id,
            status="DRAFT",
            outcome=payload.outcome,
            objectives_met=payload.objectives_met,
            actual_impact=payload.actual_impact,
            actual_outage_minutes=payload.actual_outage_minutes,
            incidents_caused=payload.incidents_caused,
            lessons_learned=payload.lessons_learned,
            follow_up_actions_json=payload.follow_up_actions,
            prepared_by_id=current_user.id,
            version=1,
        )
        db.add(item)
    else:
        if item.status != "DRAFT":
            raise HTTPException(status_code=409, detail="Submitted PIR is immutable")
        if payload.expected_version is None:
            raise HTTPException(status_code=422, detail="expected_version is required")
        _version(item.version, payload.expected_version, "PIR")
        for field in (
            "outcome",
            "objectives_met",
            "actual_impact",
            "actual_outage_minutes",
            "incidents_caused",
            "lessons_learned",
        ):
            setattr(item, field, getattr(payload, field))
        item.follow_up_actions_json = payload.follow_up_actions
        item.version += 1
    change.pir_status = "DRAFT"
    change.version += 1
    _record_history(
        db,
        change,
        current_user,
        event_type="PIR_UPDATED",
        message=f"Post-implementation review saved: {payload.outcome}",
        metadata={"pir_id": item.id},
    )
    _audit_request(db, request, change, current_user, "changes.pir_updated")
    _commit(db, "A PIR already exists for this change")
    db.refresh(item)
    return _pir_response(db, item)


@router.post("/changes/{change_id}/pir/submit")
def submit_pir(
    change_id: str,
    payload: VersionRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.execute")
    change = _get_change(db, change_id, current_user)
    item = pir_for_change(db, change.id)
    if item is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    _version(item.version, payload.expected_version, "PIR")
    if item.status != "DRAFT":
        raise HTTPException(status_code=409, detail="PIR is already submitted")
    item.status = "SUBMITTED"
    item.submitted_at = now_utc()
    item.version += 1
    change.pir_status = "SUBMITTED"
    change.version += 1
    _record_history(
        db,
        change,
        current_user,
        event_type="PIR_SUBMITTED",
        message="Post-implementation review submitted for independent approval",
        metadata={"pir_id": item.id},
    )
    _audit_request(db, request, change, current_user, "changes.pir_submitted")
    db.commit()
    db.refresh(item)
    return _pir_response(db, item)


@router.post("/changes/{change_id}/pir/approve")
def approve_pir(
    change_id: str,
    payload: PIRApprovalRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    change = _get_change(db, change_id, current_user)
    item = pir_for_change(db, change.id)
    if item is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    _version(item.version, payload.expected_version, "PIR")
    if item.status != "SUBMITTED":
        raise HTTPException(status_code=409, detail="PIR is not awaiting approval")
    if item.prepared_by_id == current_user.id:
        raise HTTPException(status_code=403, detail="PIR author cannot approve it")
    item.status = "APPROVED"
    item.approved_by_id = current_user.id
    item.approved_at = now_utc()
    item.approval_comment = payload.comment
    item.version += 1
    change.pir_status = "APPROVED"
    change.outcome = item.outcome
    change.post_implementation_review = item.lessons_learned
    change.version += 1
    update_standard_model_outcome(db, change, item.outcome)
    _record_history(
        db,
        change,
        current_user,
        event_type="PIR_APPROVED",
        message=f"Post-implementation review approved: {item.outcome}",
        metadata={"pir_id": item.id, "comment": payload.comment},
    )
    _audit_request(db, request, change, current_user, "changes.pir_approved")
    db.commit()
    db.refresh(item)
    return _pir_response(db, item)


@router.get("/cab/meetings")
def list_meetings(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "changes.read")
    resolved = _tenant_id(db, current_user, tenant_id)
    statement = select(CABMeeting)
    if resolved:
        statement = statement.where(CABMeeting.tenant_id == resolved)
    rows = db.scalars(
        statement.order_by(CABMeeting.scheduled_at.desc()).limit(100)
    ).all()
    return [_meeting_response(db, item) for item in rows]


@router.post("/cab/meetings", status_code=status.HTTP_201_CREATED)
def create_meeting(
    payload: MeetingCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    tenant_id = _tenant_id(
        db,
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    assert tenant_id is not None
    chair = validate_user(db, payload.chair_user_id, tenant_id)
    for participant_id in payload.participant_user_ids:
        validate_user(db, participant_id, tenant_id)
    item = CABMeeting(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        title=payload.title,
        meeting_type=payload.meeting_type,
        status="DRAFT",
        scheduled_at=payload.scheduled_at,
        duration_minutes=payload.duration_minutes,
        location_or_url=payload.location_or_url,
        chair_user_id=chair.id if chair else current_user.id,
        participant_user_ids_json=list(
            dict.fromkeys(payload.participant_user_ids)
        ),
        version=1,
        created_by_id=current_user.id,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        request,
        current_user,
        action="change.cab_meeting_created",
        entity_type="cab_meeting",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"meeting_type": item.meeting_type},
    )
    db.commit()
    db.refresh(item)
    return _meeting_response(db, item)


@router.patch("/cab/meetings/{meeting_id}")
def update_meeting(
    meeting_id: str,
    payload: MeetingUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    tenant_id = _tenant_id(db, current_user)
    item = db.get(CABMeeting, meeting_id)
    if item is None or (tenant_id and item.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="CAB meeting not found")
    _version(item.version, payload.expected_version, "CAB meeting")
    if payload.status:
        allowed = {
            "DRAFT": {"PUBLISHED", "CANCELLED"},
            "PUBLISHED": {"IN_PROGRESS", "CANCELLED"},
            "IN_PROGRESS": {"COMPLETED"},
            "COMPLETED": set(),
            "CANCELLED": set(),
        }
        if payload.status != item.status and payload.status not in allowed[item.status]:
            raise HTTPException(status_code=409, detail="Invalid meeting transition")
        item.status = payload.status
    if payload.minutes is not None:
        item.minutes = payload.minutes
    if item.status == "COMPLETED" and not (item.minutes or "").strip():
        raise HTTPException(status_code=422, detail="Meeting minutes are required")
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="change.cab_meeting_updated",
        entity_type="cab_meeting",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"status": item.status},
    )
    db.commit()
    db.refresh(item)
    return _meeting_response(db, item)


@router.post(
    "/cab/meetings/{meeting_id}/agenda",
    status_code=status.HTTP_201_CREATED,
)
def add_agenda_item(
    meeting_id: str,
    payload: AgendaAdd,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    tenant_id = _tenant_id(db, current_user)
    meeting = db.get(CABMeeting, meeting_id)
    if meeting is None or (tenant_id and meeting.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="CAB meeting not found")
    if meeting.status not in {"DRAFT", "PUBLISHED"}:
        raise HTTPException(status_code=409, detail="CAB agenda is locked")
    change = db.get(ChangeRequest, payload.change_id)
    if change is None or change.tenant_id != meeting.tenant_id:
        raise HTTPException(status_code=404, detail="Change request not found")
    presenter = validate_user(
        db,
        payload.presenter_user_id,
        meeting.tenant_id,
    )
    sequence = int(
        db.scalar(
            select(func.max(CABAgendaItem.sequence)).where(
                CABAgendaItem.meeting_id == meeting.id
            )
        )
        or 0
    ) + 1
    item = CABAgendaItem(
        id=str(uuid.uuid4()),
        tenant_id=meeting.tenant_id,
        meeting_id=meeting.id,
        change_id=change.id,
        sequence=sequence,
        presenter_user_id=presenter.id if presenter else change.owner_id,
        recommendation=payload.recommendation,
        evidence_json={},
    )
    db.add(item)
    meeting.version += 1
    _audit(
        db,
        request,
        current_user,
        action="change.cab_agenda_added",
        entity_type="cab_meeting",
        entity_id=meeting.id,
        tenant_id=meeting.tenant_id,
        metadata={"change_id": change.id},
    )
    _commit(db, "Change is already on this CAB agenda")
    db.refresh(meeting)
    return _meeting_response(db, meeting)


@router.post("/cab/agenda/{agenda_item_id}/decision")
def decide_agenda_item(
    agenda_item_id: str,
    payload: AgendaDecision,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    tenant_id = _tenant_id(db, current_user)
    item = db.get(CABAgendaItem, agenda_item_id)
    if item is None or (tenant_id and item.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="CAB agenda item not found")
    meeting = db.get(CABMeeting, item.meeting_id)
    change = db.get(ChangeRequest, item.change_id)
    if meeting is None or change is None:
        raise HTTPException(status_code=409, detail="CAB evidence is incomplete")
    if meeting.status not in {"PUBLISHED", "IN_PROGRESS"}:
        raise HTTPException(status_code=409, detail="CAB meeting is not active")
    if item.decision is not None:
        raise HTTPException(status_code=409, detail="Agenda decision is immutable")
    if change.requested_by_id == current_user.id:
        raise HTTPException(status_code=403, detail="Requester cannot decide own change")
    instant = now_utc()
    item.decision = payload.decision
    item.decision_comment = payload.comment
    item.evidence_json = payload.evidence
    item.decided_by_id = current_user.id
    item.decided_at = instant
    if payload.decision in {"APPROVED", "REJECTED"}:
        if change.status != "APPROVAL_PENDING":
            raise HTTPException(
                status_code=409,
                detail="Change is not awaiting a CAB decision",
            )
        db.add(
            ChangeApproval(
                id=str(uuid.uuid4()),
                tenant_id=change.tenant_id,
                change_id=change.id,
                approver_id=current_user.id,
                approver_name=current_user.full_name,
                approver_email=current_user.email,
                decision=payload.decision,
                decision_comment=payload.comment,
                decided_at=instant,
            )
        )
        previous = change.status
        change.approval_status = payload.decision
        change.status = (
            "APPROVED" if payload.decision == "APPROVED" else "REJECTED"
        )
        change.version += 1
        _record_history(
            db,
            change,
            current_user,
            event_type="CAB_AGENDA_DECISION",
            message=f"{meeting.meeting_type} decision: {payload.decision}",
            from_status=previous,
            to_status=change.status,
            metadata={
                "meeting_id": meeting.id,
                "agenda_item_id": item.id,
                "evidence": payload.evidence,
            },
        )
    _audit(
        db,
        request,
        current_user,
        action="change.cab_agenda_decided",
        entity_type="cab_agenda_item",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"decision": payload.decision, "change_id": change.id},
    )
    db.commit()
    db.refresh(meeting)
    return _meeting_response(db, meeting)


@router.get("/analytics")
def get_change_analytics(
    tenant_id: str | None = Query(default=None),
    days: int = Query(default=90, ge=7, le=730),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.read")
    resolved = _tenant_id(db, current_user, tenant_id)
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    metrics = change_metrics(db, resolved, starts_at=start, ends_at=end)
    if resolved:
        open_task_query = select(func.count(ChangeImplementationTask.id)).where(
            ChangeImplementationTask.tenant_id == resolved,
            ChangeImplementationTask.status.in_(["PENDING", "IN_PROGRESS"]),
        )
    else:
        open_task_query = select(func.count(ChangeImplementationTask.id)).where(
            ChangeImplementationTask.status.in_(["PENDING", "IN_PROGRESS"])
        )
    metrics["open_tasks"] = int(db.scalar(open_task_query) or 0)
    metrics["overdue_standard_reviews"] = int(
        db.scalar(
            select(func.count(StandardChangeModel.id)).where(
                *(
                    [StandardChangeModel.tenant_id == resolved]
                    if resolved
                    else []
                ),
                StandardChangeModel.is_active.is_(True),
                StandardChangeModel.review_due_at <= end,
            )
        )
        or 0
    )
    return metrics
