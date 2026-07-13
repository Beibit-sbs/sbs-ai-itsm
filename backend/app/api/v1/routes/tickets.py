from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.sla import SlaPolicy
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.ticket_category import TicketCategory
from app.models.ticket_comment import TicketComment
from app.models.ticket_history import TicketHistory
from app.models.ticket_knowledge_link import TicketKnowledgeLink
from app.models.ticket_priority import TicketPriority
from app.models.ticket_status import TicketStatus
from app.models.user import User
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_usage_log import KnowledgeUsageLog
from app.services.asset_sla import calculate_ticket_sla_status
from app.services.audit import log_audit
from app.services.automation import build_ticket_context, trigger_automation_event
from app.services.notifications import create_ticket_event_notification
from app.services.rbac import require_permissions
from app.services.service_desk import build_ticket_summary, calculate_response_minutes, next_ticket_number
from app.services.sla import calculate_sla_state

router = APIRouter(prefix="/tickets")

STATUS_CANONICAL_MAP = {
    "new": "NEW",
    "triage": "TRIAGE",
    "triaged": "TRIAGE",
    "assigned": "ASSIGNED",
    "in_progress": "IN_PROGRESS",
    "waiting_user": "WAITING_USER",
    "waiting_vendor": "WAITING_VENDOR",
    "resolved": "RESOLVED",
    "closed": "CLOSED",
    "reopened": "REOPENED",
    "cancelled": "CANCELLED",
}

STATUS_COMPAT_OUT = {
    "TRIAGED": "TRIAGE",
}

STATUS_LABELS_RU = {
    "NEW": "Новая",
    "TRIAGE": "Разбор",
    "ASSIGNED": "Назначена",
    "IN_PROGRESS": "В работе",
    "WAITING_USER": "Ожидает пользователя",
    "WAITING_VENDOR": "Ожидает поставщика",
    "RESOLVED": "Решена",
    "CLOSED": "Закрыта",
    "REOPENED": "Переоткрыта",
    "CANCELLED": "Отменена",
}

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"TRIAGE", "ASSIGNED", "CANCELLED"},
    "TRIAGE": {"ASSIGNED", "WAITING_USER", "CANCELLED"},
    "ASSIGNED": {"IN_PROGRESS", "WAITING_USER", "WAITING_VENDOR"},
    "IN_PROGRESS": {"RESOLVED", "WAITING_USER", "WAITING_VENDOR"},
    "WAITING_USER": {"IN_PROGRESS", "CANCELLED"},
    "WAITING_VENDOR": {"IN_PROGRESS"},
    "RESOLVED": {"CLOSED", "REOPENED"},
    "CLOSED": {"REOPENED"},
    "REOPENED": {"TRIAGE", "ASSIGNED"},
    "CANCELLED": set(),
}

CLOSED_STATUSES = {"RESOLVED", "CLOSED", "CANCELLED"}


class TicketCommentResponse(BaseModel):
    id: str
    author_id: str | None = None
    author_name: str
    author_role: str
    body: str
    is_internal: bool = False
    created_at: datetime


class TicketHistoryResponse(BaseModel):
    id: str
    actor_name: str
    event_type: str
    field_name: str | None
    old_value: str | None
    new_value: str | None
    message: str
    created_at: datetime


class TicketListResponse(BaseModel):
    id: str
    ticket_number: str | None
    title: str
    description: str | None
    requester_id: str | None = None
    requester_name: str
    requester_email: str
    department: str
    location: str
    category: str
    category_label: str
    category_color: str
    priority: str
    priority_label: str
    priority_color: str
    status: str
    status_label: str
    status_color: str
    assignee_id: str | None = None
    assignee_name: str | None
    asset_id: str | None = None
    asset_tag: str | None = None
    asset_name: str | None = None
    asset_type: str | None = None
    sla_due_at: datetime | None
    sla_policy_id: str | None = None
    response_due_at: datetime | None = None
    resolution_due_at: datetime | None = None
    sla_status: str | None = None
    sla_badge: str | None = None
    response_remaining_minutes: int | None = None
    resolution_remaining_minutes: int | None = None
    is_response_breached: bool = False
    is_resolution_breached: bool = False
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    reopened_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    response_minutes: int | None = None


class TicketDetailResponse(TicketListResponse):
    comments: list[TicketCommentResponse] = Field(default_factory=list)
    history_count: int = 0


class TicketPageResponse(BaseModel):
    items: list[TicketListResponse]
    total: int
    page: int
    page_size: int


class TicketCreateRequest(BaseModel):
    title: str
    description: str | None = None
    requester_id: str | None = None
    requester_name: str | None = None
    requester_email: str | None = None
    requester_contact: str | None = None
    department: str
    location: str | None = None
    category: str
    priority: str
    assignee_id: str | None = None
    assignee_name: str | None = None
    asset_id: str | None = None


class TicketPatchRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    requester_name: str | None = None
    requester_email: str | None = None
    department: str | None = None
    location: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    assignee_id: str | None = None
    assignee_name: str | None = None
    sla_due_at: datetime | None = None
    asset_id: str | None = None


