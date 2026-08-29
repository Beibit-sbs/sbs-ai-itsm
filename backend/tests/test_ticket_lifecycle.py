from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.ticket_history import TicketHistory
from app.models.user import User
from app.services.ticket_lifecycle import (
    CANONICAL_TICKET_STATUSES,
    TERMINAL_TICKET_STATUSES,
    TICKET_STATUS_TRANSITIONS,
    TicketLifecycleError,
    allowed_ticket_transition,
    canonical_ticket_status,
    transition_ticket_status,
    transition_ticket_status_path,
)


EXPECTED_TRANSITIONS = {
    "NEW": {"TRIAGE", "ASSIGNED", "CANCELLED"},
    "TRIAGE": {"ASSIGNED", "WAITING_USER", "CANCELLED"},
    "ASSIGNED": {"IN_PROGRESS", "WAITING_USER", "WAITING_VENDOR"},
    "IN_PROGRESS": {"RESOLVED", "WAITING_USER", "WAITING_VENDOR"},
    "WAITING_USER": {"IN_PROGRESS", "CANCELLED"},
    "WAITING_VENDOR": {"IN_PROGRESS"},
    "RESOLVED": {"CLOSED", "REOPENED"},
    "CLOSED": {"REOPENED"},
    "REOPENED": {"TRIAGE", "ASSIGNED"},
    "CANCELLED": set(),
}


def _ticket(db_session, *, status: str = "NEW") -> tuple[Ticket, User]:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=f"Lifecycle tenant {suffix}",
        slug=f"lifecycle-{suffix}",
        status="active",
    )
    actor = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        email=f"lifecycle-{suffix}@example.test",
        full_name="Lifecycle Manager",
        password_hash="not-used",
        is_active=True,
        is_superuser=False,
        is_root=False,
    )
    now = datetime.now(UTC)
    ticket = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        ticket_number=f"LFC-{suffix.upper()}",
        title="Lifecycle contract target",
        description="Canonical lifecycle test",
        requester_name="Lifecycle Requester",
        requester_email=f"requester-{suffix}@example.test",
        department="IT",
        location="HQ",
        category="GENERAL",
        priority="MEDIUM",
        status=status,
        assignee_id=actor.id,
        assignee_name=actor.full_name,
        governance_version=1,
        resolved_at=now if status == "RESOLVED" else None,
        closed_at=now if status == "CLOSED" else None,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([tenant, actor, ticket])
    db_session.flush()
    return ticket, actor


def test_canonical_ticket_lifecycle_contract_is_closed_and_legacy_safe() -> None:
    assert set(TICKET_STATUS_TRANSITIONS) == CANONICAL_TICKET_STATUSES
    assert TERMINAL_TICKET_STATUSES == {"CANCELLED"}
    assert all(
        target in CANONICAL_TICKET_STATUSES
        for targets in TICKET_STATUS_TRANSITIONS.values()
        for target in targets
    )
    assert canonical_ticket_status("triaged") == "TRIAGE"
    assert canonical_ticket_status("in_progress") == "IN_PROGRESS"
    assert canonical_ticket_status("open") is None
    assert canonical_ticket_status("pending") is None
    assert canonical_ticket_status("waiting") is None
    assert canonical_ticket_status("not-a-ticket-status") is None
    assert allowed_ticket_transition("NEW", "TRIAGE") is True
    assert allowed_ticket_transition("NEW", "CLOSED") is False


@pytest.mark.parametrize("current", sorted(CANONICAL_TICKET_STATUSES))
@pytest.mark.parametrize("target", sorted(CANONICAL_TICKET_STATUSES))
def test_complete_ten_by_ten_transition_matrix(current: str, target: str) -> None:
    assert allowed_ticket_transition(current, target) is (
        target in EXPECTED_TRANSITIONS[current]
    )


@pytest.mark.parametrize("invalid", [None, "", "OPEN", "PENDING", "WAITING", "UNKNOWN"])
def test_non_ticket_statuses_are_rejected(invalid: str | None) -> None:
    assert canonical_ticket_status(invalid) is None


