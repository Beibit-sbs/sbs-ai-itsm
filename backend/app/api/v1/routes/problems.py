from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.change_request import ChangeRequest
from app.models.problem import Problem
from app.models.problem_history import ProblemHistory
from app.models.problem_link import ProblemAssetLink, ProblemChangeLink, ProblemTicketLink
from app.models.problem_governance import ProblemCorrectiveAction
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.user import User
from app.services.audit import log_audit
from app.services.rbac import require_permissions


router = APIRouter(prefix="/problems")

ProblemType = Literal["REACTIVE", "PROACTIVE"]
ImpactLevel = Literal["LOW", "MEDIUM", "HIGH", "ENTERPRISE"]
UrgencyLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
TransitionAction = Literal[
    "START_INVESTIGATION",
    "IDENTIFY_ROOT_CAUSE",
    "PUBLISH_KNOWN_ERROR",
    "RESOLVE",
    "CLOSE",
    "REOPEN",
    "RETIRE_KNOWN_ERROR",
    "CANCEL",
]

TERMINAL_STATUSES = {"CLOSED", "CANCELLED"}
OPEN_STATUSES = {
    "NEW",
    "INVESTIGATING",
    "ROOT_CAUSE_IDENTIFIED",
    "KNOWN_ERROR",
    "RESOLVED",
}


class ProblemCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10, max_length=20_000)
    problem_type: ProblemType = "REACTIVE"
    service_name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=120)
    impact_level: ImpactLevel = "MEDIUM"
    urgency_level: UrgencyLevel = "MEDIUM"
    detection_source: str | None = Field(default=None, max_length=120)
    symptoms: str = Field(min_length=10, max_length=20_000)
    owner_id: str | None = None
    first_observed_at: datetime | None = None
    target_resolution_at: datetime | None = None
    ticket_ids: list[str] = Field(default_factory=list, max_length=200)
    asset_ids: list[str] = Field(default_factory=list, max_length=100)
    change_ids: list[str] = Field(default_factory=list, max_length=100)


class ProblemPatchRequest(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = Field(default=None, min_length=10, max_length=20_000)
    problem_type: ProblemType | None = None
    service_name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=120)
    impact_level: ImpactLevel | None = None
    urgency_level: UrgencyLevel | None = None
    detection_source: str | None = Field(default=None, max_length=120)
    symptoms: str | None = Field(default=None, min_length=10, max_length=20_000)
    owner_id: str | None = None
    first_observed_at: datetime | None = None
    target_resolution_at: datetime | None = None
    ticket_ids: list[str] | None = Field(default=None, max_length=200)
    asset_ids: list[str] | None = Field(default=None, max_length=100)
    change_ids: list[str] | None = Field(default=None, max_length=100)


class ProblemTransitionRequest(BaseModel):
    action: TransitionAction
    expected_version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=10_000)
    root_cause: str | None = Field(default=None, max_length=30_000)
    known_error_title: str | None = Field(default=None, max_length=255)
    workaround: str | None = Field(default=None, max_length=30_000)
    resolution_summary: str | None = Field(default=None, max_length=30_000)
    validation_summary: str | None = Field(default=None, max_length=30_000)


class LinkedTicketResponse(BaseModel):
    id: str
    ticket_number: str | None
    title: str
    status: str
    priority: str


class LinkedAssetResponse(BaseModel):
    id: str
    asset_tag: str
    name: str
    status: str
    location: str


class LinkedChangeResponse(BaseModel):
    id: str
    change_number: str
    title: str
    status: str
    risk_level: str


class ProblemHistoryResponse(BaseModel):
    id: str
    actor_name: str
    actor_email: str
    event_type: str
    from_status: str | None
    to_status: str | None
    message: str
    metadata: dict[str, object]
    created_at: datetime


