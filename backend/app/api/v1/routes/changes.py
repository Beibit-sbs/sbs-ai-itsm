from __future__ import annotations

import hashlib
import json
import struct
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.change_approval import ChangeApproval
from app.models.change_history import ChangeHistory
from app.models.change_link import ChangeAssetLink, ChangeTicketLink
from app.models.change_request import ChangeRequest
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.user import User
from app.services.audit import log_audit
from app.services.change_governance import (
    assess_change_window,
    pir_for_change,
    required_tasks_complete,
    update_standard_model_outcome,
)
from app.services.rbac import require_permissions


router = APIRouter(prefix="/changes")

ChangeType = Literal["STANDARD", "NORMAL", "EMERGENCY"]
ImpactLevel = Literal["LOW", "MEDIUM", "HIGH", "ENTERPRISE"]
Decision = Literal["APPROVED", "REJECTED"]
TransitionAction = Literal[
    "SUBMIT",
    "REQUEST_APPROVAL",
    "SCHEDULE",
    "START",
    "COMPLETE",
    "CLOSE",
    "FAIL",
    "ROLLBACK",
    "CANCEL",
]

EDITABLE_STATUSES = {"DRAFT", "ASSESSMENT", "REJECTED"}
ACTIVE_WINDOW_STATUSES = {"SCHEDULED", "IMPLEMENTING"}
REQUIRED_ASSESSMENT_FIELDS = (
    "business_justification",
    "implementation_plan",
    "test_plan",
    "rollback_plan",
    "validation_plan",
)


class ChangeCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10, max_length=20_000)
    change_type: ChangeType = "NORMAL"
    service_name: str | None = Field(default=None, max_length=200)
    environment: str = Field(default="PRODUCTION", min_length=2, max_length=80)
    impact_level: ImpactLevel = "MEDIUM"
    likelihood: int = Field(default=2, ge=1, le=5)
    business_justification: str | None = Field(default=None, max_length=10_000)
    implementation_plan: str | None = Field(default=None, max_length=20_000)
    test_plan: str | None = Field(default=None, max_length=20_000)
    rollback_plan: str | None = Field(default=None, max_length=20_000)
    validation_plan: str | None = Field(default=None, max_length=20_000)
    owner_id: str | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    outage_required: bool = False
    outage_minutes: int = Field(default=0, ge=0, le=100_800)
    asset_ids: list[str] = Field(default_factory=list, max_length=100)
    ticket_ids: list[str] = Field(default_factory=list, max_length=100)


