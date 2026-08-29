from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.email_message_log import EmailMessageLog
from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference
from app.models.notification_template import NotificationTemplate
from app.models.user import User
from app.services.audit import log_audit
from app.services.email_operations import EmailOperationError
from app.services.notifications import (
    list_email_log_paged,
    list_notifications_paged,
    list_user_preferences,
    mark_all_as_read,
    mark_as_read,
    patch_user_preferences,
    retry_email_log,
    send_mock_email,
)
from app.services.rbac import is_saas_root, require_permissions

router = APIRouter(prefix="/notifications")


class NotificationResponse(BaseModel):
    id: str
    type: str
    event_type: str | None
    severity: str | None
    title: str
    message: str
    recipient_name: str
    recipient_email: str
    channel: str
    status: str
    is_read: bool
    related_ticket_id: str | None
    entity_type: str | None
    entity_id: str | None
    action_url: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
    read_at: datetime | None


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    page: int
    page_size: int
    unread_count: int


class NotificationTemplateResponse(BaseModel):
    id: str
    tenant_id: str | None
    key: str | None
    event_type: str | None
    locale: str
    code: str
    name: str
    subject_template: str
    body_template: str
    channel: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class NotificationTemplatePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=255)
    subject_template: str | None = Field(default=None, min_length=2, max_length=255)
    body_template: str | None = Field(default=None, min_length=2, max_length=20_000)
    channel: str | None = Field(
        default=None,
        pattern="^(in_app|email)$",
    )
    is_active: bool | None = None


class EmailMessageLogResponse(BaseModel):
    id: str
    tenant_id: str | None
    notification_id: str | None
    event_type: str | None
    channel_id: str | None
    direction: str
    provider: str
    provider_message_id: str | None
    internet_message_id: str | None
    conversation_id: str | None
    idempotency_key: str | None
    from_email: str | None
    from_name: str | None
    to_email: str
    to_name: str | None
    subject: str
    body: str
    status: str
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime | None
    payload: dict[str, Any] | None
    metadata: dict[str, Any] | None
    error_message: str | None
    related_ticket_id: str | None
    related_request_id: str | None
    created_at: datetime
    queued_at: datetime | None
    accepted_at: datetime | None
    sent_at: datetime | None
    delivered_at: datetime | None
    bounced_at: datetime | None


class EmailLogListResponse(BaseModel):
    items: list[EmailMessageLogResponse]
    total: int
    page: int
    page_size: int


class NotificationPreferenceResponse(BaseModel):
    id: str
    event_type: str
    channel_in_app: bool
    channel_email: bool
    is_muted: bool
    updated_at: datetime


class NotificationPreferencePatchItem(BaseModel):
    event_type: str
    channel_in_app: bool | None = None
    channel_email: bool | None = None
    is_muted: bool | None = None


class NotificationPreferencePatchRequest(BaseModel):
    items: list[NotificationPreferencePatchItem]


class TestEmailRequest(BaseModel):
    to_email: str
    subject: str
    body: str
    related_ticket_id: str | None = None


def _ensure_access(current_user: AuthUserResponse) -> None:
    if current_user.role != "saas_root" and current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access required")


def _tenant_scope(current_user: AuthUserResponse) -> str | None:
    return None if is_saas_root(current_user) else current_user.tenant_id


def _notification_to_response(item: Notification) -> NotificationResponse:
    metadata = None
    if item.metadata_json:
        try:
            metadata = json.loads(item.metadata_json)
        except json.JSONDecodeError:
            metadata = None
    return NotificationResponse(
        id=item.id,
        type=item.type,
        event_type=item.event_type,
        severity=item.severity,
        title=item.title,
        message=item.message,
        recipient_name=item.recipient_name,
        recipient_email=item.recipient_email,
        channel=item.channel,
        status=item.status,
        is_read=item.is_read or item.status == "READ",
        related_ticket_id=item.related_ticket_id,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        action_url=item.action_url,
        metadata=metadata,
        created_at=item.created_at,
        read_at=item.read_at,
    )


