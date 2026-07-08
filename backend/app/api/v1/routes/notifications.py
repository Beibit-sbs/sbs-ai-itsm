from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.email_message_log import EmailMessageLog
from app.models.notification import Notification
from app.models.notification_template import NotificationTemplate
from app.models.user import User
from app.services.audit import log_audit
from app.services.notifications import (
    list_notifications,
    mark_all_as_read,
    mark_as_read,
    send_mock_email,
    unread_count,
)
from app.services.rbac import require_permissions

router = APIRouter(prefix="/notifications")


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    message: str
    recipient_name: str
    recipient_email: str
    channel: str
    status: str
    related_ticket_id: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class NotificationTemplateResponse(BaseModel):
    id: str
    code: str
    name: str
    subject_template: str
    body_template: str
    channel: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class NotificationTemplatePatchRequest(BaseModel):
    name: str | None = None
    subject_template: str | None = None
    body_template: str | None = None
    channel: str | None = None
    is_active: bool | None = None


class EmailMessageLogResponse(BaseModel):
    id: str
    provider: str
    to_email: str
    subject: str
    body: str
    status: str
    error_message: str | None
    related_ticket_id: str | None
    created_at: datetime
    sent_at: datetime | None


class TestEmailRequest(BaseModel):
    to_email: str
    subject: str
    body: str
    related_ticket_id: str | None = None


def _ensure_access(current_user: AuthUserResponse) -> None:
    if current_user.role != "saas_root" and current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access required")


@router.get("", response_model=list[NotificationResponse])
def get_notifications(
    status_filter: str | None = Query(default=None, alias="status"),
    type_filter: str | None = Query(default=None, alias="type"),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[NotificationResponse]:
    require_permissions(current_user, "notifications.read")
    _ensure_access(current_user)
    notifications = list_notifications(db, status=status_filter, type=type_filter)
    return [NotificationResponse(**{field: getattr(item, field) for field in NotificationResponse.model_fields.keys()}) for item in notifications]


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
def get_unread_count(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> NotificationUnreadCountResponse:
    require_permissions(current_user, "notifications.read")
    _ensure_access(current_user)
    return NotificationUnreadCountResponse(unread_count=unread_count(db))


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def patch_notification_read(notification_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> NotificationResponse:
    require_permissions(current_user, "notifications.read")
    _ensure_access(current_user)
    notification = mark_as_read(db, notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    db.commit()
    db.refresh(notification)
    return NotificationResponse(**{field: getattr(notification, field) for field in NotificationResponse.model_fields.keys()})


@router.patch("/read-all")
def patch_read_all(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, int]:
    require_permissions(current_user, "notifications.manage")
    _ensure_access(current_user)
    updated = mark_all_as_read(db)
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
    require_permissions(current_user, "notifications.manage")
    _ensure_access(current_user)
    templates = db.scalars(select(NotificationTemplate).order_by(NotificationTemplate.code.asc())).all()
    return [NotificationTemplateResponse(**{field: getattr(item, field) for field in NotificationTemplateResponse.model_fields.keys()}) for item in templates]


@router.patch("/templates/{template_id}", response_model=NotificationTemplateResponse)
def patch_template(
    template_id: str,
    request: NotificationTemplatePatchRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationTemplateResponse:
    require_permissions(current_user, "notifications.manage")
    _ensure_access(current_user)
    template = db.scalar(select(NotificationTemplate).where(NotificationTemplate.id == template_id))
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    for field_name, value in request.model_dump(exclude_unset=True).items():
        setattr(template, field_name, value)
    template.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(template)
    return NotificationTemplateResponse(**{field: getattr(template, field) for field in NotificationTemplateResponse.model_fields.keys()})


@router.get("/email-log", response_model=list[EmailMessageLogResponse])
def get_email_log(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[EmailMessageLogResponse]:
    require_permissions(current_user, "email_log.read")
    _ensure_access(current_user)
    logs = db.scalars(select(EmailMessageLog).order_by(EmailMessageLog.created_at.desc())).all()
    return [EmailMessageLogResponse(**{field: getattr(item, field) for field in EmailMessageLogResponse.model_fields.keys()}) for item in logs]


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
    return EmailMessageLogResponse(**{field: getattr(log, field) for field in EmailMessageLogResponse.model_fields.keys()})
