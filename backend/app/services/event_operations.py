from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
import secrets
import struct
from typing import Any
import uuid

from fastapi import HTTPException
from sqlalchemy import case, or_, select, text, update
from sqlalchemy.orm import Session

from app.models.event_operations import (
    EventCorrelationGroup,
    EventCorrelationPolicy,
    EventGroupActivity,
    EventSource,
    EventSuppressionRule,
    NormalizedEvent,
)
from app.models.notification import Notification
from app.models.sla import SlaPolicy
from app.models.ticket import Ticket
from app.models.ticket_history import TicketHistory
from app.models.user import User
from app.services.enterprise_sla import sync_ticket_sla
from app.services.notifications import create_notification
from app.services.ticket_lifecycle import (
    TicketLifecycleError,
    transition_ticket_status,
    transition_ticket_status_path,
)


SEVERITY_ORDER = {
    "INFO": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}
SEVERITY_PRIORITY = {
    "INFO": "LOW",
    "LOW": "LOW",
    "MEDIUM": "MEDIUM",
    "HIGH": "HIGH",
    "CRITICAL": "CRITICAL",
}
MATCH_OPERATORS = {"EQUALS", "NOT_EQUALS", "CONTAINS", "PREFIX", "EXISTS"}


def now_utc() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def issue_source_token() -> str:
    return f"evt_{secrets.token_urlsafe(36)}"


def source_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate_source(
    db: Session,
    source_identifier: str,
    token: str,
) -> EventSource:
    source = db.get(EventSource, source_identifier)
    if (
        source is None
        or not source.is_enabled
        or not secrets.compare_digest(source.token_hash, source_token_hash(token))
    ):
        raise HTTPException(status_code=401, detail="Invalid event source credentials")
    return source


def validate_matchers(matchers: list[dict[str, str]]) -> list[dict[str, str]]:
    if len(matchers) > 20:
        raise ValueError("At most 20 matchers are allowed")
    result: list[dict[str, str]] = []
    for raw in matchers:
        field = str(raw.get("field", "")).strip()
        operator = str(raw.get("operator", "")).strip().upper()
        value = str(raw.get("value", "")).strip()
        if not field or len(field) > 160:
            raise ValueError("Matcher field is required and must be at most 160 chars")
        if operator not in MATCH_OPERATORS:
            raise ValueError(f"Unsupported matcher operator: {operator}")
        if operator != "EXISTS" and not value:
            raise ValueError("Matcher value is required")
        if len(value) > 500:
            raise ValueError("Matcher value must be at most 500 chars")
        result.append({"field": field, "operator": operator, "value": value})
    return result


def validate_group_by(fields: list[str]) -> list[str]:
    result = list(dict.fromkeys(str(item).strip() for item in fields if str(item).strip()))
    if not result:
        return ["fingerprint"]
    if len(result) > 12 or any(len(item) > 160 for item in result):
        raise ValueError("group_by supports at most 12 fields of 160 chars")
    return result


def _field(event: dict[str, Any], field_name: str) -> str:
    if field_name.startswith("label."):
        return str(event.get("labels", {}).get(field_name.removeprefix("label."), ""))
    if field_name.startswith("annotation."):
        return str(
            event.get("annotations", {}).get(
                field_name.removeprefix("annotation."),
                "",
            )
        )
    value = event.get(field_name)
    return "" if value is None else str(value)


def matches_event(matchers: list[dict[str, str]], event: dict[str, Any]) -> bool:
    for matcher in matchers:
        actual = _field(event, matcher["field"])
        expected = matcher.get("value", "")
        operator = matcher["operator"]
        if operator == "EXISTS" and not actual:
            return False
        if operator == "EQUALS" and actual.casefold() != expected.casefold():
            return False
        if operator == "NOT_EQUALS" and actual.casefold() == expected.casefold():
            return False
        if operator == "CONTAINS" and expected.casefold() not in actual.casefold():
            return False
        if operator == "PREFIX" and not actual.casefold().startswith(expected.casefold()):
            return False
    return True


