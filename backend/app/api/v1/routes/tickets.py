from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.sla import SlaPolicy
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.ticket_governance_action import TicketGovernanceAction
from app.models.ticket_bulk_plan import TicketBulkPlan
from app.models.ticket_category import TicketCategory
from app.models.ticket_comment import TicketComment
from app.models.ticket_history import TicketHistory
from app.models.ticket_knowledge_link import TicketKnowledgeLink
from app.models.ticket_priority import TicketPriority
from app.models.ticket_participant import TicketParticipant
from app.models.ticket_status import TicketStatus
from app.models.user import User
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_usage_log import KnowledgeUsageLog
from app.services.asset_sla import calculate_ticket_sla_status
from app.services.audit import log_audit
from app.services.automation import build_ticket_context, trigger_automation_event
from app.services.enterprise_sla import sync_ticket_sla
from app.services.notifications import create_ticket_event_notification
from app.services.rbac import (
    can_read_ticket as rbac_can_read_ticket,
    has_permission,
    is_ticket_assigned_only,
    is_ticket_requester_only,
    require_permissions,
    ticket_assigned_to_current,
    ticket_is_unassigned,
    ticket_requested_by_current,
    ticket_visibility_scopes,
)
from app.services.service_desk import build_ticket_summary, calculate_response_minutes, next_ticket_number
from app.services.sla import calculate_sla_state
from app.services.ticket_lifecycle import (
    RESOLUTION_COMPLETE_STATUSES,
    TICKET_STATUS_TRANSITIONS,
    TicketActorKind,
    TicketLifecycleError,
    allowed_ticket_transition,
    canonical_ticket_status,
    transition_ticket_status,
    transition_ticket_status_path,
)

router = APIRouter(prefix="/tickets")

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

STATUS_TRANSITIONS = TICKET_STATUS_TRANSITIONS
CLOSED_STATUSES = RESOLUTION_COMPLETE_STATUSES


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
    tenant_id: str | None
    ticket_number: str | None
    title: str
    description: str | None
    requester_id: str | None = None
    requester_name: str
    requester_email: str
    requester_contact: str | None = None
    created_by_id: str | None = None
    created_by_name: str | None = None
    creation_channel: str = "LEGACY"
    parent_ticket_id: str | None = None
    merged_into_id: str | None = None
    governance_version: int = 1
    merge_reason: str | None = None
    merged_by_id: str | None = None
    merged_by_name: str | None = None
    merged_at: datetime | None = None
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
    allowed_transitions: list[str] = Field(default_factory=list)
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
    satisfaction_score: int | None = None
    reopen_reason: str | None = None
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
    on_behalf_reason: str | None = Field(default=None, max_length=2_000)
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
    expected_version: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class CommentCreateRequest(BaseModel):
    body: str
    is_internal: bool = False


class TicketTransitionRequest(BaseModel):
    status: str
    comment: str | None = None
    is_internal: bool = False
    satisfaction_score: int | None = Field(default=None, ge=1, le=5)
    reopen_reason: str | None = None
    expected_version: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class TicketAssignRequest(BaseModel):
    assignee_id: str | None = None
    comment: str | None = None


class TicketBulkPreviewRequest(BaseModel):
    ticket_ids: list[str] = Field(min_length=1, max_length=50)
    status: str | None = None
    assignee_id: str | None = None
    comment: str | None = Field(default=None, max_length=500)


class TicketBulkTargetPreview(BaseModel):
    ticket_id: str
    ticket_number: str | None
    title: str
    current_status: str
    effective_status: str
    target_status: str | None
    current_assignee_name: str | None
    target_assignee_name: str | None
    eligible: bool
    reason: str | None


class TicketBulkPreviewResponse(BaseModel):
    plan_id: str
    status: str
    revision: int
    operation_sha256: str
    targets_sha256: str
    confirmation_phrase: str
    eligible_count: int
    skipped_count: int
    expires_at: datetime
    targets: list[TicketBulkTargetPreview]


class TicketBulkExecuteRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    confirmation_phrase: str = Field(min_length=1, max_length=80)


class TicketBulkExecuteResponse(BaseModel):
    plan_id: str
    status: str
    revision: int
    updated_count: int
    skipped_count: int
    already_executed: bool
    executed_at: datetime


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


class TicketParticipantCreateRequest(BaseModel):
    user_id: str | None = None
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    participant_role: str = Field(default="WATCHER", pattern=r"^(WATCHER|COLLABORATOR|REQUESTER_REPRESENTATIVE)$")
    notification_scope: str = Field(default="PUBLIC_ONLY", pattern=r"^(ALL|PUBLIC_ONLY|STATUS_ONLY|NONE)$")
    notify_in_app: bool = True
    notify_email: bool = False
    reason: str = Field(min_length=3, max_length=2_000)

    @model_validator(mode="after")
    def validate_identity(self) -> "TicketParticipantCreateRequest":
        if not self.user_id and (not self.display_name or not self.email):
            raise ValueError("user_id or display_name and email are required")
        return self


class TicketParticipantPatchRequest(BaseModel):
    expected_version: int = Field(ge=1)
    participant_role: str | None = Field(default=None, pattern=r"^(WATCHER|COLLABORATOR|REQUESTER_REPRESENTATIVE)$")
    notification_scope: str | None = Field(default=None, pattern=r"^(ALL|PUBLIC_ONLY|STATUS_ONLY|NONE)$")
    notify_in_app: bool | None = None
    notify_email: bool | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class TicketWatchRequest(BaseModel):
    notification_scope: str = Field(default="PUBLIC_ONLY", pattern=r"^(ALL|PUBLIC_ONLY|STATUS_ONLY|NONE)$")
    notify_in_app: bool = True
    notify_email: bool = False


class TicketParticipantResponse(BaseModel):
    id: str
    ticket_id: str
    user_id: str | None
    display_name: str
    email: str
    participant_role: str
    notification_scope: str
    notify_in_app: bool
    notify_email: bool
    is_active: bool
    version_number: int
    added_by_id: str | None
    removed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TicketParticipantCandidateResponse(BaseModel):
    id: str
    full_name: str
    email: str
    role: str


class TicketRequesterCandidateResponse(BaseModel):
    id: str
    full_name: str
    email: str
    department: str | None
    location: str | None
    phone: str | None
    role: str


class TicketDuplicateCandidateResponse(BaseModel):
    id: str
    ticket_number: str | None
    title: str
    requester_name: str
    requester_email: str
    category: str
    priority: str
    status: str
    created_at: datetime
    governance_version: int
    score: float
    evidence: list[str]
    pair_key: str


class TicketDuplicateDismissRequest(BaseModel):
    expected_ticket_version: int = Field(ge=1)
    expected_candidate_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class TicketMergeRequest(BaseModel):
    target_ticket_id: str
    expected_source_version: int = Field(ge=1)
    expected_target_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class TicketSplitRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    category: str | None = None
    priority: str | None = None
    expected_source_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class TicketGovernanceActionResponse(BaseModel):
    id: str
    action_type: str
    source_ticket_id: str
    target_ticket_id: str | None
    reason: str
    actor_name: str
    score: float | None
    evidence: dict[str, object] | None
    created_at: datetime


class TicketGovernanceResultResponse(BaseModel):
    action: TicketGovernanceActionResponse
    source_ticket_id: str
    target_ticket_id: str | None
    source_version: int
    target_version: int | None
    already_applied: bool = False


def _canonical_status(value: str | None) -> str | None:
    return canonical_ticket_status(value)


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


def _ticket_visibility_scopes(current_user: AuthUserResponse) -> frozenset[str]:
    return ticket_visibility_scopes(current_user)


def _is_requester_only(current_user: AuthUserResponse) -> bool:
    return is_ticket_requester_only(current_user)


def _is_assigned_only(current_user: AuthUserResponse) -> bool:
    return is_ticket_assigned_only(current_user)


def _ticket_requested_by_current(ticket: Ticket, current_user: AuthUserResponse) -> bool:
    return ticket_requested_by_current(current_user, ticket)


def _ticket_assigned_to_current(ticket: Ticket, current_user: AuthUserResponse) -> bool:
    return ticket_assigned_to_current(current_user, ticket)


def _ticket_is_unassigned(ticket: Ticket) -> bool:
    return ticket_is_unassigned(ticket)


def _can_read_ticket(current_user: AuthUserResponse, ticket: Ticket) -> bool:
    return rbac_can_read_ticket(current_user, ticket)


def _can_manage_all_tickets(current_user: AuthUserResponse) -> bool:
    return has_permission(current_user, "tickets.assign")


