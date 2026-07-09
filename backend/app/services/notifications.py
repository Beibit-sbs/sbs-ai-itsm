from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.email_message_log import EmailMessageLog
from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference
from app.models.notification_template import NotificationTemplate
from app.models.ticket import Ticket
from app.services.email_provider import BaseEmailProvider, MockEmailProvider


TEMPLATE_SEEDS = [
    {
        "code": "ticket_created",
        "name": "Заявка создана",
        "subject_template": "[{{ticket_number}}] Заявка создана",
        "body_template": "Создана заявка {{ticket_number}}: {{title}}.",
        "channel": "in_app",
    },
    {
        "code": "ticket_assigned",
        "name": "Заявка назначена исполнителю",
        "subject_template": "[{{ticket_number}}] Назначен исполнитель",
        "body_template": "Заявка {{ticket_number}} назначена: {{assignee_name}}.",
        "channel": "in_app",
    },
    {
        "code": "ticket_status_changed",
        "name": "Изменение статуса заявки",
        "subject_template": "[{{ticket_number}}] Статус изменен",
        "body_template": "Статус заявки {{ticket_number}} изменен: {{status}}.",
        "channel": "in_app",
    },
    {
        "code": "ticket_comment_added",
        "name": "Добавлен комментарий",
        "subject_template": "[{{ticket_number}}] Новый комментарий",
        "body_template": "Добавлен комментарий к заявке {{ticket_number}}: {{comment}}",
        "channel": "in_app",
    },
    {
        "code": "ticket_resolved",
        "name": "Заявка решена",
        "subject_template": "[{{ticket_number}}] Заявка решена",
        "body_template": "Заявка {{ticket_number}} переведена в статус {{status}}.",
        "channel": "email",
    },
    {
        "code": "sla_warning",
        "name": "SLA предупреждение",
        "subject_template": "[{{ticket_number}}] SLA warning",
        "body_template": "По заявке {{ticket_number}} зафиксирован SLA warning.",
        "channel": "in_app",
    },
    {
        "code": "sla_breached",
        "name": "SLA нарушение",
        "subject_template": "[{{ticket_number}}] SLA breached",
        "body_template": "По заявке {{ticket_number}} зафиксирован SLA breached.",
        "channel": "email",
    },
    {
        "code": "ai_recommendation_ready",
        "name": "AI рекомендация готова",
        "subject_template": "[{{ticket_number}}] AI рекомендация",
        "body_template": "Для заявки {{ticket_number}} подготовлена AI рекомендация.",
        "channel": "in_app",
    },
]

DEFAULT_EVENT_TYPES = [
    "ticket_created",
    "ticket_assigned",
    "ticket_status_changed",
    "ticket_comment_added",
    "ticket_resolved",
    "sla_warning",
    "sla_breached",
    "ai_recommendation_ready",
    "asset_moved",
    "asset_disposed",
    "knowledge_article_published",
    "report_exported",
    "automation_failed",
    "approval_required",
    "security_high_risk",
]