class ProblemBaseResponse(BaseModel):
    id: str
    tenant_id: str
    problem_number: str
    title: str
    description: str
    problem_type: str
    status: str
    service_name: str | None
    category: str | None
    impact_level: str
    urgency_level: str
    priority: str
    detection_source: str | None
    symptoms: str
    workaround_status: str
    known_error_title: str | None
    known_error_published_at: datetime | None
    known_error_published_by_name: str | None
    created_by_id: str | None
    created_by_name: str
    created_by_email: str
    owner_id: str | None
    owner_name: str | None
    first_observed_at: datetime | None
    target_resolution_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    version: int
    incident_count: int
    asset_count: int
    change_count: int
    age_days: int
    overdue: bool
    is_known_error: bool
    created_at: datetime
    updated_at: datetime


class ProblemDetailResponse(ProblemBaseResponse):
    root_cause: str | None
    workaround: str | None
    resolution_summary: str | None
    validation_summary: str | None
    tickets: list[LinkedTicketResponse]
    assets: list[LinkedAssetResponse]
    changes: list[LinkedChangeResponse]
    history: list[ProblemHistoryResponse]


class ProblemPageResponse(BaseModel):
    items: list[ProblemBaseResponse]
    total: int
    page: int
    page_size: int


class KnownErrorResponse(BaseModel):
    id: str
    problem_number: str
    title: str
    known_error_title: str
    service_name: str | None
    category: str | None
    priority: str
    status: str
    symptoms: str
    root_cause: str
    workaround: str
    workaround_status: str
    incident_count: int
    published_at: datetime
    updated_at: datetime


class KnownErrorPageResponse(BaseModel):
    items: list[KnownErrorResponse]
    total: int
    page: int
    page_size: int


class ProblemSummaryResponse(BaseModel):
    open_problems: int
    investigating: int
    known_errors: int
    overdue: int
    recurring_problems: int
    critical_open: int


def _now() -> datetime:
    return datetime.now(UTC)


def _clean_text(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _clean_ids(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in values if item.strip()))


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


def _get_problem(
    db: Session,
    problem_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> Problem:
    statement = select(Problem).where(Problem.id == problem_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    problem = db.scalar(statement)
    if problem is None or (
        current_user.role != "saas_root" and problem.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Problem not found")
    return problem


def _assert_version(problem: Problem, expected_version: int) -> None:
    if problem.version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Problem was updated by another operator; current version is {problem.version}",
        )


def _priority(impact_level: str, urgency_level: str) -> str:
    impact = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "ENTERPRISE": 4}[impact_level]
    urgency = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}[urgency_level]
    score = impact * urgency
    if score >= 12:
        return "P1"
    if score >= 8:
        return "P2"
    if score >= 4:
        return "P3"
    return "P4"


def _owner(db: Session, tenant_id: str, owner_id: str | None) -> tuple[str | None, str | None]:
    if owner_id is None:
        return None, None
    owner = db.get(User, owner_id)
    if owner is None or owner.tenant_id != tenant_id or not owner.is_active:
        raise HTTPException(status_code=422, detail="Problem owner is unavailable")
    return owner.id, owner.full_name


def _validate_linked_records(
    db: Session,
    tenant_id: str,
    ticket_ids: list[str],
    asset_ids: list[str],
    change_ids: list[str],
) -> None:
    specs = (
        (Ticket, ticket_ids, "tickets"),
        (Asset, asset_ids, "assets"),
        (ChangeRequest, change_ids, "changes"),
    )
    for model, ids, label in specs:
        if not ids:
            continue
        records = db.scalars(select(model).where(model.id.in_(ids))).all()
        if len(records) != len(ids) or any(item.tenant_id != tenant_id for item in records):
            raise HTTPException(status_code=422, detail=f"One or more {label} are unavailable")


def _replace_links(
    db: Session,
    problem: Problem,
    *,
    ticket_ids: list[str] | None = None,
    asset_ids: list[str] | None = None,
    change_ids: list[str] | None = None,
) -> None:
    specs = (
        (ProblemTicketLink, "ticket_id", ticket_ids),
        (ProblemAssetLink, "asset_id", asset_ids),
        (ProblemChangeLink, "change_id", change_ids),
    )
    for model, field, ids in specs:
        if ids is None:
            continue
        db.execute(delete(model).where(model.problem_id == problem.id))
        for entity_id in ids:
            db.add(
                model(
                    id=str(uuid.uuid4()),
                    tenant_id=problem.tenant_id,
                    problem_id=problem.id,
                    **{field: entity_id},
                )
            )


