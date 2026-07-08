from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.ticket import Ticket
from app.models.ticket_category import TicketCategory
from app.models.ticket_comment import TicketComment
from app.models.ticket_history import TicketHistory
from app.models.ticket_priority import TicketPriority
from app.models.ticket_status import TicketStatus
from app.models.sla import SlaPolicy
from app.models.tenant import Tenant
from app.services.asset_sla import calculate_ticket_sla_status
from app.services.automation import AutomationEngine, build_ticket_context
from app.services.audit import log_audit
from app.services.notifications import create_ticket_event_notification
from app.services.rbac import can_read_ticket, require_permissions
from app.services.service_desk import build_ticket_summary, calculate_response_minutes, next_ticket_number
from app.models.user import User

router = APIRouter(prefix="/tickets")


class TicketCommentResponse(BaseModel):
    id: str
    author_name: str
    author_role: str
    body: str
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
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    response_minutes: int | None = None


class TicketDetailResponse(TicketListResponse):
    comments: list[TicketCommentResponse] = Field(default_factory=list)
    history_count: int = 0


class TicketCreateRequest(BaseModel):
    title: str
    description: str | None = None
    requester_name: str
    requester_email: str
    department: str
    location: str
    category: str
    priority: str
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
    assignee_name: str | None = None
    sla_due_at: datetime | None = None
    asset_id: str | None = None


class CommentCreateRequest(BaseModel):
    body: str


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
    status_item = statuses.get(ticket.status)
    asset = assets.get(ticket.asset_id) if ticket.asset_id else None
    payload = build_ticket_summary(
        ticket,
        category_label=category.name if category else ticket.category,
        priority_label=priority.name if priority else ticket.priority,
        status_label=status_item.name if status_item else ticket.status,
        response_minutes=response_minutes,
    )
    return TicketListResponse(
        **payload,
        category_color=category.color if category else "#8fa6bb",
        priority_color=priority.color if priority else "#8fa6bb",
        status_color=status_item.color if status_item else "#8fa6bb",
        asset_tag=asset.asset_tag if asset else None,
        asset_name=asset.name if asset else None,
        asset_type=asset.asset_type if asset else None,
    )


def _load_histories(db: Session, ticket_ids: list[str]) -> dict[str, list[TicketHistory]]:
    if not ticket_ids:
        return {}

    histories = db.scalars(
        select(TicketHistory).where(TicketHistory.ticket_id.in_(ticket_ids)).order_by(TicketHistory.created_at.asc())
    ).all()
    grouped: dict[str, list[TicketHistory]] = {}
    for history in histories:
        grouped.setdefault(history.ticket_id, []).append(history)
    return grouped


def _load_comments(db: Session, ticket_id: str) -> list[TicketComment]:
    return db.scalars(
        select(TicketComment).where(TicketComment.ticket_id == ticket_id).order_by(TicketComment.created_at.asc())
    ).all()


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


@router.get("", response_model=list[TicketListResponse])
def list_tickets(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TicketListResponse]:
    require_permissions(current_user, "tickets.read")
    _ensure_access(current_user)
    categories, priorities, statuses, _, assets = _lookup_maps(db)
    tickets = db.scalars(_ticket_base_query(current_user, db).order_by(Ticket.updated_at.desc(), Ticket.created_at.desc())).all()
    if current_user.role == "requester":
        tickets = [item for item in tickets if item.requester_email.lower() == current_user.email.lower()]
    if current_user.role == "it_agent":
        tickets = [item for item in tickets if item.assignee_name and item.assignee_name.lower() == current_user.full_name.lower()]
    histories = _load_histories(db, [ticket.id for ticket in tickets])
    return [
        _serialize_ticket(ticket, categories, priorities, statuses, assets, calculate_response_minutes(ticket, histories.get(ticket.id, [])))
        for ticket in tickets
    ]