def _event_key(source: EventSource, event: dict[str, Any]) -> str:
    supplied = str(event["idempotency_key"]).strip()
    return hashlib.sha256(f"{source.id}\0{supplied}".encode()).hexdigest()


def _raw_hash(event: dict[str, Any]) -> str:
    encoded = json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _lock_event(db: Session, source_id: str, event_key: str) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    digest = hashlib.sha256(f"{source_id}\0{event_key}".encode()).digest()
    lock_key = struct.unpack(">q", digest[:8])[0]
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": lock_key},
    )


def _lock_group(
    db: Session,
    tenant_id: str,
    policy_id: str,
    correlation_key: str,
) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    digest = hashlib.sha256(
        f"{tenant_id}\0{policy_id}\0{correlation_key}".encode()
    ).digest()
    lock_key = struct.unpack(">q", digest[:8])[0]
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": lock_key},
    )


def _activity(
    db: Session,
    group: EventCorrelationGroup,
    *,
    activity_type: str,
    message: str,
    event: NormalizedEvent | None = None,
    actor: User | None = None,
    actor_name: str = "Event Operations",
    metadata: dict[str, object] | None = None,
) -> EventGroupActivity:
    item = EventGroupActivity(
        id=str(uuid.uuid4()),
        tenant_id=group.tenant_id,
        correlation_group_id=group.id,
        event_id=event.id if event else None,
        activity_type=activity_type,
        actor_user_id=actor.id if actor else None,
        actor_name=actor.full_name if actor else actor_name,
        message=message,
        metadata_json=metadata or {},
        created_at=now_utc(),
    )
    db.add(item)
    return item


