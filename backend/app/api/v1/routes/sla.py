from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.sla import (
    SlaBusinessCalendar,
    SlaCalendarException,
    SlaPolicy,
    TicketSlaInstance,
    TicketSlaPause,
    TicketSlaTarget,
    TicketSlaTimeline,
)
from app.models.ticket import Ticket
from app.models.tenant import Tenant
from app.models.user import User
from app.services.asset_sla import summarize_sla_overview
from app.services.audit import log_audit
from app.services.enterprise_sla import (
    DEFAULT_WEEKLY_HOURS,
    as_utc,
    business_minutes_between,
    complete_target,
    current_instance,
    ensure_ticket_sla_instance,
    evaluate_tenant_sla,
    instance_targets,
    now_utc,
    pause_instance,
    resume_instance,
    validate_escalations,
    validate_intervals,
    validate_targets,
    validate_timezone,
    validate_weekly_hours,
)
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/sla")


class CalendarCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    weekly_hours: dict[str, list[list[str]]] = Field(
        default_factory=lambda: dict(DEFAULT_WEEKLY_HOURS)
    )
    is_default: bool = False
    is_active: bool = True


class CalendarUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    weekly_hours: dict[str, list[list[str]]] | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class CalendarExceptionInput(BaseModel):
    exception_date: date
    kind: Literal["HOLIDAY", "WORKING_DAY"]
    name: str = Field(min_length=2, max_length=200)
    intervals: list[list[str]] = Field(default_factory=list, max_length=4)


class SlaTargetInput(BaseModel):
    type: Literal["RESPONSE", "RESOLUTION", "FULFILLMENT", "OLA", "SUPPLIER"]
    name: str = Field(min_length=2, max_length=200)
    minutes: int = Field(ge=1, le=5_256_000)
    warning_percent: int = Field(default=80, ge=1, le=100)
    owner_type: str | None = Field(default=None, max_length=32)
    owner_ref: str = Field(default="", max_length=255)


class SlaEscalationInput(BaseModel):
    at_percent: int = Field(ge=1, le=500)
    target_type: Literal[
        "RESPONSE",
        "RESOLUTION",
        "FULFILLMENT",
        "OLA",
        "SUPPLIER",
    ] | None = None
    recipient_user_id: str | None = None
    label: str = Field(min_length=2, max_length=200)


class PolicyCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)
    priority: str = Field(min_length=2, max_length=32)
    calendar_id: str | None = None
    priority_order: int = Field(default=100, ge=1, le=10_000)
    scope: dict[str, object] = Field(default_factory=dict)
    targets: list[SlaTargetInput] = Field(default_factory=list, max_length=12)
    pause_statuses: list[str] = Field(
        default_factory=lambda: ["WAITING_USER", "WAITING_VENDOR"],
        max_length=20,
    )
    pause_reasons: list[str] = Field(
        default_factory=lambda: [
            "WAITING_CUSTOMER",
            "WAITING_VENDOR",
            "APPROVED_HOLD",
        ],
        max_length=20,
    )
    warning_percent: int = Field(default=80, ge=1, le=100)
    escalations: list[SlaEscalationInput] = Field(
        default_factory=list,
        max_length=10,
    )
    is_active: bool = True


class PolicyUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)
    priority: str | None = Field(default=None, min_length=2, max_length=32)
    calendar_id: str | None = None
    priority_order: int | None = Field(default=None, ge=1, le=10_000)
    scope: dict[str, object] | None = None
    targets: list[SlaTargetInput] | None = Field(default=None, max_length=12)
    pause_statuses: list[str] | None = Field(default=None, max_length=20)
    pause_reasons: list[str] | None = Field(default=None, max_length=20)
    warning_percent: int | None = Field(default=None, ge=1, le=100)
    escalations: list[SlaEscalationInput] | None = Field(
        default=None,
        max_length=10,
    )
    is_active: bool | None = None


class PauseRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason_code: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=3, max_length=5_000)


class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class CompleteTargetRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=5_000)


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


def _assert_version(current: int, expected: int, entity: str) -> None:
    if current != expected:
        raise HTTPException(
            status_code=409,
            detail=f"{entity} version conflict; current version is {current}",
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


def _calendar(db: Session, calendar_id: str, tenant_id: str) -> SlaBusinessCalendar:
    item = db.get(SlaBusinessCalendar, calendar_id)
    if item is None or item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="SLA calendar not found")
    return item


