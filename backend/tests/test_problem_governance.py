from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sbs!2026"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _problem(client: TestClient, token: str) -> dict:
    response = client.post(
        "/api/v1/problems",
        headers=_headers(token),
        json={
            "title": "Recurring payment configuration failures",
            "description": "Repeated incidents require governed root cause analysis.",
            "problem_type": "REACTIVE",
            "service_name": "Payments",
            "category": "Application",
            "impact_level": "HIGH",
            "urgency_level": "HIGH",
            "detection_source": "TREND_ANALYTICS",
            "symptoms": "Payment API becomes unavailable after configuration rollout.",
        },
    )
    assert response.status_code == 201, response.text
    problem = response.json()
    started = client.post(
        f"/api/v1/problems/{problem['id']}/transitions",
        headers=_headers(token),
        json={
            "expected_version": problem["version"],
            "action": "START_INVESTIGATION",
        },
    )
    assert started.status_code == 200, started.text
    return started.json()


def test_structured_rca_and_independent_effectiveness_gate(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        admin = _login(client, "admin@sbs.local")
        problem = _problem(client, manager)
        saved = client.put(
            f"/api/v1/problem-governance/problems/{problem['id']}/rca",
            headers=_headers(manager),
            json={
                "method": "FIVE_WHYS",
                "problem_statement": "Configuration rollout repeatedly disrupts payments.",
                "five_whys": [
                    {"why": f"Why {index}?", "answer": f"Governed cause {index}."}
                    for index in range(1, 6)
                ],
                "ishikawa": {},
                "fault_tree": {},
                "contributing_factors": [{"factor": "Missing deployment control"}],
                "evidence": [{"type": "INCIDENT", "reference": "cluster"}],
                "conclusion": "A mandatory configuration validation gate was absent.",
            },
        )
        assert saved.status_code == 200, saved.text
        rca = saved.json()
        submitted = client.post(
            f"/api/v1/problem-governance/problems/{problem['id']}/rca/submit",
            headers=_headers(manager),
            json={"expected_version": rca["version"]},
        )
        assert submitted.status_code == 200, submitted.text
        rca = submitted.json()
        self_approval = client.post(
            f"/api/v1/problem-governance/problems/{problem['id']}/rca/decision",
            headers=_headers(manager),
            json={
                "expected_version": rca["version"],
                "decision": "APPROVED",
                "comment": "Self approval must not be accepted.",
            },
        )
        assert self_approval.status_code == 409
        approved = client.post(
            f"/api/v1/problem-governance/problems/{problem['id']}/rca/decision",
            headers=_headers(admin),
            json={
                "expected_version": rca["version"],
                "decision": "APPROVED",
                "comment": "Independent reviewer accepted evidence and conclusion.",
            },
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "APPROVED"

        created = client.post(
            f"/api/v1/problem-governance/problems/{problem['id']}/actions",
            headers=_headers(manager),
            json={
                "action_type": "CORRECTIVE",
                "title": "Add configuration validation gate",
                "description": "Block promotion when configuration validation fails.",
                "is_required": True,
                "due_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                "effectiveness_criteria": "No recurrence during a 30-day review period.",
            },
        )
        assert created.status_code == 201, created.text
        action = created.json()
        for target in ("IN_PROGRESS", "IMPLEMENTED"):
            updated = client.patch(
                (
                    f"/api/v1/problem-governance/problems/{problem['id']}/"
                    f"actions/{action['id']}"
                ),
                headers=_headers(manager),
                json={
                    "expected_version": action["version"],
                    "status": target,
                    "implementation_evidence": (
                        "Pipeline logs and signed change evidence."
                        if target == "IMPLEMENTED"
                        else None
                    ),
                },
            )
            assert updated.status_code == 200, updated.text
            action = updated.json()
        self_review = client.patch(
            (
                f"/api/v1/problem-governance/problems/{problem['id']}/"
                f"actions/{action['id']}"
            ),
            headers=_headers(manager),
            json={
                "expected_version": action["version"],
                "status": "VERIFIED",
                "effectiveness_score": 95,
                "effectiveness_evidence": "No recurrence during observation.",
            },
        )
        assert self_review.status_code == 409
        reviewed = client.patch(
            (
                f"/api/v1/problem-governance/problems/{problem['id']}/"
                f"actions/{action['id']}"
            ),
            headers=_headers(admin),
            json={
                "expected_version": action["version"],
                "status": "VERIFIED",
                "effectiveness_score": 95,
                "effectiveness_evidence": "Independent 30-day review found no recurrence.",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["status"] == "VERIFIED"


def test_trend_scan_and_problem_governance_tenant_isolation(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        other_admin = _login(client, "other.admin@sbs.local")
        problem = _problem(client, manager)
        scanned = client.post(
            "/api/v1/problem-governance/trends/scan",
            headers=_headers(manager),
        )
        assert scanned.status_code == 200, scanned.text
        assert "signals_created_or_refreshed" in scanned.json()
        hidden = client.get(
            f"/api/v1/problem-governance/problems/{problem['id']}/rca",
            headers=_headers(other_admin),
        )
        assert hidden.status_code == 404
