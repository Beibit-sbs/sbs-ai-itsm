"""Integration tests for Stage 027: Policy Enforcement & Metrics Monitoring."""
import pytest
import json
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.session import get_db
from app.models import (
    PolicyApprovalRequest,
    PolicyCanaryRollout,
    ConsumerPolicyOverride,
    AuditLog,
)
from app.services.jobs.policy_canary_enforcement import (
    should_consumer_get_policy,
    merge_consumer_override,
    get_effective_policy,
)
from tests.conftest import client, db_session, test_user_email, admin_user_email


@pytest.mark.usefixtures("db_session")
def test_canary_hash_based_consumer_selection(db_session: Session) -> None:
    """Test that hash-based canary selection is deterministic."""
    # Same consumer always selected for same canary percentage
    assert should_consumer_get_policy("consumer-1", 5) == should_consumer_get_policy("consumer-1", 5)
    assert should_consumer_get_policy("consumer-2", 5) == should_consumer_get_policy("consumer-2", 5)
    
    # 100% always includes all consumers
    assert should_consumer_get_policy("any-consumer", 100) is True
    
    # 0% always excludes all consumers
    assert should_consumer_get_policy("any-consumer", 0) is False


@pytest.mark.usefixtures("db_session")
def test_apply_policy_canary_rollout(db_session: Session) -> None:
    """Test applying approved policy to canary percentage of consumers."""
    # Create and approve an approval request first
    approval = PolicyApprovalRequest(
        id="test-apr-canary-001",
        policy_type="autoremediation",
        requested_by_email=test_user_email,
        current_version=1,
        requested_version=2,
        payload_json=json.dumps({"canary_mode": True, "canary_limit_per_cycle": 10}),
        status="approved",
        approved_by_email=admin_user_email,
        canary_percentage=5,
    )
    db_session.add(approval)
    db_session.commit()

    # Apply canary rollout
    response = client.post(
        "/api/v1/jobs/policy/test-apr-canary-001/apply-canary",
        json={
            "approval_request_id": "test-apr-canary-001",
            "canary_percentage": 5,
        },
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "in_progress"
    assert data["current_canary_percentage"] == 5
    assert data["affected_consumers_count"] > 0
    assert data["auto_rollback_triggered"] is False

    # Verify audit log
    audit = db_session.query(AuditLog).filter_by(action="policy.canary.applied").first()
    assert audit is not None
    assert "rollout_id" in audit.metadata


@pytest.mark.usefixtures("db_session")
def test_cannot_apply_canary_to_unapproved_request(db_session: Session) -> None:
    """Test that canary can only be applied to approved requests."""
    approval = PolicyApprovalRequest(
        id="test-apr-pending",
        policy_type="runbook",
        requested_by_email=test_user_email,
        current_version=1,
        requested_version=2,
        payload_json=json.dumps({"allowed_codes": ["INC001"]}),
        status="pending",  # Still pending
        canary_percentage=0,
    )
    db_session.add(approval)
    db_session.commit()

    response = client.post(
        "/api/v1/jobs/policy/test-apr-pending/apply-canary",
        json={
            "approval_request_id": "test-apr-pending",
            "canary_percentage": 5,
        },
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response.status_code == 400
    assert "approved" in response.json()["detail"].lower()


@pytest.mark.usefixtures("db_session")
def test_graduate_canary_rollout(db_session: Session) -> None:
    """Test graduating canary rollout to next percentage."""
    # Create a canary rollout first
    approval = PolicyApprovalRequest(
        id="test-apr-grad-001",
        policy_type="autoremediation",
        requested_by_email=test_user_email,
        current_version=1,
        requested_version=2,
        payload_json=json.dumps({"canary_mode": True}),
        status="approved",
        approved_by_email=admin_user_email,
        canary_percentage=5,
    )
    db_session.add(approval)
    db_session.flush()

    rollout = PolicyCanaryRollout(
        id="test-crl-001",
        approval_request_id="test-apr-grad-001",
        policy_type="autoremediation",
        current_canary_percentage=5,
        affected_consumers_count=10,
        status="in_progress",
    )
    db_session.add(rollout)
    db_session.commit()

    # Graduate to 25%
    response = client.post(
        "/api/v1/jobs/policy/test-crl-001/graduate-canary",
        json={
            "rollout_id": "test-crl-001",
            "new_canary_percentage": 25,
        },
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["current_canary_percentage"] == 25
    assert data["status"] == "in_progress"

    # Verify audit log
    audit = db_session.query(AuditLog).filter_by(action="policy.canary.graduated").first()
    assert audit is not None
    assert audit.metadata.get("new_percentage") == 25


@pytest.mark.usefixtures("db_session")
def test_cannot_graduate_to_lower_percentage(db_session: Session) -> None:
    """Test that canary cannot graduate to lower percentage."""
    rollout = PolicyCanaryRollout(
        id="test-crl-downgrade",
        approval_request_id="test-apr-invalid",
        policy_type="autoremediation",
        current_canary_percentage=25,
        affected_consumers_count=50,
        status="in_progress",
    )
    db_session.add(rollout)
    db_session.commit()

    response = client.post(
        "/api/v1/jobs/policy/test-crl-downgrade/graduate-canary",
        json={
            "rollout_id": "test-crl-downgrade",
            "new_canary_percentage": 5,  # Lower than current 25%
        },
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response.status_code == 400
    assert "must be >" in response.json()["detail"].lower()


@pytest.mark.usefixtures("db_session")
def test_get_canary_rollout_status(db_session: Session) -> None:
    """Test retrieving canary rollout status."""
    rollout = PolicyCanaryRollout(
        id="test-crl-status",
        approval_request_id="test-apr-status",
        policy_type="runbook",
        current_canary_percentage=5,
        affected_consumers_count=10,
        status="in_progress",
        error_rate_baseline=0.5,
        error_rate_current=0.48,
    )
    db_session.add(rollout)
    db_session.commit()

    response = client.get(
        "/api/v1/jobs/policy/test-crl-status/canary-status",
        headers={"Authorization": f"Bearer {test_user_email}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["rollout_id"] == "test-crl-status"
    assert data["current_canary_percentage"] == 5
    assert data["error_rate_baseline"] == 0.5
    assert data["error_rate_current"] == 0.48


@pytest.mark.usefixtures("db_session")
def test_complete_rollout_marks_approval_rolled_out(db_session: Session) -> None:
    """Test completing rollout updates approval request status."""
    approval = PolicyApprovalRequest(
        id="test-apr-complete",
        policy_type="autoremediation",
        requested_by_email=test_user_email,
        current_version=1,
        requested_version=2,
        payload_json=json.dumps({"canary_mode": True}),
        status="approved",
        approved_by_email=admin_user_email,
        canary_percentage=100,
    )
    db_session.add(approval)
    db_session.flush()

    rollout = PolicyCanaryRollout(
        id="test-crl-complete",
        approval_request_id="test-apr-complete",
        policy_type="autoremediation",
        current_canary_percentage=100,
        affected_consumers_count=200,
        status="in_progress",
    )
    db_session.add(rollout)
    db_session.commit()

    # Complete rollout
    response = client.post(
        "/api/v1/jobs/policy/test-crl-complete/complete-rollout",
        json={},
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["current_canary_percentage"] == 100

    # Verify approval request is now rolled_out
    approval = db_session.query(PolicyApprovalRequest).filter_by(id="test-apr-complete").first()
    assert approval.status == "rolled_out"

    # Verify audit log
    audit = db_session.query(AuditLog).filter_by(action="policy.canary.completed").first()
    assert audit is not None


@pytest.mark.usefixtures("db_session")
def test_consumer_override_merges_with_global_policy(db_session: Session) -> None:
    """Test that consumer overrides merge correctly with global policy."""
    global_policy = {
        "canary_mode": True,
        "canary_limit_per_cycle": 10,
        "burst_max_per_10m": 50,
    }

    override = ConsumerPolicyOverride(
        id="ovr-test",
        consumer_name="vip-consumer",
        policy_type="autoremediation",
        policy_version=2,
        overrides_json=json.dumps({
            "canary_mode": False,  # Override: disable canary
            "canary_limit_per_cycle": 100,  # Override: higher limit
        }),
        reason="VIP customer",
        created_by_email=test_user_email,
    )
    db_session.add(override)
    db_session.commit()

    # Get effective policy for VIP consumer
    effective = get_effective_policy(db_session, "vip-consumer", "autoremediation", global_policy)
    
    # Verify overrides applied
    assert effective["canary_mode"] is False  # Overridden
    assert effective["canary_limit_per_cycle"] == 100  # Overridden
    assert effective["burst_max_per_10m"] == 50  # From global (not overridden)


@pytest.mark.usefixtures("db_session")
def test_regular_consumer_gets_global_policy(db_session: Session) -> None:
    """Test that consumers without overrides get pure global policy."""
    global_policy = {
        "canary_mode": True,
        "canary_limit_per_cycle": 10,
    }

    # No override created for this consumer
    effective = get_effective_policy(db_session, "regular-consumer", "autoremediation", global_policy)
    
    # Should match global policy exactly
    assert effective == global_policy