def _template_to_response(item: NotificationTemplate) -> NotificationTemplateResponse:
    return NotificationTemplateResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        key=item.key,
        event_type=item.event_type,
        locale=item.locale,
        code=item.code,
        name=item.name,
        subject_template=item.subject_template,
        body_template=item.body_template,
        channel=item.channel,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _email_log_to_response(item: EmailMessageLog) -> EmailMessageLogResponse:
    payload = None
    metadata = None
    if item.payload_json:
        try:
            payload = json.loads(item.payload_json)
        except json.JSONDecodeError:
            payload = None
    if item.metadata_json:
        try:
            metadata = json.loads(item.metadata_json)
        except json.JSONDecodeError:
            metadata = None
    return EmailMessageLogResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        notification_id=item.notification_id,
        event_type=item.event_type,
        channel_id=item.channel_id,
        direction=item.direction,
        provider=item.provider,
        provider_message_id=item.provider_message_id,
        internet_message_id=item.internet_message_id,
        conversation_id=item.conversation_id,
        idempotency_key=item.idempotency_key,
        from_email=item.from_email,
        from_name=item.from_name,
        to_email=item.to_email,
        to_name=item.to_name,
        subject=item.subject,
        body=item.body,
        status=item.status,
        attempt_count=item.attempt_count,
        max_attempts=item.max_attempts,
        next_retry_at=item.next_retry_at,
        payload=payload,
        metadata=metadata,
        error_message=item.error_message,
        related_ticket_id=item.related_ticket_id,
        related_request_id=item.related_request_id,
        created_at=item.created_at,
        queued_at=item.queued_at,
        accepted_at=item.accepted_at,
        sent_at=item.sent_at,
        delivered_at=item.delivered_at,
        bounced_at=item.bounced_at,
    )


def _preference_to_response(item: NotificationPreference) -> NotificationPreferenceResponse:
    return NotificationPreferenceResponse(
        id=item.id,
        event_type=item.event_type,
        channel_in_app=item.channel_in_app,
        channel_email=item.channel_email,
        is_muted=item.is_muted,
        updated_at=item.updated_at,
    )