def _record_history(
    db: Session,
    problem: Problem,
    current_user: AuthUserResponse,
    *,
    event_type: str,
    message: str,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        ProblemHistory(
            id=str(uuid.uuid4()),
            tenant_id=problem.tenant_id,
            problem_id=problem.id,
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
    problem: Problem,
    current_user: AuthUserResponse,
    action: str,
    metadata: dict[str, object] | None = None,
) -> None:
    log_audit(
        db,
        action=action,
        entity_type="problem",
        entity_id=problem.id,
        actor_email=current_user.email,
        tenant_id=problem.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"problem_number": problem.problem_number, **(metadata or {})},
    )


def _parse_metadata(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _age_days(problem: Problem) -> int:
    start = problem.first_observed_at or problem.created_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    return max(0, (_now() - start.astimezone(UTC)).days)


def _is_overdue(problem: Problem) -> bool:
    if problem.target_resolution_at is None or problem.status not in OPEN_STATUSES:
        return False
    target = problem.target_resolution_at
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    return target.astimezone(UTC) < _now()


def _link_counts(
    db: Session, problem_ids: list[str]
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    if not problem_ids:
        return {}, {}, {}

    def counts(model) -> dict[str, int]:
        return dict(
            db.execute(
                select(model.problem_id, func.count(model.id))
                .where(model.problem_id.in_(problem_ids))
                .group_by(model.problem_id)
            ).all()
        )

    return counts(ProblemTicketLink), counts(ProblemAssetLink), counts(ProblemChangeLink)


def _base_response(
    problem: Problem,
    *,
    incident_count: int,
    asset_count: int,
    change_count: int,
) -> ProblemBaseResponse:
    derived = {
        "incident_count": incident_count,
        "asset_count": asset_count,
        "change_count": change_count,
        "age_days": _age_days(problem),
        "overdue": _is_overdue(problem),
        "is_known_error": problem.known_error_published_at is not None,
    }
    return ProblemBaseResponse(
        **{
            field: getattr(problem, field)
            for field in ProblemBaseResponse.model_fields
            if field not in derived
        },
        **derived,
    )


def _detail_response(db: Session, problem: Problem) -> ProblemDetailResponse:
    tickets = db.scalars(
        select(Ticket)
        .join(ProblemTicketLink, ProblemTicketLink.ticket_id == Ticket.id)
        .where(ProblemTicketLink.problem_id == problem.id)
        .order_by(Ticket.created_at.desc())
    ).all()
    assets = db.scalars(
        select(Asset)
        .join(ProblemAssetLink, ProblemAssetLink.asset_id == Asset.id)
        .where(ProblemAssetLink.problem_id == problem.id)
        .order_by(Asset.asset_tag)
    ).all()
    changes = db.scalars(
        select(ChangeRequest)
        .join(ProblemChangeLink, ProblemChangeLink.change_id == ChangeRequest.id)
        .where(ProblemChangeLink.problem_id == problem.id)
        .order_by(ChangeRequest.updated_at.desc())
    ).all()
    history = db.scalars(
        select(ProblemHistory)
        .where(ProblemHistory.problem_id == problem.id)
        .order_by(ProblemHistory.created_at.desc(), ProblemHistory.id.desc())
    ).all()
    base = _base_response(
        problem,
        incident_count=len(tickets),
        asset_count=len(assets),
        change_count=len(changes),
    )
    return ProblemDetailResponse(
        **base.model_dump(),
        root_cause=problem.root_cause,
        workaround=problem.workaround,
        resolution_summary=problem.resolution_summary,
        validation_summary=problem.validation_summary,
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
        changes=[
            LinkedChangeResponse(
                id=item.id,
                change_number=item.change_number,
                title=item.title,
                status=item.status,
                risk_level=item.risk_level,
            )
            for item in changes
        ],
        history=[
            ProblemHistoryResponse(
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


@router.get("", response_model=ProblemPageResponse)
def list_problems(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    problem_status: str | None = Query(default=None, alias="status", max_length=40),
    problem_type: str | None = Query(default=None, max_length=24),
    priority: str | None = Query(default=None, max_length=8),
    known_error: bool | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ProblemPageResponse:
    require_permissions(current_user, "problems.read")
    filters = []
    if current_user.role != "saas_root":
        filters.append(Problem.tenant_id == current_user.tenant_id)
    if problem_status:
        filters.append(Problem.status == problem_status.upper())
    if problem_type:
        filters.append(Problem.problem_type == problem_type.upper())
    if priority:
        filters.append(Problem.priority == priority.upper())
    if known_error is True:
        filters.append(Problem.known_error_published_at.is_not(None))
    elif known_error is False:
        filters.append(Problem.known_error_published_at.is_(None))
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Problem.problem_number.ilike(pattern),
                Problem.title.ilike(pattern),
                Problem.service_name.ilike(pattern),
                Problem.symptoms.ilike(pattern),
            )
        )
    total = int(db.scalar(select(func.count(Problem.id)).where(*filters)) or 0)
    problems = db.scalars(
        select(Problem)
        .where(*filters)
        .order_by(Problem.updated_at.desc(), Problem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    ticket_counts, asset_counts, change_counts = _link_counts(
        db, [item.id for item in problems]
    )
    return ProblemPageResponse(
        items=[
            _base_response(
                item,
                incident_count=ticket_counts.get(item.id, 0),
                asset_count=asset_counts.get(item.id, 0),
                change_count=change_counts.get(item.id, 0),
            )
            for item in problems
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=ProblemSummaryResponse)
def problem_summary(
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ProblemSummaryResponse:
    require_permissions(current_user, "problems.read")
    tenant_filter = []
    if current_user.role != "saas_root":
        tenant_filter.append(Problem.tenant_id == current_user.tenant_id)

    def count(*extra) -> int:
        return int(db.scalar(select(func.count(Problem.id)).where(*tenant_filter, *extra)) or 0)

    recurring_ids = (
        select(ProblemTicketLink.problem_id)
        .group_by(ProblemTicketLink.problem_id)
        .having(func.count(ProblemTicketLink.id) >= 3)
    )
    return ProblemSummaryResponse(
        open_problems=count(Problem.status.in_(OPEN_STATUSES)),
        investigating=count(Problem.status == "INVESTIGATING"),
        known_errors=count(
            Problem.known_error_published_at.is_not(None),
            Problem.workaround_status == "PUBLISHED",
        ),
        overdue=count(
            Problem.status.in_(OPEN_STATUSES),
            Problem.target_resolution_at.is_not(None),
            Problem.target_resolution_at < _now(),
        ),
        recurring_problems=count(Problem.id.in_(recurring_ids)),
        critical_open=count(
            Problem.priority == "P1", Problem.status.in_(OPEN_STATUSES)
        ),
    )


@router.get("/known-errors", response_model=KnownErrorPageResponse)
def list_known_errors(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    service_name: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> KnownErrorPageResponse:
    require_permissions(current_user, "problems.read")
    filters = [
        Problem.known_error_published_at.is_not(None),
        Problem.workaround_status == "PUBLISHED",
        Problem.status != "CANCELLED",
    ]
    if current_user.role != "saas_root":
        filters.append(Problem.tenant_id == current_user.tenant_id)
    if service_name:
        filters.append(Problem.service_name == service_name)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Problem.problem_number.ilike(pattern),
                Problem.title.ilike(pattern),
                Problem.known_error_title.ilike(pattern),
                Problem.symptoms.ilike(pattern),
                Problem.root_cause.ilike(pattern),
                Problem.workaround.ilike(pattern),
            )
        )
    total = int(db.scalar(select(func.count(Problem.id)).where(*filters)) or 0)
    problems = db.scalars(
        select(Problem)
        .where(*filters)
        .order_by(Problem.known_error_published_at.desc(), Problem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    ticket_counts, _, _ = _link_counts(db, [item.id for item in problems])
    return KnownErrorPageResponse(
        items=[
            KnownErrorResponse(
                id=item.id,
                problem_number=item.problem_number,
                title=item.title,
                known_error_title=item.known_error_title or item.title,
                service_name=item.service_name,
                category=item.category,
                priority=item.priority,
                status=item.status,
                symptoms=item.symptoms,
                root_cause=item.root_cause or "",
                workaround=item.workaround or "",
                workaround_status=item.workaround_status,
                incident_count=ticket_counts.get(item.id, 0),
                published_at=item.known_error_published_at,
                updated_at=item.updated_at,
            )
            for item in problems
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{problem_id}", response_model=ProblemDetailResponse)
def get_problem(
    problem_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ProblemDetailResponse:
    require_permissions(current_user, "problems.read")
    return _detail_response(db, _get_problem(db, problem_id, current_user))


@router.post("", response_model=ProblemDetailResponse, status_code=status.HTTP_201_CREATED)
def create_problem(
    payload: ProblemCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ProblemDetailResponse:
    require_permissions(current_user, "problems.create")
    tenant_id = _resolve_tenant_id(db, current_user)
    ticket_ids = _clean_ids(payload.ticket_ids)
    asset_ids = _clean_ids(payload.asset_ids)
    change_ids = _clean_ids(payload.change_ids)
    _validate_linked_records(db, tenant_id, ticket_ids, asset_ids, change_ids)
    owner_id, owner_name = _owner(db, tenant_id, payload.owner_id)
    if owner_id is None:
        owner_id, owner_name = current_user.id, current_user.full_name
    problem = Problem(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        problem_number=f"PRB-{_now().year}-{uuid.uuid4().hex[:8].upper()}",
        title=payload.title.strip(),
        description=payload.description.strip(),
        problem_type=payload.problem_type,
        status="NEW",
        service_name=_clean_text(payload.service_name),
        category=_clean_text(payload.category),
        impact_level=payload.impact_level,
        urgency_level=payload.urgency_level,
        priority=_priority(payload.impact_level, payload.urgency_level),
        detection_source=_clean_text(payload.detection_source),
        symptoms=payload.symptoms.strip(),
        workaround_status="NONE",
        created_by_id=current_user.id,
        created_by_name=current_user.full_name,
        created_by_email=current_user.email,
        owner_id=owner_id,
        owner_name=owner_name,
        first_observed_at=payload.first_observed_at,
        target_resolution_at=payload.target_resolution_at,
        version=1,
    )
    db.add(problem)
    db.flush()
    _replace_links(
        db,
        problem,
        ticket_ids=ticket_ids,
        asset_ids=asset_ids,
        change_ids=change_ids,
    )
    _record_history(
        db,
        problem,
        current_user,
        event_type="CREATED",
        message="Problem record created",
        to_status="NEW",
        metadata={
            "priority": problem.priority,
            "incident_count": len(ticket_ids),
            "problem_type": problem.problem_type,
        },
    )
    _audit_request(db, request, problem, current_user, "problems.create")
    db.commit()
    db.refresh(problem)
    return _detail_response(db, problem)


@router.patch("/{problem_id}", response_model=ProblemDetailResponse)
def patch_problem(
    problem_id: str,
    payload: ProblemPatchRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ProblemDetailResponse:
    require_permissions(current_user, "problems.update")
    problem = _get_problem(db, problem_id, current_user, lock=True)
    _assert_version(problem, payload.expected_version)
    if payload.action == "CLOSE":
        incomplete_actions = int(
            db.scalar(
                select(func.count(ProblemCorrectiveAction.id)).where(
                    ProblemCorrectiveAction.problem_id == problem.id,
                    ProblemCorrectiveAction.is_required.is_(True),
                    ProblemCorrectiveAction.status != "VERIFIED",
                )
            )
            or 0
        )
        if incomplete_actions:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Required corrective actions must pass independent "
                    "effectiveness review before closure"
                ),
            )
    if problem.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Closed or cancelled problems are not editable")
    updates = payload.model_dump(exclude_unset=True)
    updates.pop("expected_version", None)
    ticket_ids_raw = updates.pop("ticket_ids", None)
    asset_ids_raw = updates.pop("asset_ids", None)
    change_ids_raw = updates.pop("change_ids", None)
    ticket_ids = _clean_ids(ticket_ids_raw) if ticket_ids_raw is not None else None
    asset_ids = _clean_ids(asset_ids_raw) if asset_ids_raw is not None else None
    change_ids = _clean_ids(change_ids_raw) if change_ids_raw is not None else None
    current_ticket_ids = list(
        db.scalars(
            select(ProblemTicketLink.ticket_id).where(ProblemTicketLink.problem_id == problem.id)
        ).all()
    )
    current_asset_ids = list(
        db.scalars(
            select(ProblemAssetLink.asset_id).where(ProblemAssetLink.problem_id == problem.id)
        ).all()
    )
    current_change_ids = list(
        db.scalars(
            select(ProblemChangeLink.change_id).where(ProblemChangeLink.problem_id == problem.id)
        ).all()
    )
    _validate_linked_records(
        db,
        problem.tenant_id,
        ticket_ids if ticket_ids is not None else current_ticket_ids,
        asset_ids if asset_ids is not None else current_asset_ids,
        change_ids if change_ids is not None else current_change_ids,
    )
    if "owner_id" in updates:
        owner_id, owner_name = _owner(db, problem.tenant_id, updates.pop("owner_id"))
        problem.owner_id = owner_id
        problem.owner_name = owner_name
    text_fields = {"service_name", "category", "detection_source"}
    for field, value in updates.items():
        if field in text_fields:
            value = _clean_text(value)
        elif field in {"title", "description", "symptoms"} and value is not None:
            value = value.strip()
        setattr(problem, field, value)
    problem.priority = _priority(problem.impact_level, problem.urgency_level)
    problem.version += 1
    _replace_links(
        db,
        problem,
        ticket_ids=ticket_ids,
        asset_ids=asset_ids,
        change_ids=change_ids,
    )
    _record_history(
        db,
        problem,
        current_user,
        event_type="UPDATED",
        message="Problem assessment and relationships updated",
        metadata={"priority": problem.priority},
    )
    _audit_request(db, request, problem, current_user, "problems.update")
    db.commit()
    db.refresh(problem)
    return _detail_response(db, problem)


@router.post("/{problem_id}/transitions", response_model=ProblemDetailResponse)
def transition_problem(
    problem_id: str,
    payload: ProblemTransitionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ProblemDetailResponse:
    permission = {
        "START_INVESTIGATION": "problems.investigate",
        "IDENTIFY_ROOT_CAUSE": "problems.investigate",
        "PUBLISH_KNOWN_ERROR": "problems.publish_known_error",
        "RESOLVE": "problems.resolve",
        "CLOSE": "problems.resolve",
        "REOPEN": "problems.resolve",
        "RETIRE_KNOWN_ERROR": "problems.publish_known_error",
        "CANCEL": "problems.update",
    }[payload.action]
    require_permissions(current_user, permission)
    problem = _get_problem(db, problem_id, current_user, lock=True)
    _assert_version(problem, payload.expected_version)
    previous = problem.status
    message, metadata = _apply_transition(problem, payload, current_user)
    problem.version += 1
    _record_history(
        db,
        problem,
        current_user,
        event_type=payload.action,
        message=message,
        from_status=previous,
        to_status=problem.status,
        metadata=metadata,
    )
    _audit_request(
        db,
        request,
        problem,
        current_user,
        f"problems.transition.{payload.action.lower()}",
        {"from_status": previous, "to_status": problem.status},
    )
    db.commit()
    db.refresh(problem)
    return _detail_response(db, problem)


def _apply_transition(
    problem: Problem,
    payload: ProblemTransitionRequest,
    current_user: AuthUserResponse,
) -> tuple[str, dict[str, object]]:
    action = payload.action
    comment = _clean_text(payload.comment)
    if action == "START_INVESTIGATION":
        if problem.status != "NEW":
            raise HTTPException(status_code=409, detail="Only a new problem can enter investigation")
        problem.status = "INVESTIGATING"
        return "Root-cause investigation started", {}
    if action == "IDENTIFY_ROOT_CAUSE":
        if problem.status != "INVESTIGATING":
            raise HTTPException(status_code=409, detail="Problem is not under investigation")
        root_cause = _clean_text(payload.root_cause)
        if root_cause is None or len(root_cause) < 10:
            raise HTTPException(status_code=422, detail="Root-cause evidence is required")
        problem.root_cause = root_cause
        problem.status = "ROOT_CAUSE_IDENTIFIED"
        return "Root cause identified and documented", {"root_cause_recorded": True}
    if action == "PUBLISH_KNOWN_ERROR":
        if problem.status not in {"ROOT_CAUSE_IDENTIFIED", "KNOWN_ERROR"}:
            raise HTTPException(status_code=409, detail="Root cause must be identified first")
        title = _clean_text(payload.known_error_title)
        workaround = _clean_text(payload.workaround)
        if title is None or len(title) < 3 or workaround is None or len(workaround) < 10:
            raise HTTPException(
                status_code=422,
                detail="Known Error title and actionable workaround are required",
            )
        if not problem.root_cause:
            raise HTTPException(status_code=422, detail="Root cause is required")
        first_publication = problem.known_error_published_at is None
        problem.known_error_title = title
        problem.workaround = workaround
        problem.workaround_status = "PUBLISHED"
        problem.known_error_published_at = problem.known_error_published_at or _now()
        problem.known_error_published_by_id = current_user.id
        problem.known_error_published_by_name = current_user.full_name
        problem.status = "KNOWN_ERROR"
        return (
            "Known Error and workaround published" if first_publication else "Known Error updated",
            {"first_publication": first_publication},
        )
    if action == "RESOLVE":
        if problem.status not in {"ROOT_CAUSE_IDENTIFIED", "KNOWN_ERROR"}:
            raise HTTPException(status_code=409, detail="Problem cannot be resolved from this status")
        resolution = _clean_text(payload.resolution_summary)
        if resolution is None or len(resolution) < 10:
            raise HTTPException(status_code=422, detail="Resolution evidence is required")
        problem.resolution_summary = resolution
        problem.resolved_at = _now()
        problem.status = "RESOLVED"
        return "Problem marked as resolved; validation required", {}
    if action == "CLOSE":
        if problem.status != "RESOLVED":
            raise HTTPException(status_code=409, detail="Only a resolved problem can be closed")
        validation = _clean_text(payload.validation_summary)
        if validation is None or len(validation) < 10:
            raise HTTPException(status_code=422, detail="Closure validation evidence is required")
        problem.validation_summary = validation
        problem.closed_at = _now()
        problem.status = "CLOSED"
        return "Problem closed after effectiveness validation", {}
    if action == "REOPEN":
        if problem.status not in {"RESOLVED", "CLOSED"}:
            raise HTTPException(status_code=409, detail="Only a resolved or closed problem can be reopened")
        if comment is None or len(comment) < 3:
            raise HTTPException(status_code=422, detail="Reopen reason is required")
        problem.status = "INVESTIGATING"
        problem.resolved_at = None
        problem.closed_at = None
        problem.resolution_summary = None
        problem.validation_summary = None
        return "Problem reopened for renewed investigation", {"reason": comment}
    if action == "RETIRE_KNOWN_ERROR":
        if problem.known_error_published_at is None or problem.workaround_status != "PUBLISHED":
            raise HTTPException(status_code=409, detail="No published Known Error is active")
        if problem.status not in {"RESOLVED", "CLOSED"}:
            raise HTTPException(status_code=409, detail="Known Error can be retired after resolution")
        if comment is None or len(comment) < 3:
            raise HTTPException(status_code=422, detail="Retirement reason is required")
        problem.workaround_status = "RETIRED"
        return "Known Error workaround retired", {"reason": comment}
    if action == "CANCEL":
        if problem.status not in {"NEW", "INVESTIGATING"}:
            raise HTTPException(status_code=409, detail="Problem can no longer be cancelled")
        if comment is None or len(comment) < 3:
            raise HTTPException(status_code=422, detail="Cancellation reason is required")
        problem.status = "CANCELLED"
        return "Problem record cancelled", {"reason": comment}
    raise HTTPException(status_code=422, detail="Unsupported transition")