def test_transition_is_versioned_idempotent_and_audited(db_session) -> None:
    ticket, actor = _ticket(db_session)
    first = transition_ticket_status(
        db_session,
        ticket,
        "TRIAGE",
        actor_name=actor.full_name,
        actor_kind="MANAGER",
        actor_user=actor,
        expected_version=1,
        idempotency_key="lifecycle-transition-0001",
        source="contract_test",
    )
    db_session.flush()
    assert first.already_applied is False
    assert ticket.status == "TRIAGE"
    assert ticket.governance_version == 2
    assert db_session.scalar(
        select(func.count(TicketHistory.id)).where(
            TicketHistory.ticket_id == ticket.id,
            TicketHistory.event_type == "status_changed",
        )
    ) == 1
    assert db_session.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.entity_id == ticket.id)
    ) == 1

    replay = transition_ticket_status(
        db_session,
        ticket,
        "TRIAGE",
        actor_name=actor.full_name,
        actor_kind="MANAGER",
        actor_user=actor,
        expected_version=1,
        idempotency_key="lifecycle-transition-0001",
        source="contract_test",
    )
    db_session.flush()
    assert replay.already_applied is True
    assert ticket.governance_version == 2
    assert db_session.scalar(
        select(func.count(TicketHistory.id)).where(
            TicketHistory.ticket_id == ticket.id,
            TicketHistory.event_type == "status_changed",
        )
    ) == 1

    with pytest.raises(TicketLifecycleError, match="different target") as conflict:
        transition_ticket_status(
            db_session,
            ticket,
            "ASSIGNED",
            actor_name=actor.full_name,
            idempotency_key="lifecycle-transition-0001",
        )
    assert conflict.value.code == "idempotency_conflict"

    with pytest.raises(TicketLifecycleError, match="version conflict") as stale:
        transition_ticket_status(
            db_session,
            ticket,
            "ASSIGNED",
            actor_name=actor.full_name,
            expected_version=1,
            idempotency_key="lifecycle-transition-0002",
        )
    assert stale.value.code == "version_conflict"

    with pytest.raises(TicketLifecycleError, match="state conflict") as state_conflict:
        transition_ticket_status(
            db_session,
            ticket,
            "ASSIGNED",
            actor_name=actor.full_name,
            actor_kind="MANAGER",
            actor_user=actor,
            expected_status="NEW",
        )
    assert state_conflict.value.code == "state_conflict"


def test_requester_policy_and_resolution_timestamps_are_canonical(db_session) -> None:
    ticket, actor = _ticket(db_session, status="RESOLVED")
    ticket.requester_id = actor.id
    ticket.requester_email = actor.email
    db_session.flush()
    with pytest.raises(TicketLifecycleError) as missing_score:
        transition_ticket_status(
            db_session,
            ticket,
            "CLOSED",
            actor_name="Lifecycle Requester",
            actor_kind="REQUESTER",
            actor_user=actor,
        )
    assert missing_score.value.code == "validation_error"

    transition_ticket_status(
        db_session,
        ticket,
        "CLOSED",
        actor_name="Lifecycle Requester",
        actor_kind="REQUESTER",
        actor_user=actor,
        satisfaction_score=5,
        idempotency_key="requester-close-0001",
    )
    assert ticket.closed_at is not None
    assert ticket.satisfaction_score == 5

    with pytest.raises(TicketLifecycleError) as missing_reason:
        transition_ticket_status(
            db_session,
            ticket,
            "REOPENED",
            actor_name="Lifecycle Requester",
            actor_kind="REQUESTER",
            actor_user=actor,
        )
    assert missing_reason.value.code == "validation_error"

    transition_ticket_status(
        db_session,
        ticket,
        "REOPENED",
        actor_name="Lifecycle Requester",
        actor_kind="REQUESTER",
        actor_user=actor,
        reopen_reason="The issue returned after confirmation.",
        idempotency_key="requester-reopen-0001",
    )
    assert ticket.reopened_at is not None
    assert ticket.resolved_at is None
    assert ticket.closed_at is None
    assert ticket.reopen_reason == "The issue returned after confirmation."
    assert ticket.governance_version == 3


def test_cancelled_does_not_reuse_closed_timestamp(db_session) -> None:
    ticket, actor = _ticket(db_session, status="WAITING_USER")
    transition_ticket_status(
        db_session,
        ticket,
        "CANCELLED",
        actor_name=actor.full_name,
        actor_kind="MANAGER",
        actor_user=actor,
        idempotency_key="cancel-without-close-0001",
    )
    assert ticket.status == "CANCELLED"
    assert ticket.closed_at is None
    assert ticket.resolved_at is None