def _can_self_assign_ticket(current_user: AuthUserResponse) -> bool:
    return has_permission(
        current_user,
        "tickets.self_assign",
    ) or _can_manage_all_tickets(current_user)


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
    payload["requester_contact"] = ticket.requester_contact
    payload["created_by_id"] = ticket.created_by_id
    payload["created_by_name"] = ticket.created_by_name
    payload["creation_channel"] = ticket.creation_channel
    payload["parent_ticket_id"] = ticket.parent_ticket_id
    payload["merged_into_id"] = ticket.merged_into_id
    payload["governance_version"] = ticket.governance_version
    payload["merge_reason"] = ticket.merge_reason
    payload["merged_by_id"] = ticket.merged_by_id
    payload["merged_by_name"] = ticket.merged_by_name
    payload["merged_at"] = ticket.merged_at
    payload["assignee_id"] = ticket.assignee_id
    payload["closed_at"] = ticket.closed_at
    payload["reopened_at"] = ticket.reopened_at
    payload["satisfaction_score"] = ticket.satisfaction_score
    payload["reopen_reason"] = ticket.reopen_reason
    sla_state = calculate_sla_state(ticket)
    return TicketListResponse(
        **payload,
        allowed_transitions=sorted(TICKET_STATUS_TRANSITIONS[status_code]),
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
    if _is_requester_only(current_user):
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
    scopes = _ticket_visibility_scopes(current_user)
    if "all" in scopes:
        return statement
    clauses = []
    if "requester" in scopes:
        clauses.append(
            or_(
                Ticket.requester_id == current_user.id,
                func.lower(Ticket.requester_email) == current_user.email.lower(),
            )
        )
    if "assigned" in scopes:
        clauses.append(
            or_(
                Ticket.assignee_id == current_user.id,
                func.lower(func.coalesce(Ticket.assignee_name, ""))
                == current_user.full_name.lower(),
                and_(
                    Ticket.assignee_id.is_(None),
                    or_(
                        Ticket.assignee_name.is_(None),
                        func.length(func.trim(Ticket.assignee_name)) == 0,
                    ),
                ),
            )
        )
    if not clauses:
        return statement.where(Ticket.id.is_(None))
    return statement.where(or_(*clauses))


def _apply_queue_scope(statement, queue: str, current_user: AuthUserResponse):
    now = datetime.now(UTC)
    queue_value = queue.lower()
    if queue_value == "mine":
        scopes = _ticket_visibility_scopes(current_user)
        clauses = []
        if "requester" in scopes and "all" not in scopes:
            clauses.append(
                or_(
                    Ticket.requester_id == current_user.id,
                    func.lower(Ticket.requester_email) == current_user.email.lower(),
                )
            )
        if "all" in scopes or "assigned" in scopes:
            clauses.append(
                or_(
                Ticket.assignee_id == current_user.id,
                    func.lower(func.coalesce(Ticket.assignee_name, ""))
                    == current_user.full_name.lower(),
                )
            )
        return statement.where(or_(*clauses)) if clauses else statement.where(Ticket.id.is_(None))
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
    statement = select(User).where(User.id == user_id, User.is_active.is_(True))
    if tenant_id is not None:
        statement = statement.where(User.tenant_id == tenant_id)
    return db.scalar(statement)


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.scalar(select(User).where(User.id == current_user.id))


def _bulk_canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _bulk_sha256(value: object) -> str:
    payload = value if isinstance(value, str) else _bulk_canonical_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ticket_bulk_fingerprint(ticket: Ticket) -> str:
    updated_at = ticket.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return _bulk_sha256(
        {
            "id": ticket.id,
            "tenant_id": ticket.tenant_id,
            "status": _canonical_status(ticket.status),
            "assignee_id": ticket.assignee_id,
            "assignee_name": ticket.assignee_name,
            "governance_version": ticket.governance_version,
            "updated_at": updated_at.astimezone(UTC).isoformat(),
        }
    )


def _bulk_expired(plan: TicketBulkPlan) -> bool:
    expires_at = plan.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def _bulk_target_preview(
    ticket: Ticket,
    current_user: AuthUserResponse,
    *,
    target_status: str | None,
    target_assignee: User | None,
) -> tuple[TicketBulkTargetPreview, dict[str, object] | None]:
    reason: str | None = None
    effective_status = _canonical_status(ticket.status) or ticket.status
    if not _can_read_ticket(current_user, ticket):
        reason = "Ticket is not visible to the current user"
    if target_assignee is not None and not _can_manage_all_tickets(current_user):
        reason = "Bulk assignment requires queue management scope"
    if _is_assigned_only(current_user):
        assigned_to_current = (
            _ticket_assigned_to_current(ticket, current_user)
        )
        if not assigned_to_current:
            reason = "Agent can bulk-transition only assigned tickets"
    if target_assignee is not None and effective_status in {"NEW", "TRIAGE"}:
        effective_status = "ASSIGNED"
    if target_status is not None:
        if target_status == effective_status:
            reason = "Ticket is already in the target status"
        elif not _allowed_transition(effective_status, target_status):
            reason = (
                f"Invalid transition {effective_status} -> {target_status}"
            )
    eligible = reason is None
    preview = TicketBulkTargetPreview(
        ticket_id=ticket.id,
        ticket_number=ticket.ticket_number,
        title=ticket.title,
        current_status=_canonical_status(ticket.status) or ticket.status,
        effective_status=effective_status,
        target_status=target_status,
        current_assignee_name=ticket.assignee_name,
        target_assignee_name=(
            target_assignee.full_name if target_assignee is not None else None
        ),
        eligible=eligible,
        reason=reason,
    )
    if not eligible:
        return preview, None
    return preview, {
        "ticket_id": ticket.id,
        "fingerprint": _ticket_bulk_fingerprint(ticket),
        "current_status": _canonical_status(ticket.status) or ticket.status,
        "effective_status": effective_status,
    }


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
    return allowed_ticket_transition(current_status, target_status)


def _lifecycle_actor_kind(current_user: AuthUserResponse) -> TicketActorKind:
    if _is_requester_only(current_user):
        return "REQUESTER"
    if _is_assigned_only(current_user):
        return "ASSIGNED_AGENT"
    return "MANAGER"


def _raise_lifecycle_http(error: TicketLifecycleError) -> None:
    if error.code == "not_found":
        raise HTTPException(status_code=404, detail=str(error)) from error
    if error.code == "forbidden":
        raise HTTPException(status_code=403, detail=str(error)) from error
    if error.code in {"version_conflict", "state_conflict", "idempotency_conflict"}:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if error.code == "validation_error":
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise HTTPException(status_code=400, detail=str(error)) from error


def _duplicate_pair_key(first_ticket_id: str, second_ticket_id: str) -> str:
    return ":".join(sorted((first_ticket_id, second_ticket_id)))


def _normalized_duplicate_text(value: str | None) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", value or "", flags=re.UNICODE).casefold().split())


def _aware_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _duplicate_score(source: Ticket, candidate: Ticket) -> tuple[float, list[str]]:
    source_title = _normalized_duplicate_text(source.title)
    candidate_title = _normalized_duplicate_text(candidate.title)
    title_similarity = SequenceMatcher(None, source_title, candidate_title).ratio()
    score = title_similarity * 50
    evidence: list[str] = []
    if title_similarity >= 0.85:
        evidence.append("very_similar_title")
    elif title_similarity >= 0.60:
        evidence.append("similar_title")

    if source.requester_email.casefold() == candidate.requester_email.casefold():
        score += 20
        evidence.append("same_requester")
    if source.category == candidate.category:
        score += 15
        evidence.append("same_category")
    if source.asset_id and source.asset_id == candidate.asset_id:
        score += 10
        evidence.append("same_asset")

    source_description = _normalized_duplicate_text(source.description)
    candidate_description = _normalized_duplicate_text(candidate.description)
    if source_description and candidate_description:
        description_similarity = SequenceMatcher(
            None, source_description, candidate_description
        ).ratio()
        score += description_similarity * 10
        if description_similarity >= 0.70:
            evidence.append("similar_description")

    age = abs((_aware_datetime(source.created_at) - _aware_datetime(candidate.created_at)).total_seconds())
    if age <= 24 * 60 * 60:
        score += 10
        evidence.append("created_within_24h")
    elif age <= 7 * 24 * 60 * 60:
        score += 5
        evidence.append("created_within_7d")
    return round(min(100.0, score), 1), evidence


def _serialize_governance_action(
    action: TicketGovernanceAction,
) -> TicketGovernanceActionResponse:
    return TicketGovernanceActionResponse(
        id=action.id,
        action_type=action.action_type,
        source_ticket_id=action.source_ticket_id,
        target_ticket_id=action.target_ticket_id,
        reason=action.reason,
        actor_name=action.actor_name,
        score=action.score,
        evidence=action.evidence_json,
        created_at=action.created_at,
    )


def _governance_result(
    action: TicketGovernanceAction,
    source: Ticket,
    target: Ticket | None,
    *,
    already_applied: bool,
) -> TicketGovernanceResultResponse:
    return TicketGovernanceResultResponse(
        action=_serialize_governance_action(action),
        source_ticket_id=source.id,
        target_ticket_id=target.id if target is not None else action.target_ticket_id,
        source_version=source.governance_version,
        target_version=target.governance_version if target is not None else None,
        already_applied=already_applied,
    )


def _visible_governance_ticket(
    db: Session,
    ticket_id: str,
    current_user: AuthUserResponse,
) -> Ticket:
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id).with_for_update())
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    _ensure_ticket_access(ticket, current_user)
    if not _can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if ticket.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ticket must belong to a tenant before governance actions",
        )
    return ticket