class ChangePatchRequest(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = Field(default=None, min_length=10, max_length=20_000)
    change_type: ChangeType | None = None
    service_name: str | None = Field(default=None, max_length=200)
    environment: str | None = Field(default=None, min_length=2, max_length=80)
    impact_level: ImpactLevel | None = None
    likelihood: int | None = Field(default=None, ge=1, le=5)
    business_justification: str | None = Field(default=None, max_length=10_000)
    implementation_plan: str | None = Field(default=None, max_length=20_000)
    test_plan: str | None = Field(default=None, max_length=20_000)
    rollback_plan: str | None = Field(default=None, max_length=20_000)
    validation_plan: str | None = Field(default=None, max_length=20_000)
    owner_id: str | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    outage_required: bool | None = None
    outage_minutes: int | None = Field(default=None, ge=0, le=100_800)
    asset_ids: list[str] | None = Field(default=None, max_length=100)
    ticket_ids: list[str] | None = Field(default=None, max_length=100)


class ChangeVersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class ChangeDecisionRequest(ChangeVersionRequest):
    decision: Decision
    comment: str = Field(min_length=3, max_length=5_000)


class ChangeTransitionRequest(ChangeVersionRequest):
    action: TransitionAction
    comment: str | None = Field(default=None, max_length=10_000)
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    blackout_override_reason: str | None = Field(default=None, max_length=5_000)


class ChangeBaseResponse(BaseModel):
    id: str
    tenant_id: str
    change_number: str
    title: str
    description: str
    change_type: str
    status: str
    service_name: str | None
    environment: str
    standard_model_id: str | None
    impact_level: str
    likelihood: int
    risk_score: int
    risk_level: str
    requested_by_id: str | None
    requested_by_name: str
    requested_by_email: str
    owner_id: str | None
    owner_name: str | None
    cab_required: bool
    approval_status: str
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    actual_start_at: datetime | None
    actual_end_at: datetime | None
    outage_required: bool
    outage_minutes: int
    failure_reason: str | None
    post_implementation_review: str | None
    validation_status: str
    pir_status: str
    outcome: str | None
    blackout_override_reason: str | None
    version: int
    asset_count: int
    ticket_count: int
    created_at: datetime
    updated_at: datetime


class LinkedAssetResponse(BaseModel):
    id: str
    asset_tag: str
    name: str
    status: str
    location: str


class LinkedTicketResponse(BaseModel):
    id: str
    ticket_number: str | None
    title: str
    status: str
    priority: str


class ChangeApprovalResponse(BaseModel):
    id: str
    approver_id: str | None
    approver_name: str
    approver_email: str
    decision: str
    decision_comment: str
    decided_at: datetime


class ChangeHistoryResponse(BaseModel):
    id: str
    actor_name: str
    actor_email: str
    event_type: str
    from_status: str | None
    to_status: str | None
    message: str
    metadata: dict[str, object]
    created_at: datetime


class ChangeDetailResponse(ChangeBaseResponse):
    business_justification: str | None
    implementation_plan: str | None
    test_plan: str | None
    rollback_plan: str | None
    validation_plan: str | None
    assets: list[LinkedAssetResponse]
    tickets: list[LinkedTicketResponse]
    approvals: list[ChangeApprovalResponse]
    history: list[ChangeHistoryResponse]


class ChangePageResponse(BaseModel):
    items: list[ChangeBaseResponse]
    total: int
    page: int
    page_size: int


class ChangeSummaryResponse(BaseModel):
    open_changes: int
    awaiting_approval: int
    scheduled_next_7_days: int
    high_risk_open: int
    failed_last_30_days: int


def _now() -> datetime:
    return datetime.now(UTC)


def _resolve_tenant_id(db: Session, current_user: AuthUserResponse) -> str:
    if current_user.tenant_id:
        return current_user.tenant_id
    tenant = db.scalar(
        select(Tenant)
        .where(func.lower(Tenant.status) == "active")
        .order_by(Tenant.created_at)
    )
    if tenant is None:
        raise HTTPException(status_code=422, detail="No active tenant is available")
    return tenant.id


def _get_change(
    db: Session,
    change_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> ChangeRequest:
    statement = select(ChangeRequest).where(ChangeRequest.id == change_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    change = db.scalar(statement)
    if change is None:
        raise HTTPException(status_code=404, detail="Change request not found")
    if current_user.role != "saas_root" and change.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Change request not found")
    return change


def _assert_version(change: ChangeRequest, expected_version: int) -> None:
    if change.version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Change was updated by another operator; current version is {change.version}",
        )


def _risk_score(
    *,
    impact_level: str,
    likelihood: int,
    outage_required: bool,
    change_type: str,
    asset_count: int,
) -> tuple[int, str, bool]:
    impact_weight = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "ENTERPRISE": 4}[impact_level]
    score = impact_weight * likelihood
    score += 2 if outage_required else 0
    score += 3 if change_type == "EMERGENCY" else 0
    score += min(asset_count, 3)
    if score <= 5:
        level = "LOW"
    elif score <= 10:
        level = "MEDIUM"
    elif score <= 16:
        level = "HIGH"
    else:
        level = "CRITICAL"
    cab_required = change_type != "STANDARD" or level in {"HIGH", "CRITICAL"} or outage_required
    return score, level, cab_required


def _clean_ids(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in values if item.strip()))


def _validate_linked_records(
    db: Session,
    tenant_id: str,
    asset_ids: list[str],
    ticket_ids: list[str],
) -> None:
    if asset_ids:
        assets = db.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()
        if len(assets) != len(asset_ids) or any(item.tenant_id != tenant_id for item in assets):
            raise HTTPException(status_code=422, detail="One or more assets are unavailable")
    if ticket_ids:
        tickets = db.scalars(select(Ticket).where(Ticket.id.in_(ticket_ids))).all()
        if len(tickets) != len(ticket_ids) or any(item.tenant_id != tenant_id for item in tickets):
            raise HTTPException(status_code=422, detail="One or more tickets are unavailable")


