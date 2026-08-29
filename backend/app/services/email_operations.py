from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import re
import secrets
import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.email_channel import (
    EmailAttachment,
    EmailChannel,
    EmailConversation,
    EmailDeliveryEvent,
    EmailInboundMessage,
    EmailWebhookEvent,
)
from app.models.email_message_log import EmailMessageLog
from app.models.service_request import RequestActivity, ServiceRequest
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_history import TicketHistory
from app.models.user import User
from app.services.credential_crypto import decrypt_credential, encrypt_credential
from app.services.email_attachments import store_graph_attachments
from app.services.microsoft_graph_email import (
    GraphEmailError,
    MicrosoftGraphEmailClient,
)
from app.services.request_fulfillment import request_number
from app.services.service_desk import next_ticket_number


THREAD_MARKER = re.compile(
    r"\[SBS:(?P<entity>T|R):(?P<token>[A-Za-z0-9_-]{16,64})\]",
    re.IGNORECASE,
)
_REPLY_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|sv)\s*:\s*)+", re.IGNORECASE)
_BOUNCE_LOG_ID = re.compile(
    r"(?:X-SBS-Message-ID\s*:\s*|SBS delivery reference\s+)([0-9a-f-]{36})",
    re.IGNORECASE,
)
_AUTO_SENDERS = (
    "mailer-daemon",
    "postmaster",
    "mail delivery subsystem",
    "microsoft outlook",
)


class EmailOperationError(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "li", "tr"}:
            self.parts.append("\n")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        return utcnow()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return utcnow()
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _normalize_email(value: str) -> str:
    _, address = parseaddr(value)
    return address.strip().lower()


def _normalize_subject(value: str) -> str:
    without_marker = THREAD_MARKER.sub("", value or "")
    normalized = _REPLY_PREFIX.sub("", without_marker).strip()
    return re.sub(r"\s+", " ", normalized)[:255] or "Email request"


def _plain_text(content: str, content_type: str) -> str:
    if content_type.lower() != "html":
        return content.replace("\x00", "")[:2_000_000].strip()
    parser = _TextExtractor()
    parser.feed(content[:4_000_000])
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()[:2_000_000]


def _safe_html(text: str) -> str:
    return escape(text).replace("\n", "<br>\n")