def _render(template: str, context: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return str(context.get(key, ""))

    return re.sub(r"{{\s*([\w_]+)\s*}}", replace, template)


def render_template(template: NotificationTemplate, context: dict[str, str]) -> tuple[str, str]:
    return _render(template.subject_template, context), _render(template.body_template, context)


def create_notification(
    db: Session,
    *,
    type: str,
    title: str,
    message: str,
    recipient_name: str,
    recipient_email: str,
    channel: str,
    status: str = "UNREAD",
    related_ticket_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    event_type: str | None = None,
    severity: str = "info",
    entity_type: str | None = None,
    entity_id: str | None = None,
    action_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Notification:
    created_at = datetime.now(UTC)
    normalized_event_type = event_type or type
    is_read = status.upper() == "READ"
    if entity_type is None and related_ticket_id is not None:
        entity_type = "ticket"
    if entity_id is None and related_ticket_id is not None:
        entity_id = related_ticket_id
    notification = Notification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        tenant_id=tenant_id,
        event_type=normalized_event_type,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        action_url=action_url,
        is_read=is_read,
        expires_at=None,
        metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
        type=type,
        title=title,
        message=message,
        recipient_name=recipient_name,
        recipient_email=recipient_email,
        channel=channel,
        status=status,
        related_ticket_id=related_ticket_id,
        created_at=created_at,
        read_at=created_at if is_read else None,
    )
    db.add(notification)
    return notification


def mark_as_read(db: Session, notification_id: str) -> Notification | None:
    notification = db.scalar(select(Notification).where(Notification.id == notification_id))
    if notification is None:
        return None
    if notification.status != "READ":
        notification.status = "READ"
        notification.read_at = datetime.now(UTC)
        notification.is_read = True
    return notification


def mark_all_as_read(db: Session) -> int:
    notifications = db.scalars(select(Notification).where(Notification.status != "READ")).all()
    now = datetime.now(UTC)
    for notification in notifications:
        notification.status = "READ"
        notification.read_at = now
        notification.is_read = True
    return len(notifications)


def list_notifications(db: Session, *, status: str | None = None, type: str | None = None) -> list[Notification]:
    statement: Select[tuple[Notification]] = select(Notification).order_by(Notification.created_at.desc())
    if status:
        statement = statement.where(Notification.status == status)
    if type:
        statement = statement.where(Notification.type == type)
    return db.scalars(statement).all()


def unread_count(db: Session) -> int:
    return int(db.scalar(select(func.count(Notification.id)).where(Notification.status != "READ")) or 0)


def list_notifications_paged(
    db: Session,
    *,
    tenant_id: str | None,
    page: int,
    page_size: int,
    status: str | None = None,
    event_type: str | None = None,
    q: str | None = None,
) -> tuple[list[Notification], int, int]:
    statement: Select[tuple[Notification]] = select(Notification)
    total_statement = select(func.count(Notification.id))
    unread_statement = select(func.count(Notification.id)).where(Notification.status != "READ")

    if tenant_id is not None:
        tenant_filter = (Notification.tenant_id == tenant_id) | (Notification.tenant_id.is_(None))
        statement = statement.where(tenant_filter)
        total_statement = total_statement.where(tenant_filter)
        unread_statement = unread_statement.where(tenant_filter)

    if status and status.upper() != "ALL":
        statement = statement.where(Notification.status == status)
        total_statement = total_statement.where(Notification.status == status)

    if event_type and event_type.upper() != "ALL":
        statement = statement.where((Notification.event_type == event_type) | (Notification.type == event_type))
        total_statement = total_statement.where((Notification.event_type == event_type) | (Notification.type == event_type))
        unread_statement = unread_statement.where((Notification.event_type == event_type) | (Notification.type == event_type))

    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            (Notification.title.ilike(pattern))
            | (Notification.message.ilike(pattern))
            | (Notification.recipient_email.ilike(pattern))
            | (Notification.recipient_name.ilike(pattern))
        )
        total_statement = total_statement.where(
            (Notification.title.ilike(pattern))
            | (Notification.message.ilike(pattern))
            | (Notification.recipient_email.ilike(pattern))
            | (Notification.recipient_name.ilike(pattern))
        )

    statement = statement.order_by(Notification.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = db.scalars(statement).all()
    total = int(db.scalar(total_statement) or 0)
    unread = int(db.scalar(unread_statement) or 0)
    return items, total, unread


def send_mock_email(
    db: Session,
    *,
    to_email: str,
    subject: str,
    body: str,
    related_ticket_id: str | None = None,
    tenant_id: str | None = None,
    notification_id: str | None = None,
    event_type: str | None = None,
    to_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    provider: BaseEmailProvider | None = None,
):
    now = datetime.now(UTC)
    active_provider = provider or MockEmailProvider()
    if isinstance(active_provider, MockEmailProvider):
        log = EmailMessageLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            notification_id=notification_id,
            event_type=event_type,
            provider="mock",
            provider_message_id=f"mock-{uuid.uuid4()}",
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body=body,
            status="SENT",
            attempt_count=1,
            max_attempts=3,
            next_retry_at=None,
            payload_json=json.dumps({"subject": subject, "body": body}, ensure_ascii=False),
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
            error_message=None,
            related_ticket_id=related_ticket_id,
            created_at=now,
            sent_at=now,
        )
        db.add(log)
        return log

    return active_provider.send_email(
        db,
        to_email=to_email,
        subject=subject,
        body=body,
        related_ticket_id=related_ticket_id,
    )


