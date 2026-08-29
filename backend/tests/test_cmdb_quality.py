from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sbs!2026"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["access_token"], body["user"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _class(client: TestClient, token: str, code: str) -> dict:
    response = client.get("/api/v1/cmdb/classes", headers=_headers(token))
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["code"] == code)


def _create_ci(client: TestClient, token: str, ci_class: dict) -> dict:
    response = client.post(
        "/api/v1/cmdb/items",
        headers=_headers(token),
        json={
            "ci_class_id": ci_class["id"],
            "asset_tag": "CI-QUALITY-001",
            "name": "Quality governance test cluster",
            "criticality": "CRITICAL",
            "environment": "PRODUCTION",
            "location": "Location unknown",
            "attributes": {"hostname": "ci-quality-001"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _scan(client: TestClient, token: str) -> dict:
    response = client.post(
        "/api/v1/cmdb/quality/scan",
        headers=_headers(token),
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_quality_scan_remediation_certification_and_tenant_isolation(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = _login(client, "manager@sbs.local")
        other_token, _ = _login(client, "other.admin@sbs.local")
        ci = _create_ci(
            client,
            manager_token,
            _class(client, manager_token, "INFRASTRUCTURE"),
        )

        first = _scan(client, manager_token)
        assert first["integrity_valid"] is True
        assert 0 <= first["overall_score"] <= 100
        assert first["ci_count"] >= 1
        assert first["open_finding_count"] >= 3
        assert first["result"]["affected"]["completeness"] >= 1
        assert first["result"]["affected"]["orphan"] >= 1

        findings_response = client.get(
            "/api/v1/cmdb/quality/findings?finding_status=OPEN",
            headers=_headers(manager_token),
        )
        assert findings_response.status_code == 200, findings_response.text
        findings = findings_response.json()
        support_finding = next(
            item
            for item in findings
            if item["asset_id"] == ci["id"]
            and item["rule_code"] == "MISSING_SUPPORT_GROUP"
        )
        assert support_finding["severity"] == "CRITICAL"
        assert support_finding["overdue"] is False

        assigned_response = client.patch(
            f"/api/v1/cmdb/quality/findings/{support_finding['id']}",
            headers=_headers(manager_token),
            json={
                "expected_version": support_finding["version"],
                "owner_user_id": manager["id"],
                "finding_status": "IN_PROGRESS",
            },
        )
        assert assigned_response.status_code == 200, assigned_response.text
        assigned = assigned_response.json()
        assert assigned["owner_user_id"] == manager["id"]
        assert assigned["status"] == "IN_PROGRESS"

        updated_ci_response = client.patch(
            f"/api/v1/cmdb/items/{ci['id']}",
            headers=_headers(manager_token),
            json={
                "expected_version": ci["version"],
                "support_group": "Platform Operations",
                "comment": "Assigned accountable operational support group",
            },
        )
        assert updated_ci_response.status_code == 200, updated_ci_response.text
        updated_ci = updated_ci_response.json()

        second = _scan(client, manager_token)
        assert second["resolved_finding_count"] >= 1
        resolved_response = client.get(
            "/api/v1/cmdb/quality/findings"
            "?finding_status=RESOLVED&dimension=COMPLETENESS",
            headers=_headers(manager_token),
        )
        assert resolved_response.status_code == 200, resolved_response.text
        resolved = next(
            item
            for item in resolved_response.json()
            if item["id"] == support_finding["id"]
        )
        assert resolved["status"] == "RESOLVED"
        assert "Automatically resolved" in resolved["resolution_note"]

        summary_response = client.get(
            "/api/v1/cmdb/quality/summary",
            headers=_headers(manager_token),
        )
        assert summary_response.status_code == 200, summary_response.text
        summary = summary_response.json()
        assert summary["latest"]["id"] == second["id"]
        assert len(summary["trend"]) == 2

        due_at = datetime.now(UTC) + timedelta(days=14)
        campaign_response = client.post(
            "/api/v1/cmdb/quality/campaigns",
            headers=_headers(manager_token),
            json={
                "name": "Critical production CI certification",
                "description": "Quarterly owner certification evidence.",
                "due_at": due_at.isoformat(),
                "scope": {
                    "asset_ids": [ci["id"]],
                    "default_certifier_user_id": manager["id"],
                },
            },
        )
        assert campaign_response.status_code == 201, campaign_response.text
        campaign = campaign_response.json()
        assert campaign["status"] == "DRAFT"

        activated_response = client.post(
            f"/api/v1/cmdb/quality/campaigns/{campaign['id']}/activate",
            headers=_headers(manager_token),
            json={"expected_version": campaign["version"]},
        )
        assert activated_response.status_code == 200, activated_response.text
        activated = activated_response.json()
        assert activated["status"] == "ACTIVE"
        assert activated["total_items"] == 1
        item = activated["items"][0]
        assert item["asset_version"] == updated_ci["version"]
        assert item["asset_changed"] is False
        assert item["integrity_valid"] is True

        decision_response = client.post(
            f"/api/v1/cmdb/quality/campaigns/{campaign['id']}"
            f"/items/{item['id']}/decision",
            headers=_headers(manager_token),
            json={
                "expected_version": item["version"],
                "decision": "CERTIFIED",
                "note": "Owner, dependency scope, and support data confirmed.",
            },
        )
        assert decision_response.status_code == 200, decision_response.text
        decided = decision_response.json()
        assert decided["certified_items"] == 1
        assert decided["progress_percent"] == 100

        completed_response = client.post(
            f"/api/v1/cmdb/quality/campaigns/{campaign['id']}/complete",
            headers=_headers(manager_token),
            json={"expected_version": activated["version"]},
        )
        assert completed_response.status_code == 200, completed_response.text
        assert completed_response.json()["status"] == "COMPLETED"

        stale_decision_campaign = client.post(
            "/api/v1/cmdb/quality/campaigns",
            headers=_headers(manager_token),
            json={
                "name": "Stale snapshot protection",
                "due_at": due_at.isoformat(),
                "scope": {"asset_ids": [ci["id"]]},
            },
        ).json()
        stale_activated = client.post(
            f"/api/v1/cmdb/quality/campaigns/"
            f"{stale_decision_campaign['id']}/activate",
            headers=_headers(manager_token),
            json={"expected_version": stale_decision_campaign["version"]},
        ).json()
        current_ci = client.patch(
            f"/api/v1/cmdb/items/{ci['id']}",
            headers=_headers(manager_token),
            json={
                "expected_version": updated_ci["version"],
                "support_group": "SRE Platform Operations",
                "comment": "Changed after certification campaign activation",
            },
        )
        assert current_ci.status_code == 200, current_ci.text
        stale_item = stale_activated["items"][0]
        stale_decision = client.post(
            f"/api/v1/cmdb/quality/campaigns/"
            f"{stale_decision_campaign['id']}/items/"
            f"{stale_item['id']}/decision",
            headers=_headers(manager_token),
            json={
                "expected_version": stale_item["version"],
                "decision": "CERTIFIED",
                "note": "Attempt to certify an obsolete CI snapshot.",
            },
        )
        assert stale_decision.status_code == 409
        assert "changed after campaign activation" in stale_decision.text

        hidden_findings = client.get(
            "/api/v1/cmdb/quality/findings?finding_status=ALL",
            headers=_headers(other_token),
        )
        assert hidden_findings.status_code == 200
        assert all(
            item["tenant_id"] != first["tenant_id"]
            for item in hidden_findings.json()
        )
        hidden_campaign = client.get(
            f"/api/v1/cmdb/quality/campaigns/{campaign['id']}",
            headers=_headers(other_token),
        )
        assert hidden_campaign.status_code == 404