def _ticket_history(
    db: Session,
    ticket: Ticket,
    *,
    event_type: str,
    message: str,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    db.add(
        TicketHistory(
            id=str(uuid.uuid4()),
            ticket_id=ticket.id,
            actor_name="Event Operations",
            event_type=event_type,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            message=message,
            created_at=now_utc(),
        )
    )


def _policy_for_event(
    db: Session,
    tenant_id: str,
    event: dict[str, Any],
) -> EventCorrelationPolicy | None:
    policies = db.scalars(
        select(EventCorrelationPolicy)
        .where(
            EventCorrelationPolicy.tenant_id == tenant_id,
            EventCorrelationPolicy.is_active.is_(True),
        )
        .order_by(
            EventCorrelationPolicy.priority_order,
            EventCorrelationPolicy.created_at,
        )
    ).all()
    return next(
        (
            item
            for item in policies
            if matches_event(item.matchers_json or [], event)
        ),
        None,
    )


def _suppression_for_event(
    db: Session,
    tenant_id: str,
    event: dict[str, Any],
    now: datetime,
) -> EventSuppressionRule | None:
    rules = db.scalars(
        select(EventSuppressionRule).where(
            EventSuppressionRule.tenant_id == tenant_id,
            EventSuppressionRule.is_active.is_(True),
        )
    ).all()
    for rule in rules:
        if rule.starts_at and aware(rule.starts_at) > now:
            continue
        if rule.ends_at and aware(rule.ends_at) <= now:
            continue
        if matches_event(rule.matchers_json or [], event):
            return rule
    return None


def _correlation_key(policy: EventCorrelationPolicy, event: dict[str, Any]) -> str:
    fields = validate_group_by(policy.group_by_json or [])
    values = [f"{field}={_field(event, field) or '<empty>'}" for field in fields]
    readable = "|".join(values)
    if len(readable) <= 512:
        return readable
    digest = hashlib.sha256(readable.encode()).hexdigest()
    return f"{readable[:443]}|sha256={digest}"


def _safe_title(template: str, event: dict[str, Any]) -> str:
    values = {
        "summary": str(event.get("summary") or "Monitoring event"),
        "service": str(event.get("service") or "unknown service"),
        "resource": str(event.get("resource") or "unknown resource"),
        "severity": str(event.get("severity") or "UNKNOWN"),
        "environment": str(event.get("environment") or "unknown"),
    }

    def replace(match: re.Match[str]) -> str:
        return values.get(match.group(1), match.group(0))

    title = re.sub(r"\{([a-z_]+)\}", replace, template).strip()
    return (title or values["summary"])[:255]


def _valid_user(db: Session, user_id: str | None, tenant_id: str) -> User | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or user.tenant_id != tenant_id or not user.is_active:
        return None
    return user


def _apply_sla(db: Session, ticket: Ticket, started_at: datetime) -> None:
    policy = db.scalar(
        select(SlaPolicy)
        .where(
            SlaPolicy.priority == ticket.priority,
            or_(
                SlaPolicy.tenant_id == ticket.tenant_id,
                SlaPolicy.tenant_id.is_(None),
            ),
        )
        .order_by(
            case(
                (SlaPolicy.tenant_id == ticket.tenant_id, 0),
                else_=1,
            )
        )
    )
    if policy is None:
        return
    response_minutes = policy.response_minutes or policy.target_response_minutes
    resolution_minutes = (
        policy.resolution_minutes or policy.target_resolution_minutes
    )
    ticket.sla_policy_id = policy.id
    ticket.response_due_at = started_at + timedelta(minutes=response_minutes)
    ticket.resolution_due_at = started_at + timedelta(
        minutes=resolution_minutes
    )
    ticket.sla_due_at = ticket.resolution_due_at
    ticket.sla_status = "OK"


def _notify_assignee(
    db: Session,
    group: EventCorrelationGroup,
    ticket: Ticket,
    user: User | None,
    *,
    event_type: str,
    title: str,
    message: str,
    severity: str,
) -> Notification | None:
    if user is None:
        return None
    return create_notification(
        db,
        type=event_type,
        event_type=event_type,
        title=title,
        message=message,
        recipient_name=user.full_name,
        recipient_email=user.email,
        channel="in_app",
        related_ticket_id=ticket.id,
        user_id=user.id,
        tenant_id=group.tenant_id,
        severity=severity.lower(),
        entity_type="event_group",
        entity_id=group.id,
        action_url=f"/events?group={group.id}",
        metadata={
            "ticket_number": ticket.ticket_number,
            "correlation_key": group.correlation_key,
        },
    )


def _create_incident(
    db: Session,
    source: EventSource,
    policy: EventCorrelationPolicy,
    group: EventCorrelationGroup,
    event: dict[str, Any],
) -> Ticket:
    now = now_utc()
    assignee = _valid_user(db, policy.primary_user_id, source.tenant_id)
    priority = policy.fixed_priority or SEVERITY_PRIORITY[str(event["severity"])]
    ticket = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=source.tenant_id,
        ticket_number=f"EVT-{uuid.uuid4().hex[:12].upper()}",
        title=_safe_title(policy.title_template, event),
        description=(
            f"Automatically created from {source.name}.\n\n"
            f"Summary: {event['summary']}\n"
            f"Description: {event.get('description') or '—'}\n"
            f"Service: {event.get('service') or '—'}\n"
            f"Resource: {event.get('resource') or '—'}\n"
            f"Environment: {event.get('environment') or '—'}\n"
            f"Correlation: {group.correlation_key}"
        ),
        requester_id=None,
        requester_name="Event Operations",
        requester_email="event-operations@sbs.local",
        department="IT Operations",
        location=event.get("environment") or "Automated monitoring",
        category=policy.category,
        priority=priority,
        status="ASSIGNED" if assignee else "NEW",
        assignee_id=assignee.id if assignee else None,
        assignee_name=assignee.full_name if assignee else None,
        created_at=now,
        updated_at=now,
    )
    _apply_sla(db, ticket, now)
    db.add(ticket)
    db.flush()
    sync_ticket_sla(
        db,
        ticket,
        old_status=None,
        actor=None,
        at=now,
    )
    _ticket_history(
        db,
        ticket,
        event_type="created",
        message=(
            f"Ticket {ticket.ticket_number} automatically created from "
            f"correlated monitoring events."
        ),
        new_value=ticket.title,
    )
    _ticket_history(
        db,
        ticket,
        event_type="event_correlated",
        message=(
            f"{event['severity']} event correlated: {event['summary']} "
            f"(occurrence {group.occurrence_count})."
        ),
    )
    _notify_assignee(
        db,
        group,
        ticket,
        assignee,
        event_type="event_incident_created",
        title=f"[{ticket.ticket_number}] Monitoring incident assigned",
        message=group.title,
        severity=group.severity,
    )
    return ticket