def _replace_links(
    db: Session,
    change: ChangeRequest,
    *,
    asset_ids: list[str] | None = None,
    ticket_ids: list[str] | None = None,
) -> None:
    if asset_ids is not None:
        db.execute(delete(ChangeAssetLink).where(ChangeAssetLink.change_id == change.id))
        for asset_id in asset_ids:
            db.add(
                ChangeAssetLink(
                    id=str(uuid.uuid4()),
                    tenant_id=change.tenant_id,
                    change_id=change.id,
                    asset_id=asset_id,
                )
            )
    if ticket_ids is not None:
        db.execute(delete(ChangeTicketLink).where(ChangeTicketLink.change_id == change.id))
        for ticket_id in ticket_ids:
            db.add(
                ChangeTicketLink(
                    id=str(uuid.uuid4()),
                    tenant_id=change.tenant_id,
                    change_id=change.id,
                    ticket_id=ticket_id,
                )
            )


def _record_history(
    db: Session,
    change: ChangeRequest,
    current_user: AuthUserResponse,
    *,
    event_type: str,
    message: str,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        ChangeHistory(
            id=str(uuid.uuid4()),
            tenant_id=change.tenant_id,
            change_id=change.id,
            actor_user_id=current_user.id,
            actor_name=current_user.full_name,
            actor_email=current_user.email,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            message=message,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
        )
    )


def _audit_request(
    db: Session,
    request: Request,
    change: ChangeRequest,
    current_user: AuthUserResponse,
    action: str,
    metadata: dict[str, object] | None = None,
) -> None:
    log_audit(
        db,
        action=action,
        entity_type="change_request",
        entity_id=change.id,
        actor_email=current_user.email,
        tenant_id=change.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"change_number": change.change_number, **(metadata or {})},
    )


def _base_response(
    change: ChangeRequest,
    *,
    asset_count: int,
    ticket_count: int,
) -> ChangeBaseResponse:
    return ChangeBaseResponse(
        **{
            column: getattr(change, column)
            for column in ChangeBaseResponse.model_fields
            if column not in {"asset_count", "ticket_count"}
        },
        asset_count=asset_count,
        ticket_count=ticket_count,
    )


def _counts_for_changes(
    db: Session, change_ids: list[str]
) -> tuple[dict[str, int], dict[str, int]]:
    if not change_ids:
        return {}, {}
    asset_counts = dict(
        db.execute(
            select(ChangeAssetLink.change_id, func.count(ChangeAssetLink.id))
            .where(ChangeAssetLink.change_id.in_(change_ids))
            .group_by(ChangeAssetLink.change_id)
        ).all()
    )
    ticket_counts = dict(
        db.execute(
            select(ChangeTicketLink.change_id, func.count(ChangeTicketLink.id))
            .where(ChangeTicketLink.change_id.in_(change_ids))
            .group_by(ChangeTicketLink.change_id)
        ).all()
    )
    return asset_counts, ticket_counts


def _detail_response(db: Session, change: ChangeRequest) -> ChangeDetailResponse:
    assets = db.scalars(
        select(Asset)
        .join(ChangeAssetLink, ChangeAssetLink.asset_id == Asset.id)
        .where(ChangeAssetLink.change_id == change.id)
        .order_by(Asset.asset_tag)
    ).all()
    tickets = db.scalars(
        select(Ticket)
        .join(ChangeTicketLink, ChangeTicketLink.ticket_id == Ticket.id)
        .where(ChangeTicketLink.change_id == change.id)
        .order_by(Ticket.created_at.desc())
    ).all()
    approvals = db.scalars(
        select(ChangeApproval)
        .where(ChangeApproval.change_id == change.id)
        .order_by(ChangeApproval.decided_at.desc())
    ).all()
    history = db.scalars(
        select(ChangeHistory)
        .where(ChangeHistory.change_id == change.id)
        .order_by(ChangeHistory.created_at.desc(), ChangeHistory.id.desc())
    ).all()
    base = _base_response(change, asset_count=len(assets), ticket_count=len(tickets))
    return ChangeDetailResponse(
        **base.model_dump(),
        business_justification=change.business_justification,
        implementation_plan=change.implementation_plan,
        test_plan=change.test_plan,
        rollback_plan=change.rollback_plan,
        validation_plan=change.validation_plan,
        assets=[
            LinkedAssetResponse(
                id=item.id,
                asset_tag=item.asset_tag,
                name=item.name,
                status=item.status,
                location=item.location,
            )
            for item in assets
        ],
        tickets=[
            LinkedTicketResponse(
                id=item.id,
                ticket_number=item.ticket_number,
                title=item.title,
                status=item.status,
                priority=item.priority,
            )
            for item in tickets
        ],
        approvals=[
            ChangeApprovalResponse(
                id=item.id,
                approver_id=item.approver_id,
                approver_name=item.approver_name,
                approver_email=item.approver_email,
                decision=item.decision,
                decision_comment=item.decision_comment,
                decided_at=item.decided_at,
            )
            for item in approvals
        ],
        history=[
            ChangeHistoryResponse(
                id=item.id,
                actor_name=item.actor_name,
                actor_email=item.actor_email,
                event_type=item.event_type,
                from_status=item.from_status,
                to_status=item.to_status,
                message=item.message,
                metadata=_parse_metadata(item.metadata_json),
                created_at=item.created_at,
            )
            for item in history
        ],
    )


