from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_history import TicketHistory
from app.models.user import User
from app.services.asset_sla import calculate_ticket_sla_status
from app.services.audit import log_audit
from app.services.enterprise_sla import sync_ticket_sla
from app.services.notifications import create_ticket_event_notification


TicketActorKind = Literal["REQUESTER", "ASSIGNED_AGENT", "MANAGER", "SYSTEM"]

CANONICAL_TICKET_STATUSES = frozenset(
    {
        "NEW",
        "TRIAGE",
        "ASSIGNED",
        "IN_PROGRESS",
        "WAITING_USER",
        "WAITING_VENDOR",
        "RESOLVED",
        "CLOSED",
        "REOPENED",
        "CANCELLED",
    }
)

# CANCELLED is the only graph-terminal state. CLOSED is a closure state but has
# the explicit governed CLOSED -> REOPENED edge in the authoritative contract.
TERMINAL_TICKET_STATUSES = frozenset({"CANCELLED"})
RESOLUTION_COMPLETE_STATUSES = frozenset({"RESOLVED", "CLOSED", "CANCELLED"})

_TRANSITIONS = {
    "NEW": frozenset({"TRIAGE", "ASSIGNED", "CANCELLED"}),
    "TRIAGE": frozenset({"ASSIGNED", "WAITING_USER", "CANCELLED"}),
    "ASSIGNED": frozenset({"IN_PROGRESS", "WAITING_USER", "WAITING_VENDOR"}),
    "IN_PROGRESS": frozenset({"RESOLVED", "WAITING_USER", "WAITING_VENDOR"}),
    "WAITING_USER": frozenset({"IN_PROGRESS", "CANCELLED"}),
    "WAITING_VENDOR": frozenset({"IN_PROGRESS"}),
    "RESOLVED": frozenset({"CLOSED", "REOPENED"}),
    "CLOSED": frozenset({"REOPENED"}),
    "REOPENED": frozenset({"TRIAGE", "ASSIGNED"}),
    "CANCELLED": frozenset(),
}
TICKET_STATUS_TRANSITIONS = MappingProxyType(_TRANSITIONS)

_LEGACY_STATUS_ALIASES = MappingProxyType(
    {
        # TRIAGED exists in historical demo rows and was the only compatibility
        # alias accepted by the pre-Gate API. OPEN/PENDING/WAITING are not Ticket
        # states and are deliberately rejected instead of being reinterpreted.
        "TRIAGED": "TRIAGE",
    }
)
_REQUESTER_TARGETS = frozenset({"CLOSED", "REOPENED"})
_IDEMPOTENCY_NAMESPACE = uuid.UUID("7ca036a0-b793-5e47-98a9-f159ba3aa26b")


class TicketLifecycleError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        current_status: str | None = None,
        target_status: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.current_status = current_status
        self.target_status = target_status


@dataclass(frozen=True)
class TicketTransitionResult:
    ticket: Ticket
    previous_status: str
    target_status: str
    governance_version: int
    already_applied: bool = False


def canonical_ticket_status(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    normalized = _LEGACY_STATUS_ALIASES.get(normalized, normalized)
    return normalized if normalized in CANONICAL_TICKET_STATUSES else None


def allowed_ticket_transition(current_status: str, target_status: str) -> bool:
    current = canonical_ticket_status(current_status)
    target = canonical_ticket_status(target_status)
    return bool(
        current is not None
        and target is not None
        and target in TICKET_STATUS_TRANSITIONS[current]
    )


def ticket_transition_path(current_status: str, target_status: str) -> tuple[str, ...]:
    current = canonical_ticket_status(current_status)
    target = canonical_ticket_status(target_status)
    if current is None or target is None:
        raise TicketLifecycleError(
            "unknown_status",
            "Unknown ticket lifecycle status",
            current_status=current_status,
            target_status=target_status,
        )
    if current == target:
        return ()
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(current, ())])
    visited = {current}
    while queue:
        status, path = queue.popleft()
        for next_status in sorted(TICKET_STATUS_TRANSITIONS[status]):
            if next_status in visited:
                continue
            next_path = (*path, next_status)
            if next_status == target:
                return next_path
            visited.add(next_status)
            queue.append((next_status, next_path))
    raise TicketLifecycleError(
        "invalid_transition",
        f"Invalid ticket transition {current} -> {target}",
        current_status=current,
        target_status=target,
    )


def _transition_history_id(ticket_id: str, idempotency_key: str) -> str:
    return str(
        uuid.uuid5(
            _IDEMPOTENCY_NAMESPACE,
            f"{ticket_id}:{idempotency_key}",
        )
    )