def _update_incident(
    db: Session,
    ticket: Ticket,
    group: EventCorrelationGroup,
    event: dict[str, Any],
) -> None:
    old_status = ticket.status
    if ticket.status in {"RESOLVED", "CLOSED"}:
        transition_ticket_status(
            db,
            ticket,
            "REOPENED",
            actor_name="Event Operations",
            actor_kind="SYSTEM",
            actor_email="event-operations@sbs.local",
            expected_status=old_status,
            idempotency_key=(
                f"event-reopen:{group.id}:{group.occurrence_count}"[-120:]
            ),
            source="event_operations",
            reason="Monitoring event fired again; ticket reopened.",
        )
    ticket.updated_at = now_utc()
    if old_status == ticket.status:
        sync_ticket_sla(
            db,
            ticket,
            old_status=old_status,
            actor=None,
            at=ticket.updated_at,
        )
    _ticket_history(
        db,
        ticket,
        event_type="event_correlated",
        message=(
            f"{event['severity']} event correlated: {event['summary']} "
            f"(occurrence {group.occurrence_count})."
        ),
    )


def _resolve_group(
    db: Session,
    group: EventCorrelationGroup,
    policy: EventCorrelationPolicy,
    event: NormalizedEvent,
) -> None:
    now = now_utc()
    group.status = "RESOLVED"
    group.resolved_at = now
    group.next_escalation_at = None
    group.version += 1
    group.updated_at = now
    ticket = db.get(Ticket, group.ticket_id) if group.ticket_id else None
    if (
        ticket is not None
        and policy.resolution_action != "NONE"
        and ticket.status not in {"RESOLVED", "CLOSED"}
    ):
        target_status = (
            "CLOSED" if policy.resolution_action == "CLOSE" else "RESOLVED"
        )
        try:
            transition_ticket_status_path(
                db,
                ticket,
                target_status,
                actor_name="Event Operations",
                actor_kind="SYSTEM",
                actor_email="event-operations@sbs.local",
                idempotency_key=f"event-recovery:{event.id}"[-120:],
                at=now,
                source="event_operations",
                reason="Trusted monitoring recovery resolved the correlated group.",
            )
        except TicketLifecycleError as error:
            _ticket_history(
                db,
                ticket,
                event_type="lifecycle_transition_rejected",
                field_name="status",
                old_value=ticket.status,
                new_value=target_status,
                message=f"Monitoring recovery could not transition ticket: {error}",
            )
    _activity(
        db,
        group,
        activity_type="GROUP_RESOLVED",
        message="Recovery event resolved the correlation group.",
        event=event,
        metadata={"resolution_action": policy.resolution_action},
    )


