from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest
from sqlalchemy import select

from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.ticket_history import TicketHistory
from app.models.user import User
from app.models.workflow_engine import (
    WorkflowExecution,
    WorkflowExecutionEvent,
    WorkflowVersion,
)
from app.services.workflow_engine import (
    compare_workflow_versions,
    create_workflow,
    create_workflow_draft,
    decide_workflow_review,
    enqueue_workflow_execution,
    process_workflow_execution,
    publish_workflow_version,
    request_workflow_review,
    simulate_workflow,
    update_workflow_draft,
    validate_workflow_definition,
    verify_workflow_event_chain,
)


def _tenant(db_session) -> Tenant:
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Workflow Engine Test",
        slug=f"workflow-engine-{suffix}",
        status="active",
    )
    db_session.add(tenant)
    db_session.flush()
    return tenant


def _user(db_session, tenant: Tenant, label: str) -> User:
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        email=f"{label}-{uuid.uuid4().hex[:8]}@workflow.test",
        full_name=f"Workflow {label.title()}",
        password_hash="not-used-by-service-tests",
        is_active=True,
        is_superuser=False,
        is_root=False,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _ticket(db_session, tenant: Tenant, *, status: str = "NEW") -> Ticket:
    now = datetime.now(UTC)
    ticket = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        ticket_number=f"WF-{uuid.uuid4().hex[:10].upper()}",
        title="Workflow lifecycle target",
        requester_name="Workflow Requester",
        requester_email=f"requester-{uuid.uuid4().hex[:8]}@workflow.test",
        department="IT",
        location="HQ",
        category="GENERAL",
        priority="MEDIUM",
        status=status,
        governance_version=1,
        created_at=now,
        updated_at=now,
    )
    db_session.add(ticket)
    db_session.flush()
    return ticket


def _branch_definition() -> dict:
    return {
        "schema_version": "1.0",
        "trigger": {"type": "ticket.created"},
        "entrypoint": "priority_gate",
        "on_failure": "FAIL",
        "nodes": [
            {
                "key": "priority_gate",
                "type": "CONDITION",
                "name": "Check priority",
                "config": {
                    "path": "context.ticket.priority",
                    "operator": "eq",
                    "value": "critical",
                },
                "next": {"true": "set_route", "false": "end"},
            },
            {
                "key": "set_route",
                "type": "ACTION",
                "name": "Set route",
                "config": {
                    "action": "context.set_variable",
                    "name": "route",
                    "value": "major_incident",
                },
                "retry": {"max_attempts": 3, "backoff_seconds": 10},
                "next": "end",
            },
            {
                "key": "end",
                "type": "END",
                "name": "Complete",
                "config": {},
            },
        ],
    }


def test_validator_rejects_cycles_secrets_and_malformed_retry() -> None:
    malformed = _branch_definition()
    malformed["nodes"][1]["retry"] = {
        "max_attempts": "forever",
        "backoff_seconds": False,
    }
    validation = validate_workflow_definition(
        malformed,
        expected_trigger_type="ticket.created",
    )
    assert validation["valid"] is False
    assert any("max_attempts" in error for error in validation["errors"])
    assert any("backoff_seconds" in error for error in validation["errors"])

    cyclic = _branch_definition()
    cyclic["nodes"][2]["type"] = "ACTION"
    cyclic["nodes"][2]["config"] = {
        "action": "context.set_variable",
        "name": "loop",
        "value": True,
    }
    cyclic["nodes"][2]["next"] = "priority_gate"
    validation = validate_workflow_definition(cyclic)
    assert validation["valid"] is False
    assert any("cycle" in error.lower() for error in validation["errors"])

    secret_bearing = _branch_definition()
    secret_bearing["nodes"][1]["config"]["api_token"] = "do-not-store"
    validation = validate_workflow_definition(secret_bearing)
    assert validation["valid"] is False
    assert any("secret-like field" in error for error in validation["errors"])

    for non_ticket_status in ("OPEN", "PENDING", "WAITING"):
        invalid_transition = _branch_definition()
        invalid_transition["nodes"][1]["config"] = {
            "action": "ticket.transition",
            "ticket_id": "T-INVALID",
            "status": non_ticket_status,
        }
        validation = validate_workflow_definition(invalid_transition)
        assert validation["valid"] is False
        assert any("unknown ticket status" in error for error in validation["errors"])


