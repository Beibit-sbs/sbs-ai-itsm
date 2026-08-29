from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.problem_governance import ProblemRCA, ProblemTrendSignal
from app.models.ticket import Ticket


def now_utc() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def validate_rca(item: ProblemRCA) -> list[str]:
    errors: list[str] = []
    if len(item.problem_statement.strip()) < 10:
        errors.append("Problem statement requires at least 10 characters")
    if len(item.conclusion.strip()) < 10:
        errors.append("RCA conclusion requires at least 10 characters")
    if not item.evidence_json:
        errors.append("At least one evidence reference is required")
    if item.method == "FIVE_WHYS":
        valid = [
            step
            for step in item.five_whys_json
            if str(step.get("why") or "").strip()
            and str(step.get("answer") or "").strip()
        ]
        if len(valid) < 3:
            errors.append("Five Whys requires at least three answered steps")
    elif item.method == "ISHIKAWA":
        populated = [
            values
            for values in item.ishikawa_json.values()
            if isinstance(values, list) and any(str(value).strip() for value in values)
        ]
        if len(populated) < 3:
            errors.append("Ishikawa requires at least three populated categories")
    elif item.method == "FAULT_TREE" and not item.fault_tree_json:
        errors.append("Fault Tree requires a structured tree")
    return errors


def _signature(ticket: Ticket) -> tuple[str, str]:
    words = re.findall(r"[\w-]+", ticket.title.casefold(), flags=re.UNICODE)
    stable_words = sorted({word for word in words if len(word) >= 4})[:4]
    fingerprint = "|".join(
        [
            ticket.category.strip().casefold(),
            *stable_words,
        ]
    )
    label = " · ".join(
        [ticket.category, " ".join(stable_words[:3]) or ticket.title[:80]]
    )
    return fingerprint[:255], label[:255]


def scan_ticket_trends(
    db: Session,
    tenant_id: str,
    *,
    days: int,
    minimum_occurrences: int,
) -> list[ProblemTrendSignal]:
    end = now_utc()
    start = end - timedelta(days=days)
    baseline_start = start - timedelta(days=days)
    tickets = list(
        db.scalars(
            select(Ticket).where(
                Ticket.tenant_id == tenant_id,
                Ticket.created_at >= baseline_start,
                Ticket.created_at < end,
            )
        ).all()
    )
    current: dict[str, list[Ticket]] = defaultdict(list)
    baseline: dict[str, list[Ticket]] = defaultdict(list)
    labels: dict[str, str] = {}
    for ticket in tickets:
        signature, label = _signature(ticket)
        labels[signature] = label
        if aware(ticket.created_at) >= start:
            current[signature].append(ticket)
        else:
            baseline[signature].append(ticket)
    updated: list[ProblemTrendSignal] = []
    for signature, items in current.items():
        if len(items) < minimum_occurrences:
            continue
        old_count = len(baseline.get(signature, []))
        growth = round((len(items) - old_count) * 100 / max(1, old_count))
        score = min(
            100,
            len(items) * 12
            + max(0, growth) // 5
            + sum(ticket.priority in {"P1", "CRITICAL"} for ticket in items) * 15,
        )
        signal = db.scalar(
            select(ProblemTrendSignal).where(
                ProblemTrendSignal.tenant_id == tenant_id,
                ProblemTrendSignal.signature == signature,
            )
        )
        if signal is None:
            signal = ProblemTrendSignal(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                signal_type="VOLUME_SPIKE" if growth >= 100 else "RECURRENCE",
                signature=signature,
                title=f"Recurring incident cluster: {labels[signature]}",
                service_name=None,
                category=items[0].category,
                window_start_at=start,
                window_end_at=end,
                baseline_count=old_count,
                current_count=len(items),
                growth_percent=growth,
                score=score,
                incident_ids_json=[ticket.id for ticket in items],
                evidence_json={
                    "ticket_numbers": [ticket.ticket_number for ticket in items],
                    "priorities": [ticket.priority for ticket in items],
                },
                status="OPEN",
                version=1,
            )
            db.add(signal)
        else:
            signal.signal_type = "VOLUME_SPIKE" if growth >= 100 else "RECURRENCE"
            signal.window_start_at = start
            signal.window_end_at = end
            signal.baseline_count = old_count
            signal.current_count = len(items)
            signal.growth_percent = growth
            signal.score = score
            signal.incident_ids_json = [ticket.id for ticket in items]
            signal.evidence_json = {
                "ticket_numbers": [ticket.ticket_number for ticket in items],
                "priorities": [ticket.priority for ticket in items],
            }
            if signal.status == "DISMISSED":
                signal.status = "OPEN"
                signal.disposition_comment = None
            signal.version += 1
            signal.updated_at = end
        updated.append(signal)
    return updated
