from __future__ import annotations

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


def _create_published_class(
    client: TestClient,
    token: str,
    *,
    code: str,
    name: str,
) -> dict:
    created_response = client.post(
        "/api/v1/cmdb/classes",
        headers=_headers(token),
        json={"code": code, "name": name},
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    publish_response = client.post(
        f"/api/v1/cmdb/classes/{created['id']}/publish",
        headers=_headers(token),
        json={
            "expected_revision": created["draft_version"]["revision"],
            "reason": f"{name} approved for relationship testing",
        },
    )
    assert publish_response.status_code == 200, publish_response.text
    return publish_response.json()


def _create_ci(
    client: TestClient,
    token: str,
    *,
    ci_class_id: str,
    asset_tag: str,
) -> dict:
    response = client.post(
        "/api/v1/cmdb/items",
        headers=_headers(token),
        json={
            "ci_class_id": ci_class_id,
            "asset_tag": asset_tag,
            "name": asset_tag.lower(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_relationship_cardinality_cycle_topology_history_and_tenant_isolation(
    app,
) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        other_token, _ = _login(client, "other.admin@sbs.local")
        admin_token, _ = _login(client, "admin@sbs.local")

        node_class = _create_published_class(
            client,
            manager_token,
            code="TOPOLOGY_NODE",
            name="Topology node",
        )
        node_a = _create_ci(
            client,
            manager_token,
            ci_class_id=node_class["id"],
            asset_tag="CI-TOPO-A",
        )
        node_b = _create_ci(
            client,
            manager_token,
            ci_class_id=node_class["id"],
            asset_tag="CI-TOPO-B",
        )
        node_c = _create_ci(
            client,
            manager_token,
            ci_class_id=node_class["id"],
            asset_tag="CI-TOPO-C",
        )

        type_response = client.post(
            "/api/v1/cmdb/relationship-types",
            headers=_headers(manager_token),
            json={
                "code": "DEPENDS_ON",
                "name": "Depends on",
                "forward_label": "depends on",
                "reverse_label": "supports",
                "source_class_id": node_class["id"],
                "target_class_id": node_class["id"],
                "source_cardinality": "MANY",
                "target_cardinality": "MANY",
                "allow_cycles": False,
            },
        )
        assert type_response.status_code == 201, type_response.text
        relationship_type = type_response.json()
        assert relationship_type["version"] == 1
        assert relationship_type["active_relationships"] == 0

        edge_ab_response = client.post(
            "/api/v1/cmdb/relationships",
            headers=_headers(manager_token),
            json={
                "relationship_type_id": relationship_type["id"],
                "source_ci_id": node_a["id"],
                "target_ci_id": node_b["id"],
                "description": "A depends on B",
            },
        )
        assert edge_ab_response.status_code == 201, edge_ab_response.text
        edge_ab = edge_ab_response.json()
        assert edge_ab["forward_label"] == "depends on"

        edge_bc_response = client.post(
            "/api/v1/cmdb/relationships",
            headers=_headers(manager_token),
            json={
                "relationship_type_id": relationship_type["id"],
                "source_ci_id": node_b["id"],
                "target_ci_id": node_c["id"],
            },
        )
        assert edge_bc_response.status_code == 201, edge_bc_response.text
        edge_bc = edge_bc_response.json()

        cycle = client.post(
            "/api/v1/cmdb/relationships",
            headers=_headers(manager_token),
            json={
                "relationship_type_id": relationship_type["id"],
                "source_ci_id": node_c["id"],
                "target_ci_id": node_a["id"],
            },
        )
        assert cycle.status_code == 409
        assert "cycle" in cycle.text.lower()

        self_relationship = client.post(
            "/api/v1/cmdb/relationships",
            headers=_headers(manager_token),
            json={
                "relationship_type_id": relationship_type["id"],
                "source_ci_id": node_a["id"],
                "target_ci_id": node_a["id"],
            },
        )
        assert self_relationship.status_code == 422

        topology_response = client.get(
            f"/api/v1/cmdb/topology/{node_a['id']}?direction=downstream&depth=5",
            headers=_headers(manager_token),
        )
        assert topology_response.status_code == 200, topology_response.text
        topology = topology_response.json()
        assert topology["truncated"] is False
        assert {node["id"] for node in topology["nodes"]} == {
            node_a["id"],
            node_b["id"],
            node_c["id"],
        }
        assert {edge["id"] for edge in topology["edges"]} == {
            edge_ab["id"],
            edge_bc["id"],
        }
        assert {
            node["id"]: node["depth"] for node in topology["nodes"]
        } == {
            node_a["id"]: 0,
            node_b["id"]: 1,
            node_c["id"]: 2,
        }

        cross_tenant = client.get(
            f"/api/v1/cmdb/topology/{node_a['id']}",
            headers=_headers(other_token),
        )
        assert cross_tenant.status_code == 404

        cardinality_type_response = client.post(
            "/api/v1/cmdb/relationship-types",
            headers=_headers(manager_token),
            json={
                "code": "PRIMARY_TARGET",
                "name": "Primary target",
                "forward_label": "uses primary",
                "reverse_label": "is primary for",
                "source_class_id": node_class["id"],
                "target_class_id": node_class["id"],
                "source_cardinality": "ONE",
                "target_cardinality": "MANY",
            },
        )
        assert cardinality_type_response.status_code == 201
        cardinality_type = cardinality_type_response.json()
        first_primary = client.post(
            "/api/v1/cmdb/relationships",
            headers=_headers(manager_token),
            json={
                "relationship_type_id": cardinality_type["id"],
                "source_ci_id": node_a["id"],
                "target_ci_id": node_b["id"],
            },
        )
        assert first_primary.status_code == 201
        second_primary = client.post(
            "/api/v1/cmdb/relationships",
            headers=_headers(manager_token),
            json={
                "relationship_type_id": cardinality_type["id"],
                "source_ci_id": node_a["id"],
                "target_ci_id": node_c["id"],
            },
        )
        assert second_primary.status_code == 409
        assert "cardinality" in second_primary.text.lower()

        retire_response = client.post(
            f"/api/v1/cmdb/relationships/{edge_bc['id']}/retire",
            headers=_headers(manager_token),
            json={
                "expected_version": edge_bc["version"],
                "reason": "Dependency removed after architecture review",
            },
        )
        assert retire_response.status_code == 200, retire_response.text
        retired = retire_response.json()
        assert retired["status"] == "RETIRED"
        assert retired["version"] == edge_bc["version"] + 1

        topology_after_retire = client.get(
            f"/api/v1/cmdb/topology/{node_a['id']}?direction=downstream&depth=5",
            headers=_headers(manager_token),
        ).json()
        assert {node["id"] for node in topology_after_retire["nodes"]} == {
            node_a["id"],
            node_b["id"],
        }

        history_response = client.get(
            f"/api/v1/assets/{node_b['id']}/history",
            headers=_headers(manager_token),
        )
        assert history_response.status_code == 200
        actions = {entry["action"] for entry in history_response.json()}
        assert "ci_relationship_created" in actions
        assert "ci_relationship_retired" in actions

        audit_response = client.get(
            "/api/v1/admin/audit-logs?action=ci_relationship_retired",
            headers=_headers(admin_token),
        )
        assert audit_response.status_code == 200
        assert any(
            entry["entity_id"] == edge_bc["id"]
            for entry in audit_response.json()
        )


def test_relationship_type_optimistic_version_and_inactive_guard(app) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        node_class = _create_published_class(
            client,
            manager_token,
            code="TYPE_VERSION_NODE",
            name="Type version node",
        )
        node_a = _create_ci(
            client,
            manager_token,
            ci_class_id=node_class["id"],
            asset_tag="CI-TYPE-A",
        )
        node_b = _create_ci(
            client,
            manager_token,
            ci_class_id=node_class["id"],
            asset_tag="CI-TYPE-B",
        )
        type_response = client.post(
            "/api/v1/cmdb/relationship-types",
            headers=_headers(manager_token),
            json={
                "code": "VERSIONED_LINK",
                "name": "Versioned link",
                "forward_label": "links",
                "reverse_label": "linked from",
                "source_class_id": node_class["id"],
                "target_class_id": node_class["id"],
            },
        )
        assert type_response.status_code == 201
        relationship_type = type_response.json()

        updated_response = client.patch(
            f"/api/v1/cmdb/relationship-types/{relationship_type['id']}",
            headers=_headers(manager_token),
            json={
                "expected_version": relationship_type["version"],
                "status": "INACTIVE",
                "reason": "Type temporarily disabled by CMDB owner",
            },
        )
        assert updated_response.status_code == 200
        updated = updated_response.json()
        assert updated["status"] == "INACTIVE"
        assert updated["version"] == 2

        stale = client.patch(
            f"/api/v1/cmdb/relationship-types/{relationship_type['id']}",
            headers=_headers(manager_token),
            json={
                "expected_version": 1,
                "name": "Stale update",
                "reason": "This update uses a stale version",
            },
        )
        assert stale.status_code == 409

        denied = client.post(
            "/api/v1/cmdb/relationships",
            headers=_headers(manager_token),
            json={
                "relationship_type_id": relationship_type["id"],
                "source_ci_id": node_a["id"],
                "target_ci_id": node_b["id"],
            },
        )
        assert denied.status_code == 409
        assert "inactive" in denied.text.lower()