def test_simulation_is_deterministic_and_side_effect_free() -> None:
    definition = _branch_definition()
    result = simulate_workflow(
        definition,
        {"ticket": {"id": "T-1", "priority": "critical"}},
        expected_trigger_type="ticket.created",
    )
    assert result["valid"] is True
    assert result["completed"] is True
    assert result["variables"] == {"route": "major_incident"}
    assert [step["node_key"] for step in result["trace"]] == [
        "priority_gate",
        "set_route",
        "end",
    ]

    normal = simulate_workflow(
        definition,
        {"ticket": {"id": "T-2", "priority": "normal"}},
        expected_trigger_type="ticket.created",
    )
    assert [step["node_key"] for step in normal["trace"]] == [
        "priority_gate",
        "end",
    ]


def test_workflow_ticket_transition_uses_canonical_lifecycle(db_session) -> None:
    tenant = _tenant(db_session)
    ticket = _ticket(db_session, tenant)

    def definition(status: str) -> dict:
        return {
            "schema_version": "1.0",
            "trigger": {"type": "manual"},
            "entrypoint": "transition",
            "on_failure": "FAIL",
            "nodes": [
                {
                    "key": "transition",
                    "type": "ACTION",
                    "name": "Transition ticket",
                    "config": {
                        "action": "ticket.transition",
                        "ticket_id": ticket.id,
                        "status": status,
                    },
                    "next": "end",
                },
                {
                    "key": "end",
                    "type": "END",
                    "name": "Complete",
                    "config": {},
                },
            ],
        }

    workflow, draft = create_workflow(
        db_session,
        tenant_id=tenant.id,
        code="canonical-ticket-transition",
        name="Canonical ticket transition",
        description=None,
        trigger_type="manual",
        concurrency_policy="ALLOW",
        max_active_executions=10,
        actor_id=None,
    )
    validation = update_workflow_draft(
        draft,
        workflow,
        definition=definition("TRIAGE"),
        expected_revision=1,
        change_summary="Use canonical lifecycle",
        actor_id=None,
    )
    assert validation["valid"] is True
    publish_workflow_version(
        db_session,
        workflow,
        draft,
        expected_workflow_revision=1,
        expected_version_revision=2,
        actor_id=None,
        activate=True,
    )
    execution, _ = enqueue_workflow_execution(
        db_session,
        workflow,
        context={"entity_type": "ticket", "entity_id": ticket.id},
        idempotency_key=f"canonical-transition:{ticket.id}",
        source="MANUAL",
        actor_id=None,
    )
    process_workflow_execution(db_session, execution)
    assert execution.status == "SUCCEEDED"
    assert ticket.status == "TRIAGE"
    assert ticket.governance_version == 2
    history = db_session.scalars(
        select(TicketHistory).where(
            TicketHistory.ticket_id == ticket.id,
            TicketHistory.field_name == "status",
        )
    ).all()
    assert [(item.old_value, item.new_value) for item in history] == [
        ("NEW", "TRIAGE")
    ]

    invalid_workflow, invalid_draft = create_workflow(
        db_session,
        tenant_id=tenant.id,
        code="dynamic-invalid-ticket-transition",
        name="Dynamic invalid ticket transition",
        description=None,
        trigger_type="manual",
        concurrency_policy="ALLOW",
        max_active_executions=10,
        actor_id=None,
    )
    validation = update_workflow_draft(
        invalid_draft,
        invalid_workflow,
        definition=definition("${context.target_status}"),
        expected_revision=1,
        change_summary="Runtime status validation",
        actor_id=None,
    )
    assert validation["valid"] is True
    publish_workflow_version(
        db_session,
        invalid_workflow,
        invalid_draft,
        expected_workflow_revision=1,
        expected_version_revision=2,
        actor_id=None,
        activate=True,
    )
    rejected, _ = enqueue_workflow_execution(
        db_session,
        invalid_workflow,
        context={
            "entity_type": "ticket",
            "entity_id": ticket.id,
            "target_status": "OPEN",
        },
        idempotency_key=f"invalid-transition:{ticket.id}",
        source="MANUAL",
        actor_id=None,
    )
    process_workflow_execution(db_session, rejected)
    assert rejected.status == "FAILED"
    assert "unknown_status" in str(rejected.last_error)
    assert ticket.status == "TRIAGE"