def ingest_normalized_event(
    db: Session,
    source: EventSource,
    payload: dict[str, Any],
) -> dict[str, Any]:
    now = now_utc()
    event_key = _event_key(source, payload)
    _lock_event(db, source.id, event_key)
    existing = db.scalar(
        select(NormalizedEvent).where(
            NormalizedEvent.source_id == source.id,
            NormalizedEvent.event_key == event_key,
        )
    )
    db.execute(
        update(EventSource)
        .where(EventSource.id == source.id)
        .values(
            total_events=EventSource.total_events + 1,
            last_event_at=now,
            updated_at=now,
        )
    )
    if existing is not None:
        db.execute(
            update(EventSource)
            .where(EventSource.id == source.id)
            .values(duplicate_events=EventSource.duplicate_events + 1)
        )
        db.commit()
        return {
            "duplicate": True,
            "event_id": existing.id,
            "disposition": existing.disposition,
            "group_id": existing.correlation_group_id,
            "ticket_id": existing.ticket_id,
        }

    labels = {
        str(key)[:120]: str(value)[:2_000]
        for key, value in list((payload.get("labels") or {}).items())[:80]
    }
    annotations = {
        str(key)[:120]: str(value)[:5_000]
        for key, value in list((payload.get("annotations") or {}).items())[:40]
    }
    normalized = {
        **payload,
        "labels": labels,
        "annotations": annotations,
        "state": str(payload["state"]).upper(),
        "severity": str(payload["severity"]).upper(),
    }
    event = NormalizedEvent(
        id=str(uuid.uuid4()),
        tenant_id=source.tenant_id,
        source_id=source.id,
        event_key=event_key,
        external_id=str(payload["external_id"])[:255],
        fingerprint=str(payload["fingerprint"])[:255],
        state=normalized["state"],
        severity=normalized["severity"],
        summary=str(payload["summary"]).strip()[:500],
        description=(
            str(payload["description"]).strip()
            if payload.get("description")
            else None
        ),
        service=str(payload["service"]).strip()[:200]
        if payload.get("service")
        else None,
        resource=str(payload["resource"]).strip()[:255]
        if payload.get("resource")
        else None,
        environment=str(payload["environment"]).strip()[:80]
        if payload.get("environment")
        else None,
        labels_json=labels,
        annotations_json=annotations,
        raw_payload_hash=_raw_hash(normalized),
        occurred_at=aware(payload["occurred_at"]),
        received_at=now,
        disposition="IGNORED",
    )
    db.add(event)
    db.flush()

    if event.state == "FIRING":
        suppression = _suppression_for_event(
            db,
            source.tenant_id,
            normalized,
            now,
        )
        if suppression is not None:
            event.disposition = "SUPPRESSED"
            event.suppression_rule_id = suppression.id
            db.execute(
                update(EventSource)
                .where(EventSource.id == source.id)
                .values(suppressed_events=EventSource.suppressed_events + 1)
            )
            db.commit()
            return {
                "duplicate": False,
                "event_id": event.id,
                "disposition": event.disposition,
                "suppression_rule_id": suppression.id,
                "group_id": None,
                "ticket_id": None,
            }

    previous: NormalizedEvent | None = None
    group: EventCorrelationGroup | None = None
    policy: EventCorrelationPolicy | None = None
    if event.state == "RESOLVED":
        previous = db.scalar(
            select(NormalizedEvent)
            .where(
                NormalizedEvent.source_id == source.id,
                NormalizedEvent.fingerprint == event.fingerprint,
                NormalizedEvent.state == "FIRING",
                NormalizedEvent.correlation_group_id.is_not(None),
            )
            .order_by(NormalizedEvent.occurred_at.desc())
            .limit(1)
        )
        if previous and previous.correlation_group_id:
            group = db.get(
                EventCorrelationGroup,
                previous.correlation_group_id,
            )
            policy = (
                db.get(EventCorrelationPolicy, group.policy_id)
                if group
                else None
            )

    if policy is None:
        policy = _policy_for_event(db, source.tenant_id, normalized)
    if policy is None or policy.incident_mode == "IGNORE":
        event.disposition = "IGNORED"
        db.commit()
        return {
            "duplicate": False,
            "event_id": event.id,
            "disposition": event.disposition,
            "group_id": None,
            "ticket_id": None,
        }

    correlation_key = _correlation_key(policy, normalized)
    _lock_group(db, source.tenant_id, policy.id, correlation_key)
    if group is None:
        group = db.scalar(
            select(EventCorrelationGroup)
            .where(
                EventCorrelationGroup.tenant_id == source.tenant_id,
                EventCorrelationGroup.policy_id == policy.id,
                EventCorrelationGroup.correlation_key == correlation_key,
                EventCorrelationGroup.status == "OPEN",
            )
            .with_for_update()
        )
    if (
        event.state == "FIRING"
        and group is not None
        and group.ticket_id is None
        and aware(group.last_event_at)
        + timedelta(minutes=policy.correlation_window_minutes)
        < event.occurred_at
    ):
        group.status = "RESOLVED"
        group.resolved_at = now
        group.next_escalation_at = None
        group.version += 1
        group.updated_at = now
        _activity(
            db,
            group,
            activity_type="CORRELATION_WINDOW_EXPIRED",
            message="Correlation window expired before incident threshold.",
        )
        db.flush()
        group = None
    if event.state == "RESOLVED":
        if group is None or group.status != "OPEN":
            event.disposition = "IGNORED"
        else:
            event.correlation_policy_id = policy.id
            event.correlation_group_id = group.id
            event.ticket_id = group.ticket_id
            event.disposition = "RESOLVED"
            _resolve_group(db, group, policy, event)
        db.commit()
        return {
            "duplicate": False,
            "event_id": event.id,
            "disposition": event.disposition,
            "group_id": group.id if group else None,
            "ticket_id": group.ticket_id if group else None,
        }

    created_group = group is None
    if group is None:
        assigned = _valid_user(db, policy.primary_user_id, source.tenant_id)
        group = EventCorrelationGroup(
            id=str(uuid.uuid4()),
            tenant_id=source.tenant_id,
            policy_id=policy.id,
            correlation_key=correlation_key,
            title=str(payload["summary"]).strip()[:500],
            status="OPEN",
            severity=event.severity,
            first_event_at=event.occurred_at,
            last_event_at=event.occurred_at,
            occurrence_count=1,
            assigned_user_id=assigned.id if assigned else None,
            next_escalation_at=now
            + timedelta(minutes=policy.acknowledge_within_minutes),
            escalation_level=0,
            version=1,
            created_at=now,
            updated_at=now,
        )
        db.add(group)
        db.flush()
    else:
        group.occurrence_count += 1
        group.last_event_at = max(
            aware(group.last_event_at),
            event.occurred_at,
        )
        if SEVERITY_ORDER[event.severity] > SEVERITY_ORDER[group.severity]:
            group.severity = event.severity
        group.version += 1
        group.updated_at = now

    event.correlation_policy_id = policy.id
    event.correlation_group_id = group.id
    event.disposition = "CORRELATED"
    _activity(
        db,
        group,
        activity_type="GROUP_CREATED" if created_group else "EVENT_CORRELATED",
        message=(
            f"{event.severity} event correlated: {event.summary} "
            f"(occurrence {group.occurrence_count})."
        ),
        event=event,
        metadata={
            "source_id": source.id,
            "fingerprint": event.fingerprint,
        },
    )

    ticket: Ticket | None = db.get(Ticket, group.ticket_id) if group.ticket_id else None
    if (
        policy.incident_mode == "CREATE_UPDATE"
        and group.occurrence_count >= policy.min_occurrences
    ):
        if ticket is None:
            ticket = _create_incident(db, source, policy, group, normalized)
            group.ticket_id = ticket.id
            event.disposition = "INCIDENT_CREATED"
            _activity(
                db,
                group,
                activity_type="INCIDENT_CREATED",
                message=f"Ticket {ticket.ticket_number} created.",
                event=event,
                metadata={"ticket_id": ticket.id},
            )
        else:
            _update_incident(db, ticket, group, normalized)
            event.disposition = "INCIDENT_UPDATED"
        event.ticket_id = ticket.id

    db.commit()
    return {
        "duplicate": False,
        "event_id": event.id,
        "disposition": event.disposition,
        "group_id": group.id,
        "ticket_id": event.ticket_id,
    }


