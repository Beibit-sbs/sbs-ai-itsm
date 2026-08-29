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


def _create_release(
    client: TestClient,
    token: str,
    *,
    name: str,
    version_name: str,
) -> dict:
    now = datetime.now(UTC)
    response = client.post(
        "/api/v1/releases",
        headers=_headers(token),
        json={
            "name": name,
            "version_name": version_name,
            "release_type": "MINOR",
            "service_name": "Payments",
            "description": "Governed release with immutable packages and evidence.",
            "scope": "Approved payment service changes in the signed release package.",
            "release_notes": f"Release notes for {version_name}.",
            "risk_level": "MEDIUM",
            "target_release_at": (now + timedelta(minutes=30)).isoformat(),
            "window_start_at": (now - timedelta(minutes=5)).isoformat(),
            "window_end_at": (now + timedelta(hours=2)).isoformat(),
            "validation_plan": "Run smoke tests and validate payment transactions.",
            "rollback_plan": "Restore the previous signed package and verify health.",
            "communication_plan": "Notify CAB, Service Desk, and the service owner.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _approved_change(
    client: TestClient,
    manager: str,
    admin: str,
) -> dict:
    response = client.post(
        "/api/v1/changes",
        headers=_headers(manager),
        json={
            "title": "Release-scoped payment update",
            "description": "A controlled change aggregated into the release train.",
            "change_type": "NORMAL",
            "service_name": "Payments",
            "environment": "PRODUCTION",
            "impact_level": "MEDIUM",
            "likelihood": 2,
            "business_justification": "Deliver an approved service improvement.",
            "implementation_plan": "Deploy the signed package and monitor.",
            "test_plan": "Run synthetic payment transactions.",
            "rollback_plan": "Restore the previous signed package.",
            "validation_plan": "Confirm health and business owner acceptance.",
        },
    )
    assert response.status_code == 201, response.text
    change = response.json()
    for action in ("SUBMIT", "REQUEST_APPROVAL"):
        transitioned = client.post(
            f"/api/v1/changes/{change['id']}/transitions",
            headers=_headers(manager),
            json={"expected_version": change["version"], "action": action},
        )
        assert transitioned.status_code == 200, transitioned.text
        change = transitioned.json()
    approved = client.post(
        f"/api/v1/changes/{change['id']}/decisions",
        headers=_headers(admin),
        json={
            "expected_version": change["version"],
            "decision": "APPROVED",
            "comment": "CAB accepted risk, test, and rollback evidence.",
        },
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def _transition(
    client: TestClient,
    token: str,
    release: dict,
    action: str,
) -> dict:
    response = client.post(
        f"/api/v1/releases/{release['id']}/transition",
        headers=_headers(token),
        json={
            "expected_version": release["version"],
            "action": action,
            "comment": f"Controlled release transition {action}.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _deployment_action(
    client: TestClient,
    token: str,
    release: dict,
    environment_code: str,
    action: str,
) -> dict:
    deployment = next(
        item
        for item in release["deployments"]
        if item["environment"]["code"] == environment_code
    )
    evidence = "Signed execution logs, health checks, and operator evidence."
    response = client.patch(
        f"/api/v1/releases/{release['id']}/deployments/{deployment['id']}",
        headers=_headers(token),
        json={
            "expected_version": deployment["version"],
            "action": action,
            "deployment_evidence": evidence,
            "validation_evidence": evidence if action == "SUCCEED" else None,
            "smoke_test_status": "PASSED" if action == "SUCCEED" else None,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_release_train_go_no_go_promotion_and_publication(app) -> None:
    with TestClient(app) as client:
        manager, _ = _login(client, "manager@sbs.local")
        admin, _ = _login(client, "admin@sbs.local")
        agent, _ = _login(client, "agent.support@sbs.local")
        now = datetime.now(UTC)

        for code, name, environment_type, order, production in (
            ("STAGE", "Staging", "STAGING", 10, False),
            ("PROD", "Production", "PRODUCTION", 20, True),
        ):
            response = client.post(
                "/api/v1/releases/environments",
                headers=_headers(admin),
                json={
                    "code": code,
                    "name": name,
                    "environment_type": environment_type,
                    "promotion_order": order,
                    "requires_approval": production,
                    "requires_smoke_test": True,
                    "is_production": production,
                    "is_active": True,
                },
            )
            assert response.status_code == 201, response.text

        change = _approved_change(client, manager, admin)
        release = _create_release(
            client,
            manager,
            name="Payments 2.4 controlled release",
            version_name="2.4.0",
        )
        linked = client.post(
            f"/api/v1/releases/{release['id']}/changes",
            headers=_headers(manager),
            json={
                "change_id": change["id"],
                "sequence": 1,
                "is_mandatory": True,
            },
        )
        assert linked.status_code == 201, linked.text
        release = linked.json()

        package = client.post(
            f"/api/v1/releases/{release['id']}/packages",
            headers=_headers(manager),
            json={
                "component_name": "payments-api",
                "package_type": "APPLICATION",
                "version_name": "2.4.0",
                "artifact_uri": "registry.local/payments-api@sha256:test",
                "checksum_sha256": "a" * 64,
                "build_reference": "build-240",
                "dependencies": [],
            },
        )
        assert package.status_code == 201, package.text
        release = package.json()
        verified = client.patch(
            (
                f"/api/v1/releases/{release['id']}/packages/"
                f"{release['packages'][0]['id']}"
            ),
            headers=_headers(admin),
            json={
                "expected_version": release["packages"][0]["version"],
                "verification_status": "VERIFIED",
                "evidence": "Registry signature and SHA-256 checksum verified.",
            },
        )
        assert verified.status_code == 200, verified.text
        release = verified.json()
        release = _transition(client, manager, release, "SUBMIT")

        for gate in release["readiness"]["gates"]:
            if gate["gate_type"] not in {"TEST", "SECURITY", "BUSINESS"}:
                continue
            decision = client.patch(
                f"/api/v1/releases/{release['id']}/gates/{gate['id']}",
                headers=_headers(admin),
                json={
                    "expected_version": gate["version"],
                    "status": "PASSED",
                    "evidence": f"{gate['name']} evidence accepted.",
                    "comment": "Independent reviewer accepted the control evidence.",
                },
            )
            assert decision.status_code == 200, decision.text
            release = decision.json()

        release = _transition(client, manager, release, "MARK_READY")
        go = client.post(
            f"/api/v1/releases/{release['id']}/decision",
            headers=_headers(admin),
            json={
                "expected_version": release["version"],
                "decision": "GO",
                "comment": "All mandatory readiness gates passed independently.",
                "conditions": [],
            },
        )
        assert go.status_code == 200, go.text
        release = go.json()
        assert release["status"] == "APPROVED"

        environments = client.get(
            "/api/v1/releases/environments",
            headers=_headers(manager),
        ).json()
        for code, scheduled in (
            ("STAGE", now.isoformat()),
            ("PROD", (now + timedelta(minutes=10)).isoformat()),
        ):
            environment = next(item for item in environments if item["code"] == code)
            planned = client.post(
                f"/api/v1/releases/{release['id']}/deployments",
                headers=_headers(manager),
                json={
                    "environment_id": environment["id"],
                    "scheduled_at": scheduled,
                    "deployment_reference": f"pipeline://{code.lower()}/240",
                },
            )
            assert planned.status_code == 201, planned.text
            release = planned.json()

        release = _deployment_action(client, agent, release, "STAGE", "START")
        release = _deployment_action(client, agent, release, "STAGE", "VALIDATE")
        release = _deployment_action(client, agent, release, "STAGE", "SUCCEED")
        release = _deployment_action(client, agent, release, "PROD", "START")
        release = _deployment_action(client, agent, release, "PROD", "VALIDATE")
        release = _deployment_action(client, agent, release, "PROD", "SUCCEED")
        assert release["status"] == "VALIDATING"

        release = _transition(client, agent, release, "PUBLISH")
        assert release["status"] == "RELEASED"
        assert release["actual_released_at"]
        analytics = client.get(
            "/api/v1/releases/analytics",
            headers=_headers(manager),
        )
        assert analytics.status_code == 200
        assert analytics.json()["production_deployments"] >= 1


def test_release_dependency_cycle_and_tenant_isolation(app) -> None:
    with TestClient(app) as client:
        manager, _ = _login(client, "manager@sbs.local")
        other_admin, _ = _login(client, "other.admin@sbs.local")
        first = _create_release(
            client,
            manager,
            name="Dependency foundation",
            version_name="3.0.0",
        )
        second = _create_release(
            client,
            manager,
            name="Dependent application",
            version_name="3.1.0",
        )
        linked = client.post(
            f"/api/v1/releases/{second['id']}/dependencies",
            headers=_headers(manager),
            json={
                "dependency_release_id": first["id"],
                "dependency_type": "REQUIRES",
            },
        )
        assert linked.status_code == 201, linked.text
        cycle = client.post(
            f"/api/v1/releases/{first['id']}/dependencies",
            headers=_headers(manager),
            json={
                "dependency_release_id": second["id"],
                "dependency_type": "REQUIRES",
            },
        )
        assert cycle.status_code == 422
        hidden = client.get(
            f"/api/v1/releases/{first['id']}",
            headers=_headers(other_admin),
        )
        assert hidden.status_code == 404