def test_published_versions_are_immutable_and_execution_is_idempotent(
    db_session,
) -> None:
    tenant = _tenant(db_session)
    workflow, draft = create_workflow(
        db_session,
        tenant_id=tenant.id,
        code="ticket-routing",
        name="Ticket routing",
        description="Deterministic routing test",
        trigger_type="ticket.created",
        concurrency_policy="ALLOW",
        max_active_executions=10,
        actor_id=None,
    )
    validation = update_workflow_draft(
        draft,
        workflow,
        definition=_branch_definition(),
        expected_revision=1,
        change_summary="Add deterministic routing",
        actor_id=None,
    )
    assert validation["valid"] is True
    publish_workflow_version(
        db_session,
        workflow,
        draft,
        expected_workflow_revision=1,
        expected_version_revision=2,
        actor_id=None,
        activate=True,
    )
    assert draft.status == "PUBLISHED"
    with pytest.raises(ValueError, match="immutable"):
        update_workflow_draft(
            draft,
            workflow,
            definition=_branch_definition(),
            expected_revision=2,
            change_summary="Illegal published edit",
            actor_id=None,
        )

    first, first_deduplicated = enqueue_workflow_execution(
        db_session,
        workflow,
        context={
            "entity_type": "ticket",
            "entity_id": "T-1",
            "ticket": {"id": "T-1", "priority": "critical"},
        },
        idempotency_key="ticket-created:T-1",
        source="AUTOMATIC",
        actor_id=None,
    )
    duplicate, duplicate_deduplicated = enqueue_workflow_execution(
        db_session,
        workflow,
        context={
            "entity_type": "ticket",
            "entity_id": "T-1",
            "ticket": {"id": "T-1", "priority": "critical"},
        },
        idempotency_key="ticket-created:T-1",
        source="AUTOMATIC",
        actor_id=None,
    )
    assert first_deduplicated is False
    assert duplicate_deduplicated is True
    assert duplicate.id == first.id

    process_workflow_execution(db_session, first)
    assert first.status == "SUCCEEDED"
    assert first.workflow_version_number == 1
    events = db_session.scalars(
        select(WorkflowExecutionEvent)
        .where(WorkflowExecutionEvent.execution_id == first.id)
        .order_by(WorkflowExecutionEvent.sequence_number)
    ).all()
    assert events
    assert events[0].previous_hash == "0" * 64
    for previous, current in zip(events, events[1:], strict=False):
        assert current.previous_hash == previous.event_hash
    assert verify_workflow_event_chain(db_session, first.id)["valid"] is True
    events[-1].details_json = '{"tampered":true}'
    db_session.flush()
    invalid_chain = verify_workflow_event_chain(db_session, first.id)
    assert invalid_chain["valid"] is False
    assert invalid_chain["first_invalid_sequence"] == events[-1].sequence_number

    persisted = db_session.scalar(
        select(WorkflowVersion).where(WorkflowVersion.id == draft.id)
    )
    assert persisted is not None
    assert persisted.definition_sha256 == draft.definition_sha256