def _idempotent_action(
    db: Session,
    *,
    tenant_id: str,
    action_type: str,
    idempotency_key: str,
) -> TicketGovernanceAction | None:
    return db.scalar(
        select(TicketGovernanceAction).where(
            TicketGovernanceAction.tenant_id == tenant_id,
            TicketGovernanceAction.action_type == action_type,
            TicketGovernanceAction.idempotency_key == idempotency_key,
        )
    )


def _assert_idempotent_action_matches(
    action: TicketGovernanceAction,
    *,
    source_ticket_id: str,
    target_ticket_id: str | None,
) -> None:
    if (
        action.source_ticket_id != source_ticket_id
        or action.target_ticket_id != target_ticket_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used for another ticket operation",
        )


def _locked_governance_pair(
    db: Session,
    source_ticket_id: str,
    target_ticket_id: str,
    current_user: AuthUserResponse,
) -> tuple[Ticket, Ticket]:
    tickets = db.scalars(
        select(Ticket)
        .where(Ticket.id.in_([source_ticket_id, target_ticket_id]))
        .order_by(Ticket.id.asc())
        .with_for_update()
    ).all()
    by_id = {ticket.id: ticket for ticket in tickets}
    source = by_id.get(source_ticket_id)
    target = by_id.get(target_ticket_id)
    if source is None or target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    for ticket in (source, target):
        _ensure_ticket_access(ticket, current_user)
        if not _can_read_ticket(current_user, ticket):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if source.tenant_id is None or source.tenant_id != target.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tickets must belong to the same tenant",
        )
    return source, target


def _assert_governance_version(ticket: Ticket, expected: int, label: str) -> None:
    if ticket.governance_version != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{label} governance version changed; refresh and retry",
        )


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