class CommentCreateRequest(BaseModel):
    body: str
    is_internal: bool = False


class TicketTransitionRequest(BaseModel):
    status: str
    comment: str | None = None
    is_internal: bool = False


class TicketAssignRequest(BaseModel):
    assignee_id: str | None = None
    comment: str | None = None


class TicketKnowledgeLinkCreateRequest(BaseModel):
    article_id: str
    link_type: str = "manual"
    confidence: float | None = None
    comment: str | None = None


class TicketKnowledgeLinkResponse(BaseModel):
    id: str
    ticket_id: str
    article_id: str
    article_number: str
    article_title: str
    linked_by_id: str | None
    linked_by_name: str | None
    link_type: str
    confidence: float | None
    comment: str | None
    created_at: datetime


def _canonical_status(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    return STATUS_CANONICAL_MAP.get(normalized, value.strip().upper())


def _status_for_output(value: str) -> str:
    return STATUS_COMPAT_OUT.get(value, value)


def _status_label(code: str, status_item: TicketStatus | None) -> str:
    canonical = _status_for_output(code)
    return status_item.name if status_item is not None else STATUS_LABELS_RU.get(canonical, canonical)


def _ensure_access(current_user: AuthUserResponse) -> None:
    if current_user.role != "saas_root" and current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access required")


def _resolve_tenant_id(db: Session, current_user: AuthUserResponse) -> str | None:
    if current_user.tenant_id:
        return current_user.tenant_id
    tenant = db.scalar(select(Tenant).order_by(Tenant.created_at.asc()))
    return tenant.id if tenant is not None else None


def _ensure_ticket_access(ticket: Ticket, current_user: AuthUserResponse) -> None:
    if current_user.role != "saas_root" and ticket.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")


def _can_read_ticket(current_user: AuthUserResponse, ticket: Ticket) -> bool:
    if current_user.role == "saas_root":
        return True
    if current_user.tenant_id != ticket.tenant_id:
        return False
    if current_user.role == "requester":
        return current_user.email.lower() == ticket.requester_email.lower()
    if current_user.role == "it_agent":
        if ticket.assignee_id == current_user.id:
            return True
        if ticket.assignee_name and ticket.assignee_name.lower() == current_user.full_name.lower():
            return True
        if ticket.assignee_id is None and not (ticket.assignee_name or "").strip():
            return True
    return True


def _can_manage_all_tickets(current_user: AuthUserResponse) -> bool:
    return current_user.role in {"saas_root", "organization_admin", "it_manager"}


def _lookup_maps(db: Session) -> tuple[dict[str, TicketCategory], dict[str, TicketPriority], dict[str, TicketStatus], dict[str, SlaPolicy], dict[str, Asset]]:
    categories = {item.code: item for item in db.scalars(select(TicketCategory)).all()}
    priorities = {item.code: item for item in db.scalars(select(TicketPriority)).all()}
    statuses = {item.code: item for item in db.scalars(select(TicketStatus)).all()}
    sla_policies = {item.priority.upper(): item for item in db.scalars(select(SlaPolicy)).all()}
    assets = {item.id: item for item in db.scalars(select(Asset)).all()}
    return categories, priorities, statuses, sla_policies, assets


def _apply_ticket_sla(ticket: Ticket, policy: SlaPolicy, started_at: datetime) -> None:
    response_minutes = policy.response_minutes or policy.target_response_minutes
    resolution_minutes = policy.resolution_minutes or policy.target_resolution_minutes
    ticket.sla_policy_id = policy.id
    ticket.response_due_at = started_at + timedelta(minutes=response_minutes)
    ticket.resolution_due_at = started_at + timedelta(minutes=resolution_minutes)
    ticket.sla_due_at = ticket.resolution_due_at
    ticket.sla_status = "OK"


def _serialize_ticket(
    ticket: Ticket,
    categories: dict[str, TicketCategory],
    priorities: dict[str, TicketPriority],
    statuses: dict[str, TicketStatus],
    assets: dict[str, Asset],
    response_minutes: int | None = None,
) -> TicketListResponse:
    category = categories.get(ticket.category)
    priority = priorities.get(ticket.priority)
    status_code = _status_for_output(ticket.status)
    status_item = statuses.get(ticket.status) or statuses.get(status_code)
    asset = assets.get(ticket.asset_id) if ticket.asset_id else None
    payload = build_ticket_summary(
        ticket,
        category_label=category.name if category else ticket.category,
        priority_label=priority.name if priority else ticket.priority,
        status_label=_status_label(ticket.status, status_item),
        response_minutes=response_minutes,
    )
    payload["status"] = status_code
    payload["requester_id"] = ticket.requester_id
    payload["assignee_id"] = ticket.assignee_id
    payload["closed_at"] = ticket.closed_at
    payload["reopened_at"] = ticket.reopened_at
    sla_state = calculate_sla_state(ticket)
    return TicketListResponse(
        **payload,
        category_color=category.color if category else "#8fa6bb",
        priority_color=priority.color if priority else "#8fa6bb",
        status_color=status_item.color if status_item else "#8fa6bb",
        asset_tag=asset.asset_tag if asset else None,
        asset_name=asset.name if asset else None,
        asset_type=asset.asset_type if asset else None,
        sla_badge=str(sla_state["badge"]),
        response_remaining_minutes=sla_state["response_remaining_minutes"],
        resolution_remaining_minutes=sla_state["resolution_remaining_minutes"],
        is_response_breached=bool(sla_state["is_response_breached"]),
        is_resolution_breached=bool(sla_state["is_resolution_breached"]),
    )


def _load_histories(db: Session, ticket_ids: list[str]) -> dict[str, list[TicketHistory]]:
    if not ticket_ids:
        return {}
    histories = db.scalars(select(TicketHistory).where(TicketHistory.ticket_id.in_(ticket_ids)).order_by(TicketHistory.created_at.asc())).all()
    grouped: dict[str, list[TicketHistory]] = {}
    for history in histories:
        grouped.setdefault(history.ticket_id, []).append(history)
    return grouped


def _comments_query_for_user(current_user: AuthUserResponse, ticket_id: str):
    statement = select(TicketComment).where(TicketComment.ticket_id == ticket_id)
    if current_user.role == "requester":
        statement = statement.where(TicketComment.is_internal == False)  # noqa: E712
    return statement.order_by(TicketComment.created_at.asc())


def _load_comments(db: Session, current_user: AuthUserResponse, ticket_id: str) -> list[TicketComment]:
    return db.scalars(_comments_query_for_user(current_user, ticket_id)).all()


def _record_notification_history(ticket_id: str, actor_name: str, event_code: str) -> TicketHistory:
    return TicketHistory(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        actor_name=actor_name,
        event_type="notification_created",
        field_name="notification",
        old_value=None,
        new_value=event_code,
        message=f"Создано уведомление: {event_code}.",
        created_at=datetime.now(UTC),
    )


def _ticket_base_query(current_user: AuthUserResponse):
    statement = select(Ticket)
    if current_user.role != "saas_root":
        statement = statement.where(Ticket.tenant_id == current_user.tenant_id)
    return statement


def _apply_role_scope(statement, current_user: AuthUserResponse):
    if current_user.role == "requester":
        return statement.where(func.lower(Ticket.requester_email) == current_user.email.lower())
    if current_user.role == "it_agent":
        return statement.where(
            or_(
                Ticket.assignee_id == current_user.id,
                func.lower(func.coalesce(Ticket.assignee_name, "")) == current_user.full_name.lower(),
                and_(Ticket.assignee_id.is_(None), or_(Ticket.assignee_name.is_(None), func.length(func.trim(Ticket.assignee_name)) == 0)),
            )
        )
    return statement


def _apply_queue_scope(statement, queue: str, current_user: AuthUserResponse):
    now = datetime.now(UTC)
    queue_value = queue.lower()
    if queue_value == "mine":
        if current_user.role == "requester":
            return statement.where(func.lower(Ticket.requester_email) == current_user.email.lower())
        return statement.where(
            or_(
                Ticket.assignee_id == current_user.id,
                func.lower(func.coalesce(Ticket.assignee_name, "")) == current_user.full_name.lower(),
            )
        )
    if queue_value == "unassigned":
        return statement.where(and_(Ticket.assignee_id.is_(None), or_(Ticket.assignee_name.is_(None), func.length(func.trim(Ticket.assignee_name)) == 0)))
    if queue_value == "critical":
        return statement.where(Ticket.priority == "CRITICAL")
    if queue_value == "sla_breached":
        return statement.where(
            or_(
                and_(Ticket.resolution_due_at.is_not(None), Ticket.resolution_due_at < now, Ticket.status.not_in(CLOSED_STATUSES)),
                and_(Ticket.response_due_at.is_not(None), Ticket.response_due_at < now, Ticket.status.in_(["NEW", "TRIAGE", "TRIAGED"])),
            )
        )
    if queue_value == "due_today":
        return statement.where(
            and_(
                Ticket.status.not_in(CLOSED_STATUSES),
                or_(
                    func.date(Ticket.resolution_due_at) == now.date(),
                    func.date(Ticket.sla_due_at) == now.date(),
                ),
            )
        )
    if queue_value == "created_by_me":
        return statement.where(or_(Ticket.requester_id == current_user.id, func.lower(Ticket.requester_email) == current_user.email.lower()))
    if queue_value == "closed":
        return statement.where(Ticket.status.in_(CLOSED_STATUSES))
    return statement


def _resolve_user_by_id(db: Session, user_id: str | None, tenant_id: str | None) -> User | None:
    if not user_id:
        return None
    statement = select(User).where(User.id == user_id)
    if tenant_id is not None:
        statement = statement.where(User.tenant_id == tenant_id)
    return db.scalar(statement)


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.scalar(select(User).where(User.id == current_user.id))


def _write_history(
    db: Session,
    *,
    ticket_id: str,
    actor_name: str,
    event_type: str,
    field_name: str | None,
    old_value: str | None,
    new_value: str | None,
    message: str,
) -> TicketHistory:
    entry = TicketHistory(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        actor_name=actor_name,
        event_type=event_type,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        message=message,
        created_at=datetime.now(UTC),
    )
    db.add(entry)
    return entry


def _allowed_transition(current_status: str, target_status: str) -> bool:
    normalized_current = _canonical_status(current_status) or current_status
    normalized_target = _canonical_status(target_status) or target_status
    allowed = STATUS_TRANSITIONS.get(normalized_current, set())
    return normalized_target in allowed


@router.get("", response_model=TicketPageResponse)
def list_tickets(
    q: str | None = Query(default=None, min_length=1),
    queue: str = Query(default="all"),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    category: str | None = Query(default=None),
    assignee_name: str | None = Query(default=None),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketPageResponse:
    require_permissions(current_user, "tickets.read")
    _ensure_access(current_user)
    categories, priorities, statuses, _, assets = _lookup_maps(db)

    statement = _ticket_base_query(current_user)
    statement = _apply_role_scope(statement, current_user)
    statement = _apply_queue_scope(statement, queue, current_user)

    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Ticket.ticket_number.ilike(pattern),
                Ticket.title.ilike(pattern),
                Ticket.requester_name.ilike(pattern),
                Ticket.requester_email.ilike(pattern),
                Ticket.department.ilike(pattern),
                Ticket.location.ilike(pattern),
                Ticket.assignee_name.ilike(pattern),
            )
        )
    if status and status != "ALL":
        statement = statement.where(Ticket.status == (_canonical_status(status) or status))
    if priority and priority != "ALL":
        statement = statement.where(Ticket.priority == priority)
    if category and category != "ALL":
        statement = statement.where(Ticket.category == category)
    if assignee_name and assignee_name != "ALL":
        statement = statement.where(Ticket.assignee_name == assignee_name)

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    sort_map = {
        "ticket_number": Ticket.ticket_number,
        "priority": Ticket.priority,
        "status": Ticket.status,
        "sla_due_at": Ticket.sla_due_at,
        "updated_at": Ticket.updated_at,
        "created_at": Ticket.created_at,
    }
    order_column = sort_map.get(sort_by, Ticket.updated_at)
    direction = asc if sort_dir.lower() == "asc" else desc

    tickets = db.scalars(statement.order_by(direction(order_column), Ticket.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    histories = _load_histories(db, [ticket.id for ticket in tickets])
    items = [_serialize_ticket(ticket, categories, priorities, statuses, assets, calculate_response_minutes(ticket, histories.get(ticket.id, []))) for ticket in tickets]
    return TicketPageResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
def get_ticket(ticket_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> TicketDetailResponse:
    require_permissions(current_user, "tickets.read")
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    _ensure_ticket_access(ticket, current_user)
    if not _can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    categories, priorities, statuses, _, assets = _lookup_maps(db)
    histories = _load_histories(db, [ticket.id]).get(ticket.id, [])
    comments = _load_comments(db, current_user, ticket.id)
    payload = _serialize_ticket(ticket, categories, priorities, statuses, assets, calculate_response_minutes(ticket, histories))
    return TicketDetailResponse(
        **payload.model_dump(),
        comments=[
            TicketCommentResponse(
                id=comment.id,
                author_id=comment.author_id,
                author_name=comment.author_name,
                author_role=comment.author_role,
                body=comment.body,
                is_internal=comment.is_internal,
                created_at=comment.created_at,
            )
            for comment in comments
        ],
        history_count=len(histories),
    )


@router.post("", response_model=TicketDetailResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    request: TicketCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketDetailResponse:
    require_permissions(current_user, "tickets.create")
    _ensure_access(current_user)
    categories, priorities, statuses, sla_policies, assets = _lookup_maps(db)

    if request.category not in categories:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket category")
    if request.priority not in priorities:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket priority")
    if request.asset_id is not None and request.asset_id not in assets:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown asset")

    tenant_id = _resolve_tenant_id(db, current_user)
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to resolve tenant")

    requester_user: User | None = None
    assignee_user: User | None = None

    if current_user.role == "requester":
        requester_user = db.scalar(select(User).where(User.id == current_user.id))
        if requester_user is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester account not found")
        if request.assignee_id or (request.assignee_name or "").strip():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester cannot set assignee")
    else:
        requester_user = _resolve_user_by_id(db, request.requester_id, tenant_id)
        if request.requester_id and requester_user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown requester")

    if request.assignee_id:
        if not _can_manage_all_tickets(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only manager/admin can assign on create")
        assignee_user = _resolve_user_by_id(db, request.assignee_id, tenant_id)
        if assignee_user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown assignee")

    requester_name = requester_user.full_name if requester_user is not None else (request.requester_name or current_user.full_name)
    requester_email = requester_user.email if requester_user is not None else (request.requester_email or current_user.email)
    assignee_name = assignee_user.full_name if assignee_user is not None else request.assignee_name

    created_at = datetime.now(UTC)
    initial_status = "NEW"
    ticket = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ticket_number=next_ticket_number(db),
        title=request.title,
        description=request.description,
        requester_id=requester_user.id if requester_user is not None else (current_user.id if current_user.role == "requester" else None),
        requester_name=requester_name,
        requester_email=requester_email,
        department=request.department,
        location=request.location or "Не указано",
        category=request.category,
        priority=request.priority,
        status=initial_status,
        assignee_id=assignee_user.id if assignee_user is not None else None,
        assignee_name=assignee_name,
        asset_id=request.asset_id,
        created_at=created_at,
        updated_at=created_at,
    )

    if assignee_name:
        ticket.status = "ASSIGNED"

    sla_policy = sla_policies.get(request.priority)
    if sla_policy is not None:
        _apply_ticket_sla(ticket, sla_policy, created_at)

    db.add(ticket)
    db.flush()

    _write_history(
        db,
        ticket_id=ticket.id,
        actor_name=current_user.full_name,
        event_type="created",
        field_name=None,
        old_value=None,
        new_value=request.title,
        message=f"Заявка {ticket.ticket_number} создана.",
    )
    _write_history(
        db,
        ticket_id=ticket.id,
        actor_name=current_user.full_name,
        event_type="status_changed",
        field_name="status",
        old_value=None,
        new_value=ticket.status,
        message=f"Статус установлен в {_status_for_output(ticket.status)}.",
    )

    notification_events: list[TicketHistory] = []
    created_notification = create_ticket_event_notification(db, event_code="ticket_created", ticket=ticket, actor_name=current_user.full_name)
    if created_notification is not None:
        notification_events.append(_record_notification_history(ticket.id, current_user.full_name, "ticket_created"))
    if ticket.assignee_name:
        assigned_notification = create_ticket_event_notification(db, event_code="ticket_assigned", ticket=ticket, actor_name=current_user.full_name)
        if assigned_notification is not None:
            notification_events.append(_record_notification_history(ticket.id, current_user.full_name, "ticket_assigned"))
    if notification_events:
        db.add_all(notification_events)

    log_audit(
        db,
        action="ticket_created",
        entity_type="ticket",
        entity_id=ticket.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"ticket_number": ticket.ticket_number},
    )

    trigger_automation_event(
        db,
        tenant_id=ticket.tenant_id,
        trigger_type="ticket_created",
        context=build_ticket_context(ticket),
        actor_email=current_user.email,
    )

    db.commit()
    db.refresh(ticket)
    return get_ticket(ticket.id, current_user, db)


@router.patch("/{ticket_id}", response_model=TicketDetailResponse)
def patch_ticket(
    ticket_id: str,
    request: TicketPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketDetailResponse:
    require_permissions(current_user, "tickets.update")
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    _ensure_ticket_access(ticket, current_user)
    if not _can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    categories, priorities, statuses, sla_policies, assets = _lookup_maps(db)
    updates = request.model_dump(exclude_unset=True)

    if current_user.role == "it_agent":
        forbidden_fields = {"priority", "category", "sla_due_at"}
        if any(field in updates for field in forbidden_fields):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent cannot update priority/category/sla")
        if "assignee_id" in updates or "assignee_name" in updates:
            if not (ticket.assignee_id is None and not (ticket.assignee_name or "").strip() and (updates.get("assignee_id") in {None, current_user.id} or (updates.get("assignee_name") or "").strip().lower() == current_user.full_name.lower())):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent can only take unassigned ticket")

    if "status" in updates:
        target_status = _canonical_status(str(updates["status"]))
        if target_status is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket status")
        if target_status not in statuses and target_status not in STATUS_LABELS_RU:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket status")
        if not _allowed_transition(ticket.status, target_status) and not _can_manage_all_tickets(current_user):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status transition")
        updates["status"] = target_status

    if "category" in updates and updates["category"] not in categories:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket category")
    if "priority" in updates and updates["priority"] not in priorities:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket priority")
    if "asset_id" in updates and updates["asset_id"] is not None and updates["asset_id"] not in assets:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown asset")

    if "assignee_id" in updates and updates["assignee_id"] is not None:
        assignee = _resolve_user_by_id(db, updates["assignee_id"], ticket.tenant_id)
        if assignee is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown assignee")
        updates["assignee_name"] = assignee.full_name
    elif "assignee_name" in updates and updates["assignee_name"]:
        assignee = db.scalar(select(User).where(User.tenant_id == ticket.tenant_id, func.lower(User.full_name) == str(updates["assignee_name"]).strip().lower()))
        updates["assignee_id"] = assignee.id if assignee else None

    changes: list[TicketHistory] = []
    old_values = {field_name: getattr(ticket, field_name) for field_name in updates.keys()}

    for field_name, new_value in updates.items():
        old_value = getattr(ticket, field_name)
        if old_value == new_value:
            continue
        setattr(ticket, field_name, new_value)
        changes.append(
            TicketHistory(
                id=str(uuid.uuid4()),
                ticket_id=ticket.id,
                actor_name=current_user.full_name,
                event_type="status_changed" if field_name == "status" else "updated",
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                message=f"Поле {field_name} изменено.",
                created_at=datetime.now(UTC),
            )
        )

    if "priority" in updates and updates["priority"] in sla_policies:
        _apply_ticket_sla(ticket, sla_policies[updates["priority"]], ticket.created_at)

    if "status" in updates:
        if ticket.status == "RESOLVED" and ticket.resolved_at is None:
            ticket.resolved_at = datetime.now(UTC)
        if ticket.status == "CLOSED":
            ticket.closed_at = datetime.now(UTC)
        if ticket.status == "REOPENED":
            ticket.reopened_at = datetime.now(UTC)
            ticket.closed_at = None

    ticket.updated_at = datetime.now(UTC)
    ticket.sla_status = calculate_ticket_sla_status(ticket)

    if changes:
        db.add_all(changes)

    actor_user = _actor(db, current_user)
    if "assignee_id" in updates or "assignee_name" in updates:
        log_audit(
            db,
            action="ticket_assigned",
            entity_type="ticket",
            entity_id=ticket.id,
            actor_user=actor_user,
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
            metadata={"assignee": ticket.assignee_name or ""},
        )
        create_ticket_event_notification(db, event_code="ticket_assigned", ticket=ticket, actor_name=current_user.full_name)

    if "status" in updates:
        status_event = "ticket_reopened" if ticket.status == "REOPENED" else "ticket_closed" if ticket.status == "CLOSED" else "ticket_status_changed"
        log_audit(
            db,
            action=status_event,
            entity_type="ticket",
            entity_id=ticket.id,
            actor_user=actor_user,
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
            metadata={"status": _status_for_output(ticket.status)},
        )
        create_ticket_event_notification(db, event_code="ticket_status_changed", ticket=ticket, actor_name=current_user.full_name)
        if ticket.status in {"RESOLVED", "CLOSED"}:
            create_ticket_event_notification(db, event_code="ticket_resolved", ticket=ticket, actor_name=current_user.full_name)

    context = build_ticket_context(ticket)
    if "status" in updates:
        trigger_automation_event(
            db,
            tenant_id=ticket.tenant_id,
            trigger_type="ticket_status_changed",
            context=context,
            actor_email=current_user.email,
        )
    if "priority" in updates:
        trigger_automation_event(
            db,
            tenant_id=ticket.tenant_id,
            trigger_type="ticket_priority_changed",
            context=context,
            actor_email=current_user.email,
        )
    if "status" not in updates and "priority" not in updates:
        trigger_automation_event(
            db,
            tenant_id=ticket.tenant_id,
            trigger_type="ticket_assigned" if ("assignee_id" in updates or "assignee_name" in updates) else "ticket_created",
            context=context,
            actor_email=current_user.email,
        )

    db.commit()
    db.refresh(ticket)
    return get_ticket(ticket.id, current_user, db)


@router.post("/{ticket_id}/transition", response_model=TicketDetailResponse)
def transition_ticket(
    ticket_id: str,
    request: TicketTransitionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketDetailResponse:
    require_permissions(current_user, "tickets.update")
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    _ensure_ticket_access(ticket, current_user)
    if not _can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    target_status = _canonical_status(request.status)
    if target_status is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket status")
    if not _allowed_transition(ticket.status, target_status):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status transition")

    if current_user.role == "it_agent":
        assigned_to_current = ticket.assignee_id == current_user.id or (ticket.assignee_name and ticket.assignee_name.lower() == current_user.full_name.lower())
        if not assigned_to_current:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent can transition only own tickets")

    old_status = ticket.status
    ticket.status = target_status
    now = datetime.now(UTC)
    if target_status == "RESOLVED" and ticket.resolved_at is None:
        ticket.resolved_at = now
    if target_status == "CLOSED":
        ticket.closed_at = now
    if target_status == "REOPENED":
        ticket.reopened_at = now
        ticket.closed_at = None
    ticket.updated_at = now
    ticket.sla_status = calculate_ticket_sla_status(ticket)

    _write_history(
        db,
        ticket_id=ticket.id,
        actor_name=current_user.full_name,
        event_type="status_changed",
        field_name="status",
        old_value=_status_for_output(old_status),
        new_value=_status_for_output(target_status),
        message=f"Статус изменен на {_status_for_output(target_status)}.",
    )

    if request.comment and request.comment.strip():
        if request.is_internal and current_user.role == "requester":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester cannot add internal comment")
        comment = TicketComment(
            id=str(uuid.uuid4()),
            ticket_id=ticket.id,
            author_id=current_user.id,
            author_name=current_user.full_name,
            author_role=current_user.role,
            body=request.comment.strip(),
            is_internal=request.is_internal,
        )
        db.add(comment)
        _write_history(
            db,
            ticket_id=ticket.id,
            actor_name=current_user.full_name,
            event_type="comment_added",
            field_name="comment",
            old_value=None,
            new_value=request.comment.strip(),
            message="Добавлен комментарий к переходу статуса.",
        )

    actor_user = _actor(db, current_user)
    action = "ticket_reopened" if target_status == "REOPENED" else "ticket_closed" if target_status == "CLOSED" else "ticket_status_changed"
    log_audit(
        db,
        action=action,
        entity_type="ticket",
        entity_id=ticket.id,
        actor_user=actor_user,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"old_status": _status_for_output(old_status), "new_status": _status_for_output(target_status)},
    )

    notification_history: list[TicketHistory] = []
    status_notification = create_ticket_event_notification(db, event_code="ticket_status_changed", ticket=ticket, actor_name=current_user.full_name)
    if status_notification is not None:
        notification_history.append(_record_notification_history(ticket.id, current_user.full_name, "ticket_status_changed"))
    if target_status in {"RESOLVED", "CLOSED"}:
        resolved_notification = create_ticket_event_notification(db, event_code="ticket_resolved", ticket=ticket, actor_name=current_user.full_name)
        if resolved_notification is not None:
            notification_history.append(_record_notification_history(ticket.id, current_user.full_name, "ticket_resolved"))
    if notification_history:
        db.add_all(notification_history)

    db.commit()
    db.refresh(ticket)
    return get_ticket(ticket.id, current_user, db)


@router.post("/{ticket_id}/assign", response_model=TicketDetailResponse)
def assign_ticket(
    ticket_id: str,
    request: TicketAssignRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketDetailResponse:
    require_permissions(current_user, "tickets.update")
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    _ensure_ticket_access(ticket, current_user)
    if not _can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    target_assignee: User | None = None
    if _can_manage_all_tickets(current_user):
        if request.assignee_id:
            target_assignee = _resolve_user_by_id(db, request.assignee_id, ticket.tenant_id)
            if target_assignee is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown assignee")
    elif current_user.role == "it_agent":
        if ticket.assignee_id is not None or (ticket.assignee_name or "").strip():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent can take only unassigned ticket")
        target_assignee = db.scalar(select(User).where(User.id == current_user.id))
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assignment is not allowed")

    if target_assignee is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assignee is required")

    old_assignee = ticket.assignee_name
    ticket.assignee_id = target_assignee.id
    ticket.assignee_name = target_assignee.full_name
    if _canonical_status(ticket.status) in {"NEW", "TRIAGE"}:
        ticket.status = "ASSIGNED"
    ticket.updated_at = datetime.now(UTC)

    _write_history(
        db,
        ticket_id=ticket.id,
        actor_name=current_user.full_name,
        event_type="assigned",
        field_name="assignee",
        old_value=old_assignee,
        new_value=target_assignee.full_name,
        message=f"Назначено на {target_assignee.full_name}.",
    )

    if request.comment and request.comment.strip():
        comment = TicketComment(
            id=str(uuid.uuid4()),
            ticket_id=ticket.id,
            author_id=current_user.id,
            author_name=current_user.full_name,
            author_role=current_user.role,
            body=request.comment.strip(),
            is_internal=current_user.role != "requester",
        )
        db.add(comment)

    log_audit(
        db,
        action="ticket_assigned",
        entity_type="ticket",
        entity_id=ticket.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"assignee_id": target_assignee.id, "assignee_name": target_assignee.full_name},
    )

    assigned_notification = create_ticket_event_notification(db, event_code="ticket_assigned", ticket=ticket, actor_name=current_user.full_name)
    if assigned_notification is not None:
        db.add(_record_notification_history(ticket.id, current_user.full_name, "ticket_assigned"))

    db.commit()
    db.refresh(ticket)
    return get_ticket(ticket.id, current_user, db)


@router.post("/{ticket_id}/comments", response_model=TicketCommentResponse, status_code=status.HTTP_201_CREATED)
def add_comment(
    ticket_id: str,
    request: CommentCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketCommentResponse:
    require_permissions(current_user, "tickets.comment")
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    _ensure_ticket_access(ticket, current_user)
    if not _can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    if current_user.role == "requester" and request.is_internal:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester cannot add internal comments")

    comment = TicketComment(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        author_id=current_user.id,
        author_name=current_user.full_name,
        author_role=current_user.role,
        body=request.body,
        is_internal=request.is_internal,
    )
    _write_history(
        db,
        ticket_id=ticket.id,
        actor_name=current_user.full_name,
        event_type="comment_added",
        field_name="comment",
        old_value=None,
        new_value=request.body,
        message="Добавлен комментарий к заявке.",
    )

    comment_notification = create_ticket_event_notification(
        db,
        event_code="ticket_comment_added",
        ticket=ticket,
        actor_name=current_user.full_name,
        extra_context={"comment": request.body},
    )
    if comment_notification is not None:
        db.add(_record_notification_history(ticket.id, current_user.full_name, "ticket_comment_added"))

    log_audit(
        db,
        action="ticket_comment_added",
        entity_type="ticket",
        entity_id=ticket.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"comment_length": len(request.body), "is_internal": request.is_internal},
    )

    trigger_automation_event(
        db,
        tenant_id=ticket.tenant_id,
        trigger_type="ticket_comment_added",
        context=build_ticket_context(ticket),
        actor_email=current_user.email,
    )

    ticket.updated_at = datetime.now(UTC)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return TicketCommentResponse(
        id=comment.id,
        author_id=comment.author_id,
        author_name=comment.author_name,
        author_role=comment.author_role,
        body=comment.body,
        is_internal=comment.is_internal,
        created_at=comment.created_at,
    )


@router.get("/{ticket_id}/history", response_model=list[TicketHistoryResponse])
def get_ticket_history(ticket_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TicketHistoryResponse]:
    require_permissions(current_user, "tickets.read")
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    _ensure_ticket_access(ticket, current_user)
    if not _can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    histories = db.scalars(select(TicketHistory).where(TicketHistory.ticket_id == ticket.id).order_by(TicketHistory.created_at.asc())).all()
    return [
        TicketHistoryResponse(
            id=history.id,
            actor_name=history.actor_name,
            event_type=history.event_type,
            field_name=history.field_name,
            old_value=history.old_value,
            new_value=history.new_value,
            message=history.message,
            created_at=history.created_at,
        )
        for history in histories
    ]


@router.get("/{ticket_id}/knowledge-links", response_model=list[TicketKnowledgeLinkResponse])
def list_ticket_knowledge_links(
    ticket_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TicketKnowledgeLinkResponse]:
    require_permissions(current_user, "knowledge.attach.read")
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    _ensure_ticket_access(ticket, current_user)

    links = db.scalars(select(TicketKnowledgeLink).where(TicketKnowledgeLink.ticket_id == ticket_id).order_by(TicketKnowledgeLink.created_at.desc())).all()
    article_ids = [link.article_id for link in links]
    user_ids = [link.linked_by_id for link in links if link.linked_by_id]
    articles = {item.id: item for item in db.scalars(select(KnowledgeArticle).where(KnowledgeArticle.id.in_(article_ids))).all()} if article_ids else {}
    users = {item.id: item for item in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}
    return [
        TicketKnowledgeLinkResponse(
            id=link.id,
            ticket_id=link.ticket_id,
            article_id=link.article_id,
            article_number=articles[link.article_id].article_number if link.article_id in articles else "",
            article_title=articles[link.article_id].title if link.article_id in articles else "",
            linked_by_id=link.linked_by_id,
            linked_by_name=users[link.linked_by_id].full_name if link.linked_by_id and link.linked_by_id in users else None,
            link_type=link.link_type,
            confidence=link.confidence,
            comment=link.comment,
            created_at=link.created_at,
        )
        for link in links
    ]


@router.post("/{ticket_id}/knowledge-links", response_model=TicketKnowledgeLinkResponse, status_code=status.HTTP_201_CREATED)
def add_ticket_knowledge_link(
    ticket_id: str,
    request: TicketKnowledgeLinkCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketKnowledgeLinkResponse:
    require_permissions(current_user, "knowledge.attach")
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    _ensure_ticket_access(ticket, current_user)

    article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.id == request.article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown article")
    if current_user.role == "requester" and article.visibility == "internal":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester cannot attach internal article")

    existing = db.scalar(
        select(TicketKnowledgeLink).where(
            TicketKnowledgeLink.ticket_id == ticket_id,
            TicketKnowledgeLink.article_id == request.article_id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Article already linked")

    link = TicketKnowledgeLink(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        article_id=request.article_id,
        linked_by_id=current_user.id,
        link_type=request.link_type,
        confidence=request.confidence,
        comment=request.comment,
    )
    db.add(link)
    db.add(
        KnowledgeUsageLog(
            id=str(uuid.uuid4()),
            article_id=article.id,
            ticket_id=ticket_id,
            user_id=current_user.id,
            action="attached_to_ticket",
            context={"link_type": request.link_type},
        )
    )
    article.last_used_at = datetime.now(UTC)

    log_audit(
        db,
        action="knowledge_attached_to_ticket",
        entity_type="ticket",
        entity_id=ticket.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"article_id": article.id, "link_type": request.link_type},
    )

    db.commit()
    db.refresh(link)
    return TicketKnowledgeLinkResponse(
        id=link.id,
        ticket_id=link.ticket_id,
        article_id=link.article_id,
        article_number=article.article_number,
        article_title=article.title,
        linked_by_id=link.linked_by_id,
        linked_by_name=current_user.full_name,
        link_type=link.link_type,
        confidence=link.confidence,
        comment=link.comment,
        created_at=link.created_at,
    )


@router.delete("/{ticket_id}/knowledge-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_ticket_knowledge_link(
    ticket_id: str,
    link_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    require_permissions(current_user, "knowledge.attach")
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    _ensure_ticket_access(ticket, current_user)

    link = db.scalar(select(TicketKnowledgeLink).where(TicketKnowledgeLink.id == link_id, TicketKnowledgeLink.ticket_id == ticket_id))
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    db.delete(link)
    db.commit()
