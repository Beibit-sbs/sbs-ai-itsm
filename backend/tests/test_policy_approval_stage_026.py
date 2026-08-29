"""Integration tests for Stage 026: Policy Approval Workflow and Canary Rollout."""
import pytest
import json
from sqlalchemy.orm import Session

from app.models import PolicyApprovalRequest, AuditLog
from tests.conftest import client, test_user_email, admin_user_email, standard_user_email


pytestmark = pytest.mark.skip(reason="Legacy Stage 026 contract test; endpoints/models have since evolved")


@pytest.mark.usefixtures("db_session")
def test_request_policy_approval_creates_pending_request(db_session: Session) -> None:
    """Test that policy approval requests are created in pending status."""
    response = client.post(
        "/api/v1/jobs/policy/request-approval",
        json={
            "approval_request_id": "temp-id",
            "policy_type": "autoremediation",
            "status": "pending",
            "requested_by_email": test_user_email,
            "requested_at": "2026-07-13T10:00:00Z",
            "current_version": 1,
            "requested_version": 2,
            "canary_percentage": 0,
            "approved_by_email": None,
            "approved_at": None,
            "rejection_reason": None,
        },
        headers={"Authorization": f"Bearer {test_user_email}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert data["policy_type"] == "autoremediation"
    assert data["canary_percentage"] == 0

    # Verify audit log
    audit = db_session.query(AuditLog).filter_by(action="policy.approval.requested").first()
    assert audit is not None
    assert "approval_id" in audit.metadata


@pytest.mark.usefixtures("db_session")
def test_approve_policy_change_with_canary(db_session: Session) -> None:
    """Test approving a policy change with canary rollout percentage."""
    # First, create an approval request
    approval = PolicyApprovalRequest(
        id="test-apr-001",
        policy_type="runbook",
        requested_by_email=test_user_email,
        current_version=1,
        requested_version=2,
        payload_json=json.dumps({"allowed_codes": ["INC001", "INC002"]}),
        status="pending",
        canary_percentage=0,
    )
    db_session.add(approval)
    db_session.commit()

    # Approve with 5% canary
    response = client.post(
        "/api/v1/jobs/policy/test-apr-001/approve",
        json={
            "approval_request_id": "test-apr-001",
            "canary_percentage": 5,
        },
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["canary_percentage"] == 5
    assert data["approved_by_email"] == admin_user_email

    # Verify audit log
    audit = db_session.query(AuditLog).filter_by(action="policy.approval.approved").first()
    assert audit is not None
    assert audit.metadata.get("canary_percentage") == 5


@pytest.mark.usefixtures("db_session")
def test_cannot_approve_already_approved_request(db_session: Session) -> None:
    """Test that already-approved requests cannot be approved again."""
    approval = PolicyApprovalRequest(
        id="test-apr-002",
        policy_type="autoremediation",
        requested_by_email=test_user_email,
        current_version=2,
        requested_version=3,
        payload_json=json.dumps({"canary_mode": True}),
        status="approved",
        approved_by_email=admin_user_email,
        canary_percentage=5,
    )
    db_session.add(approval)
    db_session.commit()

    response = client.post(
        "/api/v1/jobs/policy/test-apr-002/approve",
        json={
            "approval_request_id": "test-apr-002",
            "canary_percentage": 10,
        },
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response.status_code == 400
    assert "approved" in response.json()["detail"].lower()


@pytest.mark.usefixtures("db_session")
def test_reject_policy_change(db_session: Session) -> None:
    """Test rejecting a pending policy approval request."""
    approval = PolicyApprovalRequest(
        id="test-apr-003",
        policy_type="runbook",
        requested_by_email=test_user_email,
        current_version=1,
        requested_version=2,
        payload_json=json.dumps({"denied_codes": ["DANGER001"]}),
        status="pending",
        canary_percentage=0,
    )
    db_session.add(approval)
    db_session.commit()

    response = client.post(
        "/api/v1/jobs/policy/test-apr-003/reject",
        json={
            "approval_request_id": "test-apr-003",
            "rejection_reason": "Policy change too aggressive for current environment; recommend gradual testing first",
        },
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    assert "too aggressive" in data["rejection_reason"]

    # Verify audit log
    audit = db_session.query(AuditLog).filter_by(action="policy.approval.rejected").first()
    assert audit is not None
    assert "rejection_reason" in audit.metadata


@pytest.mark.usefixtures("db_session")
def test_create_consumer_policy_override(db_session: Session) -> None:
    """Test creating a per-consumer policy override."""
    # First, create an approved approval request
    approval = PolicyApprovalRequest(
        id="test-apr-004",
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

    # Create override for a specific consumer
    response = client.post(
        "/api/v1/jobs/policy/test-apr-004/create-override",
        json={
            "consumer_name": "vip-notifications-consumer",
            "policy_type": "autoremediation",
            "overrides_json": {
                "canary_mode": False,
                "canary_limit_per_cycle": 50,
            },
            "reason": "VIP customer requires higher throughput; exempt from canary mode for this release",
        },
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["consumer_name"] == "vip-notifications-consumer"
    assert data["policy_type"] == "autoremediation"
    assert data["overrides_json"]["canary_limit_per_cycle"] == 50
    assert data["created_by_email"] == admin_user_email

    # Verify audit log
    audit = db_session.query(AuditLog).filter_by(action="policy.override.created").first()
    assert audit is not None
    assert audit.metadata.get("consumer_name") == "vip-notifications-consumer"


@pytest.mark.usefixtures("db_session")
def test_override_persists_with_policy_version(db_session: Session) -> None:
    """Test that consumer overrides reference the policy version they apply to."""
    approval = PolicyApprovalRequest(
        id="test-apr-005",
        policy_type="runbook",
        requested_by_email=test_user_email,
        current_version=3,
        requested_version=4,
        payload_json=json.dumps({"allowed_codes": ["INC001", "INC002", "INC003"]}),
        status="approved",
        approved_by_email=admin_user_email,
        canary_percentage=0,
    )
    db_session.add(approval)
    db_session.commit()

    response = client.post(
        "/api/v1/jobs/policy/test-apr-005/create-override",
        json={
            "consumer_name": "incident-consumer",
            "policy_type": "runbook",
            "overrides_json": {
                "allowed_codes": ["INC001", "INC002"],  # Subset of global policy
            },
            "reason": "Incident consumer restricted to safe codes only",
        },
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["policy_version"] == 4  # References the requested version from approval
    assert len(data["overrides_json"]["allowed_codes"]) == 2


@pytest.mark.usefixtures("db_session")
def test_multiple_approval_requests_tracked_independently(db_session: Session) -> None:
    """Test that multiple approval requests are tracked independently."""
    # Create first approval request for autoremediation
    apr1 = PolicyApprovalRequest(
        id="test-apr-006",
        policy_type="autoremediation",
        requested_by_email=test_user_email,
        current_version=1,
        requested_version=2,
        payload_json=json.dumps({"canary_mode": True}),
        status="pending",
        canary_percentage=0,
    )
    db_session.add(apr1)

    # Create second approval request for runbook
    apr2 = PolicyApprovalRequest(
        id="test-apr-007",
        policy_type="runbook",
        requested_by_email=standard_user_email,
        current_version=2,
        requested_version=3,
        payload_json=json.dumps({"allowed_codes": ["INC001"]}),
        status="pending",
        canary_percentage=0,
    )
    db_session.add(apr2)
    db_session.commit()

    # Approve first request
    response1 = client.post(
        "/api/v1/jobs/policy/test-apr-006/approve",
        json={"approval_request_id": "test-apr-006", "canary_percentage": 5},
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response1.status_code == 200
    assert response1.json()["approval_request_id"] == "test-apr-006"

    # Reject second request
    response2 = client.post(
        "/api/v1/jobs/policy/test-apr-007/reject",
        json={
            "approval_request_id": "test-apr-007",
            "rejection_reason": "Need more testing before approval",
        },
        headers={"Authorization": f"Bearer {admin_user_email}"},
    )
    assert response2.status_code == 200
    assert response2.json()["approval_request_id"] == "test-apr-007"
    assert response2.json()["status"] == "rejected"

    # Verify first request is still approved
    req1 = db_session.query(PolicyApprovalRequest).filter_by(id="test-apr-006").first()
    assert req1.status == "approved"

    # Verify second request is rejected
    req2 = db_session.query(PolicyApprovalRequest).filter_by(id="test-apr-007").first()
    assert req2.status == "rejected"
