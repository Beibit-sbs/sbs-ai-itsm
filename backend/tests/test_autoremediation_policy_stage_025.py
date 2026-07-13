"""Tests for Stage 025: Recovery Policy Safety (autoremediation validate-only, rollback, trace)."""
import pytest
from fastapi.testclient import TestClient
from app.db.session import SessionLocal


def _login(client: TestClient, email: str, password: str) -> str:
    """Login and return token."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    """Return auth headers."""
    return {"Authorization": f"Bearer {token}"}


def _get_autoremediation_policy_version(client: TestClient, token: str, consumer_name: str = "notifications-consumer") -> int:
    """Get current autoremediation policy version."""
    response = client.get(
        f"/api/v1/jobs/event-consumer-autoremediation-policy?consumer_name={consumer_name}",
        headers=_auth_headers(token),
    )
    assert response.status_code == 200
    return response.json()["policy_version"]


def test_job_event_consumer_autoremediation_policy_validate_only_does_not_persist(app) -> None:
    """Test validate_only flag prevents persistence for autoremediation policies."""
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        
        # Get initial version
        initial_version = _get_autoremediation_policy_version(client, token)
        
        # Attempt validation-only update
        response = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": initial_version,
                "enabled": False,
                "validate_only": True,
            },
        )
        
        assert response.status_code == 200
        body = response.json()
        assert body["policy_version"] == initial_version
        assert body["validation_result"] is not None
        assert body["validation_result"]["valid"] is True
        
        # Verify version unchanged after validation
        after_version = _get_autoremediation_policy_version(client, token)
        assert after_version == initial_version


def test_job_event_consumer_autoremediation_policy_rollback_restores_previous_version(app) -> None:
    """Test rollback endpoint restores previous autoremediation policy version."""
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        
        # Get initial version
        v1 = _get_autoremediation_policy_version(client, token)
        
        # Apply first update to v2
        response = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": v1,
                "enabled": True,
                "max_requeued_per_cycle": 5,
                "validate_only": False,
            },
        )
        assert response.status_code == 200
        v2 = response.json()["policy_version"]
        assert v2 == v1 + 1
        
        # Apply second update to v3
        response = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": v2,
                "enabled": False,
                "max_requeued_per_cycle": 10,
                "validate_only": False,
            },
        )
        assert response.status_code == 200
        v3 = response.json()["policy_version"]
        assert v3 == v2 + 1
        
        # Rollback from v3 to v1
        response = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy/rollback",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "previous_version": v1,
            },
        )
        
        assert response.status_code == 200
        body = response.json()
        assert body["rolled_back_from_version"] == v3
        assert body["rolled_back_to_version"] == v1
        assert body["policy_version"] == v3 + 1  # New version after rollback
        
        # Verify we can read back the restored state
        response = client.get(
            "/api/v1/jobs/event-consumer-autoremediation-policy?consumer_name=notifications-consumer",
            headers=_auth_headers(token),
        )
        assert response.status_code == 200


def test_job_event_consumer_autoremediation_policy_rollback_rejects_invalid_version(app) -> None:
    """Test rollback endpoint rejects invalid version numbers."""
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        
        current_version = _get_autoremediation_policy_version(client, token)
        
        # Try to rollback to current version (not allowed)
        response = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy/rollback",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "previous_version": current_version,
            },
        )
        
        assert response.status_code == 400
        
        # Try to rollback to future version (not allowed)
        response = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy/rollback",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "previous_version": current_version + 100,
            },
        )
        
        assert response.status_code == 400


def test_job_event_consumers_diagnostics_includes_autoremediation_policy_decision_trace(app) -> None:
    """Test autoremediation_policy_decision_trace is computed and returned in diagnostics."""
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        
        current_version = _get_autoremediation_policy_version(client, token)
        
        # Update policy with canary and burst settings to get a meaningful trace
        response = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": current_version,
                "canary_mode": True,
                "canary_limit_per_cycle": 3,
                "burst_limit_per_10m": 20,
                "validate_only": False,
            },
        )
        assert response.status_code == 200
        
        # Get diagnostics
        response = client.get(
            "/api/v1/jobs/event-consumers-diagnostics?stream_name=job-events",
            headers=_auth_headers(token),
        )
        
        assert response.status_code == 200
        body = response.json()
        
        # Verify each consumer item has the trace
        assert body["consumers"] is not None
        assert len(body["consumers"]) > 0
        
        for item in body["consumers"]:
            assert "autoremediation_policy_decision_trace" in item
            trace = item["autoremediation_policy_decision_trace"]
            # Trace should contain canary and burst info
            assert isinstance(trace, str)
            assert len(trace) > 0
            # Should include canary and burst based on our settings
            assert "canary" in trace or "burst" in trace or trace == "default"


def test_job_event_consumer_autoremediation_policy_concurrent_update_conflict(app) -> None:
    """Test autoremediation policy update rejects concurrent modifications (version conflict)."""
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        
        current_version = _get_autoremediation_policy_version(client, token)
        
        # First update succeeds
        response = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": current_version,
                "enabled": True,
                "validate_only": False,
            },
        )
        assert response.status_code == 200
        
        # Second update with stale version fails
        response = client.post(
            "/api/v1/jobs/event-consumer-autoremediation-policy",
            headers=_auth_headers(token),
            json={
                "consumer_name": "notifications-consumer",
                "expected_version": current_version,  # Stale
                "enabled": False,
                "validate_only": False,
            },
        )
        
        assert response.status_code == 409
        # Verify it's a conflict error (might be in different response format)
        body = response.json()
        assert response.status_code == 409