def acknowledge_group(
    db: Session,
    group: EventCorrelationGroup,
    actor: User,
    expected_version: int,
    note: str,
) -> EventCorrelationGroup:
    if group.status != "OPEN":
        raise HTTPException(status_code=409, detail="Event group is resolved")
    if group.version != expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Event group version conflict; current version is {group.version}",
        )
    if group.acknowledged_at is not None:
        raise HTTPException(status_code=409, detail="Event group is already acknowledged")
    group.acknowledged_by_id = actor.id
    group.acknowledged_at = now_utc()
    group.next_escalation_at = None
    group.version += 1
    group.updated_at = now_utc()
    _activity(
        db,
        group,
        activity_type="ACKNOWLEDGED",
        message=note,
        actor=actor,
    )
    return group


def evaluate_escalations(
    db: Session,
    tenant_id: str,
) -> list[EventCorrelationGroup]:
    now = now_utc()
    groups = db.scalars(
        select(EventCorrelationGroup)
        .where(
            EventCorrelationGroup.tenant_id == tenant_id,
            EventCorrelationGroup.status == "OPEN",
            EventCorrelationGroup.acknowledged_at.is_(None),
            EventCorrelationGroup.next_escalation_at.is_not(None),
            EventCorrelationGroup.next_escalation_at <= now,
        )
        .order_by(EventCorrelationGroup.next_escalation_at)
        .with_for_update()
        .limit(500)
    ).all()
    changed: list[EventCorrelationGroup] = []
    for group in groups:
        policy = db.get(EventCorrelationPolicy, group.policy_id)
        if policy is None:
            group.next_escalation_at = None
            continue
        fallback = _valid_user(db, policy.fallback_user_id, tenant_id)
        target = fallback or _valid_user(db, policy.primary_user_id, tenant_id)
        group.escalation_level += 1
        group.escalated_at = now
        group.assigned_user_id = target.id if target else group.assigned_user_id
        group.next_escalation_at = (
            now + timedelta(minutes=policy.escalate_after_minutes)
            if group.escalation_level == 1 and fallback is not None
            else None
        )
        group.version += 1
        group.updated_at = now
        ticket = db.get(Ticket, group.ticket_id) if group.ticket_id else None
        if ticket is not None and target is not None:
            old_assignee = ticket.assignee_name
            old_status = ticket.status
            ticket.assignee_id = target.id
            ticket.assignee_name = target.full_name
            if ticket.status == "NEW":
                transition_ticket_status(
                    db,
                    ticket,
                    "ASSIGNED",
                    actor_name="Event Operations",
                    actor_kind="SYSTEM",
                    actor_email="event-operations@sbs.local",
                    expected_status="NEW",
                    idempotency_key=(
                        f"event-escalation:{group.id}:{group.escalation_level}"[-120:]
                    ),
                    at=now,
                    source="event_operations",
                    reason=(
                        "Monitoring escalation assigned the ticket to the "
                        "fallback responder."
                    ),
                )
            ticket.updated_at = now
            if old_status == ticket.status:
                sync_ticket_sla(
                    db,
                    ticket,
                    old_status=old_status,
                    actor=None,
                    at=now,
                )
            _ticket_history(
                db,
                ticket,
                event_type="assigned",
                field_name="assignee_name",
                old_value=old_assignee,
                new_value=target.full_name,
                message=(
                    "Event acknowledgment deadline missed; "
                    f"escalated to {target.full_name}."
                ),
            )
            _notify_assignee(
                db,
                group,
                ticket,
                target,
                event_type="event_escalated",
                title=f"[{ticket.ticket_number}] Monitoring escalation",
                message=f"Acknowledgment overdue: {group.title}",
                severity=group.severity,
            )
        _activity(
            db,
            group,
            activity_type="ESCALATED",
            message=(
                f"Acknowledgment deadline missed; escalated to "
                f"{target.full_name if target else 'unassigned operations queue'}."
            ),
            metadata={"escalation_level": group.escalation_level},
        )
        changed.append(group)
    return changed
