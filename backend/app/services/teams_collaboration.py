from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.major_incident import MajorIncident
from app.models.teams_collaboration import (
    TeamsConnector,
    TeamsDelivery,
    TeamsMajorIncidentRoom,
)
from app.services.credential_crypto import decrypt_credential


logger = logging.getLogger("app.teams")
DEFAULT_TEAMS_EVENTS = [
    "ticket_created",
    "ticket_assigned",
    "ticket_status_changed",
    "ticket_resolved",
    "sla_warning",
    "sla_breached",
    "approval_required",
    "approval.requested",
    "approval_approved",
    "approval_rejected",
    "security_high_risk",
    "major_incident.declared",
    "major_incident.update",
    "major_incident.transitioned",
    "automation_failed",
    "jobs.failed",
    "jobs.dead_letter",
]
_SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_ -]?key|authorization)\b\s*[:=]\s*\S+"
)


class TeamsDeliveryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


def utcnow() -> datetime:
    return datetime.now(UTC)


def _purpose_for_event(event_type: str) -> set[str]:
    normalized = event_type.lower()
    if "major_incident" in normalized:
        return {"DEFAULT", "MAJOR_INCIDENT"}
    if "approval" in normalized:
        return {"DEFAULT", "APPROVALS"}
    if "security" in normalized:
        return {"DEFAULT", "SECURITY"}
    return {"DEFAULT"}


def _normalize_severity(value: str | None) -> str:
    normalized = (value or "INFO").strip().upper()
    aliases = {
        "INFORMATION": "INFO",
        "SUCCESS": "INFO",
        "LOW": "INFO",
        "MEDIUM": "WARNING",
        "WARN": "WARNING",
        "HIGH": "CRITICAL",
        "ERROR": "CRITICAL",
        "DANGER": "CRITICAL",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in _SEVERITY_RANK else "INFO"


def _sanitized_text(value: str, *, max_length: int) -> str:
    cleaned = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}: [REDACTED]", value)
    cleaned = " ".join(cleaned.split())
    return cleaned[:max_length]


def _host_allowed(hostname: str, allowed_hosts: list[str]) -> bool:
    host = hostname.rstrip(".").lower()
    for raw in allowed_hosts:
        rule = raw.strip().lower().rstrip(".")
        if not rule:
            continue
        if rule.startswith("."):
            if host.endswith(rule) and host != rule[1:]:
                return True
        elif host == rule:
            return True
    return False


def validate_workflow_webhook_url(
    value: str,
    *,
    settings: Settings | None = None,
) -> str:
    runtime = settings or get_settings()
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.port not in {None, 443}
    ):
        raise ValueError("Teams Workflow webhook must be an explicit HTTPS URL")
    allowed = [str(item) for item in runtime.teams_webhook_allowed_hosts]
    if not _host_allowed(parsed.hostname, allowed):
        raise ValueError("Teams Workflow webhook host is not in the configured allowlist")
    return normalized


def validate_teams_deep_link(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Teams link must be an explicit HTTPS URL")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname not in {"teams.microsoft.com", "teams.live.com"}:
        raise ValueError("Only Microsoft Teams deep links are accepted")
    return normalized


def _secure_action_url(
    action_url: str | None,
    *,
    settings: Settings,
) -> str | None:
    if not action_url or not settings.teams_public_base_url:
        return None
    base = settings.teams_public_base_url.rstrip("/") + "/"
    parsed_action = urlsplit(action_url)
    if parsed_action.scheme or parsed_action.netloc:
        candidate = action_url
    else:
        candidate = urljoin(base, action_url.lstrip("/"))
    candidate_parts = urlsplit(candidate)
    base_parts = urlsplit(base)
    if (
        candidate_parts.scheme != "https"
        or candidate_parts.hostname != base_parts.hostname
        or candidate_parts.port != base_parts.port
    ):
        return None
    return candidate


def build_teams_card(
    *,
    event_type: str,
    severity: str,
    title: str,
    message: str,
    entity_type: str | None,
    entity_id: str | None,
    action_url: str | None,
    channel_url: str | None = None,
    meeting_url: str | None = None,
) -> dict[str, object]:
    body: list[dict[str, object]] = [
        {
            "type": "TextBlock",
            "text": _sanitized_text(title, max_length=255),
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": _sanitized_text(message, max_length=2_500),
            "wrap": True,
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Event", "value": event_type[:120]},
                {"title": "Severity", "value": severity},
                {
                    "title": "Object",
                    "value": (
                        f"{entity_type}: {entity_id}"
                        if entity_type and entity_id
                        else "Platform event"
                    ),
                },
                {"title": "Time (UTC)", "value": utcnow().isoformat()},
            ],
        },
    ]
    actions: list[dict[str, str]] = []
    if action_url:
        label = (
            "Review and decide securely"
            if "approval" in event_type.lower()
            else "Open in SBS AI ITSM"
        )
        actions.append({"type": "Action.OpenUrl", "title": label, "url": action_url})
    if channel_url:
        actions.append(
            {"type": "Action.OpenUrl", "title": "Open incident channel", "url": channel_url}
        )
    if meeting_url:
        actions.append(
            {"type": "Action.OpenUrl", "title": "Join incident meeting", "url": meeting_url}
        )
    card: dict[str, object] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