@router.get(
    "/requester-candidates",
    response_model=list[TicketRequesterCandidateResponse],
)
def list_ticket_requester_candidates(
    q: str | None = Query(default=None, min_length=1, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TicketRequesterCandidateResponse]:
    require_permissions(current_user, "tickets.create.on_behalf")
    _ensure_access(current_user)
    tenant_id = _resolve_tenant_id(db, current_user)
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to resolve tenant")

    statement = select(User).where(
        User.tenant_id == tenant_id,
        User.is_active.is_(True),
    )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                User.department.ilike(pattern),
            )
        )
    users = db.scalars(statement.order_by(User.full_name.asc()).limit(limit)).all()
    return [
        TicketRequesterCandidateResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            department=user.department,
            location=user.location,
            phone=user.phone,
            role=user.role.code if user.role is not None else "custom",
        )
        for user in users
    ]


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

    actor_user = _actor(db, current_user)
    if actor_user is None or not actor_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active creator account required")

    requester_user: User | None = None
    assignee_user: User | None = None
    requester_only = _is_requester_only(current_user)

    submitted_email = (request.requester_email or "").strip().lower()
    actor_email = actor_user.email.strip().lower()
    if requester_only:
        if request.requester_id and request.requester_id != actor_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester cannot create on behalf of another user")
        if submitted_email and submitted_email != actor_email:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester identity cannot be overridden")
        requester_user = actor_user
        if request.assignee_id or (request.assignee_name or "").strip():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester cannot set assignee")
    else:
        if request.requester_id:
            requester_user = _resolve_user_by_id(db, request.requester_id, tenant_id)
            if requester_user is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown or inactive requester")
        elif not submitted_email or submitted_email == actor_email:
            if actor_user.tenant_id == tenant_id:
                requester_user = actor_user

    is_on_behalf = requester_user is None or requester_user.id != actor_user.id
    on_behalf_reason = (request.on_behalf_reason or "").strip()
    if is_on_behalf:
        require_permissions(current_user, "tickets.create.on_behalf")
        if len(on_behalf_reason) < 3:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="On-behalf registration reason must contain at least 3 characters",
            )
        if requester_user is None:
            if not (request.requester_name or "").strip() or not submitted_email or "@" not in submitted_email:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="External requester name and valid email are required",
                )

    if request.assignee_id:
        if not _can_manage_all_tickets(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only manager/admin can assign on create")
        assignee_user = _resolve_user_by_id(db, request.assignee_id, tenant_id)
        if assignee_user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown assignee")
    elif (request.assignee_name or "").strip() and not _can_manage_all_tickets(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only manager/admin can assign on create")

    requester_name = requester_user.full_name if requester_user is not None else (request.requester_name or "").strip()
    requester_email = requester_user.email if requester_user is not None else submitted_email
    requester_contact = (request.requester_contact or "").strip() or (
        requester_user.phone if requester_user is not None else None
    )
    assignee_name = assignee_user.full_name if assignee_user is not None else request.assignee_name

    created_at = datetime.now(UTC)
    # Creation starts in exactly one canonical state. This is initialization,
    # not a lifecycle mutation; later assignment changes use the lifecycle service.
    initial_status = "ASSIGNED" if assignee_name else "NEW"
    ticket = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ticket_number=next_ticket_number(db),
        title=request.title,
        description=request.description,
        requester_id=requester_user.id if requester_user is not None else None,
        requester_name=requester_name,
        requester_email=requester_email,
        requester_contact=requester_contact,
        created_by_id=actor_user.id,
        created_by_name=actor_user.full_name,
        creation_channel="ON_BEHALF" if is_on_behalf else "SELF_SERVICE",
        on_behalf_reason=on_behalf_reason if is_on_behalf else None,
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

    sla_policy = sla_policies.get(request.priority)
    if sla_policy is not None:
        _apply_ticket_sla(ticket, sla_policy, created_at)

    db.add(ticket)
    db.flush()
    sync_ticket_sla(
        db,
        ticket,
        old_status=None,
        actor=_actor(db, current_user),
        at=created_at,
    )

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
    if is_on_behalf:
        _write_history(
            db,
            ticket_id=ticket.id,
            actor_name=current_user.full_name,
            event_type="created_on_behalf",
            field_name="requester",
            old_value=None,
            new_value=requester_name,
            message=f"Заявка зарегистрирована сотрудником от имени {requester_name}.",
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
        actor_user=actor_user,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "ticket_number": ticket.ticket_number,
            "creation_channel": ticket.creation_channel,
            "requester_id": ticket.requester_id,
        },
    )
    if is_on_behalf:
        log_audit(
            db,
            action="ticket_created_on_behalf",
            entity_type="ticket",
            entity_id=ticket.id,
            actor_user=actor_user,
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
            metadata={
                "ticket_number": ticket.ticket_number,
                "requester_id": ticket.requester_id,
                "reason": on_behalf_reason,
            },
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
    ticket = db.scalar(
        select(Ticket).where(Ticket.id == ticket_id).with_for_update()
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    _ensure_ticket_access(ticket, current_user)
    if not _can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    categories, priorities, statuses, sla_policies, assets = _lookup_maps(db)
    updates = request.model_dump(exclude_unset=True)
    expected_version = updates.pop("expected_version", None)
    idempotency_key = updates.pop("idempotency_key", None)
    old_status_before_update = ticket.status
    target_status: str | None = None

    if _is_assigned_only(current_user):
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
        updates.pop("status")

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

    if changes:
        ticket.updated_at = datetime.now(UTC)

    if changes:
        db.add_all(changes)

    actor_user = _actor(db, current_user)
    status_transition_applied = False
    if target_status is not None:
        try:
            transition_result = transition_ticket_status(
                db,
                ticket,
                target_status,
                actor_name=current_user.full_name,
                actor_kind=_lifecycle_actor_kind(current_user),
                actor_user=actor_user,
                actor_email=current_user.email,
                allow_cross_tenant_actor=current_user.role == "saas_root",
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                source="ticket_patch",
                priority_changed="priority" in updates,
                ip_address=http_request.client.host if http_request.client else None,
                user_agent=http_request.headers.get("user-agent"),
            )
            status_transition_applied = not transition_result.already_applied
        except TicketLifecycleError as error:
            _raise_lifecycle_http(error)
    elif (
        sync_ticket_sla(
            db,
            ticket,
            old_status=old_status_before_update,
            actor=actor_user,
            priority_changed="priority" in updates,
            at=ticket.updated_at,
        )
        is None
    ):
        ticket.sla_status = calculate_ticket_sla_status(ticket)
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

    context = build_ticket_context(ticket)
    if target_status is not None and status_transition_applied:
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
    if target_status is None and "priority" not in updates:
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
    requester_only = _is_requester_only(current_user)
    if requester_only:
        require_permissions(current_user, "tickets.comment")
    else:
        require_permissions(current_user, "tickets.update")
    _ensure_access(current_user)
    ticket = db.scalar(
        select(Ticket).where(Ticket.id == ticket_id).with_for_update()
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    _ensure_ticket_access(ticket, current_user)
    if not _can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    target_status = _canonical_status(request.status)
    if target_status is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket status")
    if request.is_internal and requester_only:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester cannot add internal comment")
    actor_user = _actor(db, current_user)
    try:
        transition_result = transition_ticket_status(
            db,
            ticket,
            target_status,
            actor_name=current_user.full_name,
            actor_kind=_lifecycle_actor_kind(current_user),
            actor_user=actor_user,
            actor_email=current_user.email,
            allow_cross_tenant_actor=current_user.role == "saas_root",
            expected_version=request.expected_version,
            idempotency_key=request.idempotency_key,
            comment=request.comment,
            is_internal_comment=request.is_internal,
            satisfaction_score=request.satisfaction_score,
            reopen_reason=request.reopen_reason,
            source="ticket_transition_api",
            reason=f"Статус изменен на {_status_for_output(target_status)}.",
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
        )
    except TicketLifecycleError as error:
        _raise_lifecycle_http(error)

    if not transition_result.already_applied:
        trigger_automation_event(
            db,
            tenant_id=ticket.tenant_id,
            trigger_type="ticket_status_changed",
            context=build_ticket_context(ticket),
            actor_email=current_user.email,
        )

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
    ticket = db.scalar(
        select(Ticket).where(Ticket.id == ticket_id).with_for_update()
    )
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
        elif _can_self_assign_ticket(current_user):
            target_assignee = db.scalar(select(User).where(User.id == current_user.id))
    elif _can_self_assign_ticket(current_user):
        if ticket.assignee_id is not None or (ticket.assignee_name or "").strip():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent can take only unassigned ticket")
        target_assignee = db.scalar(select(User).where(User.id == current_user.id))
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assignment is not allowed")

    if target_assignee is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assignee is required")

    old_assignee = ticket.assignee_name
    old_status = ticket.status
    ticket.assignee_id = target_assignee.id
    ticket.assignee_name = target_assignee.full_name
    now = datetime.now(UTC)
    ticket.updated_at = now
    actor_user = _actor(db, current_user)
    if _canonical_status(old_status) in {"NEW", "TRIAGE"}:
        try:
            transition_ticket_status(
                db,
                ticket,
                "ASSIGNED",
                actor_name=current_user.full_name,
                actor_kind=_lifecycle_actor_kind(current_user),
                actor_user=actor_user,
                actor_email=current_user.email,
                allow_cross_tenant_actor=current_user.role == "saas_root",
                at=now,
                source="ticket_assignment",
                reason=f"Ticket assigned to {target_assignee.full_name}.",
                ip_address=http_request.client.host if http_request.client else None,
                user_agent=http_request.headers.get("user-agent"),
            )
        except TicketLifecycleError as error:
            _raise_lifecycle_http(error)
    else:
        sync_ticket_sla(
            db,
            ticket,
            old_status=old_status,
            actor=actor_user,
            at=now,
        )

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
            is_internal=not _is_requester_only(current_user),
        )
        db.add(comment)

    log_audit(
        db,
        action="ticket_assigned",
        entity_type="ticket",
        entity_id=ticket.id,
        actor_user=actor_user,
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


@router.post(
    "/bulk/preview",
    response_model=TicketBulkPreviewResponse,
)
def preview_ticket_bulk_action(
    payload: TicketBulkPreviewRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketBulkPreviewResponse:
    require_permissions(
        current_user,
        "tickets.read",
        "tickets.update",
        "tickets.bulk.execute",
    )
    _ensure_access(current_user)
    if _is_requester_only(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requester cannot execute bulk ticket actions",
        )
    if payload.status is None and payload.assignee_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Bulk action requires status or assignee",
        )
    target_status = _canonical_status(payload.status)
    if payload.status is not None and (
        target_status is None
        or target_status not in set(STATUS_TRANSITIONS) | set(STATUS_LABELS_RU)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown target status",
        )
    if payload.assignee_id is not None:
        require_permissions(current_user, "tickets.assign")
        if not _can_manage_all_tickets(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bulk assignment requires queue management scope",
            )

    ticket_ids = list(dict.fromkeys(payload.ticket_ids))
    statement = select(Ticket).where(Ticket.id.in_(ticket_ids))
    if current_user.role != "saas_root":
        statement = statement.where(Ticket.tenant_id == current_user.tenant_id)
    tickets = list(db.scalars(statement).all())
    tenant_ids = {ticket.tenant_id for ticket in tickets}
    if len(tenant_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A bulk plan must contain tickets from one tenant",
        )
    plan_tenant_id = (
        next(iter(tenant_ids))
        if tenant_ids
        else current_user.tenant_id
    )
    target_assignee: User | None = None
    if payload.assignee_id is not None:
        target_assignee = _resolve_user_by_id(
            db,
            payload.assignee_id,
            plan_tenant_id,
        )
        if target_assignee is None or not target_assignee.is_active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Assignee is unknown, inactive, or outside plan tenant",
            )

    by_id = {ticket.id: ticket for ticket in tickets}
    previews: list[TicketBulkTargetPreview] = []
    eligible_targets: list[dict[str, object]] = []
    for ticket_id in ticket_ids:
        ticket = by_id.get(ticket_id)
        if ticket is None:
            previews.append(
                TicketBulkTargetPreview(
                    ticket_id=ticket_id,
                    ticket_number=None,
                    title="Unavailable ticket",
                    current_status="UNKNOWN",
                    effective_status="UNKNOWN",
                    target_status=target_status,
                    current_assignee_name=None,
                    target_assignee_name=(
                        target_assignee.full_name
                        if target_assignee is not None
                        else None
                    ),
                    eligible=False,
                    reason="Ticket was not found in the permitted tenant scope",
                )
            )
            continue
        preview, target = _bulk_target_preview(
            ticket,
            current_user,
            target_status=target_status,
            target_assignee=target_assignee,
        )
        previews.append(preview)
        if target is not None:
            eligible_targets.append(target)

    operation = {
        "status": target_status,
        "assignee_id": (
            target_assignee.id if target_assignee is not None else None
        ),
        "assignee_name": (
            target_assignee.full_name if target_assignee is not None else None
        ),
        "comment": (payload.comment or "").strip() or None,
    }
    targets_evidence = {
        "eligible": eligible_targets,
        "skipped": [
            {
                "ticket_id": item.ticket_id,
                "reason": item.reason,
            }
            for item in previews
            if not item.eligible
        ],
    }
    operation_json = _bulk_canonical_json(operation)
    targets_json = _bulk_canonical_json(targets_evidence)
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    plan = TicketBulkPlan(
        id=str(uuid.uuid4()),
        tenant_id=plan_tenant_id,
        actor_user_id=current_user.id,
        status="PREVIEWED",
        operation_json=operation_json,
        operation_sha256=_bulk_sha256(operation_json),
        targets_json=targets_json,
        targets_sha256=_bulk_sha256(targets_json),
        eligible_count=len(eligible_targets),
        skipped_count=len(previews) - len(eligible_targets),
        revision=1,
        expires_at=expires_at,
    )
    db.add(plan)
    log_audit(
        db,
        action="ticket.bulk_previewed",
        entity_type="ticket_bulk_plan",
        entity_id=plan.id,
        actor_user=_actor(db, current_user),
        tenant_id=plan_tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "operation_sha256": plan.operation_sha256,
            "targets_sha256": plan.targets_sha256,
            "eligible_count": plan.eligible_count,
            "skipped_count": plan.skipped_count,
            "expires_at": expires_at.isoformat(),
        },
    )
    db.commit()
    db.refresh(plan)
    return TicketBulkPreviewResponse(
        plan_id=plan.id,
        status=plan.status,
        revision=plan.revision,
        operation_sha256=plan.operation_sha256,
        targets_sha256=plan.targets_sha256,
        confirmation_phrase=f"APPLY {plan.eligible_count}",
        eligible_count=plan.eligible_count,
        skipped_count=plan.skipped_count,
        expires_at=plan.expires_at,
        targets=previews,
    )


@router.post(
    "/bulk/{plan_id}/execute",
    response_model=TicketBulkExecuteResponse,
)
def execute_ticket_bulk_action(
    plan_id: str,
    payload: TicketBulkExecuteRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketBulkExecuteResponse:
    require_permissions(
        current_user,
        "tickets.read",
        "tickets.update",
        "tickets.bulk.execute",
    )
    _ensure_access(current_user)
    plan = db.get(TicketBulkPlan, plan_id, with_for_update=True)
    if (
        plan is None
        or plan.actor_user_id != current_user.id
        or (
            current_user.role != "saas_root"
            and plan.tenant_id != current_user.tenant_id
        )
    ):
        raise HTTPException(status_code=404, detail="Bulk plan not found")
    if plan.status == "EXECUTED":
        executed_at = plan.executed_at or plan.updated_at
        return TicketBulkExecuteResponse(
            plan_id=plan.id,
            status=plan.status,
            revision=plan.revision,
            updated_count=plan.eligible_count,
            skipped_count=plan.skipped_count,
            already_executed=True,
            executed_at=executed_at,
        )
    if plan.status != "PREVIEWED":
        raise HTTPException(
            status_code=409,
            detail=f"Bulk plan cannot execute from {plan.status}",
        )
    if _bulk_expired(plan):
        plan.status = "EXPIRED"
        plan.revision += 1
        db.commit()
        raise HTTPException(status_code=409, detail="Bulk plan expired")
    if plan.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail=f"Revision conflict: current revision is {plan.revision}",
        )
    confirmation_phrase = f"APPLY {plan.eligible_count}"
    if payload.confirmation_phrase.strip() != confirmation_phrase:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Confirmation phrase must be {confirmation_phrase}",
        )
    if plan.eligible_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Bulk plan has no eligible tickets",
        )

    operation = json.loads(plan.operation_json)
    evidence = json.loads(plan.targets_json)
    eligible_targets = list(evidence.get("eligible") or [])
    if _bulk_sha256(plan.operation_json) != plan.operation_sha256 or (
        _bulk_sha256(plan.targets_json) != plan.targets_sha256
    ):
        raise HTTPException(
            status_code=409,
            detail="Bulk plan evidence integrity check failed",
        )
    target_status = operation.get("status")
    target_assignee: User | None = None
    if operation.get("assignee_id"):
        require_permissions(current_user, "tickets.assign")
        if not _can_manage_all_tickets(current_user):
            raise HTTPException(
                status_code=403,
                detail="Bulk assignment requires queue management scope",
            )
        target_assignee = _resolve_user_by_id(
            db,
            str(operation["assignee_id"]),
            plan.tenant_id,
        )
        if target_assignee is None or not target_assignee.is_active:
            raise HTTPException(
                status_code=409,
                detail="Planned assignee is no longer eligible",
            )

    locked_tickets: list[Ticket] = []
    drift: list[dict[str, str]] = []
    for target in eligible_targets:
        ticket_id = str(target.get("ticket_id") or "")
        ticket = db.get(Ticket, ticket_id, with_for_update=True)
        if (
            ticket is None
            or ticket.tenant_id != plan.tenant_id
            or not _can_read_ticket(current_user, ticket)
        ):
            drift.append(
                {"ticket_id": ticket_id, "reason": "no longer accessible"}
            )
            continue
        preview, refreshed_target = _bulk_target_preview(
            ticket,
            current_user,
            target_status=target_status,
            target_assignee=target_assignee,
        )
        if (
            refreshed_target is None
            or preview.eligible is False
            or _ticket_bulk_fingerprint(ticket) != target.get("fingerprint")
        ):
            drift.append(
                {
                    "ticket_id": ticket.id,
                    "reason": preview.reason or "state changed after preview",
                }
            )
            continue
        locked_tickets.append(ticket)
    if drift:
        log_audit(
            db,
            action="ticket.bulk_execute_denied_drift",
            entity_type="ticket_bulk_plan",
            entity_id=plan.id,
            actor_user=_actor(db, current_user),
            tenant_id=plan.tenant_id,
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
            metadata={
                "operation_sha256": plan.operation_sha256,
                "targets_sha256": plan.targets_sha256,
                "drift": drift,
            },
        )
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Ticket state changed after preview",
                "targets": drift,
            },
        )

    actor = _actor(db, current_user)
    now = datetime.now(UTC)
    comment_body = str(operation.get("comment") or "").strip()
    for ticket in locked_tickets:
        old_status = _canonical_status(ticket.status) or ticket.status
        assignment_changed = False
        status_changed = False
        if target_assignee is not None and (
            ticket.assignee_id != target_assignee.id
        ):
            old_assignee = ticket.assignee_name
            ticket.assignee_id = target_assignee.id
            ticket.assignee_name = target_assignee.full_name
            if old_status in {"NEW", "TRIAGE"}:
                try:
                    transition_ticket_status(
                        db,
                        ticket,
                        "ASSIGNED",
                        actor_name=current_user.full_name,
                        actor_kind=_lifecycle_actor_kind(current_user),
                        actor_user=actor,
                        actor_email=current_user.email,
                        allow_cross_tenant_actor=current_user.role == "saas_root",
                        expected_status=old_status,
                        idempotency_key=f"bulk:{plan.id}:{ticket.id}:assign",
                        at=now,
                        source="ticket_bulk_assignment",
                        reason=(
                            f"Ticket assigned to {target_assignee.full_name} "
                            "by governed bulk plan."
                        ),
                        notify=target_status is None,
                        ip_address=(
                            http_request.client.host if http_request.client else None
                        ),
                        user_agent=http_request.headers.get("user-agent"),
                    )
                    status_changed = True
                except TicketLifecycleError as error:
                    raise HTTPException(status_code=409, detail=str(error)) from error
            assignment_changed = True
            _write_history(
                db,
                ticket_id=ticket.id,
                actor_name=current_user.full_name,
                event_type="assigned",
                field_name="assignee",
                old_value=old_assignee,
                new_value=target_assignee.full_name,
                message=f"Назначено на {target_assignee.full_name} массовым планом.",
            )
        effective_status = _canonical_status(ticket.status) or ticket.status
        if target_status is not None and target_status != effective_status:
            try:
                transition_ticket_status(
                    db,
                    ticket,
                    target_status,
                    actor_name=current_user.full_name,
                    actor_kind=_lifecycle_actor_kind(current_user),
                    actor_user=actor,
                    actor_email=current_user.email,
                    allow_cross_tenant_actor=current_user.role == "saas_root",
                    expected_status=effective_status,
                    idempotency_key=f"bulk:{plan.id}:{ticket.id}:status",
                    at=now,
                    source="ticket_bulk_transition",
                    reason=(
                        f"Ticket status changed to {target_status} "
                        "by governed bulk plan."
                    ),
                    ip_address=(
                        http_request.client.host if http_request.client else None
                    ),
                    user_agent=http_request.headers.get("user-agent"),
                )
            except TicketLifecycleError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            status_changed = True
        if comment_body:
            db.add(
                TicketComment(
                    id=str(uuid.uuid4()),
                    ticket_id=ticket.id,
                    author_id=current_user.id,
                    author_name=current_user.full_name,
                    author_role=current_user.role,
                    body=comment_body,
                    is_internal=True,
                )
            )
            _write_history(
                db,
                ticket_id=ticket.id,
                actor_name=current_user.full_name,
                event_type="comment_added",
                field_name="comment",
                old_value=None,
                new_value=comment_body,
                message="Добавлен внутренний комментарий массового плана.",
            )
        ticket.updated_at = now
        if not status_changed:
            sync_ticket_sla(
                db,
                ticket,
                old_status=old_status,
                actor=actor,
                at=now,
            )
        log_audit(
            db,
            action="ticket.bulk_item_executed",
            entity_type="ticket",
            entity_id=ticket.id,
            actor_user=actor,
            tenant_id=ticket.tenant_id,
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
            metadata={
                "plan_id": plan.id,
                "operation_sha256": plan.operation_sha256,
                "assignment_changed": assignment_changed,
                "status_changed": status_changed,
            },
        )
        context = build_ticket_context(ticket)
        if assignment_changed:
            trigger_automation_event(
                db,
                tenant_id=ticket.tenant_id,
                trigger_type="ticket_assigned",
                context=context,
                actor_email=current_user.email,
            )
            notification = create_ticket_event_notification(
                db,
                event_code="ticket_assigned",
                ticket=ticket,
                actor_name=current_user.full_name,
            )
            if notification is not None:
                db.add(
                    _record_notification_history(
                        ticket.id,
                        current_user.full_name,
                        "ticket_assigned",
                    )
                )
        if status_changed:
            trigger_automation_event(
                db,
                tenant_id=ticket.tenant_id,
                trigger_type="ticket_status_changed",
                context=context,
                actor_email=current_user.email,
            )

    plan.status = "EXECUTED"
    plan.revision += 1
    plan.executed_at = now
    log_audit(
        db,
        action="ticket.bulk_executed",
        entity_type="ticket_bulk_plan",
        entity_id=plan.id,
        actor_user=actor,
        tenant_id=plan.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "operation_sha256": plan.operation_sha256,
            "targets_sha256": plan.targets_sha256,
            "updated_count": len(locked_tickets),
            "skipped_count": plan.skipped_count,
            "revision": plan.revision,
        },
    )
    db.commit()
    db.refresh(plan)
    return TicketBulkExecuteResponse(
        plan_id=plan.id,
        status=plan.status,
        revision=plan.revision,
        updated_count=len(locked_tickets),
        skipped_count=plan.skipped_count,
        already_executed=False,
        executed_at=plan.executed_at or now,
    )


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

    if _is_requester_only(current_user) and request.is_internal:
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
        is_internal=request.is_internal,
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
    if _is_requester_only(current_user) and article.visibility == "internal":
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


