from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
import hashlib
import struct
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.models.sla import (
    SlaBusinessCalendar,
    SlaCalendarException,
    SlaPolicy,
    TicketSlaInstance,
    TicketSlaPause,
    TicketSlaTarget,
    TicketSlaTimeline,
)
from app.models.ticket import Ticket
from app.models.user import User
from app.services.notifications import create_domain_event_notification


DEFAULT_WEEKLY_HOURS: dict[str, list[list[str]]] = {
    str(day): [["09:00", "18:00"]] for day in range(5)
}
TARGET_TYPES = {"RESPONSE", "RESOLUTION", "FULFILLMENT", "OLA", "SUPPLIER"}
TERMINAL_TARGET_STATUSES = {"MET", "CANCELLED"}
RESPONSE_STATUSES = {
    "ASSIGNED",
    "IN_PROGRESS",
    "WAITING_USER",
    "WAITING_VENDOR",
    "RESOLVED",
    "CLOSED",
}
TERMINAL_TICKET_STATUSES = {"RESOLVED", "CLOSED"}


def now_utc() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {value}") from exc
    return value


def _parse_clock(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid time value: {value}") from exc
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ValueError("Calendar times must use local HH:MM values")
    return parsed


def validate_intervals(intervals: object) -> list[list[str]]:
    if not isinstance(intervals, list) or len(intervals) > 4:
        raise ValueError("Calendar day must contain zero to four intervals")
    normalized: list[list[str]] = []
    previous_end: time | None = None
    for item in intervals:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("Each interval must contain start and end")
        start_value = str(item[0])
        end_value = str(item[1])
        start_clock = _parse_clock(start_value)
        end_clock = _parse_clock(end_value)
        if start_clock >= end_clock:
            raise ValueError("Calendar interval end must be after start")
        if previous_end is not None and start_clock < previous_end:
            raise ValueError("Calendar intervals cannot overlap")
        normalized.append(
            [
                start_clock.isoformat(timespec="minutes"),
                end_clock.isoformat(timespec="minutes"),
            ]
        )
        previous_end = end_clock
    return normalized


def validate_weekly_hours(value: object) -> dict[str, list[list[str]]]:
    if not isinstance(value, dict):
        raise ValueError("weekly_hours must be an object keyed by weekday 0-6")
    normalized: dict[str, list[list[str]]] = {}
    for raw_day, raw_intervals in value.items():
        day = str(raw_day)
        if day not in {str(index) for index in range(7)}:
            raise ValueError("Calendar weekdays must be numbered 0 (Monday) to 6")
        normalized[day] = validate_intervals(raw_intervals)
    return normalized


def validate_targets(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > 12:
        raise ValueError("targets must be a list with at most 12 entries")
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("Each SLA target must be an object")
        target_type = str(raw.get("type", "")).upper()
        if target_type not in TARGET_TYPES:
            raise ValueError(f"Unsupported SLA target type: {target_type}")
        minutes = int(raw.get("minutes", 0))
        if minutes < 1 or minutes > 5_256_000:
            raise ValueError("SLA target minutes must be between 1 and 5,256,000")
        owner_ref = str(raw.get("owner_ref") or "")
        unique_key = (target_type, owner_ref)
        if unique_key in seen:
            raise ValueError("Target type and owner_ref must be unique")
        seen.add(unique_key)
        warning_percent = int(raw.get("warning_percent", 80))
        if warning_percent < 1 or warning_percent > 100:
            raise ValueError("warning_percent must be between 1 and 100")
        normalized.append(
            {
                "type": target_type,
                "name": str(raw.get("name") or target_type.title())[:200],
                "minutes": minutes,
                "warning_percent": warning_percent,
                "owner_type": (
                    str(raw.get("owner_type")).upper()
                    if raw.get("owner_type")
                    else None
                ),
                "owner_ref": owner_ref[:255],
            }
        )
    return normalized


def validate_escalations(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > 10:
        raise ValueError("escalations must be a list with at most 10 entries")
    normalized: list[dict[str, object]] = []
    previous_percent = 0
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("Each escalation must be an object")
        percent = int(raw.get("at_percent", 0))
        if percent < 1 or percent > 500 or percent <= previous_percent:
            raise ValueError("Escalation percentages must increase from 1 to 500")
        target_type = str(raw.get("target_type") or "").upper() or None
        if target_type and target_type not in TARGET_TYPES:
            raise ValueError("Escalation target_type is invalid")
        normalized.append(
            {
                "at_percent": percent,
                "target_type": target_type,
                "recipient_user_id": raw.get("recipient_user_id"),
                "label": str(raw.get("label") or f"Escalation {len(normalized) + 1}")[
                    :200
                ],
            }
        )
        previous_percent = percent
    return normalized


def calendar_snapshot(
    db: Session,
    calendar: SlaBusinessCalendar | None,
) -> dict[str, object] | None:
    if calendar is None:
        return None
    exceptions = db.scalars(
        select(SlaCalendarException)
        .where(SlaCalendarException.calendar_id == calendar.id)
        .order_by(SlaCalendarException.exception_date)
    ).all()
    return {
        "id": calendar.id,
        "name": calendar.name,
        "timezone": calendar.timezone,
        "weekly_hours": calendar.weekly_hours_json,
        "exceptions": {
            item.exception_date.isoformat(): {
                "kind": item.kind,
                "name": item.name,
                "intervals": item.intervals_json,
            }
            for item in exceptions
        },
        "version": calendar.version,
    }


def _snapshot_intervals(
    snapshot: dict[str, object],
    local_day: date,
) -> list[list[str]]:
    exceptions = snapshot.get("exceptions")
    if isinstance(exceptions, dict):
        exception = exceptions.get(local_day.isoformat())
        if isinstance(exception, dict):
            if exception.get("kind") == "HOLIDAY":
                return []
            intervals = exception.get("intervals")
            return validate_intervals(intervals)
    weekly = snapshot.get("weekly_hours")
    if not isinstance(weekly, dict):
        return []
    return validate_intervals(weekly.get(str(local_day.weekday()), []))


def _interval_bounds(
    local_day: date,
    intervals: Iterable[list[str]],
    timezone: ZoneInfo,
) -> Iterable[tuple[datetime, datetime]]:
    for start_value, end_value in intervals:
        start_local = datetime.combine(
            local_day,
            _parse_clock(start_value),
            tzinfo=timezone,
        )
        end_local = datetime.combine(
            local_day,
            _parse_clock(end_value),
            tzinfo=timezone,
        )
        yield start_local.astimezone(UTC), end_local.astimezone(UTC)


def add_business_minutes(
    started_at: datetime,
    minutes: int,
    snapshot: dict[str, object] | None,
) -> datetime:
    cursor = as_utc(started_at)
    if minutes <= 0:
        return cursor
    if snapshot is None:
        return cursor + timedelta(minutes=minutes)

    timezone = ZoneInfo(str(snapshot["timezone"]))
    remaining = minutes
    local_day = cursor.astimezone(timezone).date()
    for _ in range(366 * 20):
        intervals = _snapshot_intervals(snapshot, local_day)
        for interval_start, interval_end in _interval_bounds(
            local_day,
            intervals,
            timezone,
        ):
            effective_start = max(cursor, interval_start)
            if effective_start >= interval_end:
                continue
            available = int(
                (interval_end - effective_start).total_seconds() // 60
            )
            if available >= remaining:
                return effective_start + timedelta(minutes=remaining)
            remaining -= available
        local_day += timedelta(days=1)
        cursor = datetime.combine(
            local_day,
            time.min,
            tzinfo=timezone,
        ).astimezone(UTC)
    raise ValueError("Business calendar cannot resolve the requested duration")


def business_minutes_between(
    started_at: datetime,
    ended_at: datetime,
    snapshot: dict[str, object] | None,
) -> int:
    start = as_utc(started_at)
    end = as_utc(ended_at)
    if end <= start:
        return 0
    if snapshot is None:
        return int((end - start).total_seconds() // 60)

    timezone = ZoneInfo(str(snapshot["timezone"]))
    local_day = start.astimezone(timezone).date()
    last_day = end.astimezone(timezone).date()
    consumed = 0
    while local_day <= last_day:
        intervals = _snapshot_intervals(snapshot, local_day)
        for interval_start, interval_end in _interval_bounds(
            local_day,
            intervals,
            timezone,
        ):
            overlap_start = max(start, interval_start)
            overlap_end = min(end, interval_end)
            if overlap_end > overlap_start:
                consumed += int(
                    (overlap_end - overlap_start).total_seconds() // 60
                )
        local_day += timedelta(days=1)
    return consumed


def _lock_ticket(db: Session, ticket_id: str) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    key = struct.unpack(
        ">q",
        hashlib.sha256(f"sla:{ticket_id}".encode()).digest()[:8],
    )[0]
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _timeline(
    db: Session,
    instance: TicketSlaInstance,
    *,
    event_type: str,
    actor: User | None,
    message: str,
    target: TicketSlaTarget | None = None,
    data: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> TicketSlaTimeline:
    item = TicketSlaTimeline(
        id=str(uuid.uuid4()),
        tenant_id=instance.tenant_id,
        ticket_id=instance.ticket_id,
        instance_id=instance.id,
        target_id=target.id if target else None,
        event_type=event_type,
        actor_user_id=actor.id if actor else None,
        actor_name=actor.full_name if actor else "SLA Engine",
        message=message,
        data_json=data or {},
        created_at=created_at or now_utc(),
    )
    db.add(item)
    return item


def current_instance(
    db: Session,
    ticket_id: str,
) -> TicketSlaInstance | None:
    return db.scalar(
        select(TicketSlaInstance).where(
            TicketSlaInstance.ticket_id == ticket_id,
            TicketSlaInstance.is_current.is_(True),
        )
    )


def instance_targets(
    db: Session,
    instance_id: str,
) -> list[TicketSlaTarget]:
    return list(
        db.scalars(
            select(TicketSlaTarget)
            .where(TicketSlaTarget.instance_id == instance_id)
            .order_by(TicketSlaTarget.due_at, TicketSlaTarget.target_type)
        ).all()
    )


def _scope_matches(ticket: Ticket, scope: dict[str, object]) -> bool:
    for field in ("category", "department", "location"):
        expected = scope.get(field)
        if expected in (None, "", [], "*"):
            continue
        actual = str(getattr(ticket, field, "") or "").casefold()
        values = expected if isinstance(expected, list) else [expected]
        if actual not in {str(value).casefold() for value in values}:
            return False
    return True


def select_policy(db: Session, ticket: Ticket) -> SlaPolicy | None:
    policies = db.scalars(
        select(SlaPolicy).where(
            or_(
                SlaPolicy.tenant_id == ticket.tenant_id,
                SlaPolicy.tenant_id.is_(None),
            ),
            SlaPolicy.is_active.is_(True),
            SlaPolicy.status == "active",
            func.upper(SlaPolicy.priority) == ticket.priority.upper(),
        )
    ).all()
    ranked = sorted(
        policies,
        key=lambda item: (
            0 if item.tenant_id == ticket.tenant_id else 1,
            item.priority_order,
            item.name.casefold(),
        ),
    )
    return next(
        (
            policy
            for policy in ranked
            if _scope_matches(ticket, policy.scope_json or {})
        ),
        None,
    )


def _policy_targets(policy: SlaPolicy) -> list[dict[str, object]]:
    custom = validate_targets(policy.targets_json or [])
    by_type = {str(item["type"]): item for item in custom}
    if "RESPONSE" not in by_type:
        custom.append(
            {
                "type": "RESPONSE",
                "name": "First response",
                "minutes": (
                    policy.response_minutes or policy.target_response_minutes
                ),
                "warning_percent": policy.warning_percent,
                "owner_type": "SERVICE_DESK",
                "owner_ref": "",
            }
        )
    if "RESOLUTION" not in by_type:
        custom.append(
            {
                "type": "RESOLUTION",
                "name": "Resolution",
                "minutes": (
                    policy.resolution_minutes or policy.target_resolution_minutes
                ),
                "warning_percent": policy.warning_percent,
                "owner_type": "SERVICE_DESK",
                "owner_ref": "",
            }
        )
    return custom


def _policy_snapshot(policy: SlaPolicy) -> dict[str, object]:
    return {
        "id": policy.id,
        "name": policy.name,
        "version": policy.version,
        "priority": policy.priority,
        "scope": policy.scope_json or {},
        "targets": _policy_targets(policy),
        "pause_statuses": policy.pause_statuses_json or [],
        "pause_reasons": policy.pause_reasons_json or [],
        "warning_percent": policy.warning_percent,
        "escalations": validate_escalations(policy.escalations_json or []),
    }


def ensure_ticket_sla_instance(
    db: Session,
    ticket: Ticket,
    *,
    actor: User | None = None,
    at: datetime | None = None,
    force_recalculate: bool = False,
    reason: str = "Policy matched",
) -> TicketSlaInstance | None:
    if not ticket.tenant_id:
        return None
    _lock_ticket(db, ticket.id)
    existing = current_instance(db, ticket.id)
    if existing is not None and not force_recalculate:
        return existing

    instant = as_utc(at or now_utc())
    policy = select_policy(db, ticket)
    if policy is None:
        return None

    if existing is not None:
        existing.is_current = False
        existing.version += 1
        if existing.status in {"ACTIVE", "PAUSED"}:
            existing.status = "CANCELLED"
            for target in instance_targets(db, existing.id):
                if target.status not in TERMINAL_TARGET_STATUSES:
                    target.status = "CANCELLED"
                    target.version += 1
        _timeline(
            db,
            existing,
            event_type="sla.recalculated",
            actor=actor,
            message=f"Current SLA superseded: {reason}.",
            data={"reason": reason},
            created_at=instant,
        )
        db.flush()

    calendar = db.get(SlaBusinessCalendar, policy.calendar_id) if policy.calendar_id else None
    snapshot = calendar_snapshot(db, calendar)
    policy_data = _policy_snapshot(policy)
    instance = TicketSlaInstance(
        id=str(uuid.uuid4()),
        tenant_id=ticket.tenant_id,
        ticket_id=ticket.id,
        policy_id=policy.id,
        calendar_id=calendar.id if calendar else None,
        policy_version=policy.version,
        policy_snapshot_json=policy_data,
        calendar_snapshot_json=snapshot,
        status="ACTIVE",
        is_current=True,
        started_at=instant,
        last_evaluated_at=instant,
        total_paused_business_minutes=0,
        version=1,
    )
    db.add(instance)
    db.flush()

    targets: list[TicketSlaTarget] = []
    for definition in policy_data["targets"]:
        duration = int(definition["minutes"])
        warning_percent = int(definition["warning_percent"])
        target = TicketSlaTarget(
            id=str(uuid.uuid4()),
            tenant_id=ticket.tenant_id,
            ticket_id=ticket.id,
            instance_id=instance.id,
            target_type=str(definition["type"]),
            name=str(definition["name"]),
            duration_minutes=duration,
            warning_percent=warning_percent,
            due_at=add_business_minutes(instant, duration, snapshot),
            warning_at=add_business_minutes(
                instant,
                max(1, duration * warning_percent // 100),
                snapshot,
            ),
            status="PENDING",
            owner_type=(
                str(definition["owner_type"])
                if definition.get("owner_type")
                else None
            ),
            owner_ref=str(definition.get("owner_ref") or ""),
            escalation_level=0,
            version=1,
        )
        db.add(target)
        targets.append(target)
    db.flush()
    _sync_legacy_ticket(ticket, instance, targets)
    _timeline(
        db,
        instance,
        event_type="sla.started",
        actor=actor,
        message=f"SLA policy “{policy.name}” started.",
        data={"policy_id": policy.id, "policy_version": policy.version},
        created_at=instant,
    )
    return instance


def _sync_legacy_ticket(
    ticket: Ticket,
    instance: TicketSlaInstance,
    targets: Iterable[TicketSlaTarget],
) -> None:
    target_list = list(targets)
    ticket.sla_policy_id = instance.policy_id
    response = next(
        (item for item in target_list if item.target_type == "RESPONSE"),
        None,
    )
    resolution = next(
        (item for item in target_list if item.target_type == "RESOLUTION"),
        None,
    )
    ticket.response_due_at = response.due_at if response else None
    ticket.resolution_due_at = resolution.due_at if resolution else None
    ticket.sla_due_at = (
        resolution.due_at
        if resolution
        else max((item.due_at for item in target_list), default=None)
    )
    if instance.status == "PAUSED":
        ticket.sla_status = "PAUSED"
    elif any(item.status == "BREACHED" for item in target_list):
        ticket.sla_status = "BREACHED"
    elif all(item.status in TERMINAL_TARGET_STATUSES for item in target_list):
        ticket.sla_status = "MET"
    elif any(item.status == "WARNING" for item in target_list):
        ticket.sla_status = "WARNING"
    else:
        ticket.sla_status = "OK"


def pause_instance(
    db: Session,
    instance: TicketSlaInstance,
    *,
    reason_code: str,
    reason: str,
    actor: User | None,
    ticket_status: str | None = None,
    at: datetime | None = None,
) -> TicketSlaPause:
    if instance.status == "PAUSED":
        pause = db.scalar(
            select(TicketSlaPause).where(
                TicketSlaPause.instance_id == instance.id,
                TicketSlaPause.ended_at.is_(None),
            )
        )
        if pause is not None:
            return pause
    if instance.status not in {"ACTIVE", "BREACHED"}:
        raise ValueError("Only an active SLA can be paused")
    allowed = {
        str(item).upper()
        for item in instance.policy_snapshot_json.get("pause_reasons", [])
    }
    if reason_code.upper() not in allowed:
        raise ValueError("Pause reason is not allowed by the policy")
    instant = as_utc(at or now_utc())
    pause = TicketSlaPause(
        id=str(uuid.uuid4()),
        tenant_id=instance.tenant_id,
        instance_id=instance.id,
        reason_code=reason_code.upper(),
        reason=reason,
        started_at=instant,
        started_by_id=actor.id if actor else None,
        start_status=ticket_status,
    )
    db.add(pause)
    instance.status = "PAUSED"
    instance.paused_at = instant
    instance.version += 1
    _timeline(
        db,
        instance,
        event_type="sla.paused",
        actor=actor,
        message=f"SLA paused: {reason}.",
        data={"reason_code": reason_code.upper()},
        created_at=instant,
    )
    return pause


def resume_instance(
    db: Session,
    instance: TicketSlaInstance,
    *,
    actor: User | None,
    ticket_status: str | None = None,
    at: datetime | None = None,
) -> int:
    if instance.status != "PAUSED" or instance.paused_at is None:
        return 0
    instant = as_utc(at or now_utc())
    pause = db.scalar(
        select(TicketSlaPause).where(
            TicketSlaPause.instance_id == instance.id,
            TicketSlaPause.ended_at.is_(None),
        )
    )
    if pause is None:
        raise ValueError("Open SLA pause record is missing")
    paused_minutes = business_minutes_between(
        pause.started_at,
        instant,
        instance.calendar_snapshot_json,
    )
    pause.ended_at = instant
    pause.business_minutes = paused_minutes
    pause.ended_by_id = actor.id if actor else None
    pause.end_status = ticket_status
    instance.total_paused_business_minutes += paused_minutes
    instance.status = "ACTIVE"
    instance.paused_at = None
    instance.version += 1
    for target in instance_targets(db, instance.id):
        if target.status in {"PENDING", "WARNING"}:
            target.due_at = add_business_minutes(
                target.due_at,
                paused_minutes,
                instance.calendar_snapshot_json,
            )
            target.warning_at = add_business_minutes(
                target.warning_at,
                paused_minutes,
                instance.calendar_snapshot_json,
            )
            target.version += 1
    _timeline(
        db,
        instance,
        event_type="sla.resumed",
        actor=actor,
        message=f"SLA resumed; deadlines extended by {paused_minutes} business minutes.",
        data={"paused_business_minutes": paused_minutes},
        created_at=instant,
    )
    return paused_minutes


def complete_target(
    db: Session,
    instance: TicketSlaInstance,
    target_type: str,
    *,
    actor: User | None,
    at: datetime | None = None,
    owner_ref: str = "",
    reason: str = "Lifecycle milestone reached",
) -> TicketSlaTarget | None:
    target = db.scalar(
        select(TicketSlaTarget).where(
            TicketSlaTarget.instance_id == instance.id,
            TicketSlaTarget.target_type == target_type.upper(),
            TicketSlaTarget.owner_ref == owner_ref,
        )
    )
    if target is None or target.status in TERMINAL_TARGET_STATUSES:
        return target
    instant = as_utc(at or now_utc())
    target.status = "MET" if instant <= as_utc(target.due_at) else "BREACHED"
    target.met_at = instant
    if target.status == "BREACHED" and target.breached_at is None:
        target.breached_at = instant
    target.version += 1
    _timeline(
        db,
        instance,
        event_type=(
            "sla.target_met"
            if target.status == "MET"
            else "sla.target_breached"
        ),
        actor=actor,
        target=target,
        message=f"{target.name}: {reason}.",
        data={"target_type": target.target_type, "status": target.status},
        created_at=instant,
    )
    return target


def _target_progress(
    instance: TicketSlaInstance,
    target: TicketSlaTarget,
    at: datetime,
) -> int:
    consumed = business_minutes_between(
        instance.started_at,
        at,
        instance.calendar_snapshot_json,
    )
    consumed = max(0, consumed - instance.total_paused_business_minutes)
    return int(consumed * 100 / max(1, target.duration_minutes))


def _notify_escalation(
    db: Session,
    instance: TicketSlaInstance,
    target: TicketSlaTarget,
    escalation: dict[str, object],
) -> None:
    recipient_id = escalation.get("recipient_user_id")
    recipient = db.get(User, str(recipient_id)) if recipient_id else None
    if recipient is None:
        ticket = db.get(Ticket, instance.ticket_id)
        recipient = db.get(User, ticket.assignee_id) if ticket and ticket.assignee_id else None
    if recipient is None:
        return
    create_domain_event_notification(
        db,
        tenant_id=instance.tenant_id,
        event_type="sla_escalation",
        title=f"SLA escalation: {target.name}",
        message=(
            f"Target {target.name} is at escalation level "
            f"{target.escalation_level}."
        ),
        recipient_name=recipient.full_name,
        recipient_email=recipient.email,
        recipient_user_id=recipient.id,
        severity="critical" if target.status == "BREACHED" else "warning",
        entity_type="ticket",
        entity_id=instance.ticket_id,
        action_url=f"/tickets/{instance.ticket_id}",
        metadata={
            "target_id": target.id,
            "target_type": target.target_type,
            "escalation_level": target.escalation_level,
        },
    )


def evaluate_instance(
    db: Session,
    instance: TicketSlaInstance,
    *,
    at: datetime | None = None,
) -> list[TicketSlaTarget]:
    instant = as_utc(at or now_utc())
    if not instance.is_current or instance.status in {"CANCELLED", "COMPLETED"}:
        return []
    if instance.status == "PAUSED":
        instance.last_evaluated_at = instant
        return []

    changed: list[TicketSlaTarget] = []
    old_instance_status = instance.status
    escalations = validate_escalations(
        instance.policy_snapshot_json.get("escalations", [])
    )
    targets = instance_targets(db, instance.id)
    for target in targets:
        if target.status in TERMINAL_TARGET_STATUSES:
            continue
        previous = target.status
        previous_level = target.escalation_level
        if instant >= as_utc(target.due_at):
            target.status = "BREACHED"
            target.breached_at = target.breached_at or instant
        elif instant >= as_utc(target.warning_at):
            target.status = "WARNING"
        progress = _target_progress(instance, target, instant)
        applicable = [
            escalation
            for escalation in escalations
            if (
                escalation.get("target_type") in {None, target.target_type}
                and progress >= int(escalation["at_percent"])
            )
        ]
        desired_level = len(applicable)
        if desired_level > target.escalation_level:
            for level in range(target.escalation_level + 1, desired_level + 1):
                target.escalation_level = level
                target.last_escalated_at = instant
                _notify_escalation(db, instance, target, applicable[level - 1])
                _timeline(
                    db,
                    instance,
                    event_type="sla.escalated",
                    actor=None,
                    target=target,
                    message=f"{target.name} escalated to level {level}.",
                    data={"level": level, "progress_percent": progress},
                    created_at=instant,
                )
        if target.status != previous or target.escalation_level != previous_level:
            target.version += 1
            changed.append(target)
            if target.status != previous:
                _timeline(
                    db,
                    instance,
                    event_type=(
                        "sla.target_breached"
                        if target.status == "BREACHED"
                        else "sla.target_warning"
                    ),
                    actor=None,
                    target=target,
                    message=f"{target.name} changed to {target.status}.",
                    data={"progress_percent": progress},
                    created_at=instant,
                )

    if any(target.status == "BREACHED" for target in targets):
        instance.status = "BREACHED"
    elif all(target.status in TERMINAL_TARGET_STATUSES for target in targets):
        instance.status = "COMPLETED"
        instance.completed_at = instance.completed_at or instant
    else:
        instance.status = "ACTIVE"
    instance.last_evaluated_at = instant
    if instance.status != old_instance_status:
        instance.version += 1
    if instance.status == "BREACHED" and old_instance_status != "BREACHED":
        policy = db.get(SlaPolicy, instance.policy_id)
        if policy is not None:
            policy.breach_count += 1
    ticket = db.get(Ticket, instance.ticket_id)
    if ticket is not None:
        _sync_legacy_ticket(ticket, instance, targets)
    return changed


def sync_ticket_sla(
    db: Session,
    ticket: Ticket,
    *,
    old_status: str | None = None,
    actor: User | None = None,
    priority_changed: bool = False,
    at: datetime | None = None,
) -> TicketSlaInstance | None:
    instant = as_utc(at or now_utc())
    if ticket.status == "REOPENED":
        instance = ensure_ticket_sla_instance(
            db,
            ticket,
            actor=actor,
            at=instant,
            force_recalculate=True,
            reason="Ticket reopened",
        )
    else:
        instance = ensure_ticket_sla_instance(
            db,
            ticket,
            actor=actor,
            at=instant,
            force_recalculate=priority_changed,
            reason="Ticket priority or policy scope changed",
        )
    if instance is None:
        return None

    if ticket.status == "CANCELLED":
        for target in instance_targets(db, instance.id):
            if target.status not in TERMINAL_TARGET_STATUSES:
                target.status = "CANCELLED"
                target.version += 1
        instance.status = "CANCELLED"
        instance.completed_at = instant
        instance.version += 1
        ticket.sla_status = "CANCELLED"
        _timeline(
            db,
            instance,
            event_type="sla.cancelled",
            actor=actor,
            message="SLA cancelled with the ticket lifecycle.",
            created_at=instant,
        )
        return instance

    pause_statuses = {
        str(item).upper()
        for item in instance.policy_snapshot_json.get("pause_statuses", [])
    }
    if ticket.status in pause_statuses and instance.status != "PAUSED":
        reason_code = (
            "WAITING_VENDOR"
            if ticket.status == "WAITING_VENDOR"
            else "WAITING_CUSTOMER"
        )
        pause_instance(
            db,
            instance,
            reason_code=reason_code,
            reason=f"Automatic pause for ticket status {ticket.status}",
            actor=actor,
            ticket_status=ticket.status,
            at=instant,
        )
    elif old_status in pause_statuses and ticket.status not in pause_statuses:
        resume_instance(
            db,
            instance,
            actor=actor,
            ticket_status=ticket.status,
            at=instant,
        )

    if ticket.status in RESPONSE_STATUSES and old_status != ticket.status:
        complete_target(
            db,
            instance,
            "RESPONSE",
            actor=actor,
            at=instant,
            reason=f"Ticket entered {ticket.status}",
        )
    if ticket.status in TERMINAL_TICKET_STATUSES:
        complete_target(
            db,
            instance,
            "RESOLUTION",
            actor=actor,
            at=instant,
            reason=f"Ticket entered {ticket.status}",
        )
    evaluate_instance(db, instance, at=instant)
    _sync_legacy_ticket(ticket, instance, instance_targets(db, instance.id))
    return instance


def evaluate_tenant_sla(
    db: Session,
    tenant_id: str | None = None,
    *,
    at: datetime | None = None,
) -> list[TicketSlaTarget]:
    statement = select(TicketSlaInstance).where(
        TicketSlaInstance.is_current.is_(True),
        TicketSlaInstance.status.in_(["ACTIVE", "BREACHED"]),
    )
    if tenant_id:
        statement = statement.where(TicketSlaInstance.tenant_id == tenant_id)
    changed: list[TicketSlaTarget] = []
    for instance in db.scalars(statement).all():
        changed.extend(evaluate_instance(db, instance, at=at))
    return changed