def _parse_metadata(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _owner(db: Session, tenant_id: str, owner_id: str | None) -> tuple[str | None, str | None]:
    if owner_id is None:
        return None, None
    owner = db.get(User, owner_id)
    if owner is None or owner.tenant_id != tenant_id or not owner.is_active:
        raise HTTPException(status_code=422, detail="Change owner is unavailable")
    return owner.id, owner.full_name


def _validate_window(start_at: datetime | None, end_at: datetime | None) -> None:
    if start_at is None or end_at is None:
        raise HTTPException(status_code=422, detail="Planned start and end are required")
    if end_at <= start_at:
        raise HTTPException(status_code=422, detail="Planned end must be after planned start")


def _lock_asset_windows(db: Session, tenant_id: str, asset_ids: list[str]) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    keys = asset_ids or ["tenant-window"]
    for asset_id in sorted(keys):
        digest = hashlib.sha256(f"{tenant_id}:{asset_id}".encode()).digest()[:8]
        lock_key = struct.unpack(">q", digest)[0]
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})


def _window_conflicts(
    db: Session,
    change: ChangeRequest,
    asset_ids: list[str],
) -> list[dict[str, str]]:
    if not asset_ids or change.planned_start_at is None or change.planned_end_at is None:
        return []
    rows = db.execute(
        select(ChangeRequest.change_number, Asset.asset_tag)
        .join(ChangeAssetLink, ChangeAssetLink.change_id == ChangeRequest.id)
        .join(Asset, Asset.id == ChangeAssetLink.asset_id)
        .where(
            ChangeRequest.id != change.id,
            ChangeRequest.tenant_id == change.tenant_id,
            ChangeRequest.status.in_(ACTIVE_WINDOW_STATUSES),
            ChangeRequest.planned_start_at < change.planned_end_at,
            ChangeRequest.planned_end_at > change.planned_start_at,
            ChangeAssetLink.asset_id.in_(asset_ids),
        )
        .order_by(ChangeRequest.change_number, Asset.asset_tag)
    ).all()
    return [
        {"change_number": change_number, "asset_tag": asset_tag}
        for change_number, asset_tag in rows
    ]