def test_four_eyes_review_and_structural_diff(db_session) -> None:
    tenant = _tenant(db_session)
    author = _user(db_session, tenant, "author")
    reviewer = _user(db_session, tenant, "reviewer")
    workflow, draft = create_workflow(
        db_session,
        tenant_id=tenant.id,
        code="reviewed-routing",
        name="Reviewed routing",
        description=None,
        trigger_type="ticket.created",
        concurrency_policy="ALLOW",
        max_active_executions=10,
        actor_id=author.id,
        publish_approval_required=True,
    )
    update_workflow_draft(
        draft,
        workflow,
        definition=_branch_definition(),
        expected_revision=1,
        change_summary="Ready for independent review",
        actor_id=None,
    )
    with pytest.raises(ValueError, match="approved review"):
        publish_workflow_version(
            db_session,
            workflow,
            draft,
            expected_workflow_revision=1,
            expected_version_revision=2,
            actor_id=None,
            activate=True,
        )
    request_workflow_review(
        draft,
        workflow,
        expected_revision=2,
        actor_id=author.id,
        comment="Please verify routing",
    )
    with pytest.raises(ValueError, match="own review"):
        decide_workflow_review(
            draft,
            workflow,
            expected_revision=3,
            actor_id=author.id,
            decision="APPROVED",
            comment="Self approval attempt",
        )
    decide_workflow_review(
        draft,
        workflow,
        expected_revision=3,
        actor_id=reviewer.id,
        decision="APPROVED",
        comment="Independent review completed",
    )
    publish_workflow_version(
        db_session,
        workflow,
        draft,
        expected_workflow_revision=1,
        expected_version_revision=4,
        actor_id=reviewer.id,
        activate=True,
    )
    next_draft = create_workflow_draft(
        db_session,
        workflow,
        actor_id=None,
        change_summary="Change routing variable",
    )
    changed = _branch_definition()
    changed["nodes"][1]["config"]["value"] = "standard_incident"
    update_workflow_draft(
        next_draft,
        workflow,
        definition=changed,
        expected_revision=1,
        change_summary="Change routing variable",
        actor_id=None,
    )
    diff = compare_workflow_versions(draft, next_draft)
    assert diff["summary"]["changed"] >= 1
    assert any(
        item["path"].endswith("/value") for item in diff["changed"]
    )


def test_reusable_subflow_waits_for_version_bound_child(db_session) -> None:
    tenant = _tenant(db_session)
    child_workflow, child_draft = create_workflow(
        db_session,
        tenant_id=tenant.id,
        code="shared-notification",
        name="Shared notification",
        description=None,
        trigger_type="manual",
        concurrency_policy="ALLOW",
        max_active_executions=10,
        actor_id=None,
    )
    publish_workflow_version(
        db_session,
        child_workflow,
        child_draft,
        expected_workflow_revision=1,
        expected_version_revision=1,
        actor_id=None,
        activate=True,
    )

    parent_workflow, parent_draft = create_workflow(
        db_session,
        tenant_id=tenant.id,
        code="parent-flow",
        name="Parent flow",
        description=None,
        trigger_type="ticket.created",
        concurrency_policy="ALLOW",
        max_active_executions=10,
        actor_id=None,
    )
    parent_definition = {
        "schema_version": "1.0",
        "trigger": {"type": "ticket.created"},
        "entrypoint": "shared",
        "on_failure": "FAIL",
        "nodes": [
            {
                "key": "shared",
                "type": "SUBFLOW",
                "name": "Invoke reusable workflow",
                "config": {
                    "workflow_code": "shared-notification",
                    "context": {"source": "parent"},
                    "max_wait_seconds": 3_600,
                    "failure_policy": "FAIL",
                },
                "next": "end",
            },
            {
                "key": "end",
                "type": "END",
                "name": "Complete",
                "config": {},
            },
        ],
    }
    validation = update_workflow_draft(
        parent_draft,
        parent_workflow,
        definition=parent_definition,
        expected_revision=1,
        change_summary="Invoke shared workflow",
        actor_id=None,
    )
    assert validation["valid"] is True
    publish_workflow_version(
        db_session,
        parent_workflow,
        parent_draft,
        expected_workflow_revision=1,
        expected_version_revision=2,
        actor_id=None,
        activate=True,
    )
    parent, _ = enqueue_workflow_execution(
        db_session,
        parent_workflow,
        context={"entity_type": "ticket", "entity_id": "T-SUBFLOW"},
        idempotency_key="parent:T-SUBFLOW",
        source="AUTOMATIC",
        actor_id=None,
    )
    process_workflow_execution(db_session, parent)
    assert parent.status == "WAITING_SUBFLOW"
    child = db_session.scalar(
        select(WorkflowExecution).where(
            WorkflowExecution.workflow_id == child_workflow.id
        )
    )
    assert child is not None
    assert child.status == "QUEUED"
    process_workflow_execution(db_session, child)
    assert child.status == "SUCCEEDED"
    process_workflow_execution(db_session, parent)
    assert parent.status == "SUCCEEDED"