def _ticket_base_query(current_user: AuthUserResponse, db: Session):
    statement = select(Ticket)
    if current_user.role != "saas_root":
        statement = statement.where(Ticket.tenant_id == current_user.tenant_id)
    return statement


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
def get_ticket(ticket_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> TicketDetailResponse:
    require_permissions(current_user, "tickets.read")
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    _ensure_ticket_access(ticket, current_user)
    if not can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    categories, priorities, statuses, _, assets = _lookup_maps(db)
    histories = _load_histories(db, [ticket.id]).get(ticket.id, [])
    comments = _load_comments(db, ticket.id)
    payload = _serialize_ticket(ticket, categories, priorities, statuses, assets, calculate_response_minutes(ticket, histories))
    return TicketDetailResponse(
        **payload.model_dump(),
        comments=[
            TicketCommentResponse(
                id=comment.id,
                author_name=comment.author_name,
                author_role=comment.author_role,
                body=comment.body,
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

    created_at = datetime.now(UTC)
    ticket = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ticket_number=next_ticket_number(db),
        title=request.title,
        description=request.description,
        requester_name=request.requester_name,
        requester_email=request.requester_email,
        department=request.department,
        location=request.location,
        category=request.category,
        priority=request.priority,
        status="NEW",
        asset_id=request.asset_id,
        assignee_name=request.assignee_name,
        created_at=created_at,
        updated_at=created_at,
    )
    sla_policy = sla_policies.get(request.priority)
    if sla_policy is not None:
        _apply_ticket_sla(ticket, sla_policy, created_at)
    db.add(ticket)
    db.flush()
    db.add_all(
        [
            TicketHistory(
                id=str(uuid.uuid4()),
                ticket_id=ticket.id,
                actor_name=current_user.full_name,
                event_type="created",
                field_name=None,
                old_value=None,
                new_value=request.title,
                message=f"Заявка {ticket.ticket_number} создана.",
                created_at=created_at,
            ),
            TicketHistory(
                id=str(uuid.uuid4()),
                ticket_id=ticket.id,
                actor_name=current_user.full_name,
                event_type="status_changed",
                field_name="status",
                old_value=None,
                new_value="NEW",
                message="Статус установлен в NEW.",
                created_at=created_at,
            ),
        ]
    )
    notification_events: list[TicketHistory] = []
    created_notification = create_ticket_event_notification(
        db,
        event_code="ticket_created",
        ticket=ticket,
        actor_name=current_user.full_name,
    )
    if created_notification is not None:
        notification_events.append(_record_notification_history(ticket.id, current_user.full_name, "ticket_created"))
    if request.assignee_name:
        assigned_notification = create_ticket_event_notification(
            db,
            event_code="ticket_assigned",
            ticket=ticket,
            actor_name=current_user.full_name,
        )
        if assigned_notification is not None:
            notification_events.append(_record_notification_history(ticket.id, current_user.full_name, "ticket_assigned"))
    if notification_events:
        db.add_all(notification_events)
    actor = db.scalar(select(User).where(User.id == current_user.id))
    log_audit(
        db,
        action="ticket_created",
        entity_type="ticket",
        entity_id=ticket.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"ticket_number": ticket.ticket_number},
    )
    AutomationEngine.evaluate_rules(
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
    categories, priorities, statuses, sla_policies, assets = _lookup_maps(db)
    updates = request.model_dump(exclude_unset=True)
    if "assignee_name" in updates:
        require_permissions(current_user, "tickets.assign")
    if "status" in updates and updates.get("status") in {"RESOLVED", "CLOSED"}:
        require_permissions(current_user, "tickets.close")
    changes: list[TicketHistory] = []
    old_values = {field_name: getattr(ticket, field_name) for field_name in updates.keys()}
    old_sla_status = ticket.sla_status

    for field_name, new_value in updates.items():
        if field_name == "category" and new_value not in categories:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket category")
        if field_name == "priority" and new_value not in priorities:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket priority")
        if field_name == "status" and new_value not in statuses:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket status")
        if field_name == "asset_id" and new_value is not None and new_value not in assets:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown asset")

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

        if field_name == "priority" and new_value in sla_policies:
            _apply_ticket_sla(ticket, sla_policies[new_value], ticket.created_at)

        if field_name == "status" and new_value in {"RESOLVED", "CLOSED"} and ticket.resolved_at is None:
            ticket.resolved_at = datetime.now(UTC)

    ticket.updated_at = datetime.now(UTC)
    ticket.sla_status = calculate_ticket_sla_status(ticket)
    notification_events: list[TicketHistory] = []

    if "status" in updates and old_values.get("status") != ticket.status:
        status_notification = create_ticket_event_notification(
            db,
            event_code="ticket_status_changed",
            ticket=ticket,
            actor_name=current_user.full_name,
        )
        if status_notification is not None:
            notification_events.append(_record_notification_history(ticket.id, current_user.full_name, "ticket_status_changed"))
        if ticket.status in {"RESOLVED", "CLOSED"}:
            resolved_notification = create_ticket_event_notification(
                db,
                event_code="ticket_resolved",
                ticket=ticket,
                actor_name=current_user.full_name,
            )
            if resolved_notification is not None:
                notification_events.append(_record_notification_history(ticket.id, current_user.full_name, "ticket_resolved"))

    if "assignee_name" in updates and old_values.get("assignee_name") != ticket.assignee_name:
        assigned_notification = create_ticket_event_notification(
            db,
            event_code="ticket_assigned",
            ticket=ticket,
            actor_name=current_user.full_name,
        )
        if assigned_notification is not None:
            notification_events.append(_record_notification_history(ticket.id, current_user.full_name, "ticket_assigned"))

    if ticket.sla_status != old_sla_status and ticket.sla_status in {"WARNING", "BREACHED"}:
        sla_event_code = "sla_warning" if ticket.sla_status == "WARNING" else "sla_breached"
        sla_notification = create_ticket_event_notification(
            db,
            event_code=sla_event_code,
            ticket=ticket,
            actor_name=current_user.full_name,
        )
        if sla_notification is not None:
            notification_events.append(_record_notification_history(ticket.id, current_user.full_name, sla_event_code))

    if changes:
        db.add_all(changes)
    if notification_events:
        db.add_all(notification_events)
    actor = db.scalar(select(User).where(User.id == current_user.id))
    if "assignee_name" in updates and old_values.get("assignee_name") != ticket.assignee_name:
        log_audit(
            db,
            action="ticket_assigned",
            entity_type="ticket",
            entity_id=ticket.id,
            actor_user=actor,
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
            metadata={"assignee": ticket.assignee_name or ""},
        )
    if "status" in updates and old_values.get("status") != ticket.status:
        log_audit(
            db,
            action="ticket_status_changed",
            entity_type="ticket",
            entity_id=ticket.id,
            actor_user=actor,
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
            metadata={"status": ticket.status},
        )

    context = build_ticket_context(ticket)
    AutomationEngine.evaluate_rules(
        db,
        tenant_id=ticket.tenant_id,
        trigger_type="ticket_updated",
        context=context,
        actor_email=current_user.email,
    )
    if ticket.sla_status == "BREACHED":
        AutomationEngine.evaluate_rules(
            db,
            tenant_id=ticket.tenant_id,
            trigger_type="sla_breached",
            context=context,
            actor_email=current_user.email,
        )
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
    comment = TicketComment(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        author_name=current_user.full_name,
        author_role=current_user.role,
        body=request.body,
    )
    history_entry = TicketHistory(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        actor_name=current_user.full_name,
        event_type="comment_added",
        field_name="comment",
        old_value=None,
        new_value=request.body,
        message="Добавлен комментарий к заявке.",
        created_at=datetime.now(UTC),
    )
    comment_notification = create_ticket_event_notification(
        db,
        event_code="ticket_comment_added",
        ticket=ticket,
        actor_name=current_user.full_name,
        extra_context={"comment": request.body},
    )
    notification_history = _record_notification_history(ticket.id, current_user.full_name, "ticket_comment_added") if comment_notification is not None else None
    actor = db.scalar(select(User).where(User.id == current_user.id))
    log_audit(
        db,
        action="ticket_comment_added",
        entity_type="ticket",
        entity_id=ticket.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"comment_length": len(request.body)},
    )
    AutomationEngine.evaluate_rules(
        db,
        tenant_id=ticket.tenant_id,
        trigger_type="ticket_commented",
        context=build_ticket_context(ticket),
        actor_email=current_user.email,
    )
    ticket.updated_at = datetime.now(UTC)
    db.add_all([comment, history_entry] + ([notification_history] if notification_history is not None else []))
    db.commit()
    db.refresh(comment)
    return TicketCommentResponse(
        id=comment.id,
        author_name=comment.author_name,
        author_role=comment.author_role,
        body=comment.body,
        created_at=comment.created_at,
    )


@router.get("/{ticket_id}/history", response_model=list[TicketHistoryResponse])
def get_ticket_history(ticket_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TicketHistoryResponse]:
    _ensure_access(current_user)
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    _ensure_ticket_access(ticket, current_user)
    histories = db.scalars(
        select(TicketHistory).where(TicketHistory.ticket_id == ticket.id).order_by(TicketHistory.created_at.asc())
    ).all()
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