def test_actor_tenant_and_assignment_boundaries_are_enforced(db_session) -> None:
    ticket, actor = _ticket(db_session)
    other_tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Other lifecycle tenant",
        slug=f"other-lifecycle-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    outsider = User(
        id=str(uuid.uuid4()),
        tenant_id=other_tenant.id,
        email=f"outsider-{uuid.uuid4().hex[:8]}@example.test",
        full_name="Cross Tenant Actor",
        password_hash="not-used",
        is_active=True,
        is_superuser=False,
        is_root=False,
    )
    db_session.add_all([other_tenant, outsider])
    db_session.flush()
    with pytest.raises(TicketLifecycleError) as cross_tenant:
        transition_ticket_status(
            db_session,
            ticket,
            "TRIAGE",
            actor_name=outsider.full_name,
            actor_kind="MANAGER",
            actor_user=outsider,
        )
    assert cross_tenant.value.code == "forbidden"

    with pytest.raises(TicketLifecycleError) as wrong_requester:
        transition_ticket_status(
            db_session,
            ticket,
            "CLOSED",
            actor_name=actor.full_name,
            actor_kind="REQUESTER",
            actor_user=actor,
            satisfaction_score=5,
        )
    assert wrong_requester.value.code == "forbidden"

    ticket.assignee_id = None
    with pytest.raises(TicketLifecycleError) as wrong_agent:
        transition_ticket_status(
            db_session,
            ticket,
            "TRIAGE",
            actor_name=actor.full_name,
            actor_kind="ASSIGNED_AGENT",
            actor_user=actor,
        )
    assert wrong_agent.value.code == "forbidden"


def test_locked_read_refreshes_stale_identity_before_version_check(db_session) -> None:
    ticket, _ = _ticket(db_session)
    db_session.commit()
    bind = db_session.get_bind()
    stale_session = Session(bind=bind)
    writer_session = Session(bind=bind)
    try:
        stale = stale_session.get(Ticket, ticket.id)
        current = writer_session.get(Ticket, ticket.id)
        assert stale is not None and current is not None
        current.governance_version = 2
        current.updated_at = datetime.now(UTC)
        writer_session.commit()

        with pytest.raises(TicketLifecycleError) as conflict:
            transition_ticket_status(
                stale_session,
                stale,
                "TRIAGE",
                actor_name="Concurrency Test",
                actor_kind="SYSTEM",
                actor_email="concurrency@example.test",
                expected_version=1,
            )
        assert conflict.value.code == "version_conflict"
        assert stale.governance_version == 2
    finally:
        stale_session.close()
        writer_session.close()


def test_system_recovery_uses_only_canonical_edges(db_session) -> None:
    ticket, actor = _ticket(db_session)
    results = transition_ticket_status_path(
        db_session,
        ticket,
        "CLOSED",
        actor_name="Monitoring Recovery",
        actor_kind="SYSTEM",
        actor_user=actor,
        idempotency_key="monitoring-recovery-0001",
        source="contract_test",
        notify=False,
    )
    assert [item.target_status for item in results] == [
        "ASSIGNED",
        "IN_PROGRESS",
        "RESOLVED",
        "CLOSED",
    ]
    assert ticket.status == "CLOSED"
    assert ticket.resolved_at is not None
    assert ticket.closed_at is not None
    assert ticket.governance_version == 5


def test_transition_api_exposes_version_and_idempotency_contract(app) -> None:
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        created = client.post(
            "/api/v1/tickets",
            headers=headers,
            json={
                "title": "Lifecycle API concurrency target",
                "description": "Versioned transition contract",
                "requester_name": "External Lifecycle Requester",
                "requester_email": "lifecycle-api@example.test",
                "on_behalf_reason": "Lifecycle contract acceptance",
                "department": "IT",
                "location": "HQ",
                "category": "NETWORK_INTERNET",
                "priority": "MEDIUM",
            },
        )
        assert created.status_code == 201, created.text
        ticket = created.json()
        assert ticket["governance_version"] == 1
        assert set(ticket["allowed_transitions"]) == {
            "TRIAGE",
            "ASSIGNED",
            "CANCELLED",
        }
        request = {
            "status": "TRIAGE",
            "expected_version": 1,
            "idempotency_key": "api-lifecycle-transition-0001",
        }
        first = client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            headers=headers,
            json=request,
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "TRIAGE"
        assert first.json()["governance_version"] == 2
        assert set(first.json()["allowed_transitions"]) == {
            "ASSIGNED",
            "WAITING_USER",
            "CANCELLED",
        }

        replay = client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            headers=headers,
            json=request,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["governance_version"] == 2

        reused = client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            headers=headers,
            json={
                "status": "ASSIGNED",
                "expected_version": 2,
                "idempotency_key": request["idempotency_key"],
            },
        )
        assert reused.status_code == 409, reused.text

        stale = client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            headers=headers,
            json={
                "status": "ASSIGNED",
                "expected_version": 1,
                "idempotency_key": "api-lifecycle-transition-0002",
            },
        )
        assert stale.status_code == 409, stale.text

        history = client.get(
            f"/api/v1/tickets/{ticket['id']}/history",
            headers=headers,
        )
        assert history.status_code == 200, history.text
        applied = [
            item
            for item in history.json()
            if item["field_name"] == "status"
            and item["old_value"] == "NEW"
            and item["new_value"] == "TRIAGE"
        ]
        assert len(applied) == 1