@router.get("", response_model=ChangePageResponse)
def list_changes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    change_status: str | None = Query(default=None, alias="status", max_length=32),
    change_type: str | None = Query(default=None, max_length=24),
    risk_level: str | None = Query(default=None, max_length=24),
    tenant_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ChangePageResponse:
    require_permissions(current_user, "changes.read")
    filters = []
    if current_user.role == "saas_root":
        if tenant_id:
            tenant = db.get(Tenant, tenant_id)
            if tenant is None:
                raise HTTPException(status_code=404, detail="Tenant not found")
            filters.append(ChangeRequest.tenant_id == tenant_id)
    else:
        if tenant_id and tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")
        filters.append(ChangeRequest.tenant_id == current_user.tenant_id)
    if change_status:
        filters.append(ChangeRequest.status == change_status.upper())
    if change_type:
        filters.append(ChangeRequest.change_type == change_type.upper())
    if risk_level:
        filters.append(ChangeRequest.risk_level == risk_level.upper())
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                ChangeRequest.change_number.ilike(pattern),
                ChangeRequest.title.ilike(pattern),
                ChangeRequest.service_name.ilike(pattern),
            )
        )
    total = int(db.scalar(select(func.count(ChangeRequest.id)).where(*filters)) or 0)
    changes = db.scalars(
        select(ChangeRequest)
        .where(*filters)
        .order_by(ChangeRequest.updated_at.desc(), ChangeRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    asset_counts, ticket_counts = _counts_for_changes(db, [item.id for item in changes])
    return ChangePageResponse(
        items=[
            _base_response(
                item,
                asset_count=asset_counts.get(item.id, 0),
                ticket_count=ticket_counts.get(item.id, 0),
            )
            for item in changes
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=ChangeSummaryResponse)
def change_summary(
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ChangeSummaryResponse:
    require_permissions(current_user, "changes.read")
    tenant_filter = []
    if current_user.role != "saas_root":
        tenant_filter.append(ChangeRequest.tenant_id == current_user.tenant_id)
    now = _now()

    def count(*extra) -> int:
        return int(
            db.scalar(select(func.count(ChangeRequest.id)).where(*tenant_filter, *extra)) or 0
        )

    return ChangeSummaryResponse(
        open_changes=count(
            ChangeRequest.status.notin_({"COMPLETED", "CANCELLED", "ROLLED_BACK"})
        ),
        awaiting_approval=count(ChangeRequest.status == "APPROVAL_PENDING"),
        scheduled_next_7_days=count(
            ChangeRequest.status == "SCHEDULED",
            ChangeRequest.planned_start_at >= now,
            ChangeRequest.planned_start_at < now + timedelta(days=7),
        ),
        high_risk_open=count(
            ChangeRequest.risk_level.in_({"HIGH", "CRITICAL"}),
            ChangeRequest.status.notin_({"COMPLETED", "CANCELLED", "ROLLED_BACK"}),
        ),
        failed_last_30_days=count(
            ChangeRequest.status == "FAILED",
            ChangeRequest.updated_at >= now - timedelta(days=30),
        ),
    )


@router.get("/{change_id}", response_model=ChangeDetailResponse)
def get_change(
    change_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ChangeDetailResponse:
    require_permissions(current_user, "changes.read")
    return _detail_response(db, _get_change(db, change_id, current_user))


@router.post("", response_model=ChangeDetailResponse, status_code=status.HTTP_201_CREATED)
def create_change(
    payload: ChangeCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ChangeDetailResponse:
    require_permissions(current_user, "changes.create")
    tenant_id = _resolve_tenant_id(db, current_user)
    asset_ids = _clean_ids(payload.asset_ids)
    ticket_ids = _clean_ids(payload.ticket_ids)
    _validate_linked_records(db, tenant_id, asset_ids, ticket_ids)
    _validate_optional_window(payload.planned_start_at, payload.planned_end_at)
    owner_id, owner_name = _owner(db, tenant_id, payload.owner_id)
    if owner_id is None:
        owner_id, owner_name = current_user.id, current_user.full_name
    score, risk_level, cab_required = _risk_score(
        impact_level=payload.impact_level,
        likelihood=payload.likelihood,
        outage_required=payload.outage_required,
        change_type=payload.change_type,
        asset_count=len(asset_ids),
    )
    change = ChangeRequest(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        change_number=f"CHG-{_now().year}-{uuid.uuid4().hex[:8].upper()}",
        title=payload.title.strip(),
        description=payload.description.strip(),
        change_type=payload.change_type,
        status="DRAFT",
        service_name=(payload.service_name or "").strip() or None,
        environment=payload.environment.upper(),
        impact_level=payload.impact_level,
        likelihood=payload.likelihood,
        risk_score=score,
        risk_level=risk_level,
        business_justification=_clean_text(payload.business_justification),
        implementation_plan=_clean_text(payload.implementation_plan),
        test_plan=_clean_text(payload.test_plan),
        rollback_plan=_clean_text(payload.rollback_plan),
        validation_plan=_clean_text(payload.validation_plan),
        requested_by_id=current_user.id,
        requested_by_name=current_user.full_name,
        requested_by_email=current_user.email,
        owner_id=owner_id,
        owner_name=owner_name,
        cab_required=cab_required,
        approval_status="NOT_REQUESTED",
        planned_start_at=payload.planned_start_at,
        planned_end_at=payload.planned_end_at,
        outage_required=payload.outage_required,
        outage_minutes=payload.outage_minutes if payload.outage_required else 0,
        validation_status="NOT_STARTED",
        pir_status="NOT_REQUIRED",
        version=1,
    )
    db.add(change)
    db.flush()
    _replace_links(db, change, asset_ids=asset_ids, ticket_ids=ticket_ids)
    _record_history(
        db,
        change,
        current_user,
        event_type="CREATED",
        message="Change request created as draft",
        to_status="DRAFT",
        metadata={"risk_score": score, "risk_level": risk_level},
    )
    _audit_request(db, request, change, current_user, "changes.create")
    db.commit()
    db.refresh(change)
    return _detail_response(db, change)


def _validate_optional_window(start_at: datetime | None, end_at: datetime | None) -> None:
    if (start_at is None) != (end_at is None):
        raise HTTPException(status_code=422, detail="Planned start and end must be provided together")
    if start_at is not None and end_at is not None and end_at <= start_at:
        raise HTTPException(status_code=422, detail="Planned end must be after planned start")


def _clean_text(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


@router.patch("/{change_id}", response_model=ChangeDetailResponse)
def patch_change(
    change_id: str,
    payload: ChangePatchRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ChangeDetailResponse:
    require_permissions(current_user, "changes.update")
    change = _get_change(db, change_id, current_user, lock=True)
    _assert_version(change, payload.expected_version)
    if change.status not in EDITABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Change is no longer editable")
    updates = payload.model_dump(exclude_unset=True)
    updates.pop("expected_version", None)
    asset_ids_raw = updates.pop("asset_ids", None)
    ticket_ids_raw = updates.pop("ticket_ids", None)
    asset_ids = _clean_ids(asset_ids_raw) if asset_ids_raw is not None else None
    ticket_ids = _clean_ids(ticket_ids_raw) if ticket_ids_raw is not None else None
    current_asset_ids = db.scalars(
        select(ChangeAssetLink.asset_id).where(ChangeAssetLink.change_id == change.id)
    ).all()
    current_ticket_ids = db.scalars(
        select(ChangeTicketLink.ticket_id).where(ChangeTicketLink.change_id == change.id)
    ).all()
    final_asset_ids = asset_ids if asset_ids is not None else list(current_asset_ids)
    final_ticket_ids = ticket_ids if ticket_ids is not None else list(current_ticket_ids)
    _validate_linked_records(db, change.tenant_id, final_asset_ids, final_ticket_ids)
    start_at = updates.get("planned_start_at", change.planned_start_at)
    end_at = updates.get("planned_end_at", change.planned_end_at)
    _validate_optional_window(start_at, end_at)
    if "owner_id" in updates:
        owner_id, owner_name = _owner(db, change.tenant_id, updates.pop("owner_id"))
        change.owner_id = owner_id
        change.owner_name = owner_name
    text_fields = {
        "service_name",
        "business_justification",
        "implementation_plan",
        "test_plan",
        "rollback_plan",
        "validation_plan",
    }
    for field, value in updates.items():
        if field == "environment" and value is not None:
            value = value.strip().upper()
        elif field in text_fields:
            value = _clean_text(value)
        elif field in {"title", "description"} and value is not None:
            value = value.strip()
        setattr(change, field, value)
    if not change.outage_required:
        change.outage_minutes = 0
    score, risk_level, cab_required = _risk_score(
        impact_level=change.impact_level,
        likelihood=change.likelihood,
        outage_required=change.outage_required,
        change_type=change.change_type,
        asset_count=len(final_asset_ids),
    )
    change.risk_score = score
    change.risk_level = risk_level
    change.cab_required = cab_required
    change.version += 1
    _replace_links(db, change, asset_ids=asset_ids, ticket_ids=ticket_ids)
    _record_history(
        db,
        change,
        current_user,
        event_type="UPDATED",
        message="Change assessment updated",
        metadata={"risk_score": score, "risk_level": risk_level},
    )
    _audit_request(db, request, change, current_user, "changes.update")
    db.commit()
    db.refresh(change)
    return _detail_response(db, change)


@router.post("/{change_id}/decisions", response_model=ChangeDetailResponse)
def decide_change(
    change_id: str,
    payload: ChangeDecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ChangeDetailResponse:
    require_permissions(current_user, "changes.approve")
    change = _get_change(db, change_id, current_user, lock=True)
    _assert_version(change, payload.expected_version)
    if change.status != "APPROVAL_PENDING" or change.approval_status != "PENDING":
        raise HTTPException(status_code=409, detail="Change is not awaiting a CAB decision")
    if change.requested_by_id == current_user.id or (
        change.requested_by_email.lower() == current_user.email.lower()
    ):
        raise HTTPException(status_code=403, detail="Requesters cannot approve their own changes")
    decided_at = _now()
    db.add(
        ChangeApproval(
            id=str(uuid.uuid4()),
            tenant_id=change.tenant_id,
            change_id=change.id,
            approver_id=current_user.id,
            approver_name=current_user.full_name,
            approver_email=current_user.email,
            decision=payload.decision,
            decision_comment=payload.comment.strip(),
            decided_at=decided_at,
        )
    )
    previous = change.status
    change.approval_status = payload.decision
    change.status = "APPROVED" if payload.decision == "APPROVED" else "REJECTED"
    change.version += 1
    _record_history(
        db,
        change,
        current_user,
        event_type="CAB_DECISION",
        message=f"CAB decision: {payload.decision}",
        from_status=previous,
        to_status=change.status,
        metadata={"comment": payload.comment.strip()},
    )
    _audit_request(
        db,
        request,
        change,
        current_user,
        "changes.decision",
        {"decision": payload.decision},
    )
    db.commit()
    db.refresh(change)
    return _detail_response(db, change)


@router.post("/{change_id}/transitions", response_model=ChangeDetailResponse)
def transition_change(
    change_id: str,
    payload: ChangeTransitionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ChangeDetailResponse:
    permission = {
        "SUBMIT": "changes.submit",
        "REQUEST_APPROVAL": "changes.submit",
        "SCHEDULE": "changes.schedule",
        "START": "changes.execute",
        "COMPLETE": "changes.execute",
        "CLOSE": "changes.execute",
        "FAIL": "changes.execute",
        "ROLLBACK": "changes.execute",
        "CANCEL": "changes.submit",
    }[payload.action]
    require_permissions(current_user, permission)
    change = _get_change(db, change_id, current_user, lock=True)
    _assert_version(change, payload.expected_version)
    previous = change.status
    message, metadata = _apply_transition(
        db,
        change,
        payload,
        current_user,
    )
    change.version += 1
    _record_history(
        db,
        change,
        current_user,
        event_type=payload.action,
        message=message,
        from_status=previous,
        to_status=change.status,
        metadata=metadata,
    )
    _audit_request(
        db,
        request,
        change,
        current_user,
        f"changes.transition.{payload.action.lower()}",
        {"from_status": previous, "to_status": change.status, **metadata},
    )
    db.commit()
    db.refresh(change)
    return _detail_response(db, change)


def _apply_transition(
    db: Session,
    change: ChangeRequest,
    payload: ChangeTransitionRequest,
    current_user: AuthUserResponse,
) -> tuple[str, dict[str, object]]:
    action = payload.action
    comment = _clean_text(payload.comment)
    if action == "SUBMIT":
        if change.status not in {"DRAFT", "REJECTED"}:
            raise HTTPException(status_code=409, detail="Only a draft or rejected change can be submitted")
        missing = [field for field in REQUIRED_ASSESSMENT_FIELDS if not getattr(change, field)]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Assessment is incomplete: {', '.join(missing)}",
            )
        if change.change_type == "STANDARD" and change.cab_required:
            raise HTTPException(
                status_code=422,
                detail="Standard changes must be low/medium risk and cannot require an outage",
            )
        change.status = "ASSESSMENT"
        change.approval_status = "NOT_REQUIRED" if not change.cab_required else "NOT_REQUESTED"
        return "Change submitted for assessment", {}
    if action == "REQUEST_APPROVAL":
        if change.status != "ASSESSMENT":
            raise HTTPException(status_code=409, detail="Change is not in assessment")
        if change.cab_required:
            change.status = "APPROVAL_PENDING"
            change.approval_status = "PENDING"
            return "Change submitted to CAB/ECAB", {}
        change.status = "APPROVED"
        change.approval_status = "NOT_REQUIRED"
        return "Pre-authorized standard change approved", {"pre_authorized": True}
    if action == "SCHEDULE":
        if change.status != "APPROVED":
            raise HTTPException(status_code=409, detail="Only an approved change can be scheduled")
        if payload.planned_start_at is not None:
            change.planned_start_at = payload.planned_start_at
        if payload.planned_end_at is not None:
            change.planned_end_at = payload.planned_end_at
        _validate_window(change.planned_start_at, change.planned_end_at)
        asset_ids = list(
            db.scalars(
                select(ChangeAssetLink.asset_id).where(ChangeAssetLink.change_id == change.id)
            ).all()
        )
        _lock_asset_windows(db, change.tenant_id, asset_ids)
        conflicts = _window_conflicts(db, change, asset_ids)
        governance = assess_change_window(db, change)
        known_change_numbers = {
            str(item["change_number"]) for item in conflicts
        }
        conflicts.extend(
            {
                "change_number": str(item["change_number"]),
                "asset_tag": (
                    ",".join(str(value) for value in item["shared_asset_ids"])
                    or str(item.get("title") or "service collision")
                ),
            }
            for item in governance["change_conflicts"]
            if str(item["change_number"]) not in known_change_numbers
        )
        if conflicts:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Implementation window conflicts with another change", "conflicts": conflicts},
            )
        blackout_metadata: dict[str, object] = {}
        if governance["blackouts"]:
            override_reason = _clean_text(payload.blackout_override_reason)
            if change.change_type != "EMERGENCY" or not override_reason:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": "Implementation window intersects an active blackout",
                        "blackouts": governance["blackouts"],
                    },
                )
            change.blackout_override_reason = override_reason
            change.blackout_override_by_id = current_user.id
            change.blackout_override_at = _now()
            blackout_metadata = {
                "blackout_override": True,
                "blackout_override_reason": override_reason,
                "blackout_ids": [
                    str(item["id"]) for item in governance["blackouts"]
                ],
            }
        change.status = "SCHEDULED"
        return "Implementation window scheduled", {
            "planned_start_at": change.planned_start_at.isoformat(),
            "planned_end_at": change.planned_end_at.isoformat(),
            **blackout_metadata,
        }
    if action == "START":
        if change.status != "SCHEDULED":
            raise HTTPException(status_code=409, detail="Only a scheduled change can be started")
        change.status = "IMPLEMENTING"
        change.actual_start_at = _now()
        return "Implementation started", {}
    if action == "COMPLETE":
        if change.status != "IMPLEMENTING":
            raise HTTPException(status_code=409, detail="Change is not being implemented")
        if not required_tasks_complete(db, change.id, "IMPLEMENTATION"):
            raise HTTPException(
                status_code=422,
                detail="Required implementation tasks must be completed",
            )
        change.status = "REVIEW"
        change.actual_end_at = _now()
        if (
            change.change_type == "EMERGENCY"
            or change.risk_level in {"HIGH", "CRITICAL"}
            or change.outage_required
        ):
            change.pir_status = "REQUIRED"
        return "Implementation completed; validation review opened", {}
    if action == "CLOSE":
        if change.status != "REVIEW":
            raise HTTPException(status_code=409, detail="Only a reviewed implementation can be closed")
        if not comment:
            raise HTTPException(status_code=422, detail="Post-implementation review is required")
        if not required_tasks_complete(db, change.id, "VALIDATION"):
            raise HTTPException(
                status_code=422,
                detail="Required validation tasks must be completed",
            )
        if change.pir_status == "REQUIRED":
            pir = pir_for_change(db, change.id)
            if pir is None or pir.status != "APPROVED":
                raise HTTPException(
                    status_code=422,
                    detail="An independently approved PIR is required",
                )
        change.status = "COMPLETED"
        change.post_implementation_review = comment
        change.outcome = change.outcome or "SUCCESS"
        if change.standard_model_id and change.pir_status != "APPROVED":
            update_standard_model_outcome(db, change, "SUCCESS")
        return "Change completed after post-implementation review", {"review": comment}
    if action == "FAIL":
        if change.status != "IMPLEMENTING":
            raise HTTPException(status_code=409, detail="Only an active implementation can fail")
        if not comment:
            raise HTTPException(status_code=422, detail="Failure reason is required")
        change.status = "FAILED"
        change.failure_reason = comment
        change.actual_end_at = _now()
        change.outcome = "FAILED"
        change.pir_status = "REQUIRED"
        return "Implementation marked as failed", {"reason": comment}
    if action == "ROLLBACK":
        if change.status not in {"IMPLEMENTING", "FAILED"}:
            raise HTTPException(status_code=409, detail="Change cannot be rolled back from this status")
        if not comment:
            raise HTTPException(status_code=422, detail="Rollback result is required")
        change.status = "ROLLED_BACK"
        change.actual_end_at = _now()
        change.outcome = "ROLLED_BACK"
        change.pir_status = "REQUIRED"
        return "Rollback completed", {"result": comment}
    if action == "CANCEL":
        if change.status not in {
            "DRAFT",
            "ASSESSMENT",
            "APPROVAL_PENDING",
            "APPROVED",
            "SCHEDULED",
            "REJECTED",
        }:
            raise HTTPException(status_code=409, detail="Change can no longer be cancelled")
        if not comment:
            raise HTTPException(status_code=422, detail="Cancellation reason is required")
        change.status = "CANCELLED"
        return "Change cancelled", {"reason": comment}
    raise HTTPException(status_code=422, detail="Unsupported transition")