def _policy(db: Session, policy_id: str, tenant_id: str | None) -> SlaPolicy:
    item = db.get(SlaPolicy, policy_id)
    if item is None or (tenant_id is not None and item.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="SLA policy not found")
    return item


def _instance(
    db: Session,
    instance_id: str,
    tenant_id: str | None,
) -> TicketSlaInstance:
    item = db.get(TicketSlaInstance, instance_id)
    if item is None or (tenant_id is not None and item.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="SLA instance not found")
    return item


def _calendar_response(
    db: Session,
    item: SlaBusinessCalendar,
    *,
    details: bool = True,
) -> dict[str, Any]:
    exceptions: list[dict[str, Any]] = []
    if details:
        exceptions = [
            {
                "id": exception.id,
                "exception_date": exception.exception_date,
                "kind": exception.kind,
                "name": exception.name,
                "intervals": exception.intervals_json,
            }
            for exception in db.scalars(
                select(SlaCalendarException)
                .where(SlaCalendarException.calendar_id == item.id)
                .order_by(SlaCalendarException.exception_date)
            ).all()
        ]
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "name": item.name,
        "description": item.description,
        "timezone": item.timezone,
        "weekly_hours": item.weekly_hours_json,
        "is_default": item.is_default,
        "is_active": item.is_active,
        "version": item.version,
        "exceptions": exceptions,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _policy_response(db: Session, item: SlaPolicy) -> dict[str, Any]:
    tenant = db.get(Tenant, item.tenant_id) if item.tenant_id else None
    calendar = db.get(SlaBusinessCalendar, item.calendar_id) if item.calendar_id else None
    return {
        "id": item.id,
        "name": item.name,
        "priority": item.priority,
        "target_response_minutes": item.target_response_minutes,
        "target_resolution_minutes": item.target_resolution_minutes,
        "response_minutes": item.response_minutes,
        "resolution_minutes": item.resolution_minutes,
        "is_active": item.is_active,
        "status": item.status,
        "breach_count": item.breach_count,
        "description": item.description,
        "tenant_id": item.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "calendar_id": item.calendar_id,
        "calendar_name": calendar.name if calendar else "24×7 elapsed time",
        "priority_order": item.priority_order,
        "scope": item.scope_json,
        "targets": item.targets_json,
        "pause_statuses": item.pause_statuses_json,
        "pause_reasons": item.pause_reasons_json,
        "warning_percent": item.warning_percent,
        "escalations": item.escalations_json,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _target_response(
    instance: TicketSlaInstance,
    item: TicketSlaTarget,
    *,
    at: datetime | None = None,
) -> dict[str, Any]:
    instant = as_utc(at or now_utc())
    due_at = as_utc(item.due_at)
    consumed = business_minutes_between(
        instance.started_at,
        instant,
        instance.calendar_snapshot_json,
    )
    consumed = max(0, consumed - instance.total_paused_business_minutes)
    progress = min(999, round(consumed * 100 / max(item.duration_minutes, 1)))
    remaining = business_minutes_between(
        instant,
        due_at,
        instance.calendar_snapshot_json,
    )
    if instant > due_at:
        remaining = -business_minutes_between(
            due_at,
            instant,
            instance.calendar_snapshot_json,
        )
    return {
        "id": item.id,
        "target_type": item.target_type,
        "name": item.name,
        "duration_minutes": item.duration_minutes,
        "warning_percent": item.warning_percent,
        "warning_at": item.warning_at,
        "due_at": item.due_at,
        "status": item.status,
        "owner_type": item.owner_type,
        "owner_ref": item.owner_ref,
        "met_at": item.met_at,
        "breached_at": item.breached_at,
        "progress_percent": progress,
        "remaining_business_minutes": remaining,
        "escalation_level": item.escalation_level,
        "last_escalated_at": item.last_escalated_at,
        "version": item.version,
    }


def _instance_response(
    db: Session,
    item: TicketSlaInstance,
    *,
    details: bool = False,
) -> dict[str, Any]:
    ticket = db.get(Ticket, item.ticket_id)
    policy_name = str(item.policy_snapshot_json.get("name") or "SLA")
    targets = instance_targets(db, item.id)
    response: dict[str, Any] = {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "ticket_id": item.ticket_id,
        "ticket_number": ticket.ticket_number if ticket else None,
        "ticket_title": ticket.title if ticket else None,
        "ticket_priority": ticket.priority if ticket else None,
        "ticket_status": ticket.status if ticket else None,
        "policy_id": item.policy_id,
        "policy_name": policy_name,
        "policy_version": item.policy_version,
        "calendar_id": item.calendar_id,
        "calendar_name": (
            item.calendar_snapshot_json.get("name")
            if item.calendar_snapshot_json
            else "24×7 elapsed time"
        ),
        "status": item.status,
        "is_current": item.is_current,
        "started_at": item.started_at,
        "paused_at": item.paused_at,
        "completed_at": item.completed_at,
        "last_evaluated_at": item.last_evaluated_at,
        "total_paused_business_minutes": item.total_paused_business_minutes,
        "version": item.version,
        "targets": [_target_response(item, target) for target in targets],
    }
    if details:
        response["policy_snapshot"] = item.policy_snapshot_json
        response["calendar_snapshot"] = item.calendar_snapshot_json
        response["pauses"] = [
            {
                "id": pause.id,
                "reason_code": pause.reason_code,
                "reason": pause.reason,
                "started_at": pause.started_at,
                "ended_at": pause.ended_at,
                "business_minutes": pause.business_minutes,
                "start_status": pause.start_status,
                "end_status": pause.end_status,
            }
            for pause in db.scalars(
                select(TicketSlaPause)
                .where(TicketSlaPause.instance_id == item.id)
                .order_by(TicketSlaPause.started_at)
            ).all()
        ]
        response["timeline"] = [
            {
                "id": event.id,
                "target_id": event.target_id,
                "event_type": event.event_type,
                "actor_user_id": event.actor_user_id,
                "actor_name": event.actor_name,
                "message": event.message,
                "data": event.data_json,
                "created_at": event.created_at,
            }
            for event in db.scalars(
                select(TicketSlaTimeline)
                .where(TicketSlaTimeline.instance_id == item.id)
                .order_by(TicketSlaTimeline.created_at.desc())
                .limit(250)
            ).all()
        ]
    return response


def _commit_or_conflict(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc


@router.get("")
@router.get("/policies")
def list_sla_policies(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "sla.read")
    resolved_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(SlaPolicy)
    if resolved_tenant is not None:
        statement = statement.where(
            or_(
                SlaPolicy.tenant_id == resolved_tenant,
                SlaPolicy.tenant_id.is_(None),
            )
        )
    policies = db.scalars(
        statement.order_by(
            SlaPolicy.priority_order,
            SlaPolicy.priority,
            SlaPolicy.name,
        )
    ).all()
    return [_policy_response(db, item) for item in policies]


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def create_sla_policy(
    payload: PolicyCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.manage")
    tenant_id = _tenant_id(
        db,
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    assert tenant_id is not None
    if payload.calendar_id:
        _calendar(db, payload.calendar_id, tenant_id)
    targets = validate_targets(
        [item.model_dump() for item in payload.targets]
    )
    escalations = validate_escalations(
        [item.model_dump() for item in payload.escalations]
    )
    response_minutes = next(
        (
            int(item["minutes"])
            for item in targets
            if item["type"] == "RESPONSE"
        ),
        60,
    )
    resolution_minutes = next(
        (
            int(item["minutes"])
            for item in targets
            if item["type"] == "RESOLUTION"
        ),
        480,
    )
    item = SlaPolicy(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        priority=payload.priority.upper(),
        target_response_minutes=response_minutes,
        target_resolution_minutes=resolution_minutes,
        response_minutes=response_minutes,
        resolution_minutes=resolution_minutes,
        is_active=payload.is_active,
        status="active" if payload.is_active else "inactive",
        breach_count=0,
        calendar_id=payload.calendar_id,
        priority_order=payload.priority_order,
        scope_json=payload.scope,
        targets_json=targets,
        pause_statuses_json=[
            value.upper() for value in payload.pause_statuses
        ],
        pause_reasons_json=[
            value.upper() for value in payload.pause_reasons
        ],
        warning_percent=payload.warning_percent,
        escalations_json=escalations,
        version=1,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        request,
        current_user,
        action="sla.policy_created",
        entity_type="sla_policy",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"name": item.name, "priority": item.priority},
    )
    _commit_or_conflict(db, "SLA policy conflicts with existing data")
    db.refresh(item)
    return _policy_response(db, item)


@router.patch("/policies/{policy_id}")
def update_sla_policy(
    policy_id: str,
    payload: PolicyUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.manage")
    tenant_id = _tenant_id(db, current_user)
    item = _policy(db, policy_id, tenant_id)
    _assert_version(item.version, payload.expected_version, "SLA policy")
    updates = payload.model_dump(
        exclude_unset=True,
        exclude={"expected_version"},
    )
    if "calendar_id" in updates and updates["calendar_id"]:
        if item.tenant_id is None:
            raise HTTPException(
                status_code=422,
                detail="Global policy cannot use a tenant calendar",
            )
        _calendar(db, str(updates["calendar_id"]), item.tenant_id)
    if "targets" in updates:
        updates["targets_json"] = validate_targets(
            [
                value.model_dump() if isinstance(value, SlaTargetInput) else value
                for value in updates.pop("targets")
            ]
        )
    if "escalations" in updates:
        updates["escalations_json"] = validate_escalations(
            [
                value.model_dump()
                if isinstance(value, SlaEscalationInput)
                else value
                for value in updates.pop("escalations")
            ]
        )
    field_map = {
        "scope": "scope_json",
        "pause_statuses": "pause_statuses_json",
        "pause_reasons": "pause_reasons_json",
    }
    for source, target in field_map.items():
        if source in updates:
            updates[target] = updates.pop(source)
    if "priority" in updates:
        updates["priority"] = str(updates["priority"]).upper()
    for field in ("pause_statuses_json", "pause_reasons_json"):
        if field in updates:
            updates[field] = [str(value).upper() for value in updates[field]]
    if "is_active" in updates:
        updates["status"] = "active" if updates["is_active"] else "inactive"
    for field, value in updates.items():
        setattr(item, field, value)
    targets = validate_targets(item.targets_json or [])
    response_target = next(
        (value for value in targets if value["type"] == "RESPONSE"),
        None,
    )
    resolution_target = next(
        (value for value in targets if value["type"] == "RESOLUTION"),
        None,
    )
    if response_target:
        item.response_minutes = int(response_target["minutes"])
        item.target_response_minutes = item.response_minutes
    if resolution_target:
        item.resolution_minutes = int(resolution_target["minutes"])
        item.target_resolution_minutes = item.resolution_minutes
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="sla.policy_updated",
        entity_type="sla_policy",
        entity_id=item.id,
        tenant_id=item.tenant_id or "",
        metadata={"version": item.version},
    )
    _commit_or_conflict(db, "SLA policy conflicts with existing data")
    db.refresh(item)
    return _policy_response(db, item)


@router.get("/calendars")
def list_calendars(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "sla.read")
    resolved_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(SlaBusinessCalendar)
    if resolved_tenant:
        statement = statement.where(
            SlaBusinessCalendar.tenant_id == resolved_tenant
        )
    rows = db.scalars(
        statement.order_by(
            SlaBusinessCalendar.is_default.desc(),
            SlaBusinessCalendar.name,
        )
    ).all()
    return [_calendar_response(db, item, details=False) for item in rows]


@router.post("/calendars", status_code=status.HTTP_201_CREATED)
def create_calendar(
    payload: CalendarCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.manage")
    tenant_id = _tenant_id(
        db,
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    assert tenant_id is not None
    try:
        timezone = validate_timezone(payload.timezone)
        weekly_hours = validate_weekly_hours(payload.weekly_hours)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.is_default:
        for existing in db.scalars(
            select(SlaBusinessCalendar).where(
                SlaBusinessCalendar.tenant_id == tenant_id,
                SlaBusinessCalendar.is_default.is_(True),
            )
        ).all():
            existing.is_default = False
            existing.version += 1
    item = SlaBusinessCalendar(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        timezone=timezone,
        weekly_hours_json=weekly_hours,
        is_default=payload.is_default,
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
        action="sla.calendar_created",
        entity_type="sla_calendar",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"name": item.name, "timezone": item.timezone},
    )
    _commit_or_conflict(db, "Calendar name already exists")
    db.refresh(item)
    return _calendar_response(db, item)


@router.get("/calendars/{calendar_id}")
def get_calendar(
    calendar_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.read")
    tenant_id = _tenant_id(db, current_user)
    if tenant_id is None:
        item = db.get(SlaBusinessCalendar, calendar_id)
        if item is None:
            raise HTTPException(status_code=404, detail="SLA calendar not found")
    else:
        item = _calendar(db, calendar_id, tenant_id)
    return _calendar_response(db, item)


@router.patch("/calendars/{calendar_id}")
def update_calendar(
    calendar_id: str,
    payload: CalendarUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.manage")
    tenant_id = _tenant_id(db, current_user)
    if tenant_id is None:
        item = db.get(SlaBusinessCalendar, calendar_id)
        if item is None:
            raise HTTPException(status_code=404, detail="SLA calendar not found")
    else:
        item = _calendar(db, calendar_id, tenant_id)
    _assert_version(item.version, payload.expected_version, "SLA calendar")
    updates = payload.model_dump(
        exclude_unset=True,
        exclude={"expected_version"},
    )
    try:
        if "timezone" in updates:
            updates["timezone"] = validate_timezone(str(updates["timezone"]))
        if "weekly_hours" in updates:
            updates["weekly_hours_json"] = validate_weekly_hours(
                updates.pop("weekly_hours")
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updates.get("is_default"):
        for existing in db.scalars(
            select(SlaBusinessCalendar).where(
                SlaBusinessCalendar.tenant_id == item.tenant_id,
                SlaBusinessCalendar.is_default.is_(True),
                SlaBusinessCalendar.id != item.id,
            )
        ).all():
            existing.is_default = False
            existing.version += 1
    for field, value in updates.items():
        setattr(item, field, value)
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="sla.calendar_updated",
        entity_type="sla_calendar",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"version": item.version},
    )
    _commit_or_conflict(db, "Calendar update conflicts with existing data")
    db.refresh(item)
    return _calendar_response(db, item)


@router.put("/calendars/{calendar_id}/exceptions/{exception_date}")
def upsert_calendar_exception(
    calendar_id: str,
    exception_date: date,
    payload: CalendarExceptionInput,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.manage")
    tenant_id = _tenant_id(db, current_user)
    if tenant_id is None:
        calendar = db.get(SlaBusinessCalendar, calendar_id)
        if calendar is None:
            raise HTTPException(status_code=404, detail="SLA calendar not found")
    else:
        calendar = _calendar(db, calendar_id, tenant_id)
    if payload.exception_date != exception_date:
        raise HTTPException(status_code=422, detail="Exception dates do not match")
    try:
        intervals = validate_intervals(payload.intervals)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.kind == "HOLIDAY" and intervals:
        raise HTTPException(
            status_code=422,
            detail="Holiday cannot contain working intervals",
        )
    item = db.scalar(
        select(SlaCalendarException).where(
            SlaCalendarException.calendar_id == calendar.id,
            SlaCalendarException.exception_date == exception_date,
        )
    )
    action = "sla.calendar_exception_updated"
    if item is None:
        item = SlaCalendarException(
            id=str(uuid.uuid4()),
            tenant_id=calendar.tenant_id,
            calendar_id=calendar.id,
            exception_date=exception_date,
            kind=payload.kind,
            name=payload.name,
            intervals_json=intervals,
            created_by_id=current_user.id,
        )
        db.add(item)
        action = "sla.calendar_exception_created"
    else:
        item.kind = payload.kind
        item.name = payload.name
        item.intervals_json = intervals
    calendar.version += 1
    _audit(
        db,
        request,
        current_user,
        action=action,
        entity_type="sla_calendar",
        entity_id=calendar.id,
        tenant_id=calendar.tenant_id,
        metadata={"exception_date": exception_date.isoformat()},
    )
    _commit_or_conflict(db, "Calendar exception already exists")
    return _calendar_response(db, calendar)


@router.delete(
    "/calendars/{calendar_id}/exceptions/{exception_date}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_calendar_exception(
    calendar_id: str,
    exception_date: date,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    require_permissions(current_user, "sla.manage")
    tenant_id = _tenant_id(db, current_user)
    if tenant_id is None:
        calendar = db.get(SlaBusinessCalendar, calendar_id)
        if calendar is None:
            raise HTTPException(status_code=404, detail="SLA calendar not found")
    else:
        calendar = _calendar(db, calendar_id, tenant_id)
    item = db.scalar(
        select(SlaCalendarException).where(
            SlaCalendarException.calendar_id == calendar.id,
            SlaCalendarException.exception_date == exception_date,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Calendar exception not found")
    db.delete(item)
    calendar.version += 1
    _audit(
        db,
        request,
        current_user,
        action="sla.calendar_exception_deleted",
        entity_type="sla_calendar",
        entity_id=calendar.id,
        tenant_id=calendar.tenant_id,
        metadata={"exception_date": exception_date.isoformat()},
    )
    db.commit()


@router.get("/overview")
def get_sla_overview(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.read")
    resolved_tenant = _tenant_id(db, current_user, tenant_id)
    legacy = summarize_sla_overview(db, resolved_tenant)
    instance_query = select(
        TicketSlaInstance.status,
        func.count(TicketSlaInstance.id),
    ).where(TicketSlaInstance.is_current.is_(True))
    target_query = select(
        TicketSlaTarget.status,
        func.count(TicketSlaTarget.id),
    ).join(
        TicketSlaInstance,
        TicketSlaInstance.id == TicketSlaTarget.instance_id,
    ).where(TicketSlaInstance.is_current.is_(True))
    if resolved_tenant:
        instance_query = instance_query.where(
            TicketSlaInstance.tenant_id == resolved_tenant
        )
        target_query = target_query.where(
            TicketSlaTarget.tenant_id == resolved_tenant
        )
    instance_counts = dict(
        db.execute(instance_query.group_by(TicketSlaInstance.status)).all()
    )
    target_counts = dict(
        db.execute(target_query.group_by(TicketSlaTarget.status)).all()
    )
    return {
        **legacy,
        "active_instances": instance_counts.get("ACTIVE", 0),
        "paused_instances": instance_counts.get("PAUSED", 0),
        "breached_instances": instance_counts.get("BREACHED", 0),
        "warning_targets": target_counts.get("WARNING", 0),
        "breached_targets": target_counts.get("BREACHED", 0),
        "met_targets": target_counts.get("MET", 0),
    }


@router.get("/queue")
def list_sla_queue(
    tenant_id: str | None = Query(default=None),
    states: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "sla.read")
    resolved_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(TicketSlaInstance).where(
        TicketSlaInstance.is_current.is_(True)
    )
    if resolved_tenant:
        statement = statement.where(
            TicketSlaInstance.tenant_id == resolved_tenant
        )
    if states:
        statement = statement.where(
            TicketSlaInstance.status.in_([value.upper() for value in states])
        )
    rows = db.scalars(
        statement.order_by(
            TicketSlaInstance.status.desc(),
            TicketSlaInstance.started_at.desc(),
        ).limit(limit)
    ).all()
    return [_instance_response(db, item) for item in rows]


@router.get("/instances/{instance_id}")
def get_sla_instance(
    instance_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.read")
    tenant_id = _tenant_id(db, current_user)
    return _instance_response(
        db,
        _instance(db, instance_id, tenant_id),
        details=True,
    )


@router.get("/tickets/{ticket_id}")
def get_ticket_sla(
    ticket_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.read")
    tenant_id = _tenant_id(db, current_user)
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or (
        tenant_id is not None and ticket.tenant_id != tenant_id
    ):
        raise HTTPException(status_code=404, detail="Ticket not found")
    item = current_instance(db, ticket.id)
    if item is None:
        raise HTTPException(status_code=404, detail="Ticket has no SLA instance")
    return _instance_response(db, item, details=True)


@router.post("/instances/{instance_id}/pause")
def pause_sla(
    instance_id: str,
    payload: PauseRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.manage")
    tenant_id = _tenant_id(db, current_user)
    item = _instance(db, instance_id, tenant_id)
    _assert_version(item.version, payload.expected_version, "SLA instance")
    ticket = db.get(Ticket, item.ticket_id)
    try:
        pause_instance(
            db,
            item,
            reason_code=payload.reason_code,
            reason=payload.reason,
            actor=_actor(db, current_user),
            ticket_status=ticket.status if ticket else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if ticket:
        ticket.sla_status = "PAUSED"
    _audit(
        db,
        request,
        current_user,
        action="sla.instance_paused",
        entity_type="sla_instance",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason_code": payload.reason_code.upper()},
    )
    db.commit()
    db.refresh(item)
    return _instance_response(db, item, details=True)


@router.post("/instances/{instance_id}/resume")
def resume_sla(
    instance_id: str,
    payload: VersionRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.manage")
    tenant_id = _tenant_id(db, current_user)
    item = _instance(db, instance_id, tenant_id)
    _assert_version(item.version, payload.expected_version, "SLA instance")
    ticket = db.get(Ticket, item.ticket_id)
    try:
        extended = resume_instance(
            db,
            item,
            actor=_actor(db, current_user),
            ticket_status=ticket.status if ticket else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="sla.instance_resumed",
        entity_type="sla_instance",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"extended_business_minutes": extended},
    )
    db.commit()
    db.refresh(item)
    return _instance_response(db, item, details=True)


@router.post("/instances/{instance_id}/targets/{target_id}/complete")
def mark_sla_target_complete(
    instance_id: str,
    target_id: str,
    payload: CompleteTargetRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.manage")
    tenant_id = _tenant_id(db, current_user)
    item = _instance(db, instance_id, tenant_id)
    target = db.get(TicketSlaTarget, target_id)
    if target is None or target.instance_id != item.id:
        raise HTTPException(status_code=404, detail="SLA target not found")
    _assert_version(target.version, payload.expected_version, "SLA target")
    complete_target(
        db,
        item,
        target.target_type,
        owner_ref=target.owner_ref,
        actor=_actor(db, current_user),
        reason=payload.reason,
    )
    _audit(
        db,
        request,
        current_user,
        action="sla.target_completed",
        entity_type="sla_target",
        entity_id=target.id,
        tenant_id=item.tenant_id,
        metadata={"target_type": target.target_type},
    )
    db.commit()
    db.refresh(item)
    return _instance_response(db, item, details=True)


@router.post("/tickets/{ticket_id}/recalculate")
def recalculate_ticket_sla(
    ticket_id: str,
    payload: VersionRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.manage")
    tenant_id = _tenant_id(db, current_user)
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or (
        tenant_id is not None and ticket.tenant_id != tenant_id
    ):
        raise HTTPException(status_code=404, detail="Ticket not found")
    existing = current_instance(db, ticket.id)
    if existing is not None:
        _assert_version(
            existing.version,
            payload.expected_version,
            "SLA instance",
        )
    elif payload.expected_version != 1:
        raise HTTPException(status_code=409, detail="SLA instance does not exist")
    item = ensure_ticket_sla_instance(
        db,
        ticket,
        actor=_actor(db, current_user),
        force_recalculate=True,
        reason="Manual recalculation",
    )
    if item is None:
        raise HTTPException(
            status_code=422,
            detail="No active SLA policy matches this ticket",
        )
    _audit(
        db,
        request,
        current_user,
        action="sla.ticket_recalculated",
        entity_type="ticket",
        entity_id=ticket.id,
        tenant_id=item.tenant_id,
        metadata={"instance_id": item.id, "policy_id": item.policy_id},
    )
    db.commit()
    db.refresh(item)
    return _instance_response(db, item, details=True)


@router.post("/evaluate")
def evaluate_sla(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "sla.manage")
    resolved_tenant = _tenant_id(db, current_user, tenant_id)
    changed = evaluate_tenant_sla(db, resolved_tenant)
    db.commit()
    return {
        "evaluated_at": datetime.now(UTC),
        "changed_count": len(changed),
        "target_ids": [item.id for item in changed],
    }


@router.get("/breaches")
def list_sla_breaches(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "sla.read")
    resolved_tenant = _tenant_id(db, current_user, tenant_id)
    statement = (
        select(Ticket, Tenant.name)
        .join(Tenant, Tenant.id == Ticket.tenant_id, isouter=True)
        .where(Ticket.sla_status == "BREACHED")
    )
    if resolved_tenant:
        statement = statement.where(Ticket.tenant_id == resolved_tenant)
    rows = db.execute(
        statement.order_by(Ticket.updated_at.desc(), Ticket.created_at.desc())
    ).all()
    return [
        {
            "ticket_id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "priority": ticket.priority,
            "status": ticket.status,
            "sla_status": ticket.sla_status,
            "response_due_at": ticket.response_due_at,
            "resolution_due_at": ticket.resolution_due_at,
            "tenant_name": tenant_name,
        }
        for ticket, tenant_name in rows
    ]