def _participant_ticket(
    db: Session,
    ticket_id: str,
    current_user: AuthUserResponse,
) -> Ticket:
    _ensure_access(current_user)
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    _ensure_ticket_access(ticket, current_user)
    if not _can_read_ticket(current_user, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if ticket.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ticket has no tenant scope")
    return ticket


def _participant_response(item: TicketParticipant) -> TicketParticipantResponse:
    return TicketParticipantResponse(
        id=item.id,
        ticket_id=item.ticket_id,
        user_id=item.user_id,
        display_name=item.display_name,
        email=item.email,
        participant_role=item.participant_role,
        notification_scope=item.notification_scope,
        notify_in_app=item.notify_in_app,
        notify_email=item.notify_email,
        is_active=item.is_active,
        version_number=item.version_number,
        added_by_id=item.added_by_id,
        removed_at=item.removed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _participant_item(
    db: Session,
    ticket: Ticket,
    participant_id: str,
) -> TicketParticipant:
    item = db.scalar(
        select(TicketParticipant).where(
            TicketParticipant.id == participant_id,
            TicketParticipant.ticket_id == ticket.id,
            TicketParticipant.tenant_id == ticket.tenant_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket participant not found")
    return item


def _participant_can_manage(
    current_user: AuthUserResponse,
    item: TicketParticipant | None = None,
) -> bool:
    return has_permission(current_user, "tickets.participants.manage") or (
        item is not None
        and item.user_id == current_user.id
        and has_permission(current_user, "tickets.watch")
    )


@router.get(
    "/{ticket_id}/participant-candidates",
    response_model=list[TicketParticipantCandidateResponse],
)
def list_ticket_participant_candidates(
    ticket_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TicketParticipantCandidateResponse]:
    require_permissions(current_user, "tickets.participants.manage")
    ticket = _participant_ticket(db, ticket_id, current_user)
    users = db.scalars(
        select(User)
        .where(
            User.tenant_id == ticket.tenant_id,
            User.is_active.is_(True),
        )
        .order_by(User.full_name.asc())
        .limit(500)
    ).all()
    return [
        TicketParticipantCandidateResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=user.role.code if user.role is not None else "custom",
        )
        for user in users
    ]


@router.get(
    "/{ticket_id}/participants",
    response_model=list[TicketParticipantResponse],
)
def list_ticket_participants(
    ticket_id: str,
    include_inactive: bool = Query(default=False),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TicketParticipantResponse]:
    require_permissions(current_user, "tickets.participants.read")
    ticket = _participant_ticket(db, ticket_id, current_user)
    statement = select(TicketParticipant).where(
        TicketParticipant.ticket_id == ticket.id,
        TicketParticipant.tenant_id == ticket.tenant_id,
    )
    if not include_inactive:
        statement = statement.where(TicketParticipant.is_active.is_(True))
    rows = db.scalars(
        statement.order_by(TicketParticipant.is_active.desc(), TicketParticipant.created_at.asc())
    ).all()
    return [_participant_response(item) for item in rows]


@router.post(
    "/{ticket_id}/participants",
    response_model=TicketParticipantResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_ticket_participant(
    ticket_id: str,
    payload: TicketParticipantCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketParticipantResponse:
    require_permissions(current_user, "tickets.participants.manage")
    ticket = _participant_ticket(db, ticket_id, current_user)
    linked_user: User | None = None
    if payload.user_id:
        linked_user = db.get(User, payload.user_id)
        if linked_user is None or linked_user.tenant_id != ticket.tenant_id or not linked_user.is_active:
            raise HTTPException(status_code=422, detail="Participant user is unavailable in this tenant")
        display_name = linked_user.full_name
        email = linked_user.email.strip().lower()
        identity_key = f"user:{linked_user.id}"
    else:
        display_name = (payload.display_name or "").strip()
        email = (payload.email or "").strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise HTTPException(status_code=422, detail="Participant email is invalid")
        identity_key = f"email:{email}"
    existing = db.scalar(
        select(TicketParticipant).where(
            TicketParticipant.ticket_id == ticket.id,
            TicketParticipant.identity_key == identity_key,
        )
    )
    if existing is not None and existing.is_active:
        raise HTTPException(status_code=409, detail="Participant already watches this ticket")
    actor = _actor(db, current_user)
    if existing is None:
        item = TicketParticipant(
            id=str(uuid.uuid4()),
            tenant_id=ticket.tenant_id,
            ticket_id=ticket.id,
            user_id=linked_user.id if linked_user else None,
            identity_key=identity_key,
            display_name=display_name,
            email=email,
            participant_role=payload.participant_role,
            notification_scope=payload.notification_scope,
            notify_in_app=payload.notify_in_app,
            notify_email=payload.notify_email,
            added_by_id=current_user.id,
        )
        db.add(item)
        action = "ticket_participant_added"
    else:
        item = existing
        item.user_id = linked_user.id if linked_user else None
        item.display_name = display_name
        item.email = email
        item.participant_role = payload.participant_role
        item.notification_scope = payload.notification_scope
        item.notify_in_app = payload.notify_in_app
        item.notify_email = payload.notify_email
        item.is_active = True
        item.removal_reason = None
        item.removed_by_id = None
        item.removed_at = None
        item.version_number += 1
        action = "ticket_participant_reactivated"
    _write_history(
        db,
        ticket_id=ticket.id,
        actor_name=current_user.full_name,
        event_type=action,
        field_name="participants",
        old_value=None,
        new_value=email,
        message=f"Участник {display_name} добавлен к заявке.",
    )
    log_audit(
        db,
        action=action,
        entity_type="ticket_participant",
        entity_id=item.id,
        actor_user=actor,
        tenant_id=ticket.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "ticket_id": ticket.id,
            "participant_role": item.participant_role,
            "notification_scope": item.notification_scope,
            "reason": payload.reason,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Participant already watches this ticket") from exc
    db.refresh(item)
    return _participant_response(item)


@router.put(
    "/{ticket_id}/participants/self",
    response_model=TicketParticipantResponse,
)
def watch_ticket(
    ticket_id: str,
    payload: TicketWatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketParticipantResponse:
    require_permissions(current_user, "tickets.watch")
    ticket = _participant_ticket(db, ticket_id, current_user)
    user = db.get(User, current_user.id)
    if user is None or user.tenant_id != ticket.tenant_id:
        raise HTTPException(status_code=422, detail="Watcher account is unavailable")
    identity_key = f"user:{user.id}"
    item = db.scalar(
        select(TicketParticipant).where(
            TicketParticipant.ticket_id == ticket.id,
            TicketParticipant.identity_key == identity_key,
        )
    )
    created = item is None
    if item is None:
        item = TicketParticipant(
            id=str(uuid.uuid4()),
            tenant_id=ticket.tenant_id,
            ticket_id=ticket.id,
            user_id=user.id,
            identity_key=identity_key,
            display_name=user.full_name,
            email=user.email.strip().lower(),
            participant_role="WATCHER",
            added_by_id=user.id,
        )
        db.add(item)
    else:
        item.is_active = True
        item.removal_reason = None
        item.removed_by_id = None
        item.removed_at = None
        item.version_number += 1
    item.notification_scope = payload.notification_scope
    item.notify_in_app = payload.notify_in_app
    item.notify_email = payload.notify_email
    log_audit(
        db,
        action="ticket_watcher_subscribed" if created else "ticket_watcher_preferences_updated",
        entity_type="ticket_participant",
        entity_id=item.id,
        actor_user=user,
        tenant_id=ticket.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"ticket_id": ticket.id, "notification_scope": item.notification_scope},
    )
    db.commit()
    db.refresh(item)
    return _participant_response(item)


@router.patch(
    "/{ticket_id}/participants/{participant_id}",
    response_model=TicketParticipantResponse,
)
def update_ticket_participant(
    ticket_id: str,
    participant_id: str,
    payload: TicketParticipantPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketParticipantResponse:
    ticket = _participant_ticket(db, ticket_id, current_user)
    item = _participant_item(db, ticket, participant_id)
    if not _participant_can_manage(current_user, item):
        raise HTTPException(status_code=403, detail="Missing permission to update this participant")
    if item.version_number != payload.expected_version:
        raise HTTPException(status_code=409, detail="Participant was changed; reload and retry")
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version", "reason"})
    if not has_permission(current_user, "tickets.participants.manage"):
        changes.pop("participant_role", None)
    for key, value in changes.items():
        setattr(item, key, value)
    item.version_number += 1
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="ticket_participant_updated",
        entity_type="ticket_participant",
        entity_id=item.id,
        actor_user=actor,
        tenant_id=ticket.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"ticket_id": ticket.id, "changed_fields": sorted(changes), "reason": payload.reason},
    )
    db.commit()
    db.refresh(item)
    return _participant_response(item)


@router.delete(
    "/{ticket_id}/participants/{participant_id}",
    response_model=TicketParticipantResponse,
)
def remove_ticket_participant(
    ticket_id: str,
    participant_id: str,
    http_request: Request,
    reason: str = Query(min_length=3, max_length=2_000),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketParticipantResponse:
    ticket = _participant_ticket(db, ticket_id, current_user)
    item = _participant_item(db, ticket, participant_id)
    if not _participant_can_manage(current_user, item):
        raise HTTPException(status_code=403, detail="Missing permission to remove this participant")
    if not item.is_active:
        return _participant_response(item)
    now = datetime.now(UTC)
    item.is_active = False
    item.removal_reason = reason
    item.removed_by_id = current_user.id
    item.removed_at = now
    item.version_number += 1
    actor = _actor(db, current_user)
    _write_history(
        db,
        ticket_id=ticket.id,
        actor_name=current_user.full_name,
        event_type="ticket_participant_removed",
        field_name="participants",
        old_value=item.email,
        new_value=None,
        message=f"Участник {item.display_name} удалён из заявки.",
    )
    log_audit(
        db,
        action="ticket_participant_removed",
        entity_type="ticket_participant",
        entity_id=item.id,
        actor_user=actor,
        tenant_id=ticket.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"ticket_id": ticket.id, "reason": reason},
    )
    db.commit()
    db.refresh(item)
    return _participant_response(item)


@router.get(
    "/{ticket_id}/duplicate-candidates",
    response_model=list[TicketDuplicateCandidateResponse],
)
def list_ticket_duplicate_candidates(
    ticket_id: str,
    min_score: float = Query(default=45.0, ge=0, le=100),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TicketDuplicateCandidateResponse]:
    require_permissions(current_user, "tickets.duplicates.read")
    _ensure_access(current_user)
    source = _visible_governance_ticket(db, ticket_id, current_user)
    if source.merged_into_id is not None:
        return []

    statement = select(Ticket).where(
        Ticket.tenant_id == source.tenant_id,
        Ticket.id != source.id,
        Ticket.merged_into_id.is_(None),
        Ticket.status != "CANCELLED",
    )
    statement = _apply_role_scope(statement, current_user)
    candidates = db.scalars(statement.order_by(Ticket.created_at.desc()).limit(500)).all()

    suppressed_pairs = set(
        db.scalars(
            select(TicketGovernanceAction.pair_key).where(
                TicketGovernanceAction.tenant_id == source.tenant_id,
                TicketGovernanceAction.pair_key.is_not(None),
                TicketGovernanceAction.action_type.in_(["DUPLICATE_DISMISSED", "MERGED"]),
                or_(
                    TicketGovernanceAction.source_ticket_id == source.id,
                    TicketGovernanceAction.target_ticket_id == source.id,
                ),
            )
        ).all()
    )
    ranked: list[TicketDuplicateCandidateResponse] = []
    for candidate in candidates:
        pair_key = _duplicate_pair_key(source.id, candidate.id)
        if pair_key in suppressed_pairs:
            continue
        score, evidence = _duplicate_score(source, candidate)
        if score < min_score:
            continue
        ranked.append(
            TicketDuplicateCandidateResponse(
                id=candidate.id,
                ticket_number=candidate.ticket_number,
                title=candidate.title,
                requester_name=candidate.requester_name,
                requester_email=candidate.requester_email,
                category=candidate.category,
                priority=candidate.priority,
                status=_status_for_output(candidate.status),
                created_at=candidate.created_at,
                governance_version=candidate.governance_version,
                score=score,
                evidence=evidence,
                pair_key=pair_key,
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.created_at, item.id))
    return ranked[:limit]


@router.post(
    "/{ticket_id}/duplicate-candidates/{candidate_id}/dismiss",
    response_model=TicketGovernanceResultResponse,
)
def dismiss_ticket_duplicate_candidate(
    ticket_id: str,
    candidate_id: str,
    request: TicketDuplicateDismissRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketGovernanceResultResponse:
    require_permissions(current_user, "tickets.duplicates.manage")
    _ensure_access(current_user)
    if ticket_id == candidate_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A ticket cannot be compared with itself",
        )
    source, candidate = _locked_governance_pair(db, ticket_id, candidate_id, current_user)
    assert source.tenant_id is not None
    existing = _idempotent_action(
        db,
        tenant_id=source.tenant_id,
        action_type="DUPLICATE_DISMISSED",
        idempotency_key=request.idempotency_key,
    )
    if existing is not None:
        _assert_idempotent_action_matches(
            existing, source_ticket_id=source.id, target_ticket_id=candidate.id
        )
        return _governance_result(existing, source, candidate, already_applied=True)

    _assert_governance_version(source, request.expected_ticket_version, "Source ticket")
    _assert_governance_version(candidate, request.expected_candidate_version, "Candidate ticket")
    if source.merged_into_id is not None or candidate.merged_into_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Merged tickets cannot be reviewed as duplicate candidates",
        )

    score, signals = _duplicate_score(source, candidate)
    now = datetime.now(UTC)
    source.governance_version += 1
    candidate.governance_version += 1
    source.updated_at = now
    candidate.updated_at = now
    action = TicketGovernanceAction(
        id=str(uuid.uuid4()),
        tenant_id=source.tenant_id,
        action_type="DUPLICATE_DISMISSED",
        source_ticket_id=source.id,
        target_ticket_id=candidate.id,
        actor_user_id=current_user.id,
        actor_name=current_user.full_name,
        reason=request.reason.strip(),
        pair_key=_duplicate_pair_key(source.id, candidate.id),
        score=score,
        evidence_json={"signals": signals},
        idempotency_key=request.idempotency_key,
        created_at=now,
    )
    db.add(action)
    for ticket, other in ((source, candidate), (candidate, source)):
        _write_history(
            db,
            ticket_id=ticket.id,
            actor_name=current_user.full_name,
            event_type="duplicate_candidate_dismissed",
            field_name="duplicate_candidate",
            old_value=other.id,
            new_value=None,
            message=f"Кандидат {other.ticket_number or other.id} отклонён как ложный дубликат.",
        )
    actor_user = _actor(db, current_user)
    log_audit(
        db,
        action="ticket_duplicate_candidate_dismissed",
        entity_type="ticket_governance_action",
        entity_id=action.id,
        actor_user=actor_user,
        tenant_id=source.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "source_ticket_id": source.id,
            "candidate_ticket_id": candidate.id,
            "score": score,
            "reason": request.reason.strip(),
        },
    )
    db.commit()
    db.refresh(action)
    db.refresh(source)
    db.refresh(candidate)
    return _governance_result(action, source, candidate, already_applied=False)


@router.post(
    "/{source_ticket_id}/merge",
    response_model=TicketGovernanceResultResponse,
)
def merge_ticket(
    source_ticket_id: str,
    request: TicketMergeRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketGovernanceResultResponse:
    require_permissions(current_user, "tickets.merge")
    _ensure_access(current_user)
    if source_ticket_id == request.target_ticket_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A ticket cannot be merged into itself",
        )
    source, target = _locked_governance_pair(
        db, source_ticket_id, request.target_ticket_id, current_user
    )
    assert source.tenant_id is not None
    existing = _idempotent_action(
        db,
        tenant_id=source.tenant_id,
        action_type="MERGED",
        idempotency_key=request.idempotency_key,
    )
    if existing is not None:
        _assert_idempotent_action_matches(
            existing, source_ticket_id=source.id, target_ticket_id=target.id
        )
        return _governance_result(existing, source, target, already_applied=True)

    _assert_governance_version(source, request.expected_source_version, "Source ticket")
    _assert_governance_version(target, request.expected_target_version, "Target ticket")
    if source.merged_into_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source ticket is already merged",
        )
    if target.merged_into_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Target ticket is already merged",
        )
    if source.status in CLOSED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an active source ticket can be merged",
        )
    if target.status == "CANCELLED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A cancelled ticket cannot be a merge target",
        )

    now = datetime.now(UTC)
    old_status = source.status
    score, signals = _duplicate_score(source, target)
    actor_user = _actor(db, current_user)
    try:
        transition_ticket_status_path(
            db,
            source,
            "CANCELLED",
            actor_name=current_user.full_name,
            actor_kind="MANAGER",
            actor_user=actor_user,
            actor_email=current_user.email,
            allow_cross_tenant_actor=current_user.role == "saas_root",
            expected_version=request.expected_source_version,
            idempotency_key=f"merge:{request.idempotency_key}"[-120:],
            at=now,
            source="ticket_merge",
            reason=(
                f"Source ticket merged into {target.ticket_number or target.id}; "
                "lifecycle closed as CANCELLED."
            ),
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
        )
    except TicketLifecycleError as error:
        _raise_lifecycle_http(error)
    source.merged_into_id = target.id
    source.merge_reason = request.reason.strip()
    source.merged_by_id = current_user.id
    source.merged_by_name = current_user.full_name
    source.merged_at = now
    source.updated_at = now
    target.governance_version += 1
    target.updated_at = now
    action = TicketGovernanceAction(
        id=str(uuid.uuid4()),
        tenant_id=source.tenant_id,
        action_type="MERGED",
        source_ticket_id=source.id,
        target_ticket_id=target.id,
        actor_user_id=current_user.id,
        actor_name=current_user.full_name,
        reason=request.reason.strip(),
        pair_key=_duplicate_pair_key(source.id, target.id),
        score=score,
        evidence_json={"signals": signals, "source_previous_status": old_status},
        idempotency_key=request.idempotency_key,
        created_at=now,
    )
    db.add(action)
    _write_history(
        db,
        ticket_id=source.id,
        actor_name=current_user.full_name,
        event_type="ticket_merged",
        field_name="merged_into_id",
        old_value=None,
        new_value=target.id,
        message=f"Заявка объединена с {target.ticket_number or target.id}; исходная запись сохранена.",
    )
    _write_history(
        db,
        ticket_id=target.id,
        actor_name=current_user.full_name,
        event_type="ticket_merge_received",
        field_name="merged_source_id",
        old_value=None,
        new_value=source.id,
        message=f"В заявку объединена {source.ticket_number or source.id}.",
    )
    log_audit(
        db,
        action="ticket_merged",
        entity_type="ticket_governance_action",
        entity_id=action.id,
        actor_user=actor_user,
        tenant_id=source.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "source_ticket_id": source.id,
            "target_ticket_id": target.id,
            "source_previous_status": old_status,
            "reason": request.reason.strip(),
        },
    )
    db.commit()
    db.refresh(action)
    db.refresh(source)
    db.refresh(target)
    return _governance_result(action, source, target, already_applied=False)


