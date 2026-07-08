from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.notification import Notification
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
) -> Notification:
    notification = Notification(
        id=str(uuid.uuid4()),
        type=type,
        title=title,
        message=message,
        recipient_name=recipient_name,
        recipient_email=recipient_email,
        channel=channel,
        status=status,
        related_ticket_id=related_ticket_id,
        created_at=datetime.now(UTC),
        read_at=None,
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
    return notification


def mark_all_as_read(db: Session) -> int:
    notifications = db.scalars(select(Notification).where(Notification.status != "READ")).all()
    now = datetime.now(UTC)
    for notification in notifications:
        notification.status = "READ"
        notification.read_at = now
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


def send_mock_email(
    db: Session,
    *,
    to_email: str,
    subject: str,
    body: str,
    related_ticket_id: str | None = None,
    provider: BaseEmailProvider | None = None,
):
    active_provider = provider or MockEmailProvider()
    return active_provider.send_email(
        db,
        to_email=to_email,
        subject=subject,
        body=body,
        related_ticket_id=related_ticket_id,
    )


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

    subject, body = render_template(template, context)
    notification = create_notification(
        db,
        type=event_code,
        title=subject,
        message=body,
        recipient_name=ticket.requester_name,
        recipient_email=ticket.requester_email,
        channel=template.channel,
        status="UNREAD",
        related_ticket_id=ticket.id,
    )
    if template.channel == "email":
        send_mock_email(
            db,
            to_email=ticket.requester_email,
            subject=subject,
            body=body,
            related_ticket_id=ticket.id,
        )
    return notification


def seed_notification_templates(db: Session) -> None:
    existing_codes = set(db.scalars(select(NotificationTemplate.code)).all())
    for seed in TEMPLATE_SEEDS:
        if seed["code"] in existing_codes:
            continue
        now = datetime.now(UTC)
        db.add(
            NotificationTemplate(
                id=str(uuid.uuid4()),
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
        if notification:
            created += 1