def _locked_ticket(db: Session, ticket: Ticket) -> Ticket:
    # Preserve legitimate changes (for example assignee + lifecycle transition)
    # before populate_existing refreshes the identity-map instance under the lock.
    db.flush()
    locked = db.scalar(
        select(Ticket)
        .where(Ticket.id == ticket.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked is None:
        raise TicketLifecycleError("not_found", "Ticket no longer exists")
    return locked


def _assert_actor_policy(
    ticket: Ticket,
    *,
    actor_kind: TicketActorKind,
    actor_user: User | None,
    target_status: str,
    satisfaction_score: int | None,
    reopen_reason: str | None,
    allow_cross_tenant_actor: bool,
) -> None:
    if actor_kind != "SYSTEM" and actor_user is None:
        raise TicketLifecycleError(
            "forbidden",
            f"{actor_kind} transition requires an authenticated actor",
            current_status=ticket.status,
            target_status=target_status,
        )
    if (
        actor_user is not None
        and actor_user.tenant_id != ticket.tenant_id
        and not allow_cross_tenant_actor
    ):
        raise TicketLifecycleError(
            "forbidden",
            "Lifecycle actor belongs to a different tenant",
            current_status=ticket.status,
            target_status=target_status,
        )
    if actor_kind == "REQUESTER":
        assert actor_user is not None
        if not (
            ticket.requester_id == actor_user.id
            or ticket.requester_email.strip().casefold()
            == actor_user.email.strip().casefold()
        ):
            raise TicketLifecycleError(
                "forbidden",
                "Requester can transition only their own ticket",
                current_status=ticket.status,
                target_status=target_status,
            )
        if target_status not in _REQUESTER_TARGETS:
            raise TicketLifecycleError(
                "forbidden",
                "Requester can only close or reopen a ticket",
                current_status=ticket.status,
                target_status=target_status,
            )
        if target_status == "CLOSED" and satisfaction_score is None:
            raise TicketLifecycleError(
                "validation_error",
                "Requester must provide satisfaction_score when closing a ticket",
                current_status=ticket.status,
                target_status=target_status,
            )
        if target_status == "REOPENED" and not (reopen_reason or "").strip():
            raise TicketLifecycleError(
                "validation_error",
                "Requester must provide reopen_reason when reopening a ticket",
                current_status=ticket.status,
                target_status=target_status,
            )
    if actor_kind == "ASSIGNED_AGENT":
        if actor_user is None or ticket.assignee_id != actor_user.id:
            raise TicketLifecycleError(
                "forbidden",
                "Agent can transition only tickets assigned to that agent",
                current_status=ticket.status,
                target_status=target_status,
            )


def transition_ticket_status(
    db: Session,
    ticket: Ticket,
    target_status: str,
    *,
    actor_name: str,
    actor_kind: TicketActorKind = "SYSTEM",
    actor_user: User | None = None,
    actor_email: str | None = None,
    expected_version: int | None = None,
    expected_status: str | None = None,
    idempotency_key: str | None = None,
    at: datetime | None = None,
    comment: str | None = None,
    is_internal_comment: bool = False,
    satisfaction_score: int | None = None,
    reopen_reason: str | None = None,
    source: str = "ticket_api",
    reason: str | None = None,
    notify: bool = True,
    audit: bool = True,
    priority_changed: bool = False,
    ip_address: str | None = None,
    user_agent: str | None = None,
    allow_cross_tenant_actor: bool = False,
) -> TicketTransitionResult:
    target = canonical_ticket_status(target_status)
    if target is None:
        raise TicketLifecycleError(
            "unknown_status",
            "Unknown ticket lifecycle status",
            current_status=ticket.status,
            target_status=target_status,
        )
    key = (idempotency_key or "").strip()
    if len(key) > 120:
        raise TicketLifecycleError(
            "validation_error", "Idempotency key must be at most 120 characters"
        )

    ticket = _locked_ticket(db, ticket)
    _assert_actor_policy(
        ticket,
        actor_kind=actor_kind,
        actor_user=actor_user,
        target_status=target,
        satisfaction_score=satisfaction_score,
        reopen_reason=reopen_reason,
        allow_cross_tenant_actor=allow_cross_tenant_actor,
    )
    history_id = _transition_history_id(ticket.id, key) if key else None
    if history_id is not None:
        existing = db.get(TicketHistory, history_id)
        if existing is not None:
            existing_target = canonical_ticket_status(existing.new_value)
            if existing_target != target:
                raise TicketLifecycleError(
                    "idempotency_conflict",
                    "Idempotency key was already used for a different target status",
                    current_status=ticket.status,
                    target_status=target,
                )
            return TicketTransitionResult(
                ticket=ticket,
                previous_status=canonical_ticket_status(existing.old_value)
                or str(existing.old_value or ticket.status),
                target_status=target,
                governance_version=ticket.governance_version,
                already_applied=True,
            )

    current = canonical_ticket_status(ticket.status)
    if current is None:
        raise TicketLifecycleError(
            "invalid_persisted_status",
            f"Ticket contains non-canonical status {ticket.status!r}",
            current_status=ticket.status,
            target_status=target,
        )
    if expected_version is not None and ticket.governance_version != expected_version:
        raise TicketLifecycleError(
            "version_conflict",
            f"Ticket version conflict: current version is {ticket.governance_version}",
            current_status=current,
            target_status=target,
        )
    expected = canonical_ticket_status(expected_status) if expected_status else None
    if expected_status is not None and expected != current:
        raise TicketLifecycleError(
            "state_conflict",
            f"Ticket state conflict: current status is {current}",
            current_status=current,
            target_status=target,
        )

    if target not in TICKET_STATUS_TRANSITIONS[current]:
        raise TicketLifecycleError(
            "invalid_transition",
            f"Invalid ticket transition {current} -> {target}",
            current_status=current,
            target_status=target,
        )

    instant = at or datetime.now(UTC)
    ticket.status = target
    ticket.updated_at = instant
    ticket.governance_version += 1
    if target == "RESOLVED":
        ticket.resolved_at = ticket.resolved_at or instant
    elif target == "CLOSED":
        ticket.closed_at = instant
        if satisfaction_score is not None:
            ticket.satisfaction_score = satisfaction_score
    elif target == "REOPENED":
        ticket.reopened_at = instant
        ticket.resolved_at = None
        ticket.closed_at = None
        ticket.reopen_reason = (
            (reopen_reason or "").strip()
            or (comment or "").strip()
            or ticket.reopen_reason
        )
    history = TicketHistory(
        id=history_id or str(uuid.uuid4()),
        ticket_id=ticket.id,
        actor_name=actor_name[:200],
        event_type="status_changed",
        field_name="status",
        old_value=current,
        new_value=target,
        message=(reason or f"Ticket status changed from {current} to {target}.")[:10_000],
        created_at=instant,
    )
    db.add(history)

    comment_body = (comment or "").strip()
    if comment_body:
        db.add(
            TicketComment(
                id=str(uuid.uuid4()),
                ticket_id=ticket.id,
                author_id=actor_user.id if actor_user is not None else None,
                author_name=actor_name[:200],
                author_role=(actor_kind.lower() if actor_kind else "system")[:80],
                body=comment_body[:10_000],
                is_internal=is_internal_comment,
                created_at=instant,
            )
        )
        db.add(
            TicketHistory(
                id=str(uuid.uuid4()),
                ticket_id=ticket.id,
                actor_name=actor_name[:200],
                event_type="comment_added",
                field_name="comment",
                old_value=None,
                new_value=comment_body[:2_000],
                message="Comment added during ticket lifecycle transition.",
                created_at=instant,
            )
        )

    if (
        sync_ticket_sla(
            db,
            ticket,
            old_status=current,
            actor=actor_user,
            priority_changed=priority_changed,
            at=instant,
        )
        is None
    ):
        ticket.sla_status = calculate_ticket_sla_status(ticket)

    audit_action = (
        "ticket_reopened"
        if target == "REOPENED"
        else "ticket_closed"
        if target == "CLOSED"
        else "ticket_status_changed"
    )
    if audit:
        log_audit(
            db,
            action=audit_action,
            entity_type="ticket",
            entity_id=ticket.id,
            actor_user=actor_user,
            actor_email=actor_email,
            tenant_id=ticket.tenant_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={
                "old_status": current,
                "new_status": target,
                "source": source,
                "governance_version": ticket.governance_version,
                "idempotency_key_present": bool(key),
            },
        )

    if notify:
        notification_events = ["ticket_status_changed"]
        if target in {"RESOLVED", "CLOSED"}:
            notification_events.append("ticket_resolved")
        for event_code in notification_events:
            notification = create_ticket_event_notification(
                db,
                event_code=event_code,
                ticket=ticket,
                actor_name=actor_name,
            )
            if notification is not None:
                db.add(
                    TicketHistory(
                        id=str(uuid.uuid4()),
                        ticket_id=ticket.id,
                        actor_name=actor_name[:200],
                        event_type="notification_created",
                        field_name="notification",
                        old_value=None,
                        new_value=event_code,
                        message=f"Notification queued: {event_code}.",
                        created_at=instant,
                    )
                )

    return TicketTransitionResult(
        ticket=ticket,
        previous_status=current,
        target_status=target,
        governance_version=ticket.governance_version,
    )


def transition_ticket_status_path(
    db: Session,
    ticket: Ticket,
    target_status: str,
    **kwargs: object,
) -> tuple[TicketTransitionResult, ...]:
    path = ticket_transition_path(ticket.status, target_status)
    if not path:
        raise TicketLifecycleError(
            "invalid_transition",
            "Ticket is already in the target status",
            current_status=ticket.status,
            target_status=target_status,
        )
    results: list[TicketTransitionResult] = []
    base_key = str(kwargs.pop("idempotency_key", "") or "").strip()
    expected_version = kwargs.pop("expected_version", None)
    notify = bool(kwargs.pop("notify", True))
    for index, step_target in enumerate(path):
        result = transition_ticket_status(
            db,
            ticket,
            step_target,
            expected_version=(expected_version if index == 0 else None),
            idempotency_key=(
                f"{base_key}:{index}:{step_target}"[-120:] if base_key else None
            ),
            notify=notify and index == len(path) - 1,
            **kwargs,
        )
        results.append(result)
        ticket = result.ticket
    return tuple(results)
