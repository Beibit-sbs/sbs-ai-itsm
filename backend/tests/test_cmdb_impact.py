from __future__ import annotations

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


def _definitions(client: TestClient, token: str, path: str) -> dict[str, dict]:
    response = client.get(path, headers=_headers(token))
    assert response.status_code == 200, response.text
    return {item["code"]: item for item in response.json()}


def _create_ci(
    client: TestClient,
    token: str,
    ci_class: dict,
    *,
    tag: str,
    name: str,
    criticality: str = "MEDIUM",
) -> dict:
    attributes_by_class = {
        "BUSINESS_SERVICE": {"service_tier": "tier_1"},
        "APPLICATION": {
            "application_id": tag.lower(),
            "data_classification": "internal",
        },
        "INFRASTRUCTURE": {"hostname": tag.lower()},
    }
    response = client.post(
        "/api/v1/cmdb/items",
        headers=_headers(token),
        json={
            "ci_class_id": ci_class["id"],
            "asset_tag": tag,
            "name": name,
            "criticality": criticality,
            "environment": "PRODUCTION",
            "attributes": attributes_by_class.get(ci_class["code"], {}),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _link(
    client: TestClient,
    token: str,
    relationship_type: dict,
    source: dict,
    target: dict,
) -> dict:
    response = client.post(
        "/api/v1/cmdb/relationships",
        headers=_headers(token),
        json={
            "relationship_type_id": relationship_type["id"],
            "source_ci_id": source["id"],
            "target_ci_id": target["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_change(
    client: TestClient,
    token: str,
    *,
    title: str,
    asset_id: str,
) -> dict:
    response = client.post(
        "/api/v1/changes",
        headers=_headers(token),
        json={
            "title": title,
            "description": "Controlled production change with complete impact analysis.",
            "change_type": "NORMAL",
            "service_name": "Student portal",
            "impact_level": "HIGH",
            "likelihood": 3,
            "business_justification": "Remove a known availability risk.",
            "implementation_plan": "Deploy, validate telemetry, and monitor.",
            "test_plan": "Run synthetic transactions and health checks.",
            "rollback_plan": "Restore the signed previous release.",
            "validation_plan": "Confirm service KPIs and owner acceptance.",
            "asset_ids": [asset_id],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_impact_graph_cache_assessment_staleness_and_tenant_isolation(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        other_admin = _login(client, "other.admin@sbs.local")
        classes = _definitions(client, manager, "/api/v1/cmdb/classes")
        types = _definitions(
            client,
            manager,
            "/api/v1/cmdb/relationship-types",
        )

        business = _create_ci(
            client,
            manager,
            classes["BUSINESS_SERVICE"],
            tag="CI-IMPACT-BIZ",
            name="Student portal",
            criticality="CRITICAL",
        )
        technical = _create_ci(
            client,
            manager,
            classes["TECHNICAL_SERVICE"],
            tag="CI-IMPACT-TECH",
            name="Portal runtime",
            criticality="HIGH",
        )
        application = _create_ci(
            client,
            manager,
            classes["APPLICATION"],
            tag="CI-IMPACT-APP",
            name="Portal application",
            criticality="HIGH",
        )
        infrastructure = _create_ci(
            client,
            manager,
            classes["INFRASTRUCTURE"],
            tag="CI-IMPACT-INFRA",
            name="Portal cluster",
            criticality="CRITICAL",
        )
        _link(
            client,
            manager,
            types["SERVICE_DEPENDS_ON"],
            business,
            technical,
        )
        _link(
            client,
            manager,
            types["TECH_SERVICE_USES_APPLICATION"],
            technical,
            application,
        )
        infrastructure_edge = _link(
            client,
            manager,
            types["APPLICATION_RUNS_ON"],
            application,
            infrastructure,
        )

        preview_payload = {
            "root_ci_ids": [infrastructure["id"]],
            "direction": "UPSTREAM",
            "max_depth": 5,
        }
        first_response = client.post(
            "/api/v1/cmdb/impact/preview",
            headers=_headers(manager),
            json=preview_payload,
        )
        assert first_response.status_code == 200, first_response.text
        first = first_response.json()
        assert first["cache_hits"] == 0
        assert first["customer_impact"] is True
        assert first["severity"] == "CRITICAL"
        assert first["impacted_ci_count"] == 4
        assert first["impacted_service_count"] == 2
        assert {item["asset_tag"] for item in first["services"]} == {
            "CI-IMPACT-BIZ",
            "CI-IMPACT-TECH",
        }
        assert {
            item["asset_tag"]: item["depth"] for item in first["nodes"]
        } == {
            "CI-IMPACT-INFRA": 0,
            "CI-IMPACT-APP": 1,
            "CI-IMPACT-TECH": 2,
            "CI-IMPACT-BIZ": 3,
        }

        cached = client.post(
            "/api/v1/cmdb/impact/preview",
            headers=_headers(manager),
            json=preview_payload,
        )
        assert cached.status_code == 200, cached.text
        assert cached.json()["cache_hits"] == 1
        assert cached.json()["graph_hash"] == first["graph_hash"]

        cross_tenant = client.post(
            "/api/v1/cmdb/impact/preview",
            headers=_headers(other_admin),
            json=preview_payload,
        )
        assert cross_tenant.status_code == 422

        primary_change = _create_change(
            client,
            manager,
            title="Upgrade portal cluster",
            asset_id=infrastructure["id"],
        )
        competing_change = _create_change(
            client,
            manager,
            title="Update student portal authentication",
            asset_id=business["id"],
        )
        assessment_response = client.post(
            f"/api/v1/cmdb/impact/assessments/CHANGE/{primary_change['id']}",
            headers=_headers(manager),
            json={
                "expected_entity_version": primary_change["version"],
                "direction": "UPSTREAM",
                "max_depth": 5,
            },
        )
        assert assessment_response.status_code == 201, assessment_response.text
        assessment = assessment_response.json()
        assert assessment["integrity_valid"] is True
        assert assessment["is_stale"] is False
        assert assessment["snapshot"]["collision_count"] == 1
        assert assessment["snapshot"]["collisions"][0]["change_id"] == (
            competing_change["id"]
        )
        assert assessment["snapshot"]["collisions"][0]["collision_type"] == (
            "SHARED_SCOPE"
        )

        stale_version = client.post(
            f"/api/v1/cmdb/impact/assessments/CHANGE/{primary_change['id']}",
            headers=_headers(manager),
            json={
                "expected_entity_version": primary_change["version"] + 10,
            },
        )
        assert stale_version.status_code == 409

        patch = client.patch(
            f"/api/v1/changes/{primary_change['id']}",
            headers=_headers(manager),
            json={
                "expected_version": primary_change["version"],
                "title": "Upgrade portal cluster with revised scope",
            },
        )
        assert patch.status_code == 200, patch.text

        latest = client.get(
            f"/api/v1/cmdb/impact/assessments/CHANGE/{primary_change['id']}/latest",
            headers=_headers(manager),
        )
        assert latest.status_code == 200, latest.text
        assert latest.json()["entity_is_stale"] is True
        assert latest.json()["is_stale"] is True

        refreshed_response = client.post(
            f"/api/v1/cmdb/impact/assessments/CHANGE/{primary_change['id']}",
            headers=_headers(manager),
            json={
                "expected_entity_version": patch.json()["version"],
                "direction": "UPSTREAM",
                "max_depth": 5,
            },
        )
        assert refreshed_response.status_code == 201, refreshed_response.text
        refreshed = refreshed_response.json()
        assert refreshed["id"] != assessment["id"]
        assert refreshed["is_stale"] is False

        retired = client.post(
            f"/api/v1/cmdb/relationships/{infrastructure_edge['id']}/retire",
            headers=_headers(manager),
            json={
                "expected_version": infrastructure_edge["version"],
                "reason": "Architecture dependency removed after review",
            },
        )
        assert retired.status_code == 200, retired.text
        graph_stale = client.get(
            f"/api/v1/cmdb/impact/assessments/CHANGE/{primary_change['id']}/latest",
            headers=_headers(manager),
        )
        assert graph_stale.status_code == 200, graph_stale.text
        assert graph_stale.json()["graph_is_stale"] is True
        assert graph_stale.json()["integrity_valid"] is True

        history = client.get(
            f"/api/v1/cmdb/impact/assessments/CHANGE/{primary_change['id']}",
            headers=_headers(manager),
        )
        assert history.status_code == 200, history.text
        assert [item["status"] for item in history.json()] == [
            "CURRENT",
            "SUPERSEDED",
        ]
        assert all(item["integrity_valid"] for item in history.json())

        hidden = client.get(
            f"/api/v1/cmdb/impact/assessments/CHANGE/{primary_change['id']}/latest",
            headers=_headers(other_admin),
        )
        assert hidden.status_code == 404