def _headers(message: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    rows = message.get("internetMessageHeaders", [])
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip().lower()
        value = str(row.get("value") or "").replace("\x00", "").strip()
        if name and len(name) <= 160 and len(value) <= 8_000:
            result[name] = value
    return result


def _address(raw: object) -> tuple[str | None, str]:
    if not isinstance(raw, dict):
        return None, ""
    email_address = raw.get("emailAddress")
    if not isinstance(email_address, dict):
        return None, ""
    return (
        str(email_address.get("name") or "")[:255] or None,
        _normalize_email(str(email_address.get("address") or "")),
    )


def _recipient_rows(message: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for field in ("toRecipients", "ccRecipients"):
        values = message.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            name, address = _address(value)
            if address:
                rows.append(
                    {
                        "type": "to" if field == "toRecipients" else "cc",
                        "address": address,
                        "name": name or "",
                    }
                )
    return rows


def _conversation_marker(conversation: EmailConversation) -> str:
    kind = "T" if conversation.entity_type == "TICKET" else "R"
    return f"[SBS:{kind}:{conversation.thread_token}]"


def _conversation_for_entity(
    db: Session,
    *,
    channel: EmailChannel,
    related_ticket_id: str | None,
    related_request_id: str | None,
    subject: str,
    recipient_email: str,
) -> EmailConversation | None:
    entity_type: str | None = None
    entity_id: str | None = None
    if related_ticket_id:
        entity_type, entity_id = "TICKET", related_ticket_id
    elif related_request_id:
        entity_type, entity_id = "REQUEST", related_request_id
    if entity_type is None or entity_id is None:
        return None
    existing = db.scalar(
        select(EmailConversation).where(
            EmailConversation.channel_id == channel.id,
            EmailConversation.entity_type == entity_type,
            EmailConversation.entity_id == entity_id,
        )
    )
    if existing:
        return existing
    existing_entity = (
        db.get(Ticket, entity_id)
        if entity_type == "TICKET"
        else db.get(ServiceRequest, entity_id)
    )
    requester_email = (
        existing_entity.requester_email
        if existing_entity is not None
        else recipient_email
    )
    item = EmailConversation(
        id=str(uuid.uuid4()),
        tenant_id=channel.tenant_id,
        channel_id=channel.id,
        thread_token=secrets.token_urlsafe(24),
        provider_conversation_id=None,
        root_internet_message_id=None,
        entity_type=entity_type,
        entity_id=entity_id,
        related_ticket_id=entity_id if entity_type == "TICKET" else None,
        related_request_id=entity_id if entity_type == "REQUEST" else None,
        requester_email=requester_email,
        normalized_subject=_normalize_subject(subject),
        last_message_at=utcnow(),
    )
    db.add(item)
    return item


def active_email_channel(
    db: Session,
    *,
    tenant_id: str,
    outbound: bool = False,
    inbound: bool = False,
) -> EmailChannel | None:
    conditions = [
        EmailChannel.tenant_id == tenant_id,
        EmailChannel.status == "ACTIVE",
    ]
    if outbound:
        conditions.append(EmailChannel.outbound_enabled.is_(True))
    if inbound:
        conditions.append(EmailChannel.inbound_enabled.is_(True))
    return db.scalar(
        select(EmailChannel)
        .where(*conditions)
        .order_by(EmailChannel.created_at.asc())
        .limit(1)
    )


def queue_email(
    db: Session,
    *,
    to_email: str,
    subject: str,
    body: str,
    tenant_id: str | None,
    to_name: str | None = None,
    event_type: str | None = None,
    notification_id: str | None = None,
    related_ticket_id: str | None = None,
    related_request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    settings: Settings | None = None,
) -> EmailMessageLog:
    runtime_settings = settings or get_settings()
    normalized_recipient = _normalize_email(to_email)
    if not normalized_recipient:
        raise EmailOperationError("A valid recipient email address is required")
    effective_key = idempotency_key or str(uuid.uuid4())
    if tenant_id:
        existing = db.scalar(
            select(EmailMessageLog).where(
                EmailMessageLog.tenant_id == tenant_id,
                EmailMessageLog.idempotency_key == effective_key,
            )
        )
        if existing:
            return existing
    channel = (
        active_email_channel(db, tenant_id=tenant_id, outbound=True)
        if tenant_id
        else None
    )
    now = utcnow()
    conversation = (
        _conversation_for_entity(
            db,
            channel=channel,
            related_ticket_id=related_ticket_id,
            related_request_id=related_request_id,
            subject=subject,
            recipient_email=normalized_recipient,
        )
        if channel
        else None
    )
    effective_subject = subject.strip()[:255]
    if conversation:
        marker = _conversation_marker(conversation)
        if marker.lower() not in effective_subject.lower():
            effective_subject = f"{effective_subject[: 254 - len(marker)]} {marker}".strip()
    log_id = str(uuid.uuid4())
    headers: dict[str, str] = {"X-SBS-Message-ID": log_id}
    provider = (
        channel.provider_type.lower()
        if channel
        else ("mock" if runtime_settings.demo_mode else "unconfigured")
    )
    status = "QUEUED"
    sent_at: datetime | None = None
    provider_message_id: str | None = None
    error: str | None = None
    if channel:
        loop_token = decrypt_credential(
            channel.loop_token_encrypted,
            purpose=f"email-channel:{channel.id}:loop-token",
            tenant_id=channel.tenant_id,
            settings=runtime_settings,
        )
        headers["X-SBS-Loop-Token"] = loop_token
        if conversation:
            headers["X-SBS-Entity"] = (
                f"{conversation.entity_type}:{conversation.entity_id}"
            )
        if channel.provider_type == "MOCK":
            if runtime_settings.demo_mode:
                status = "SIMULATED"
                error = "Simulation only; no external email was sent"
            else:
                status = "FAILED"
                error = "Mock email channels are disabled outside demo mode"
    elif runtime_settings.demo_mode:
        status = "SIMULATED"
        error = "Simulation only; no external email was sent"
    else:
        provider = "unconfigured"
        status = "FAILED"
        error = "No active outbound email channel is configured"

    item = EmailMessageLog(
        id=log_id,
        tenant_id=tenant_id,
        notification_id=notification_id,
        event_type=event_type,
        channel_id=channel.id if channel else None,
        direction="OUTBOUND",
        provider=provider,
        provider_message_id=provider_message_id,
        internet_message_id=None,
        conversation_id=conversation.id if conversation else None,
        idempotency_key=effective_key,
        from_email=channel.mailbox_address if channel else None,
        from_name=channel.name if channel else None,
        to_email=normalized_recipient,
        to_name=to_name,
        subject=effective_subject,
        body=body,
        status=status,
        attempt_count=0,
        max_attempts=5,
        next_retry_at=now if status == "QUEUED" else None,
        payload_json=_json({"subject": effective_subject, "body": body}),
        metadata_json=_json(metadata) if metadata else None,
        headers_json=_json(headers),
        error_message=error,
        related_ticket_id=related_ticket_id,
        related_request_id=related_request_id,
        created_at=now,
        queued_at=now if status == "QUEUED" else None,
        accepted_at=None,
        sent_at=sent_at,
        delivered_at=None,
        bounced_at=None,
        updated_at=now,
    )
    db.add(item)
    if channel:
        db.add(
            EmailDeliveryEvent(
                id=str(uuid.uuid4()),
                tenant_id=channel.tenant_id,
                channel_id=channel.id,
                email_log_id=item.id,
                provider_event_id=f"queued:{item.id}",
                event_type=(
                    "QUEUED"
                    if status == "QUEUED"
                    else "SIMULATED"
                    if status == "SIMULATED"
                    else "FAILED"
                ),
                reason=error,
                metadata_json={
                    "provider": provider,
                    "simulation": status == "SIMULATED",
                    "delivery_confirmed": False,
                },
                occurred_at=now,
            )
        )
    return item


def schedule_email_retry(
    db: Session,
    *,
    item: EmailMessageLog,
    reset_attempts: bool = False,
) -> EmailMessageLog:
    if item.status in {"ACCEPTED", "DELIVERED", "SENT", "SIMULATED"}:
        raise EmailOperationError(
            "Accepted, delivered, or simulated email cannot be retried"
        )
    if item.channel_id is None:
        raise EmailOperationError("Email has no configured delivery channel")
    channel = db.get(EmailChannel, item.channel_id)
    if channel is None or channel.status != "ACTIVE" or not channel.outbound_enabled:
        raise EmailOperationError("The outbound email channel is not active")
    if reset_attempts:
        item.attempt_count = 0
    elif item.attempt_count >= item.max_attempts:
        item.max_attempts = item.attempt_count + 1
    item.status = "QUEUED"
    item.next_retry_at = utcnow()
    item.error_message = None
    item.queued_at = utcnow()
    return item


def _record_delivery(
    db: Session,
    *,
    item: EmailMessageLog,
    event_type: str,
    provider_event_id: str,
    reason: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    if not item.channel_id or not item.tenant_id:
        return
    db.add(
        EmailDeliveryEvent(
            id=str(uuid.uuid4()),
            tenant_id=item.tenant_id,
            channel_id=item.channel_id,
            email_log_id=item.id,
            provider_event_id=provider_event_id,
            event_type=event_type,
            reason=reason,
            metadata_json=metadata or {},
            occurred_at=utcnow(),
        )
    )


def process_outbound_queue(
    db: Session,
    *,
    limit: int = 50,
    settings: Settings | None = None,
    graph_client_factory: type[MicrosoftGraphEmailClient] = MicrosoftGraphEmailClient,
) -> dict[str, int]:
    runtime_settings = settings or get_settings()
    # SessionLocal disables autoflush; queue transitions made in the current
    # unit of work must be visible to the worker selection query.
    db.flush()
    now = utcnow()
    rows = list(
        db.scalars(
            select(EmailMessageLog)
            .where(
                EmailMessageLog.status.in_(["QUEUED", "RETRY"]),
                or_(
                    EmailMessageLog.next_retry_at.is_(None),
                    EmailMessageLog.next_retry_at <= now,
                ),
            )
            .order_by(EmailMessageLog.created_at.asc())
            .limit(limit)
        ).all()
    )
    result = {
        "processed": 0,
        "accepted": 0,
        "simulated": 0,
        "retried": 0,
        "failed": 0,
    }
    for item in rows:
        result["processed"] += 1
        channel = db.get(EmailChannel, item.channel_id) if item.channel_id else None
        if (
            channel is None
            or channel.status != "ACTIVE"
            or not channel.outbound_enabled
        ):
            item.status = "FAILED"
            item.error_message = "Outbound email channel is unavailable"
            item.next_retry_at = None
            result["failed"] += 1
            continue
        item.attempt_count += 1
        headers = {
            str(key): str(value)
            for key, value in _json_object(item.headers_json).items()
        }
        try:
            if channel.provider_type == "MOCK":
                item.attempt_count = 0
                if not runtime_settings.demo_mode:
                    item.status = "FAILED"
                    item.provider_message_id = None
                    item.accepted_at = None
                    item.sent_at = None
                    item.delivered_at = None
                    item.error_message = (
                        "Mock email channels are disabled outside demo mode"
                    )
                    item.next_retry_at = None
                    channel.failure_count += 1
                    channel.last_failure_at = now
                    channel.last_error = item.error_message
                    _record_delivery(
                        db,
                        item=item,
                        event_type="FAILED",
                        provider_event_id=f"failed:mock-disabled:{item.id}",
                        reason=item.error_message,
                        metadata={
                            "provider": "mock",
                            "delivery_confirmed": False,
                        },
                    )
                    result["failed"] += 1
                    continue
                item.status = "SIMULATED"
                item.sent_at = None
                item.accepted_at = None
                item.delivered_at = None
                item.provider_message_id = None
                item.next_retry_at = None
                item.error_message = "Simulation only; no external email was sent"
                _record_delivery(
                    db,
                    item=item,
                    event_type="SIMULATED",
                    provider_event_id=f"simulated:{item.id}",
                    reason=item.error_message,
                    metadata={
                        "provider": "mock",
                        "simulation": True,
                        "delivery_confirmed": False,
                    },
                )
                result["simulated"] += 1
                continue
            client = graph_client_factory(channel, settings=runtime_settings)
            sent = client.send_mail(
                to_email=item.to_email,
                to_name=item.to_name,
                subject=item.subject,
                body=item.body,
                reply_to=channel.mailbox_address,
                headers=headers,
            )
            item.status = "ACCEPTED"
            item.provider_message_id = sent.request_id
            item.accepted_at = sent.accepted_at
            item.sent_at = sent.accepted_at
            item.next_retry_at = None
            item.error_message = None
            channel.success_count += 1
            channel.last_success_at = sent.accepted_at
            channel.last_error = None
            _record_delivery(
                db,
                item=item,
                event_type="ACCEPTED",
                provider_event_id=f"accepted:{sent.request_id}:{item.id}",
                reason=(
                    "Microsoft Graph accepted the request. Delivery is not asserted "
                    "until a provider delivery signal is received."
                ),
                metadata={"request_id": sent.request_id},
            )
            result["accepted"] += 1
        except (GraphEmailError, ValueError, RuntimeError) as exc:
            retryable = isinstance(exc, GraphEmailError) and exc.retryable
            retry_after = (
                exc.retry_after_seconds
                if isinstance(exc, GraphEmailError)
                else None
            )
            channel.failure_count += 1
            channel.last_failure_at = now
            channel.last_error = str(exc)[:2_000]
            item.error_message = str(exc)[:4_000]
            if retryable and item.attempt_count < item.max_attempts:
                delay = retry_after or min(15 * (2 ** (item.attempt_count - 1)), 3600)
                item.status = "RETRY"
                item.next_retry_at = now + timedelta(seconds=delay)
                result["retried"] += 1
            else:
                item.status = "FAILED"
                item.next_retry_at = None
                _record_delivery(
                    db,
                    item=item,
                    event_type="FAILED",
                    provider_event_id=f"failed:{item.attempt_count}:{item.id}",
                    reason=item.error_message,
                )
                result["failed"] += 1
    return result


def _is_bounce(message: EmailInboundMessage) -> bool:
    sender = f"{message.from_name or ''} {message.from_email}".lower()
    subject = message.subject.lower()
    return any(marker in sender for marker in _AUTO_SENDERS) and any(
        marker in subject
        for marker in ("undeliver", "delivery", "returned", "не достав", "недостав")
    )


def _apply_bounce(db: Session, inbound: EmailInboundMessage) -> bool:
    match = _BOUNCE_LOG_ID.search(
        f"{inbound.body_text}\n"
        + "\n".join(
            f"{name}: {value}" for name, value in inbound.headers_json.items()
        )
    )
    if not match:
        return False
    item = db.get(EmailMessageLog, match.group(1))
    if item is None or item.tenant_id != inbound.tenant_id:
        return False
    item.status = "BOUNCED"
    item.bounced_at = inbound.received_at
    item.error_message = inbound.subject[:500]
    item.next_retry_at = None
    _record_delivery(
        db,
        item=item,
        event_type="BOUNCED",
        provider_event_id=f"bounce:{inbound.provider_message_id}",
        reason=inbound.subject,
        metadata={"inbound_message_id": inbound.id},
    )
    inbound.related_ticket_id = item.related_ticket_id
    inbound.related_request_id = item.related_request_id
    return True


def _validation_result(
    channel: EmailChannel,
    inbound: EmailInboundMessage,
    *,
    settings: Settings,
) -> tuple[str | None, str | None]:
    if inbound.from_email == channel.mailbox_address.lower():
        return "LOOP", "Message was sent by the configured service mailbox"
    auto_submitted = inbound.headers_json.get("auto-submitted", "").lower()
    precedence = inbound.headers_json.get("precedence", "").lower()
    if auto_submitted and auto_submitted != "no":
        return "REJECTED", f"Automated message rejected ({auto_submitted})"
    if precedence in {"bulk", "junk", "list"}:
        return "REJECTED", f"Bulk/list message rejected ({precedence})"
    loop_header = inbound.headers_json.get("x-sbs-loop-token")
    if loop_header:
        expected = decrypt_credential(
            channel.loop_token_encrypted,
            purpose=f"email-channel:{channel.id}:loop-token",
            tenant_id=channel.tenant_id,
            settings=settings,
        )
        if secrets.compare_digest(loop_header, expected):
            return "LOOP", "Platform loop header detected"
    allowed_domains = {
        value.lower().lstrip("@")
        for value in (channel.allowed_sender_domains_json or [])
    }
    sender_domain = inbound.from_email.rsplit("@", 1)[-1]
    if allowed_domains and sender_domain not in allowed_domains:
        return "QUARANTINED", f"Sender domain {sender_domain} is not allowed"
    authentication = (inbound.authentication_results or "").lower()
    if re.search(r"\bdmarc=(fail|temperror|permerror)\b", authentication):
        return "QUARANTINED", "DMARC validation did not pass"
    return None, None


def _find_conversation(
    db: Session,
    *,
    channel: EmailChannel,
    inbound: EmailInboundMessage,
) -> EmailConversation | None:
    marker = THREAD_MARKER.search(inbound.subject)
    if marker:
        item = db.scalar(
            select(EmailConversation).where(
                EmailConversation.channel_id == channel.id,
                EmailConversation.thread_token == marker.group("token"),
            )
        )
        if item:
            return item
    if inbound.provider_conversation_id:
        item = db.scalar(
            select(EmailConversation).where(
                EmailConversation.channel_id == channel.id,
                EmailConversation.provider_conversation_id
                == inbound.provider_conversation_id,
            )
        )
        if item:
            return item
    reference_ids = [
        value
        for value in [inbound.in_reply_to, *inbound.references_json]
        if value
    ]
    if reference_ids:
        item = db.scalar(
            select(EmailConversation).where(
                EmailConversation.channel_id == channel.id,
                EmailConversation.root_internet_message_id.in_(reference_ids),
            )
        )
        if item:
            return item
    return None


def _sender_can_reply(
    db: Session,
    *,
    conversation: EmailConversation,
    sender_email: str,
) -> bool:
    if sender_email == conversation.requester_email.lower():
        return True
    user = db.scalar(
        select(User).where(
            User.tenant_id == conversation.tenant_id,
            func.lower(User.email) == sender_email,
            User.is_active.is_(True),
        )
    )
    return user is not None


def _create_ticket_from_email(
    db: Session,
    *,
    channel: EmailChannel,
    inbound: EmailInboundMessage,
) -> tuple[Ticket, EmailConversation]:
    requester = db.scalar(
        select(User).where(
            User.tenant_id == channel.tenant_id,
            func.lower(User.email) == inbound.from_email,
            User.is_active.is_(True),
        )
    )
    ticket = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=channel.tenant_id,
        ticket_number=next_ticket_number(db),
        title=_normalize_subject(inbound.subject),
        description=inbound.body_text or "(empty email body)",
        requester_name=inbound.from_name or inbound.from_email,
        requester_email=inbound.from_email,
        requester_id=requester.id if requester else None,
        department=(requester.department if requester else None) or "Email",
        location=(requester.location if requester else None) or "Email",
        category="MAIL",
        priority="MEDIUM",
        status="NEW",
        assignee_name=None,
        created_at=inbound.received_at,
        updated_at=inbound.received_at,
    )
    db.add(ticket)
    db.add(
        TicketHistory(
            id=str(uuid.uuid4()),
            ticket_id=ticket.id,
            actor_name=inbound.from_name or inbound.from_email,
            event_type="created_from_email",
            field_name="source",
            old_value=None,
            new_value="EMAIL",
            message=f"Ticket {ticket.ticket_number} was created from inbound email.",
            created_at=inbound.received_at,
        )
    )
    conversation = EmailConversation(
        id=str(uuid.uuid4()),
        tenant_id=channel.tenant_id,
        channel_id=channel.id,
        thread_token=secrets.token_urlsafe(24),
        provider_conversation_id=inbound.provider_conversation_id,
        root_internet_message_id=inbound.internet_message_id,
        entity_type="TICKET",
        entity_id=ticket.id,
        related_ticket_id=ticket.id,
        related_request_id=None,
        requester_email=inbound.from_email,
        normalized_subject=_normalize_subject(inbound.subject),
        last_provider_message_id=inbound.provider_message_id,
        last_message_at=inbound.received_at,
    )
    db.add(conversation)
    inbound.related_ticket_id = ticket.id
    return ticket, conversation


def _create_request_from_email(
    db: Session,
    *,
    channel: EmailChannel,
    inbound: EmailInboundMessage,
) -> tuple[ServiceRequest, EmailConversation]:
    requester = db.scalar(
        select(User).where(
            User.tenant_id == channel.tenant_id,
            func.lower(User.email) == inbound.from_email,
            User.is_active.is_(True),
        )
    )
    now = inbound.received_at
    item = ServiceRequest(
        id=str(uuid.uuid4()),
        tenant_id=channel.tenant_id,
        request_number=request_number(now),
        idempotency_key=f"email:{channel.id}:{inbound.provider_message_id}"[:120],
        requester_id=requester.id if requester else None,
        requester_name=inbound.from_name or inbound.from_email,
        requester_email=inbound.from_email,
        title=_normalize_subject(inbound.subject),
        description=inbound.body_text or "(empty email body)",
        source="EMAIL",
        status="SUBMITTED",
        priority="MEDIUM",
        requester_department=requester.department if requester else None,
        requester_location=requester.location if requester else None,
        cost_center=requester.cost_center if requester else None,
        total_cost_minor=0,
        currency="KZT",
        risk_level="LOW",
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    activity = RequestActivity(
        id=str(uuid.uuid4()),
        tenant_id=channel.tenant_id,
        request_id=item.id,
        requested_item_id=None,
        entity_type="service_request",
        entity_id=item.id,
        event_type="request.created_from_email",
        actor_user_id=requester.id if requester else None,
        actor_name=inbound.from_name or inbound.from_email,
        actor_email=inbound.from_email,
        visibility="PUBLIC",
        message=f"Request {item.request_number} was created from inbound email.",
        created_at=now,
    )
    db.add(activity)
    conversation = EmailConversation(
        id=str(uuid.uuid4()),
        tenant_id=channel.tenant_id,
        channel_id=channel.id,
        thread_token=secrets.token_urlsafe(24),
        provider_conversation_id=inbound.provider_conversation_id,
        root_internet_message_id=inbound.internet_message_id,
        entity_type="REQUEST",
        entity_id=item.id,
        related_ticket_id=None,
        related_request_id=item.id,
        requester_email=inbound.from_email,
        normalized_subject=_normalize_subject(inbound.subject),
        last_provider_message_id=inbound.provider_message_id,
        last_message_at=now,
    )
    db.add(conversation)
    inbound.related_request_id = item.id
    inbound.request_activity_id = activity.id
    return item, conversation


def _append_to_conversation(
    db: Session,
    *,
    inbound: EmailInboundMessage,
    conversation: EmailConversation,
) -> None:
    if conversation.entity_type == "TICKET":
        ticket = db.get(Ticket, conversation.entity_id)
        if ticket is None or ticket.tenant_id != inbound.tenant_id:
            raise EmailOperationError("Threaded ticket no longer exists")
        comment = TicketComment(
            id=str(uuid.uuid4()),
            ticket_id=ticket.id,
            author_id=None,
            author_name=inbound.from_name or inbound.from_email,
            author_role="email_requester",
            body=inbound.body_text or "(empty email body)",
            is_internal=False,
            created_at=inbound.received_at,
        )
        db.add(comment)
        db.add(
            TicketHistory(
                id=str(uuid.uuid4()),
                ticket_id=ticket.id,
                actor_name=inbound.from_name or inbound.from_email,
                event_type="email_reply_added",
                field_name=None,
                old_value=None,
                new_value=inbound.provider_message_id,
                message="Public requester reply received by email.",
                created_at=inbound.received_at,
            )
        )
        ticket.updated_at = inbound.received_at
        inbound.related_ticket_id = ticket.id
        inbound.ticket_comment_id = comment.id
    else:
        service_request = db.get(ServiceRequest, conversation.entity_id)
        if (
            service_request is None
            or service_request.tenant_id != inbound.tenant_id
        ):
            raise EmailOperationError("Threaded service request no longer exists")
        activity = RequestActivity(
            id=str(uuid.uuid4()),
            tenant_id=inbound.tenant_id,
            request_id=service_request.id,
            requested_item_id=None,
            entity_type="service_request",
            entity_id=service_request.id,
            event_type="comment.added_from_email",
            actor_user_id=None,
            actor_name=inbound.from_name or inbound.from_email,
            actor_email=inbound.from_email,
            visibility="PUBLIC",
            message=inbound.body_text or "(empty email body)",
            created_at=inbound.received_at,
        )
        db.add(activity)
        service_request.updated_at = inbound.received_at
        inbound.related_request_id = service_request.id
        inbound.request_activity_id = activity.id
    conversation.provider_conversation_id = (
        conversation.provider_conversation_id or inbound.provider_conversation_id
    )
    conversation.last_provider_message_id = inbound.provider_message_id
    conversation.last_message_at = inbound.received_at


def ingest_graph_message(
    db: Session,
    *,
    channel: EmailChannel,
    message: dict[str, Any],
    graph_client: MicrosoftGraphEmailClient | None = None,
    settings: Settings | None = None,
) -> EmailInboundMessage | None:
    runtime_settings = settings or get_settings()
    provider_message_id = str(message.get("id") or "")
    if not provider_message_id or "@removed" in message:
        return None
    existing = db.scalar(
        select(EmailInboundMessage).where(
            EmailInboundMessage.channel_id == channel.id,
            EmailInboundMessage.provider_message_id == provider_message_id,
        )
    )
    if existing:
        return existing
    from_name, from_email = _address(message.get("from"))
    body = message.get("body")
    body_object = body if isinstance(body, dict) else {}
    body_content = str(body_object.get("content") or message.get("bodyPreview") or "")
    body_type = str(body_object.get("contentType") or "text")
    text = _plain_text(body_content, body_type)
    headers = _headers(message)
    inbound = EmailInboundMessage(
        id=str(uuid.uuid4()),
        tenant_id=channel.tenant_id,
        channel_id=channel.id,
        conversation_id=None,
        provider_message_id=provider_message_id,
        provider_conversation_id=str(message.get("conversationId") or "") or None,
        internet_message_id=str(message.get("internetMessageId") or "") or None,
        in_reply_to=headers.get("in-reply-to"),
        references_json=headers.get("references", "").split(),
        from_email=from_email or "unknown@invalid",
        from_name=from_name,
        recipients_json=_recipient_rows(message),
        subject=str(message.get("subject") or "(no subject)")[:512],
        body_text=text,
        body_html_sanitized=_safe_html(text),
        headers_json=headers,
        authentication_results=headers.get("authentication-results"),
        status="RECEIVED",
        rejection_reason=None,
        processing_attempts=1,
        max_attempts=5,
        next_retry_at=None,
        received_at=_parse_datetime(message.get("receivedDateTime")),
    )
    db.add(inbound)
    db.flush()

    if _is_bounce(inbound) and _apply_bounce(db, inbound):
        inbound.status = "PROCESSED"
        inbound.processed_at = utcnow()
        return inbound

    rejected_status, reason = _validation_result(
        channel,
        inbound,
        settings=runtime_settings,
    )
    if rejected_status:
        inbound.status = rejected_status
        inbound.rejection_reason = reason
        inbound.processed_at = utcnow()
        return inbound

    conversation = _find_conversation(db, channel=channel, inbound=inbound)
    if conversation and not _sender_can_reply(
        db,
        conversation=conversation,
        sender_email=inbound.from_email,
    ):
        inbound.status = "QUARANTINED"
        inbound.rejection_reason = (
            "Sender is not the requester or an active user in this tenant"
        )
        inbound.processed_at = utcnow()
        return inbound

    attachments: list[dict[str, Any]] = []
    if bool(message.get("hasAttachments")):
        client = graph_client or MicrosoftGraphEmailClient(
            channel,
            settings=runtime_settings,
        )
        attachments = client.list_attachments(provider_message_id)

    if conversation:
        inbound.conversation_id = conversation.id
        _append_to_conversation(db, inbound=inbound, conversation=conversation)
    elif channel.default_target == "REQUEST":
        _, conversation = _create_request_from_email(
            db,
            channel=channel,
            inbound=inbound,
        )
        inbound.conversation_id = conversation.id
    else:
        _, conversation = _create_ticket_from_email(
            db,
            channel=channel,
            inbound=inbound,
        )
        inbound.conversation_id = conversation.id

    if attachments:
        store_graph_attachments(
            db,
            channel=channel,
            inbound=inbound,
            graph_attachments=attachments,
            settings=runtime_settings,
        )
    inbound.status = "PROCESSED"
    inbound.processed_at = utcnow()
    channel.success_count += 1
    channel.last_success_at = utcnow()
    channel.last_error = None
    return inbound


def sync_email_channel(
    db: Session,
    *,
    channel: EmailChannel,
    settings: Settings | None = None,
    graph_client: MicrosoftGraphEmailClient | None = None,
) -> dict[str, int]:
    runtime_settings = settings or get_settings()
    if (
        channel.provider_type != "MICROSOFT_GRAPH"
        or channel.status != "ACTIVE"
        or not channel.inbound_enabled
    ):
        return {"received": 0, "processed": 0, "failed": 0}
    client = graph_client or MicrosoftGraphEmailClient(
        channel,
        settings=runtime_settings,
    )
    delta_link = (
        decrypt_credential(
            channel.delta_link_encrypted,
            purpose=f"email-channel:{channel.id}:delta-link",
            tenant_id=channel.tenant_id,
            settings=runtime_settings,
        )
        if channel.delta_link_encrypted
        else None
    )
    messages, new_delta = client.message_delta(delta_link=delta_link)
    result = {"received": len(messages), "processed": 0, "failed": 0}
    for message in messages:
        try:
            with db.begin_nested():
                item = ingest_graph_message(
                    db,
                    channel=channel,
                    message=message,
                    graph_client=client,
                    settings=runtime_settings,
                )
                if item and item.status in {
                    "PROCESSED",
                    "REJECTED",
                    "QUARANTINED",
                    "LOOP",
                }:
                    result["processed"] += 1
        except (EmailOperationError, GraphEmailError, IntegrityError, OSError, ValueError) as exc:
            result["failed"] += 1
            channel.failure_count += 1
            channel.last_failure_at = utcnow()
            channel.last_error = str(exc)[:2_000]
    if result["failed"] == 0 and new_delta:
        channel.delta_link_encrypted = encrypt_credential(
            new_delta,
            purpose=f"email-channel:{channel.id}:delta-link",
            tenant_id=channel.tenant_id,
            settings=runtime_settings,
        )
    channel.last_sync_at = utcnow()
    return result


def persist_graph_notifications(
    db: Session,
    *,
    channel: EmailChannel,
    notifications: list[dict[str, Any]],
) -> int:
    created = 0
    for payload in notifications:
        subscription_id = str(payload.get("subscriptionId") or "")
        resource = str(payload.get("resource") or "")
        explicit_id = str(payload.get("id") or "")
        digest_source = _json(
            {
                "subscription": subscription_id,
                "resource": resource,
                "change": payload.get("changeType"),
                "resource_data": payload.get("resourceData"),
            }
        )
        provider_event_id = explicit_id or hashlib.sha256(
            digest_source.encode("utf-8")
        ).hexdigest()
        exists = db.scalar(
            select(EmailWebhookEvent.id).where(
                EmailWebhookEvent.channel_id == channel.id,
                EmailWebhookEvent.provider_event_id == provider_event_id,
            )
        )
        if exists:
            continue
        db.add(
            EmailWebhookEvent(
                id=str(uuid.uuid4()),
                tenant_id=channel.tenant_id,
                channel_id=channel.id,
                provider_event_id=provider_event_id,
                subscription_id=subscription_id or None,
                resource=resource[:1024] or None,
                change_type=str(payload.get("changeType") or "")[:64] or None,
                status="PENDING",
                attempt_count=0,
                max_attempts=5,
                next_retry_at=utcnow(),
                payload_json=payload,
            )
        )
        created += 1
    return created


def _message_id_from_webhook(event: EmailWebhookEvent) -> str | None:
    resource_data = event.payload_json.get("resourceData")
    if isinstance(resource_data, dict) and resource_data.get("id"):
        return str(resource_data["id"])
    if event.resource:
        match = re.search(r"/messages/([^/?]+)", event.resource, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def process_webhook_events(
    db: Session,
    *,
    limit: int = 50,
    settings: Settings | None = None,
) -> dict[str, int]:
    runtime_settings = settings or get_settings()
    now = utcnow()
    events = list(
        db.scalars(
            select(EmailWebhookEvent)
            .where(
                EmailWebhookEvent.status.in_(["PENDING", "FAILED"]),
                or_(
                    EmailWebhookEvent.next_retry_at.is_(None),
                    EmailWebhookEvent.next_retry_at <= now,
                ),
            )
            .order_by(EmailWebhookEvent.created_at.asc())
            .limit(limit)
        ).all()
    )
    result = {"processed": 0, "failed": 0, "dead_letter": 0}
    for event in events:
        channel = db.get(EmailChannel, event.channel_id)
        if channel is None or channel.status != "ACTIVE":
            event.status = "FAILED"
            event.error_message = "Email channel is not active"
            event.next_retry_at = now + timedelta(minutes=5)
            result["failed"] += 1
            continue
        event.attempt_count += 1
        event.status = "PROCESSING"
        message_id = _message_id_from_webhook(event)
        try:
            if not message_id:
                raise EmailOperationError(
                    "Webhook notification does not contain a message ID"
                )
            client = MicrosoftGraphEmailClient(channel, settings=runtime_settings)
            message = client.get_message(message_id)
            with db.begin_nested():
                ingest_graph_message(
                    db,
                    channel=channel,
                    message=message,
                    graph_client=client,
                    settings=runtime_settings,
                )
            event.status = "PROCESSED"
            event.processed_at = utcnow()
            event.next_retry_at = None
            event.error_message = None
            result["processed"] += 1
        except (EmailOperationError, GraphEmailError, IntegrityError, OSError, ValueError) as exc:
            event.error_message = str(exc)[:4_000]
            if event.attempt_count >= event.max_attempts:
                event.status = "DEAD_LETTER"
                event.next_retry_at = None
                result["dead_letter"] += 1
            else:
                event.status = "FAILED"
                event.next_retry_at = now + timedelta(
                    seconds=min(30 * (2 ** (event.attempt_count - 1)), 3600)
                )
                result["failed"] += 1
    return result


def reprocess_inbound_message(
    db: Session,
    *,
    inbound: EmailInboundMessage,
    override_sender_authorization: bool,
    settings: Settings | None = None,
) -> EmailInboundMessage:
    runtime_settings = settings or get_settings()
    if inbound.status not in {"QUARANTINED", "FAILED", "DEAD_LETTER"}:
        raise EmailOperationError(
            "Only quarantined or failed inbound email can be reprocessed"
        )
    channel = db.get(EmailChannel, inbound.channel_id)
    if channel is None or channel.status != "ACTIVE" or not channel.inbound_enabled:
        raise EmailOperationError("Inbound email channel is not active")
    conversation = _find_conversation(db, channel=channel, inbound=inbound)
    if (
        conversation
        and not override_sender_authorization
        and not _sender_can_reply(
            db,
            conversation=conversation,
            sender_email=inbound.from_email,
        )
    ):
        raise EmailOperationError(
            "Sender is not authorized for this conversation; an explicit override is required"
        )
    client = MicrosoftGraphEmailClient(channel, settings=runtime_settings)
    if (
        not db.scalar(
            select(EmailAttachment.id).where(
                EmailAttachment.inbound_message_id == inbound.id
            )
        )
    ):
        message = client.get_message(inbound.provider_message_id)
        if bool(message.get("hasAttachments")):
            store_graph_attachments(
                db,
                channel=channel,
                inbound=inbound,
                graph_attachments=client.list_attachments(
                    inbound.provider_message_id
                ),
                settings=runtime_settings,
            )
    inbound.processing_attempts += 1
    inbound.rejection_reason = None
    inbound.next_retry_at = None
    if conversation:
        inbound.conversation_id = conversation.id
        _append_to_conversation(db, inbound=inbound, conversation=conversation)
    elif channel.default_target == "REQUEST":
        _, conversation = _create_request_from_email(
            db,
            channel=channel,
            inbound=inbound,
        )
        inbound.conversation_id = conversation.id
    else:
        _, conversation = _create_ticket_from_email(
            db,
            channel=channel,
            inbound=inbound,
        )
        inbound.conversation_id = conversation.id
    inbound.status = "PROCESSED"
    inbound.processed_at = utcnow()
    return inbound


def renew_graph_subscriptions(
    db: Session,
    *,
    settings: Settings | None = None,
) -> dict[str, int]:
    runtime_settings = settings or get_settings()
    if not runtime_settings.email_public_base_url:
        return {"renewed": 0, "failed": 0}
    threshold = utcnow() + timedelta(hours=12)
    channels = list(
        db.scalars(
            select(EmailChannel).where(
                EmailChannel.provider_type == "MICROSOFT_GRAPH",
                EmailChannel.status == "ACTIVE",
                EmailChannel.inbound_enabled.is_(True),
                EmailChannel.graph_subscription_id.is_not(None),
                EmailChannel.graph_subscription_expires_at <= threshold,
            )
        ).all()
    )
    result = {"renewed": 0, "failed": 0}
    for channel in channels:
        try:
            payload = MicrosoftGraphEmailClient(
                channel,
                settings=runtime_settings,
            ).renew_subscription(channel.graph_subscription_id or "")
            channel.graph_subscription_expires_at = _parse_datetime(
                payload.get("expirationDateTime")
            )
            channel.last_success_at = utcnow()
            channel.last_error = None
            result["renewed"] += 1
        except (GraphEmailError, ValueError, RuntimeError) as exc:
            channel.failure_count += 1
            channel.last_failure_at = utcnow()
            channel.last_error = str(exc)[:2_000]
            result["failed"] += 1
    return result


def run_email_operations_cycle(
    db: Session,
    *,
    settings: Settings | None = None,
) -> dict[str, object]:
    runtime_settings = settings or get_settings()
    outbound = process_outbound_queue(
        db,
        limit=runtime_settings.email_worker_batch_size,
        settings=runtime_settings,
    )
    webhooks = process_webhook_events(
        db,
        limit=runtime_settings.email_worker_batch_size,
        settings=runtime_settings,
    )
    polled = {"channels": 0, "received": 0, "processed": 0, "failed": 0}
    channels = list(
        db.scalars(
            select(EmailChannel).where(
                EmailChannel.provider_type == "MICROSOFT_GRAPH",
                EmailChannel.status == "ACTIVE",
                EmailChannel.inbound_enabled.is_(True),
                or_(
                    EmailChannel.last_sync_at.is_(None),
                    EmailChannel.last_sync_at
                    <= utcnow()
                    - timedelta(seconds=runtime_settings.email_poll_interval_seconds),
                ),
            )
        ).all()
    )
    for channel in channels:
        polled["channels"] += 1
        try:
            sync_result = sync_email_channel(
                db,
                channel=channel,
                settings=runtime_settings,
            )
            for key in ("received", "processed", "failed"):
                polled[key] += sync_result[key]
        except (GraphEmailError, ValueError, RuntimeError) as exc:
            channel.failure_count += 1
            channel.last_failure_at = utcnow()
            channel.last_error = str(exc)[:2_000]
            channel.last_sync_at = utcnow()
            polled["failed"] += 1
    subscriptions = renew_graph_subscriptions(db, settings=runtime_settings)
    return {
        "outbound": outbound,
        "webhooks": webhooks,
        "polling": polled,
        "subscriptions": subscriptions,
    }
