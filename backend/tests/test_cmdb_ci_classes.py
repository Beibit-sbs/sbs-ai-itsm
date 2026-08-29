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


def _publish(
    client: TestClient,
    token: str,
    ci_class: dict,
    reason: str,
) -> dict:
    draft = ci_class["draft_version"]
    response = client.post(
        f"/api/v1/cmdb/classes/{ci_class['id']}/publish",
        headers=_headers(token),
        json={"expected_revision": draft["revision"], "reason": reason},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _schema(fields: list[dict]) -> dict:
    return {"fields": fields}


def test_cmdb_class_inheritance_schema_snapshots_and_ci_governance(app) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        requester_token, _ = _login(client, "requester@sbs.local")
        other_token, _ = _login(client, "other.admin@sbs.local")
        admin_token, _ = _login(client, "admin@sbs.local")

        denied = client.post(
            "/api/v1/cmdb/classes",
            headers=_headers(requester_token),
            json={"code": "DENIED", "name": "Denied class"},
        )
        assert denied.status_code == 403

        parent_response = client.post(
            "/api/v1/cmdb/classes",
            headers=_headers(manager_token),
            json={
                "code": "COMPUTE_DEVICE",
                "name": "Вычислительное устройство",
                "description": "Общие атрибуты вычислительного оборудования.",
                "schema": _schema(
                    [
                        {
                            "key": "hostname",
                            "label": "Hostname",
                            "type": "text",
                            "required": True,
                        },
                        {
                            "key": "management_ip",
                            "label": "Management IP",
                            "type": "text",
                            "required": False,
                        },
                    ]
                ),
            },
        )
        assert parent_response.status_code == 201, parent_response.text
        parent = _publish(
            client,
            manager_token,
            parent_response.json(),
            "Базовый класс проверен CMDB manager",
        )
        assert parent["published_version"]["version"] == 1

        child_response = client.post(
            "/api/v1/cmdb/classes",
            headers=_headers(manager_token),
            json={
                "parent_class_id": parent["id"],
                "code": "VIRTUAL_MACHINE",
                "name": "Виртуальная машина",
                "schema": _schema(
                    [
                        {
                            "key": "vcpu",
                            "label": "vCPU",
                            "type": "integer",
                            "required": True,
                        },
                        {
                            "key": "operating_system",
                            "label": "Операционная система",
                            "type": "select",
                            "required": True,
                            "options": [
                                {"value": "linux", "label": "Linux"},
                                {"value": "windows", "label": "Windows"},
                            ],
                        },
                    ]
                ),
            },
        )
        assert child_response.status_code == 201, child_response.text
        child = _publish(
            client,
            manager_token,
            child_response.json(),
            "Класс виртуальных машин готов",
        )
        effective_fields = child["published_version"]["effective_schema"]["fields"]
        assert [field["key"] for field in effective_fields] == [
            "hostname",
            "management_ip",
            "vcpu",
            "operating_system",
        ]
        assert effective_fields[0]["inherited"] is True
        assert effective_fields[-1]["inherited"] is False

        invalid = client.post(
            "/api/v1/cmdb/items",
            headers=_headers(manager_token),
            json={
                "ci_class_id": child["id"],
                "asset_tag": "CI-VM-001",
                "name": "itsm-app-01",
                "attributes": {
                    "hostname": "itsm-app-01",
                    "vcpu": "not-an-integer",
                    "operating_system": "unsupported",
                    "rogue": True,
                },
            },
        )
        assert invalid.status_code == 422
        errors = invalid.json()["error"]["details"]["errors"]
        assert {"vcpu", "operating_system", "rogue"}.issubset(errors)

        created_response = client.post(
            "/api/v1/cmdb/items",
            headers=_headers(manager_token),
            json={
                "ci_class_id": child["id"],
                "asset_tag": "CI-VM-001",
                "name": "itsm-app-01",
                "inventory_number": "VM-0001",
                "lifecycle_status": "ACTIVE",
                "criticality": "CRITICAL",
                "environment": "PRODUCTION",
                "support_group": "Platform Operations",
                "location": "DC-1 / Cluster-A",
                "attributes": {
                    "hostname": "itsm-app-01",
                    "management_ip": "10.20.30.40",
                    "vcpu": "8",
                    "operating_system": "linux",
                },
            },
        )
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        original_schema_hash = created["ci_schema_hash"]
        assert created["attributes"]["vcpu"] == 8
        assert created["ci_class_code"] == "VIRTUAL_MACHINE"
        assert created["criticality"] == "CRITICAL"
        assert created["environment"] == "PRODUCTION"
        assert created["version"] == 1

        asset_detail = client.get(
            f"/api/v1/assets/{created['id']}",
            headers=_headers(manager_token),
        )
        assert asset_detail.status_code == 200, asset_detail.text
        asset = asset_detail.json()
        assert asset["ci_class_name"] == "Виртуальная машина"
        assert asset["ci_attributes"]["hostname"] == "itsm-app-01"
        assert asset["lifecycle_status"] == "ACTIVE"
        assert asset["ci_schema_hash"] == original_schema_hash

        cross_tenant_asset = client.get(
            f"/api/v1/assets/{created['id']}",
            headers=_headers(other_token),
        )
        assert cross_tenant_asset.status_code == 404
        cross_tenant_child = client.post(
            "/api/v1/cmdb/classes",
            headers=_headers(other_token),
            json={
                "parent_class_id": parent["id"],
                "code": "CROSS_TENANT",
                "name": "Cross tenant",
            },
        )
        assert cross_tenant_child.status_code == 404

        parent_draft_response = client.post(
            f"/api/v1/cmdb/classes/{parent['id']}/draft",
            headers=_headers(manager_token),
        )
        assert parent_draft_response.status_code == 201
        parent_draft = parent_draft_response.json()["draft_version"]
        parent_update = client.put(
            f"/api/v1/cmdb/classes/{parent['id']}/draft",
            headers=_headers(manager_token),
            json={
                "expected_revision": parent_draft["revision"],
                "schema": _schema(
                    [
                        {
                            "key": "hostname",
                            "label": "Hostname",
                            "type": "text",
                            "required": True,
                        },
                        {
                            "key": "management_ip",
                            "label": "Management IP",
                            "type": "text",
                            "required": False,
                        },
                        {
                            "key": "monitoring_tier",
                            "label": "Monitoring tier",
                            "type": "select",
                            "required": True,
                            "options": [
                                {"value": "gold", "label": "Gold"},
                                {"value": "silver", "label": "Silver"},
                            ],
                        },
                    ]
                ),
            },
        )
        assert parent_update.status_code == 200, parent_update.text
        parent = _publish(
            client,
            manager_token,
            parent_update.json(),
            "Добавлен обязательный monitoring tier",
        )

        unchanged = client.get(
            f"/api/v1/assets/{created['id']}",
            headers=_headers(manager_token),
        ).json()
        assert unchanged["ci_schema_hash"] == original_schema_hash
        assert "monitoring_tier" not in unchanged["ci_attributes"]

        child_draft_response = client.post(
            f"/api/v1/cmdb/classes/{child['id']}/draft",
            headers=_headers(manager_token),
        )
        assert child_draft_response.status_code == 201
        child = _publish(
            client,
            manager_token,
            child_draft_response.json(),
            "Дочерний класс привязан к новой версии родителя",
        )
        assert child["published_version"]["parent_version_id"] == (
            parent["published_version"]["id"]
        )

        missing_new_required = client.patch(
            f"/api/v1/cmdb/items/{created['id']}",
            headers=_headers(manager_token),
            json={
                "expected_version": created["version"],
                "upgrade_schema": True,
                "comment": "Upgrade without required inherited attribute",
            },
        )
        assert missing_new_required.status_code == 422
        assert "monitoring_tier" in (
            missing_new_required.json()["error"]["details"]["errors"]
        )

        upgraded_response = client.patch(
            f"/api/v1/cmdb/items/{created['id']}",
            headers=_headers(manager_token),
            json={
                "expected_version": created["version"],
                "upgrade_schema": True,
                "criticality": "HIGH",
                "attributes": {
                    **created["attributes"],
                    "monitoring_tier": "gold",
                },
                "comment": "CI certified against the new inherited schema",
            },
        )
        assert upgraded_response.status_code == 200, upgraded_response.text
        upgraded = upgraded_response.json()
        assert upgraded["version"] == 2
        assert upgraded["ci_schema_hash"] != original_schema_hash
        assert upgraded["attributes"]["monitoring_tier"] == "gold"

        history = client.get(
            f"/api/v1/assets/{created['id']}/history",
            headers=_headers(manager_token),
        )
        assert history.status_code == 200
        assert {"ci_created", "ci_updated"}.issubset(
            {entry["action"] for entry in history.json()}
        )

        audit = client.get(
            "/api/v1/admin/audit-logs?action=configuration_item_updated",
            headers=_headers(admin_token),
        )
        assert audit.status_code == 200
        assert any(entry["entity_id"] == created["id"] for entry in audit.json())


def test_saas_root_must_choose_cmdb_tenant(app) -> None:
    with TestClient(app) as client:
        root_token, _ = _login(client, "saas.root@sbs.local")
        response = client.post(
            "/api/v1/cmdb/classes",
            headers=_headers(root_token),
            json={"code": "ROOT_CLASS", "name": "Root class"},
        )
        assert response.status_code == 422
        assert "tenant_id" in response.text


def test_saas_root_ci_uses_a_tenant_owner(app) -> None:
    with TestClient(app) as client:
        root_token, root = _login(client, "saas.root@sbs.local")
        manager_token, _ = _login(client, "manager@sbs.local")

        class_response = client.post(
            "/api/v1/cmdb/classes",
            headers=_headers(manager_token),
            json={
                "code": "ROOT_OWNER_CLASS",
                "name": "Root owner isolation class",
            },
        )
        assert class_response.status_code == 201, class_response.text
        ci_class = _publish(
            client,
            manager_token,
            class_response.json(),
            "Class prepared for root ownership isolation",
        )

        created_response = client.post(
            "/api/v1/cmdb/items",
            headers=_headers(root_token),
            json={
                "ci_class_id": ci_class["id"],
                "asset_tag": "CI-ROOT-001",
                "name": "Root-created tenant CI",
            },
        )
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        assert created["owner_user_id"] != root["id"]
        assert created["owner_name"]
