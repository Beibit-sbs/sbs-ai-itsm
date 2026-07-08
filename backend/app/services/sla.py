from __future__ import annotations

from datetime import UTC, datetime

from app.models.ticket import Ticket


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _remaining_minutes(due_at: datetime | None, now: datetime) -> int | None:
    normalized = _as_utc(due_at)
    if normalized is None:
        return None
    return int((normalized - now).total_seconds() // 60)


def calculate_sla_state(ticket: Ticket) -> dict[str, int | bool | str | None]:
    now = datetime.now(UTC)
    response_remaining = _remaining_minutes(ticket.response_due_at, now)
    resolution_remaining = _remaining_minutes(ticket.resolution_due_at, now)
    response_breached = bool(response_remaining is not None and response_remaining < 0 and ticket.status in {"NEW", "TRIAGE", "TRIAGED"})
    resolution_breached = bool(resolution_remaining is not None and resolution_remaining < 0 and ticket.status not in {"RESOLVED", "CLOSED", "CANCELLED"})

    if response_breached or resolution_breached:
        badge = "BREACHED"
    elif (response_remaining is not None and response_remaining <= 60) or (resolution_remaining is not None and resolution_remaining <= 120):
        badge = "RISK"
    else:
        badge = "OK"

    return {
        "badge": badge,
        "response_remaining_minutes": response_remaining,
        "resolution_remaining_minutes": resolution_remaining,
        "is_response_breached": response_breached,
        "is_resolution_breached": resolution_breached,
    }