def _eligible_connectors(
    db: Session,
    *,
    tenant_id: str,
    event_type: str,
    severity: str,
) -> list[TeamsConnector]:
    purposes = _purpose_for_event(event_type)
    connectors = db.scalars(
        select(TeamsConnector).where(
            TeamsConnector.tenant_id == tenant_id,
            TeamsConnector.status == "ACTIVE",
            TeamsConnector.purpose.in_(purposes),
        )
    ).all()
    event_key = event_type.lower()
    minimum_rank = _SEVERITY_RANK[_normalize_severity(severity)]
    return [
        item
        for item in connectors
        if (
            "*" in item.event_types_json
            or event_key in {entry.lower() for entry in item.event_types_json}
        )
        and minimum_rank >= _SEVERITY_RANK.get(item.minimum_severity, 0)
    ]


def _recent_duplicate(
    db: Session,
    *,
    connector_id: str,
    event_type: str,
    entity_type: str | None,
    entity_id: str | None,
    title: str,
    message: str,
) -> TeamsDelivery | None:
    since = utcnow() - timedelta(seconds=15)
    return db.scalar(
        select(TeamsDelivery)
        .where(
            TeamsDelivery.connector_id == connector_id,
            TeamsDelivery.event_type == event_type,
            TeamsDelivery.entity_type == entity_type,
            TeamsDelivery.entity_id == entity_id,
            TeamsDelivery.title == title,
            TeamsDelivery.message == message,
            TeamsDelivery.created_at >= since,
        )
        .order_by(TeamsDelivery.created_at.desc())
        .limit(1)
    )


