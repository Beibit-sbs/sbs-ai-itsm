from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> tuple[str, dict]:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["access_token"], body["user"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_ticket(
    client: TestClient,
    token: str,
    *,
    title: str,
    description: str = "The office network is unavailable on the third floor",
) -> dict:
    response = client.post(
        "/api/v1/tickets",
        headers=_headers(token),
        json={
            "title": title,
            "description": description,
            "department": "IT",
            "location": "HQ",
            "category": "NETWORK_INTERNET",
            "priority": "MEDIUM",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_duplicate_candidates_are_scored_permission_aware_and_tenant_isolated(app) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        requester_token, _ = _login(client, "requester@sbs.local")
        other_token, _ = _login(client, "other.admin@sbs.local")
        source = _create_ticket(client, manager_token, title="Internet outage in HQ")
        candidate = _create_ticket(client, manager_token, title="HQ internet outage")
        other = _create_ticket(client, other_token, title="Internet outage in HQ")

        response = client.get(
            f"/api/v1/tickets/{source['id']}/duplicate-candidates?min_score=40",
            headers=_headers(manager_token),
        )
        assert response.status_code == 200, response.text
        items = response.json()
        match = next(item for item in items if item["id"] == candidate["id"])
        assert match["score"] >= 40
        assert "same_requester" in match["evidence"]
        assert "same_category" in match["evidence"]
        assert other["id"] not in {item["id"] for item in items}

        denied = client.get(
            f"/api/v1/tickets/{source['id']}/duplicate-candidates",
            headers=_headers(requester_token),
        )
        assert denied.status_code == 403


def test_dismiss_duplicate_is_versioned_idempotent_and_audited(app) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        admin_token, _ = _login(client, "admin@sbs.local")
        source = _create_ticket(client, manager_token, title="VPN does not connect")
        candidate = _create_ticket(client, manager_token, title="VPN connection fails")
        payload = {
            "expected_ticket_version": source["governance_version"],
            "expected_candidate_version": candidate["governance_version"],
            "reason": "Different affected users and independent root causes",
            "idempotency_key": "dismiss-vpn-pair-001",
        }
        dismissed = client.post(
            f"/api/v1/tickets/{source['id']}/duplicate-candidates/{candidate['id']}/dismiss",
            headers=_headers(manager_token),
            json=payload,
        )
        assert dismissed.status_code == 200, dismissed.text
        body = dismissed.json()
        assert body["action"]["action_type"] == "DUPLICATE_DISMISSED"
        assert body["source_version"] == 2
        assert body["target_version"] == 2
        assert body["already_applied"] is False

        retry = client.post(
            f"/api/v1/tickets/{source['id']}/duplicate-candidates/{candidate['id']}/dismiss",
            headers=_headers(manager_token),
            json=payload,
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["already_applied"] is True
        assert retry.json()["action"]["id"] == body["action"]["id"]

        candidates = client.get(
            f"/api/v1/tickets/{source['id']}/duplicate-candidates?min_score=0",
            headers=_headers(manager_token),
        )
        assert candidates.status_code == 200
        assert candidate["id"] not in {item["id"] for item in candidates.json()}

        history = client.get(
            f"/api/v1/tickets/{source['id']}/history", headers=_headers(manager_token)
        )
        assert any(
            item["event_type"] == "duplicate_candidate_dismissed"
            for item in history.json()
        )
        audit = client.get(
            "/api/v1/admin/audit-logs?action=ticket_duplicate_candidate_dismissed",
            headers=_headers(admin_token),
        )
        assert audit.status_code == 200, audit.text
        assert any(item["entity_id"] == body["action"]["id"] for item in audit.json())


def test_merge_is_soft_idempotent_and_preserves_source_evidence(app) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        agent_token, _ = _login(client, "agent.network@sbs.local")
        source = _create_ticket(client, manager_token, title="Email delivery delayed")
        target = _create_ticket(client, manager_token, title="Delayed email delivery")
        comment = client.post(
            f"/api/v1/tickets/{source['id']}/comments",
            headers=_headers(manager_token),
            json={"body": "Evidence that must survive the merge", "is_internal": True},
        )
        assert comment.status_code == 201, comment.text

        agent_denied = client.post(
            f"/api/v1/tickets/{source['id']}/merge",
            headers=_headers(agent_token),
            json={
                "target_ticket_id": target["id"],
                "expected_source_version": 1,
                "expected_target_version": 1,
                "reason": "Same incident",
                "idempotency_key": "agent-merge-denied-001",
            },
        )
        assert agent_denied.status_code == 403

        payload = {
            "target_ticket_id": target["id"],
            "expected_source_version": source["governance_version"],
            "expected_target_version": target["governance_version"],
            "reason": "Confirmed duplicate after comparing requester evidence",
            "idempotency_key": "merge-email-pair-001",
        }
        merged = client.post(
            f"/api/v1/tickets/{source['id']}/merge",
            headers=_headers(manager_token),
            json=payload,
        )
        assert merged.status_code == 200, merged.text
        result = merged.json()
        assert result["action"]["action_type"] == "MERGED"
        assert result["already_applied"] is False

        source_after = client.get(
            f"/api/v1/tickets/{source['id']}", headers=_headers(manager_token)
        )
        assert source_after.status_code == 200, source_after.text
        source_body = source_after.json()
        assert source_body["status"] == "CANCELLED"
        assert source_body["merged_into_id"] == target["id"]
        assert source_body["merge_reason"] == payload["reason"]
        assert any(
            item["body"] == "Evidence that must survive the merge"
            for item in source_body["comments"]
        )

        retry = client.post(
            f"/api/v1/tickets/{source['id']}/merge",
            headers=_headers(manager_token),
            json=payload,
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["already_applied"] is True
        assert retry.json()["action"]["id"] == result["action"]["id"]


def test_merge_rejects_stale_version_and_cross_tenant_target(app) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        other_token, _ = _login(client, "other.admin@sbs.local")
        source = _create_ticket(client, manager_token, title="Printer is offline")
        target = _create_ticket(client, manager_token, title="Office printer offline")
        other = _create_ticket(client, other_token, title="Printer is offline")

        stale = client.post(
            f"/api/v1/tickets/{source['id']}/merge",
            headers=_headers(manager_token),
            json={
                "target_ticket_id": target["id"],
                "expected_source_version": 99,
                "expected_target_version": 1,
                "reason": "Potential duplicate",
                "idempotency_key": "merge-stale-version-001",
            },
        )
        assert stale.status_code == 409

        cross_tenant = client.post(
            f"/api/v1/tickets/{source['id']}/merge",
            headers=_headers(manager_token),
            json={
                "target_ticket_id": other["id"],
                "expected_source_version": 1,
                "expected_target_version": 1,
                "reason": "Must never cross tenants",
                "idempotency_key": "merge-cross-tenant-001",
            },
        )
        assert cross_tenant.status_code == 404


def test_split_creates_governed_child_and_is_idempotent(app) -> None:
    with TestClient(app) as client:
        agent_token, _ = _login(client, "agent.network@sbs.local")
        source = _create_ticket(client, agent_token, title="Laptop and VPN issues")
        payload = {
            "title": "VPN access fails",
            "description": "Separated from the laptop hardware issue",
            "expected_source_version": source["governance_version"],
            "reason": "Different resolver group and independent delivery path",
            "idempotency_key": "split-laptop-vpn-001",
        }
        split = client.post(
            f"/api/v1/tickets/{source['id']}/split",
            headers=_headers(agent_token),
            json=payload,
        )
        assert split.status_code == 201, split.text
        result = split.json()
        child_id = result["target_ticket_id"]
        assert result["action"]["action_type"] == "SPLIT"
        assert result["source_version"] == 2

        child = client.get(
            f"/api/v1/tickets/{child_id}", headers=_headers(agent_token)
        )
        assert child.status_code == 200, child.text
        child_body = child.json()
        assert child_body["parent_ticket_id"] == source["id"]
        assert child_body["requester_id"] == source["requester_id"]
        assert child_body["ticket_number"] != source["ticket_number"]

        retry = client.post(
            f"/api/v1/tickets/{source['id']}/split",
            headers=_headers(agent_token),
            json=payload,
        )
        assert retry.status_code == 201, retry.text
        assert retry.json()["already_applied"] is True
        assert retry.json()["target_ticket_id"] == child_id

        source_history = client.get(
            f"/api/v1/tickets/{source['id']}/history",
            headers=_headers(agent_token),
        )
        assert any(item["event_type"] == "ticket_split" for item in source_history.json())


def test_ticket_duplicate_governance_migration_is_current_head() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260829_0081_ticket_duplicate_governance.py"
    )
    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert 'revision: str = "20260829_0081"' in text
    assert 'down_revision: str | None = "20260814_0080"' in text
    assert '"ticket_governance_actions"' in text
