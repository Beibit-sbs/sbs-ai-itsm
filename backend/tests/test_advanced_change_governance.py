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


def _create_change(
    client: TestClient,
    token: str,
    *,
    title: str,
    change_type: str = "NORMAL",
    outage_required: bool = False,
) -> dict:
    response = client.post(
        "/api/v1/changes",
        headers=_headers(token),
        json={
            "title": title,
            "description": "Controlled production change with governed evidence.",
            "change_type": change_type,
            "service_name": "Payments",
            "environment": "PRODUCTION",
            "impact_level": "HIGH" if outage_required else "MEDIUM",
            "likelihood": 2,
            "business_justification": "Remove a known availability risk.",
            "implementation_plan": "Validate health, deploy, and monitor.",
            "test_plan": "Run synthetic business transactions.",
            "rollback_plan": "Restore the previous signed release.",
            "validation_plan": "Confirm SLO and owner acceptance.",
            "outage_required": outage_required,
            "outage_minutes": 30 if outage_required else 0,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _transition(
    client: TestClient,
    token: str,
    change: dict,
    action: str,
    **extra,
) -> dict:
    response = client.post(
        f"/api/v1/changes/{change['id']}/transitions",
        headers=_headers(token),
        json={"action": action, "expected_version": change["version"], **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approve(
    client: TestClient,
    token: str,
    change: dict,
) -> dict:
    response = client.post(
        f"/api/v1/changes/{change['id']}/decisions",
        headers=_headers(token),
        json={
            "decision": "APPROVED",
            "comment": "CAB accepted the risk and rollback evidence.",
            "expected_version": change["version"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approved_change(
    client: TestClient,
    manager: str,
    admin: str,
    *,
    title: str,
    change_type: str = "NORMAL",
    outage_required: bool = False,
) -> dict:
    change = _create_change(
        client,
        manager,
        title=title,
        change_type=change_type,
        outage_required=outage_required,
    )
    change = _transition(client, manager, change, "SUBMIT")
    change = _transition(client, manager, change, "REQUEST_APPROVAL")
    return _approve(client, admin, change)


def test_blackout_blocks_normal_and_emergency_override_is_audited(app) -> None:
    with TestClient(app) as client:
        manager, manager_user = _login(client, "manager@sbs.local")
        admin, _ = _login(client, "admin@sbs.local")
        start = datetime.now(UTC) + timedelta(days=3)
        end = start + timedelta(hours=4)

        window = client.post(
            "/api/v1/change-governance/windows",
            headers=_headers(admin),
            json={
                "name": "Quarter close freeze",
                "window_type": "BLACKOUT",
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
                "timezone": "UTC",
                "services": ["Payments"],
                "environments": ["PRODUCTION"],
                "asset_ids": [],
                "is_active": True,
            },
        )
        assert window.status_code == 201, window.text

        normal = _approved_change(
            client,
            manager,
            admin,
            title="Normal change inside freeze",
        )
        blocked = client.post(
            f"/api/v1/changes/{normal['id']}/transitions",
            headers=_headers(manager),
            json={
                "action": "SCHEDULE",
                "expected_version": normal["version"],
                "planned_start_at": (start + timedelta(minutes=30)).isoformat(),
                "planned_end_at": (start + timedelta(hours=1)).isoformat(),
            },
        )
        assert blocked.status_code == 409
        assert (
            blocked.json()["error"]["message"]
            == "Implementation window intersects an active blackout"
        )

        emergency = _approved_change(
            client,
            manager,
            admin,
            title="Emergency security remediation",
            change_type="EMERGENCY",
        )
        emergency = _transition(
            client,
            manager,
            emergency,
            "SCHEDULE",
            planned_start_at=(start + timedelta(hours=1)).isoformat(),
            planned_end_at=(start + timedelta(hours=2)).isoformat(),
            blackout_override_reason=(
                "Actively exploited vulnerability requires ECAB exception."
            ),
        )
        assert emergency["status"] == "SCHEDULED"
        assert emergency["blackout_override_reason"]
        assessment = client.get(
            f"/api/v1/change-governance/changes/{emergency['id']}/readiness",
            headers=_headers(manager),
        )
        assert assessment.status_code == 200
        assert assessment.json()["checks"]
        assert manager_user["tenant_id"] == emergency["tenant_id"]


def test_standard_model_tasks_validation_and_reliability(app) -> None:
    with TestClient(app) as client:
        manager, _ = _login(client, "manager@sbs.local")
        admin, _ = _login(client, "admin@sbs.local")
        now = datetime.now(UTC)
        model_response = client.post(
            "/api/v1/change-governance/standard-models",
            headers=_headers(admin),
            json={
                "code": "STD-APP-RESTART",
                "name": "Application restart",
                "description": "Preauthorized safe application restart model.",
                "service_name": "Payments",
                "environment": "PRODUCTION",
                "default_duration_minutes": 30,
                "implementation_plan": "Drain, restart, and restore traffic.",
                "test_plan": "Run business transaction before change.",
                "rollback_plan": "Restore the previous healthy instance.",
                "validation_plan": "Validate SLO and transaction success.",
                "task_templates": [
                    {
                        "type": "IMPLEMENTATION",
                        "title": "Restart application safely",
                        "required": True,
                    },
                    {
                        "type": "VALIDATION",
                        "title": "Validate business transaction",
                        "required": True,
                    },
                ],
                "scope": {"maximum_assets": 1},
                "review_due_at": (now + timedelta(days=30)).isoformat(),
                "preauthorized_until": (now + timedelta(days=365)).isoformat(),
                "is_active": True,
            },
        )
        assert model_response.status_code == 201, model_response.text
        model = model_response.json()

        created = client.post(
            f"/api/v1/change-governance/standard-models/{model['id']}/instantiate",
            headers=_headers(manager),
            json={"planned_start_at": (now + timedelta(days=2)).isoformat()},
        )
        assert created.status_code == 201, created.text
        change = created.json()
        assert change["standard_model_id"] == model["id"]
        change = _transition(client, manager, change, "SUBMIT")
        change = _transition(client, manager, change, "REQUEST_APPROVAL")
        change = _transition(client, manager, change, "SCHEDULE")
        change = _transition(client, manager, change, "START")

        premature = client.post(
            f"/api/v1/changes/{change['id']}/transitions",
            headers=_headers(manager),
            json={
                "action": "COMPLETE",
                "expected_version": change["version"],
            },
        )
        assert premature.status_code == 422

        tasks_response = client.get(
            f"/api/v1/change-governance/changes/{change['id']}/tasks",
            headers=_headers(manager),
        )
        assert tasks_response.status_code == 200
        tasks = tasks_response.json()
        implementation = next(
            item for item in tasks if item["task_type"] == "IMPLEMENTATION"
        )
        completed_task = client.patch(
            (
                f"/api/v1/change-governance/changes/{change['id']}"
                f"/tasks/{implementation['id']}"
            ),
            headers=_headers(manager),
            json={
                "expected_version": implementation["version"],
                "status": "COMPLETED",
                "evidence": "Restart log and health check attached.",
            },
        )
        assert completed_task.status_code == 200, completed_task.text
        change = client.get(
            f"/api/v1/changes/{change['id']}",
            headers=_headers(manager),
        ).json()
        change = _transition(client, manager, change, "COMPLETE")

        validation = next(
            item for item in tasks if item["task_type"] == "VALIDATION"
        )
        completed_validation = client.patch(
            (
                f"/api/v1/change-governance/changes/{change['id']}"
                f"/tasks/{validation['id']}"
            ),
            headers=_headers(manager),
            json={
                "expected_version": validation["version"],
                "status": "COMPLETED",
                "evidence": "Synthetic payment succeeded and SLO is healthy.",
            },
        )
        assert completed_validation.status_code == 200
        change = client.get(
            f"/api/v1/changes/{change['id']}",
            headers=_headers(manager),
        ).json()
        change = _transition(
            client,
            manager,
            change,
            "CLOSE",
            comment="Standard change validated successfully.",
        )
        assert change["outcome"] == "SUCCESS"


def test_structured_pir_requires_independent_approval_and_cab_keeps_evidence(app) -> None:
    with TestClient(app) as client:
        manager, _ = _login(client, "manager@sbs.local")
        admin, _ = _login(client, "admin@sbs.local")
        change = _approved_change(
            client,
            manager,
            admin,
            title="Payment database maintenance",
            outage_required=True,
        )
        start = datetime.now(UTC) + timedelta(days=4)
        change = _transition(
            client,
            manager,
            change,
            "SCHEDULE",
            planned_start_at=start.isoformat(),
            planned_end_at=(start + timedelta(hours=1)).isoformat(),
        )
        change = _transition(client, manager, change, "START")
        change = _transition(client, manager, change, "COMPLETE")
        assert change["pir_status"] == "REQUIRED"

        pir_response = client.put(
            f"/api/v1/change-governance/changes/{change['id']}/pir",
            headers=_headers(manager),
            json={
                "outcome": "SUCCESS",
                "objectives_met": True,
                "actual_impact": "Planned 12-minute read-only window.",
                "actual_outage_minutes": 12,
                "incidents_caused": 0,
                "lessons_learned": "Pre-warming reduced the business impact.",
                "follow_up_actions": [
                    {
                        "title": "Automate pre-warming",
                        "owner": "Platform",
                    }
                ],
            },
        )
        assert pir_response.status_code == 200, pir_response.text
        pir = pir_response.json()
        submitted = client.post(
            f"/api/v1/change-governance/changes/{change['id']}/pir/submit",
            headers=_headers(manager),
            json={"expected_version": pir["version"]},
        )
        assert submitted.status_code == 200
        pir = submitted.json()
        self_approval = client.post(
            f"/api/v1/change-governance/changes/{change['id']}/pir/approve",
            headers=_headers(manager),
            json={
                "expected_version": pir["version"],
                "comment": "Self approval must fail.",
            },
        )
        assert self_approval.status_code == 403
        approved = client.post(
            f"/api/v1/change-governance/changes/{change['id']}/pir/approve",
            headers=_headers(admin),
            json={
                "expected_version": pir["version"],
                "comment": "Evidence and lessons accepted independently.",
            },
        )
        assert approved.status_code == 200
        change = client.get(
            f"/api/v1/changes/{change['id']}",
            headers=_headers(manager),
        ).json()
        change = _transition(
            client,
            manager,
            change,
            "CLOSE",
            comment="Approved PIR completed the closure gate.",
        )
        assert change["status"] == "COMPLETED"

        agenda_change = _create_change(
            client,
            manager,
            title="CAB evidence test",
        )
        agenda_change = _transition(client, manager, agenda_change, "SUBMIT")
        agenda_change = _transition(
            client,
            manager,
            agenda_change,
            "REQUEST_APPROVAL",
        )
        meeting_response = client.post(
            "/api/v1/change-governance/cab/meetings",
            headers=_headers(admin),
            json={
                "title": "Weekly production CAB",
                "meeting_type": "CAB",
                "scheduled_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "duration_minutes": 60,
                "participant_user_ids": [],
            },
        )
        assert meeting_response.status_code == 201
        meeting = meeting_response.json()
        agenda = client.post(
            f"/api/v1/change-governance/cab/meetings/{meeting['id']}/agenda",
            headers=_headers(admin),
            json={
                "change_id": agenda_change["id"],
                "recommendation": "Approve after conflict and rollback review.",
            },
        )
        assert agenda.status_code == 201
        meeting = agenda.json()
        published = client.patch(
            f"/api/v1/change-governance/cab/meetings/{meeting['id']}",
            headers=_headers(admin),
            json={
                "expected_version": meeting["version"],
                "status": "PUBLISHED",
            },
        )
        assert published.status_code == 200
        meeting = published.json()
        decision = client.post(
            (
                "/api/v1/change-governance/cab/agenda/"
                f"{meeting['agenda'][0]['id']}/decision"
            ),
            headers=_headers(admin),
            json={
                "decision": "APPROVED",
                "comment": "Quorum accepted all control evidence.",
                "evidence": {
                    "quorum_confirmed": True,
                    "rollback_reviewed": True,
                    "collision_reviewed": True,
                },
            },
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()["agenda"][0]["evidence"]["quorum_confirmed"] is True