def queue_teams_event(
    db: Session,
    *,
    tenant_id: str | None,
    event_type: str,
    title: str,
    message: str,
    severity: str = "INFO",
    entity_type: str | None = None,
    entity_id: str | None = None,
    action_url: str | None = None,
    notification_id: str | None = None,
    idempotency_source: str | None = None,
) -> list[TeamsDelivery]:
    if not tenant_id:
        return []
    runtime = get_settings()
    normalized_severity = _normalize_severity(severity)
    safe_title = _sanitized_text(title, max_length=255)
    safe_message = _sanitized_text(message, max_length=4_000)
    secure_url = _secure_action_url(action_url, settings=runtime)
    queued: list[TeamsDelivery] = []
    for connector in _eligible_connectors(
        db,
        tenant_id=tenant_id,
        event_type=event_type,
        severity=normalized_severity,
    ):
        if connector.provider_type == "MOCK" and not runtime.demo_mode:
            continue
        duplicate = _recent_duplicate(
            db,
            connector_id=connector.id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            title=safe_title,
            message=safe_message,
        )
        if duplicate is not None:
            continue
        raw_key = "|".join(
            [
                connector.id,
                idempotency_source or notification_id or str(uuid.uuid4()),
                event_type,
            ]
        )
        key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        payload = build_teams_card(
            event_type=event_type,
            severity=normalized_severity,
            title=safe_title,
            message=safe_message,
            entity_type=entity_type,
            entity_id=entity_id,
            action_url=secure_url,
            channel_url=connector.channel_url
            if connector.purpose == "MAJOR_INCIDENT"
            else None,
            meeting_url=connector.meeting_url
            if connector.purpose == "MAJOR_INCIDENT"
            else None,
        )
        now = utcnow()
        delivery = TeamsDelivery(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            connector_id=connector.id,
            notification_id=notification_id,
            event_type=event_type[:120],
            severity=normalized_severity,
            entity_type=entity_type,
            entity_id=entity_id,
            idempotency_key=key,
            title=safe_title,
            message=safe_message,
            action_url=secure_url,
            payload_json=payload,
            status="QUEUED",
            attempts=0,
            max_attempts=6,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(delivery)
        queued.append(delivery)
    return queued


def ensure_major_incident_room(
    db: Session,
    *,
    incident: MajorIncident,
    opened_by_id: str | None,
) -> TeamsMajorIncidentRoom | None:
    existing = db.scalar(
        select(TeamsMajorIncidentRoom).where(
            TeamsMajorIncidentRoom.major_incident_id == incident.id
        )
    )
    if existing is not None:
        return existing
    connector = db.scalar(
        select(TeamsConnector)
        .where(
            TeamsConnector.tenant_id == incident.tenant_id,
            TeamsConnector.status == "ACTIVE",
            TeamsConnector.purpose == "MAJOR_INCIDENT",
            *(
                ()
                if get_settings().demo_mode
                else (TeamsConnector.provider_type == "WORKFLOW_WEBHOOK",)
            ),
        )
        .order_by(TeamsConnector.created_at.asc())
        .limit(1)
    )
    if connector is None:
        return None
    now = utcnow()
    room = TeamsMajorIncidentRoom(
        id=str(uuid.uuid4()),
        tenant_id=incident.tenant_id,
        connector_id=connector.id,
        major_incident_id=incident.id,
        status="OPEN",
        channel_url=connector.channel_url,
        meeting_url=connector.meeting_url,
        opened_by_id=opened_by_id,
        opened_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(room)
    if not incident.war_room_url:
        incident.war_room_url = connector.meeting_url or connector.channel_url
    return room


def queue_major_incident_event(
    db: Session,
    *,
    incident: MajorIncident,
    event_type: str,
    detail: str,
    actor_user_id: str | None,
) -> list[TeamsDelivery]:
    room = ensure_major_incident_room(
        db,
        incident=incident,
        opened_by_id=actor_user_id,
    )
    if room is not None and incident.status in {"CLOSED", "CANCELLED"}:
        room.status = "CLOSED"
        room.closed_by_id = actor_user_id
        room.closed_at = utcnow()
        room.updated_at = utcnow()
    return queue_teams_event(
        db,
        tenant_id=incident.tenant_id,
        event_type=event_type,
        title=f"{incident.severity} {incident.major_number}: {incident.title}",
        message=(
            f"Status: {incident.status}. Service: {incident.affected_service}. "
            f"Service state: {incident.service_status}. {detail}"
        ),
        severity="CRITICAL" if incident.severity == "SEV1" else "WARNING",
        entity_type="major_incident",
        entity_id=incident.id,
        action_url=f"/major-incidents?major_incident_id={incident.id}",
        idempotency_source=f"{incident.id}:{event_type}:{incident.version}",
    )


def _retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return min(max(int(raw), 1), 3_600)
    except ValueError:
        return None


def deliver_teams_payload(
    connector: TeamsConnector,
    payload: dict[str, object],
    *,
    settings: Settings | None = None,
) -> tuple[int, str | None]:
    runtime = settings or get_settings()
    if connector.provider_type == "MOCK":
        raise TeamsDeliveryError(
            "Mock Teams connector is simulation-only",
            retryable=False,
        )
    if not connector.webhook_url_encrypted:
        raise TeamsDeliveryError("Teams webhook is not configured", retryable=False)
    try:
        webhook_url = decrypt_credential(
            connector.webhook_url_encrypted,
            purpose=f"teams-webhook:{connector.id}",
            tenant_id=connector.tenant_id,
            settings=runtime,
        )
        webhook_url = validate_workflow_webhook_url(webhook_url, settings=runtime)
    except (RuntimeError, ValueError) as exc:
        raise TeamsDeliveryError(str(exc), retryable=False) from exc
    try:
        with httpx.Client(
            timeout=runtime.teams_request_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = client.post(
                webhook_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "SBS-AI-ITSM/Teams-Delivery",
                },
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise TeamsDeliveryError(
            f"Teams network failure: {exc.__class__.__name__}",
            retryable=True,
        ) from exc
    if response.status_code in {200, 201, 202}:
        provider_reference = response.headers.get("x-ms-workflow-run-id")
        return response.status_code, provider_reference
    retryable = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
    raise TeamsDeliveryError(
        f"Teams webhook returned HTTP {response.status_code}",
        retryable=retryable,
        status_code=response.status_code,
        retry_after_seconds=_retry_after(response),
    )


def process_teams_delivery(
    db: Session,
    delivery: TeamsDelivery,
    *,
    settings: Settings | None = None,
) -> TeamsDelivery:
    runtime = settings or get_settings()
    connector = db.get(TeamsConnector, delivery.connector_id)
    now = utcnow()
    delivery.attempts += 1
    delivery.last_attempt_at = now
    delivery.updated_at = now
    if connector is None or connector.status != "ACTIVE":
        delivery.status = "CANCELLED"
        delivery.last_error = "Connector is not active"
        return delivery
    if connector.provider_type == "MOCK":
        delivery.attempts = 0
        delivery.last_attempt_at = None
        delivery.sent_at = None
        delivery.provider_status_code = None
        delivery.provider_reference = None
        delivery.next_attempt_at = now
        if runtime.demo_mode:
            delivery.status = "SIMULATED"
            delivery.last_error = (
                "Simulation only; no Microsoft Teams webhook was called"
            )
        else:
            delivery.status = "FAILED"
            delivery.last_error = (
                "Mock Teams connectors are disabled outside demo mode"
            )
            connector.last_failure_at = now
            connector.failure_count += 1
            connector.last_error = delivery.last_error
        connector.updated_at = now
        return delivery
    try:
        status_code, reference = deliver_teams_payload(
            connector,
            delivery.payload_json,
            settings=runtime,
        )
        delivery.status = "SENT"
        delivery.sent_at = now
        delivery.provider_status_code = status_code
        delivery.provider_reference = reference
        delivery.last_error = None
        connector.last_success_at = now
        connector.success_count += 1
        connector.last_error = None
    except TeamsDeliveryError as exc:
        delivery.provider_status_code = exc.status_code
        delivery.last_error = str(exc)[:2_000]
        connector.last_failure_at = now
        connector.failure_count += 1
        connector.last_error = delivery.last_error
        if exc.retryable and delivery.attempts < delivery.max_attempts:
            delay = exc.retry_after_seconds or min(30 * (2 ** (delivery.attempts - 1)), 3_600)
            delivery.status = "RETRY"
            delivery.next_attempt_at = now + timedelta(seconds=delay)
        else:
            delivery.status = "DEAD_LETTER" if delivery.attempts >= delivery.max_attempts else "FAILED"
    connector.updated_at = now
    return delivery


def run_teams_delivery_cycle(
    db: Session,
    *,
    settings: Settings | None = None,
) -> dict[str, int]:
    runtime = settings or get_settings()
    now = utcnow()
    rows = list(
        db.scalars(
            select(TeamsDelivery)
            .where(
                TeamsDelivery.status.in_(["QUEUED", "RETRY"]),
                TeamsDelivery.next_attempt_at <= now,
            )
            .order_by(TeamsDelivery.next_attempt_at.asc())
            .limit(runtime.teams_worker_batch_size)
            .with_for_update(skip_locked=True)
        ).all()
    )
    sent = 0
    simulated = 0
    failed = 0
    retried = 0
    for row in rows:
        process_teams_delivery(db, row, settings=runtime)
        if row.status == "SENT":
            sent += 1
        elif row.status == "SIMULATED":
            simulated += 1
        elif row.status == "RETRY":
            retried += 1
        elif row.status in {"FAILED", "DEAD_LETTER", "CANCELLED"}:
            failed += 1
    return {
        "processed": len(rows),
        "sent": sent,
        "simulated": simulated,
        "retried": retried,
        "failed": failed,
    }