@router.post(
    "/{source_ticket_id}/split",
    response_model=TicketGovernanceResultResponse,
    status_code=status.HTTP_201_CREATED,
)
def split_ticket(
    source_ticket_id: str,
    request: TicketSplitRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketGovernanceResultResponse:
    require_permissions(current_user, "tickets.split")
    _ensure_access(current_user)
    source = _visible_governance_ticket(db, source_ticket_id, current_user)
    assert source.tenant_id is not None
    existing = _idempotent_action(
        db,
        tenant_id=source.tenant_id,
        action_type="SPLIT",
        idempotency_key=request.idempotency_key,
    )
    if existing is not None:
        _assert_idempotent_action_matches(
            existing,
            source_ticket_id=source.id,
            target_ticket_id=existing.target_ticket_id,
        )
        child = db.scalar(select(Ticket).where(Ticket.id == existing.target_ticket_id))
        return _governance_result(existing, source, child, already_applied=True)

    source = db.scalar(
        select(Ticket).where(Ticket.id == source.id).with_for_update()
    )
    assert source is not None
    existing = _idempotent_action(
        db,
        tenant_id=source.tenant_id,
        action_type="SPLIT",
        idempotency_key=request.idempotency_key,
    )
    if existing is not None:
        _assert_idempotent_action_matches(
            existing,
            source_ticket_id=source.id,
            target_ticket_id=existing.target_ticket_id,
        )
        child = db.scalar(select(Ticket).where(Ticket.id == existing.target_ticket_id))
        return _governance_result(existing, source, child, already_applied=True)
    _assert_governance_version(source, request.expected_source_version, "Source ticket")
    if source.merged_into_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A merged ticket cannot be split",
        )
    categories, priorities, _, sla_policies, _ = _lookup_maps(db)
    category = request.category or source.category
    priority = request.priority or source.priority
    if category not in categories:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket category")
    if priority not in priorities:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket priority")

    actor_user = _actor(db, current_user)
    if actor_user is None or not actor_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active creator account required")
    now = datetime.now(UTC)
    created_on_behalf = source.requester_id != actor_user.id
    child = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=source.tenant_id,
        ticket_number=next_ticket_number(db),
        title=request.title.strip(),
        description=request.description,
        requester_id=source.requester_id,
        requester_name=source.requester_name,
        requester_email=source.requester_email,
        requester_contact=source.requester_contact,
        created_by_id=actor_user.id,
        created_by_name=actor_user.full_name,
        creation_channel="ON_BEHALF" if created_on_behalf else "SELF_SERVICE",
        on_behalf_reason=request.reason.strip() if created_on_behalf else None,
        parent_ticket_id=source.id,
        governance_version=1,
        department=source.department,
        location=source.location,
        category=category,
        priority=priority,
        status="NEW",
        asset_id=source.asset_id,
        created_at=now,
        updated_at=now,
    )
    sla_policy = sla_policies.get(priority)
    if sla_policy is not None:
        _apply_ticket_sla(child, sla_policy, now)
    source.governance_version += 1
    source.updated_at = now
    db.add(child)
    db.flush()
    sync_ticket_sla(db, child, old_status=None, actor=actor_user, at=now)
    action = TicketGovernanceAction(
        id=str(uuid.uuid4()),
        tenant_id=source.tenant_id,
        action_type="SPLIT",
        source_ticket_id=source.id,
        target_ticket_id=child.id,
        actor_user_id=current_user.id,
        actor_name=current_user.full_name,
        reason=request.reason.strip(),
        pair_key=None,
        score=None,
        evidence_json={"child_ticket_number": child.ticket_number},
        idempotency_key=request.idempotency_key,
        created_at=now,
    )
    db.add(action)
    _write_history(
        db,
        ticket_id=source.id,
        actor_name=current_user.full_name,
        event_type="ticket_split",
        field_name="child_ticket_id",
        old_value=None,
        new_value=child.id,
        message=f"Создана отдельная дочерняя заявка {child.ticket_number}.",
    )
    _write_history(
        db,
        ticket_id=child.id,
        actor_name=current_user.full_name,
        event_type="created_from_split",
        field_name="parent_ticket_id",
        old_value=None,
        new_value=source.id,
        message=f"Заявка выделена из {source.ticket_number or source.id}.",
    )
    notification = create_ticket_event_notification(
        db, event_code="ticket_created", ticket=child, actor_name=current_user.full_name
    )
    if notification is not None:
        db.add(_record_notification_history(child.id, current_user.full_name, "ticket_created"))
    log_audit(
        db,
        action="ticket_split",
        entity_type="ticket_governance_action",
        entity_id=action.id,
        actor_user=actor_user,
        tenant_id=source.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "source_ticket_id": source.id,
            "child_ticket_id": child.id,
            "reason": request.reason.strip(),
        },
    )
    trigger_automation_event(
        db,
        tenant_id=child.tenant_id,
        trigger_type="ticket_created",
        context=build_ticket_context(child),
        actor_email=current_user.email,
    )
    db.commit()
    db.refresh(action)
    db.refresh(source)
    db.refresh(child)
    return _governance_result(action, source, child, already_applied=False)