@router.get("", response_model=NotificationListResponse)
def get_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    type_filter: str | None = Query(default=None, alias="event_type"),
    legacy_type_filter: str | None = Query(default=None, alias="type"),
    q: str | None = Query(default=None),
    scope: str = Query(default="mine", pattern=r"^(mine|tenant)$"),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationListResponse:
    require_permissions(current_user, "notifications.read")
    _ensure_access(current_user)
    if scope == "tenant":
        require_permissions(current_user, "notifications.manage")
    if type_filter is None:
        type_filter = legacy_type_filter
    items, total, unread = list_notifications_paged(
        db,
        tenant_id=_tenant_scope(current_user),
        recipient_user_id=current_user.id if scope == "mine" else None,
        recipient_email=current_user.email if scope == "mine" else None,
        page=page,
        page_size=page_size,
        status=status_filter,
        event_type=type_filter,
        q=q,
    )
    return NotificationListResponse(
        items=[_notification_to_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        unread_count=unread,
    )


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
def get_unread_count(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> NotificationUnreadCountResponse:
    require_permissions(current_user, "notifications.read")
    _ensure_access(current_user)
    _, _, unread = list_notifications_paged(
        db,
        tenant_id=_tenant_scope(current_user),
        recipient_user_id=current_user.id,
        recipient_email=current_user.email,
        page=1,
        page_size=1,
    )
    return NotificationUnreadCountResponse(unread_count=unread)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def patch_notification_read(notification_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> NotificationResponse:
    require_permissions(current_user, "notifications.update")
    _ensure_access(current_user)
    notification = mark_as_read(
        db,
        notification_id,
        user_id=current_user.id,
        recipient_email=current_user.email,
        tenant_id=_tenant_scope(current_user),
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    db.commit()
    db.refresh(notification)
    return _notification_to_response(notification)


@router.patch("/read-all")
def patch_read_all(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, int]:
    require_permissions(current_user, "notifications.update")
    _ensure_access(current_user)
    updated = mark_all_as_read(
        db,
        user_id=current_user.id,
        recipient_email=current_user.email,
        tenant_id=_tenant_scope(current_user),
    )
    actor = db.scalar(select(User).where(User.id == current_user.id))
    log_audit(
        db,
        action="notification_read_all",
        entity_type="notification",
        entity_id=None,
        actor_user=actor,
        metadata={"updated": updated},
    )
    db.commit()
    return {"updated": updated}


@router.get("/templates", response_model=list[NotificationTemplateResponse])
def get_templates(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[NotificationTemplateResponse]:
    require_permissions(current_user, "notifications.templates.read")
    _ensure_access(current_user)
    statement = select(NotificationTemplate).order_by(NotificationTemplate.code.asc())
    if not is_saas_root(current_user):
        statement = statement.where((NotificationTemplate.tenant_id == current_user.tenant_id) | (NotificationTemplate.tenant_id.is_(None)))
    templates = db.scalars(statement).all()
    return [_template_to_response(item) for item in templates]


@router.patch("/templates/{template_id}", response_model=NotificationTemplateResponse)
def patch_template(
    template_id: str,
    request: NotificationTemplatePatchRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationTemplateResponse:
    require_permissions(current_user, "notifications.templates.update")
    _ensure_access(current_user)
    template = db.scalar(select(NotificationTemplate).where(NotificationTemplate.id == template_id))
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if not is_saas_root(current_user) and (
        template.tenant_id is None
        or template.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    for field_name, value in request.model_dump(exclude_unset=True).items():
        setattr(template, field_name, value)
    template.updated_at = datetime.now(UTC)
    actor = db.scalar(select(User).where(User.id == current_user.id))
    log_audit(
        db,
        action="notification_template_updated",
        entity_type="notification_template",
        entity_id=template.id,
        actor_user=actor,
        metadata={"updated_fields": sorted(request.model_dump(exclude_unset=True).keys())},
    )
    db.commit()
    db.refresh(template)
    return _template_to_response(template)


@router.get("/preferences", response_model=list[NotificationPreferenceResponse])
def get_preferences(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[NotificationPreferenceResponse]:
    require_permissions(current_user, "notifications.read")
    _ensure_access(current_user)
    items = list_user_preferences(db, user_id=current_user.id, tenant_id=current_user.tenant_id)
    db.commit()
    return [_preference_to_response(item) for item in items]


@router.patch("/preferences", response_model=list[NotificationPreferenceResponse])
def patch_preferences(
    request: NotificationPreferencePatchRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[NotificationPreferenceResponse]:
    require_permissions(current_user, "notifications.preferences.update")
    _ensure_access(current_user)
    items = patch_user_preferences(
        db,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        items=[item.model_dump(exclude_unset=True) for item in request.items],
    )
    actor = db.scalar(select(User).where(User.id == current_user.id))
    log_audit(
        db,
        action="notification_preferences_updated",
        entity_type="notification_preference",
        entity_id=current_user.id,
        actor_user=actor,
        metadata={"items": len(request.items)},
    )
    db.commit()
    return [_preference_to_response(item) for item in items]


@router.get("/email-log", response_model=EmailLogListResponse)
def get_email_log(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailLogListResponse:
    require_permissions(current_user, "notifications.email_log.read")
    _ensure_access(current_user)
    items, total = list_email_log_paged(
        db,
        tenant_id=_tenant_scope(current_user),
        page=page,
        page_size=page_size,
        status=status_filter,
        q=q,
    )
    return EmailLogListResponse(
        items=[_email_log_to_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/email-log/{email_log_id}/retry", response_model=EmailMessageLogResponse)
def retry_email_log_item(
    email_log_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailMessageLogResponse:
    require_permissions(current_user, "notifications.email_log.retry")
    _ensure_access(current_user)
    existing = db.get(EmailMessageLog, email_log_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email log entry not found")
    if not is_saas_root(current_user) and existing.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email log entry not found")
    try:
        item = retry_email_log(db, email_log_id=email_log_id)
    except EmailOperationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email log entry not found")
    actor = db.scalar(select(User).where(User.id == current_user.id))
    log_audit(
        db,
        action="email_log_retry",
        entity_type="email_message_log",
        entity_id=item.id,
        actor_user=actor,
        metadata={"attempt_count": item.attempt_count, "status": item.status},
    )
    db.commit()
    db.refresh(item)
    return _email_log_to_response(item)


@router.post("/test-email", response_model=EmailMessageLogResponse, status_code=status.HTTP_201_CREATED)
def post_test_email(request: TestEmailRequest, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> EmailMessageLogResponse:
    require_permissions(current_user, "notifications.manage")
    _ensure_access(current_user)
    log = send_mock_email(
        db,
        to_email=request.to_email,
        subject=request.subject,
        body=request.body,
        related_ticket_id=request.related_ticket_id,
        tenant_id=current_user.tenant_id,
        event_type="manual_test_email",
    )
    actor = db.scalar(select(User).where(User.id == current_user.id))
    log_audit(
        db,
        action="test_email_created",
        entity_type="email_message_log",
        entity_id=log.id,
        actor_user=actor,
        metadata={"to_email": request.to_email},
    )
    db.commit()
    db.refresh(log)
    return _email_log_to_response(log)