def list_email_log_paged(
    db: Session,
    *,
    tenant_id: str | None,
    page: int,
    page_size: int,
    status: str | None = None,
    q: str | None = None,
) -> tuple[list[EmailMessageLog], int]:
    statement: Select[tuple[EmailMessageLog]] = select(EmailMessageLog)
    total_statement = select(func.count(EmailMessageLog.id))

    if tenant_id is not None:
        tenant_filter = (EmailMessageLog.tenant_id == tenant_id) | (EmailMessageLog.tenant_id.is_(None))
        statement = statement.where(tenant_filter)
        total_statement = total_statement.where(tenant_filter)

    if status and status.upper() != "ALL":
        statement = statement.where(EmailMessageLog.status == status)
        total_statement = total_statement.where(EmailMessageLog.status == status)

    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            EmailMessageLog.to_email.ilike(pattern)
            | EmailMessageLog.subject.ilike(pattern)
            | EmailMessageLog.body.ilike(pattern)
        )
        total_statement = total_statement.where(
            EmailMessageLog.to_email.ilike(pattern)
            | EmailMessageLog.subject.ilike(pattern)
            | EmailMessageLog.body.ilike(pattern)
        )

    statement = statement.order_by(EmailMessageLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    return db.scalars(statement).all(), int(db.scalar(total_statement) or 0)


def retry_email_log(db: Session, *, email_log_id: str) -> EmailMessageLog | None:
    log = db.get(EmailMessageLog, email_log_id)
    if log is None:
        return None

    now = datetime.now(UTC)
    log.attempt_count = (log.attempt_count or 0) + 1
    if log.attempt_count > (log.max_attempts or 3):
        log.status = "FAILED"
        log.error_message = "Maximum retry attempts exceeded"
        log.next_retry_at = None
        return log

    log.status = "SENT"
    log.error_message = None
    log.sent_at = now
    log.next_retry_at = None
    log.provider_message_id = log.provider_message_id or f"mock-{uuid.uuid4()}"
    return log


def list_user_preferences(db: Session, *, user_id: str, tenant_id: str | None) -> list[NotificationPreference]:
    existing = db.scalars(select(NotificationPreference).where(NotificationPreference.user_id == user_id)).all()
    existing_by_event = {item.event_type: item for item in existing}

    for event_type in DEFAULT_EVENT_TYPES:
        if event_type in existing_by_event:
            continue
        item = NotificationPreference(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            event_type=event_type,
            channel_in_app=True,
            channel_email=event_type in {"ticket_resolved", "sla_breached", "security_high_risk"},
            is_muted=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(item)
        existing.append(item)

    return sorted(existing, key=lambda item: item.event_type)


def patch_user_preferences(
    db: Session,
    *,
    user_id: str,
    tenant_id: str | None,
    items: list[dict[str, Any]],
) -> list[NotificationPreference]:
    existing = {item.event_type: item for item in db.scalars(select(NotificationPreference).where(NotificationPreference.user_id == user_id)).all()}
    now = datetime.now(UTC)

    for payload in items:
        event_type = str(payload.get("event_type", "")).strip()
        if not event_type:
            continue
        preference = existing.get(event_type)
        if preference is None:
            preference = NotificationPreference(
                id=str(uuid.uuid4()),
                user_id=user_id,
                tenant_id=tenant_id,
                event_type=event_type,
                channel_in_app=True,
                channel_email=False,
                is_muted=False,
                created_at=now,
                updated_at=now,
            )
            db.add(preference)
            existing[event_type] = preference
        if "channel_in_app" in payload:
            preference.channel_in_app = bool(payload["channel_in_app"])
        if "channel_email" in payload:
            preference.channel_email = bool(payload["channel_email"])
        if "is_muted" in payload:
            preference.is_muted = bool(payload["is_muted"])
        preference.updated_at = now

    return sorted(existing.values(), key=lambda item: item.event_type)


def _template_map(db: Session) -> dict[str, NotificationTemplate]:
    templates = db.scalars(select(NotificationTemplate).where(NotificationTemplate.is_active == True)).all()  # noqa: E712
    return {item.code: item for item in templates}


def create_ticket_event_notification(
    db: Session,
    *,
    event_code: str,
    ticket: Ticket,
    actor_name: str,
    extra_context: dict[str, str] | None = None,
) -> Notification | None:
    templates = _template_map(db)
    template = templates.get(event_code)
    if template is None:
        return None

    context: dict[str, str] = {
        "ticket_id": ticket.id,
        "ticket_number": ticket.ticket_number or "N/A",
        "title": ticket.title,
        "status": ticket.status,
        "priority": ticket.priority,
        "assignee_name": ticket.assignee_name or "Не назначен",
        "actor_name": actor_name,
        "comment": "",
    }
    if extra_context:
        context.update(extra_context)

    tenant_id = ticket.tenant_id
    preferences = {
        item.event_type: item
        for item in db.scalars(select(NotificationPreference).where(NotificationPreference.user_id == ticket.requester_id)).all()
    }
    preference = preferences.get(event_code)
    channel_in_app = True if preference is None else (not preference.is_muted and preference.channel_in_app)
    channel_email = template.channel == "email" if preference is None else (not preference.is_muted and preference.channel_email)

    subject, body = render_template(template, context)
    notification: Notification | None = None
    if channel_in_app:
        notification = create_notification(
            db,
            type=event_code,
            title=subject,
            message=body,
            recipient_name=ticket.requester_name,
            recipient_email=ticket.requester_email,
            channel="in_app",
            status="UNREAD",
            related_ticket_id=ticket.id,
            user_id=ticket.requester_id,
            tenant_id=tenant_id,
            event_type=event_code,
            entity_type="ticket",
            entity_id=ticket.id,
            metadata={"ticket_number": ticket.ticket_number},
        )
    if channel_email:
        send_mock_email(
            db,
            to_email=ticket.requester_email,
            subject=subject,
            body=body,
            related_ticket_id=ticket.id,
            tenant_id=tenant_id,
            notification_id=notification.id if notification is not None else None,
            event_type=event_code,
            to_name=ticket.requester_name,
            metadata={"ticket_number": ticket.ticket_number},
        )
    return notification


def create_domain_event_notification(
    db: Session,
    *,
    tenant_id: str | None,
    event_type: str,
    title: str,
    message: str,
    recipient_name: str,
    recipient_email: str,
    recipient_user_id: str | None = None,
    channel: str = "in_app",
    severity: str = "info",
    entity_type: str | None = None,
    entity_id: str | None = None,
    action_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Notification:
    return create_notification(
        db,
        type=event_type,
        title=title,
        message=message,
        recipient_name=recipient_name,
        recipient_email=recipient_email,
        channel=channel,
        status="UNREAD",
        related_ticket_id=entity_id if entity_type == "ticket" else None,
        user_id=recipient_user_id,
        tenant_id=tenant_id,
        event_type=event_type,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        action_url=action_url,
        metadata=metadata,
    )


def seed_notification_templates(db: Session) -> None:
    existing_codes = set(db.scalars(select(NotificationTemplate.code)).all())
    for seed in TEMPLATE_SEEDS:
        if seed["code"] in existing_codes:
            continue
        now = datetime.now(UTC)
        db.add(
            NotificationTemplate(
                id=str(uuid.uuid4()),
                tenant_id=None,
                key=seed["code"],
                event_type=seed["code"],
                locale="ru",
                code=seed["code"],
                name=seed["name"],
                subject_template=seed["subject_template"],
                body_template=seed["body_template"],
                channel=seed["channel"],
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )


def seed_demo_notifications(db: Session) -> None:
    existing_count = int(db.scalar(select(func.count(Notification.id))) or 0)
    if existing_count >= 12:
        return

    tickets = db.scalars(select(Ticket).order_by(Ticket.created_at.desc()).limit(20)).all()
    if not tickets:
        return

    templates = _template_map(db)
    event_codes = [
        "ticket_created",
        "ticket_assigned",
        "ticket_status_changed",
        "ticket_comment_added",
        "ticket_resolved",
        "sla_warning",
        "sla_breached",
        "ai_recommendation_ready",
    ]
    created = existing_count
    for index, ticket in enumerate(tickets):
        if created >= 12:
            break
        event_code = event_codes[index % len(event_codes)]
        template = templates.get(event_code)
        if template is not None:
            notification = create_ticket_event_notification(
                db,
                event_code=event_code,
                ticket=ticket,
                actor_name="SBS Notification Bot",
                extra_context={"comment": "Demo notification event"},
            )
        else:
            notification = create_notification(
                db,
                type=event_code,
                title=f"[{ticket.ticket_number}] {event_code}",
                message=f"Demo notification for {ticket.ticket_number}: {ticket.title}",
                recipient_name=ticket.requester_name,
                recipient_email=ticket.requester_email,
                channel="in_app",
                status="UNREAD",
                related_ticket_id=ticket.id,
            )
        if notification and index % 3 == 0:
            notification.status = "READ"
            notification.read_at = datetime.now(UTC)
            notification.is_read = True
        if notification:
            created += 1


def enqueue_email_failure_demo(
    db: Session,
    *,
    tenant_id: str | None,
    to_email: str,
    subject: str,
    body: str,
    event_type: str,
    related_ticket_id: str | None = None,
) -> EmailMessageLog:
    now = datetime.now(UTC)
    log = EmailMessageLog(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        notification_id=None,
        event_type=event_type,
        provider="mock",
        provider_message_id=None,
        to_email=to_email,
        to_name=None,
        subject=subject,
        body=body,
        status="FAILED",
        attempt_count=1,
        max_attempts=3,
        next_retry_at=now + timedelta(minutes=5),
        payload_json=json.dumps({"subject": subject, "body": body}, ensure_ascii=False),
        metadata_json=None,
        error_message="Simulated delivery failure",
        related_ticket_id=related_ticket_id,
        created_at=now,
        sent_at=None,
    )
    db.add(log)
    return log
