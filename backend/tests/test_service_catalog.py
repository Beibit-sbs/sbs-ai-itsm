from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> tuple[str, dict]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["access_token"], payload["user"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_taxonomy(client: TestClient, token: str, suffix: str = "ACCESS") -> tuple[dict, dict, dict]:
    category_response = client.post(
        "/api/v1/catalog/categories",
        headers=_headers(token),
        json={
            "code": f"CAT_{suffix}",
            "name": f"{suffix.title()} services",
            "description": "Governed business service category.",
            "sort_order": 10,
        },
    )
    assert category_response.status_code == 201, category_response.text
    category = category_response.json()
    service_response = client.post(
        "/api/v1/catalog/services",
        headers=_headers(token),
        json={
            "category_id": category["id"],
            "code": f"SVC_{suffix}",
            "name": f"{suffix.title()} management",
            "description": "Managed service with an accountable support group.",
            "support_group": "Service Desk",
        },
    )
    assert service_response.status_code == 201, service_response.text
    service = service_response.json()
    offering_response = client.post(
        "/api/v1/catalog/offerings",
        headers=_headers(token),
        json={
            "service_id": service["id"],
            "code": f"OFF_{suffix}",
            "name": f"Standard {suffix.title()}",
            "description": "Standard governed fulfillment offering.",
            "support_group": "Service Desk",
            "expected_fulfillment_minutes": 480,
        },
    )
    assert offering_response.status_code == 201, offering_response.text
    return category, service, offering_response.json()


def _create_item(
    client: TestClient,
    token: str,
    user: dict,
    category: dict,
    service: dict,
    offering: dict,
) -> dict:
    response = client.post(
        "/api/v1/catalog/items",
        headers=_headers(token),
        json={
            "category_id": category["id"],
            "service_id": service["id"],
            "offering_id": offering["id"],
            "code": "REQ_VPN_ACCESS",
            "name": "Корпоративный VPN-доступ",
            "short_description": "Защищённый удалённый доступ к корпоративным системам.",
            "description": "Запрос на предоставление управляемого VPN-доступа с проверкой владельца и срока.",
            "owner_user_id": user["id"],
            "support_group": "Network Operations",
            "expected_delivery_minutes": 480,
            "approval_required": True,
            "entitlement_rules": {"roles": ["requester", "it_agent"]},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _transition(client: TestClient, token: str, item: dict, target: str) -> dict:
    response = client.post(
        f"/api/v1/catalog/items/{item['id']}/transition",
        headers=_headers(token),
        json={
            "expected_version": item["version"],
            "target_status": target,
            "reason": f"Lifecycle acceptance for {target}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_catalog_lifecycle_visibility_history_and_audit(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = _login(client, "manager@sbs.local")
        requester_token, _ = _login(client, "requester@sbs.local")
        admin_token, _ = _login(client, "admin@sbs.local")
        category, service, offering = _create_taxonomy(client, manager_token)
        item = _create_item(
            client,
            manager_token,
            manager,
            category,
            service,
            offering,
        )

        assert item["lifecycle_status"] == "DRAFT"
        requester_drafts = client.get(
            "/api/v1/catalog/items", headers=_headers(requester_token)
        )
        assert requester_drafts.status_code == 200
        assert requester_drafts.json() == []

        item = _transition(client, manager_token, item, "IN_REVIEW")
        item = _transition(client, manager_token, item, "PUBLISHED")
        assert item["published_at"]

        requester_items = client.get(
            "/api/v1/catalog/items?search=VPN", headers=_headers(requester_token)
        )
        assert requester_items.status_code == 200
        assert [entry["code"] for entry in requester_items.json()] == ["REQ_VPN_ACCESS"]

        stale = client.patch(
            f"/api/v1/catalog/items/{item['id']}",
            headers=_headers(manager_token),
            json={"expected_version": 1, "name": "Stale catalog edit"},
        )
        assert stale.status_code == 409

        revised = client.patch(
            f"/api/v1/catalog/items/{item['id']}",
            headers=_headers(manager_token),
            json={
                "expected_version": item["version"],
                "short_description": "Обновлённый безопасный VPN-доступ для сотрудников.",
            },
        )
        assert revised.status_code == 200, revised.text
        item = revised.json()
        assert item["lifecycle_status"] == "DRAFT"
        assert item["published_at"] is None

        hidden_after_revision = client.get(
            f"/api/v1/catalog/items/{item['id']}",
            headers=_headers(requester_token),
        )
        assert hidden_after_revision.status_code == 404

        history = client.get(
            f"/api/v1/catalog/items/{item['id']}/history",
            headers=_headers(manager_token),
        )
        assert history.status_code == 200, history.text
        actions = {entry["action"] for entry in history.json()}
        assert {
            "CREATED",
            "TRANSITIONED_TO_IN_REVIEW",
            "TRANSITIONED_TO_PUBLISHED",
            "PUBLISHED_VERSION_SUPERSEDED",
            "UPDATED",
        }.issubset(actions)

        audit = client.get(
            "/api/v1/admin/audit-logs?action=catalog_item_status_changed",
            headers=_headers(admin_token),
        )
        assert audit.status_code == 200, audit.text
        assert len(audit.json()) == 2


def test_catalog_rbac_and_tenant_isolation(app) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        agent_token, _ = _login(client, "agent.network@sbs.local")
        other_admin_token, _ = _login(client, "other.admin@sbs.local")

        denied = client.post(
            "/api/v1/catalog/categories",
            headers=_headers(agent_token),
            json={"code": "DENIED", "name": "Denied category"},
        )
        assert denied.status_code == 403

        other_category, _, _ = _create_taxonomy(
            client, other_admin_token, suffix="OTHER"
        )
        local_categories = client.get(
            "/api/v1/catalog/categories", headers=_headers(manager_token)
        )
        assert local_categories.status_code == 200
        assert other_category["id"] not in {
            category["id"] for category in local_categories.json()
        }

        cross_tenant_service = client.post(
            "/api/v1/catalog/services",
            headers=_headers(manager_token),
            json={
                "category_id": other_category["id"],
                "code": "CROSS_TENANT",
                "name": "Cross tenant service",
            },
        )
        assert cross_tenant_service.status_code == 422


def test_root_user_resolves_active_tenant_for_product_modules(app) -> None:
    with TestClient(app) as client:
        root_token, _ = _login(client, "saas.root@sbs.local")
        headers = _headers(root_token)

        catalog = client.get("/api/v1/catalog/summary", headers=headers)
        changes = client.get("/api/v1/changes", headers=headers)
        problems = client.get("/api/v1/problems", headers=headers)

        assert catalog.status_code == 200, catalog.text
        assert changes.status_code == 200, changes.text
        assert problems.status_code == 200, problems.text


def test_root_can_provision_tenant_with_standard_roles(app) -> None:
    with TestClient(app) as client:
        root_token, _ = _login(client, "saas.root@sbs.local")
        manager_token, _ = _login(client, "manager@sbs.local")

        created = client.post(
            "/api/v1/tenants",
            headers=_headers(root_token),
            json={
                "name": "Production Operations",
                "slug": "production-operations",
                "description": "Isolated production organization.",
            },
        )
        assert created.status_code == 201, created.text
        tenant = created.json()
        assert tenant["status"] == "active"

        roles = client.get("/api/v1/admin/roles", headers=_headers(root_token))
        assert roles.status_code == 200, roles.text
        tenant_roles = {
            role["code"]
            for role in roles.json()
            if role["tenant_id"] == tenant["id"]
        }
        assert {
            "organization_admin",
            "it_manager",
            "it_agent",
            "requester",
            "security_officer",
            "knowledge_manager",
        } == tenant_roles

        summary = client.get(
            f"/api/v1/catalog/summary?tenant_id={tenant['id']}",
            headers=_headers(root_token),
        )
        assert summary.status_code == 200, summary.text

        cmdb_classes = client.get(
            f"/api/v1/cmdb/classes?tenant_id={tenant['id']}",
            headers=_headers(root_token),
        )
        assert cmdb_classes.status_code == 200, cmdb_classes.text
        assert {
            "GENERIC_ASSET",
            "BUSINESS_SERVICE",
            "TECHNICAL_SERVICE",
            "APPLICATION",
            "INFRASTRUCTURE",
            "LOCATION",
        }.issubset({item["code"] for item in cmdb_classes.json()})
        assert all(
            item["published_version"]
            for item in cmdb_classes.json()
            if item["code"] != "GENERIC_ASSET"
        )

        relationship_types = client.get(
            f"/api/v1/cmdb/relationship-types?tenant_id={tenant['id']}",
            headers=_headers(root_token),
        )
        assert relationship_types.status_code == 200, relationship_types.text
        assert {
            "SERVICE_DEPENDS_ON",
            "TECH_SERVICE_USES_APPLICATION",
            "APPLICATION_RUNS_ON",
            "LOCATED_IN",
            "INFRASTRUCTURE_CONNECTED_TO",
        } == {item["code"] for item in relationship_types.json()}

        duplicate = client.post(
            "/api/v1/tenants",
            headers=_headers(root_token),
            json={"name": "Duplicate", "slug": "production-operations"},
        )
        assert duplicate.status_code == 409

        denied = client.post(
            "/api/v1/tenants",
            headers=_headers(manager_token),
            json={"name": "Denied", "slug": "denied-tenant"},
        )
        assert denied.status_code == 403


def test_catalog_taxonomy_can_be_updated_with_audit_and_tenant_isolation(app) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        agent_token, _ = _login(client, "agent.network@sbs.local")
        other_admin_token, _ = _login(client, "other.admin@sbs.local")
        admin_token, _ = _login(client, "admin@sbs.local")
        category, service, offering = _create_taxonomy(
            client, manager_token, suffix="EDITABLE"
        )

        category_update = client.patch(
            f"/api/v1/catalog/categories/{category['id']}",
            headers=_headers(manager_token),
            json={"name": "Access and accounts", "sort_order": 5},
        )
        service_update = client.patch(
            f"/api/v1/catalog/services/{service['id']}",
            headers=_headers(manager_token),
            json={"name": "Identity and access", "support_group": "IAM"},
        )
        offering_update = client.patch(
            f"/api/v1/catalog/offerings/{offering['id']}",
            headers=_headers(manager_token),
            json={"name": "Standard access", "expected_fulfillment_minutes": 240},
        )

        assert category_update.status_code == 200, category_update.text
        assert category_update.json()["name"] == "Access and accounts"
        assert service_update.status_code == 200, service_update.text
        assert service_update.json()["support_group"] == "IAM"
        assert offering_update.status_code == 200, offering_update.text
        assert offering_update.json()["expected_fulfillment_minutes"] == 240

        denied = client.patch(
            f"/api/v1/catalog/categories/{category['id']}",
            headers=_headers(agent_token),
            json={"name": "Denied update"},
        )
        cross_tenant = client.patch(
            f"/api/v1/catalog/categories/{category['id']}",
            headers=_headers(other_admin_token),
            json={"name": "Cross tenant update"},
        )
        assert denied.status_code == 403
        assert cross_tenant.status_code == 404

        audit = client.get(
            "/api/v1/admin/audit-logs?action=catalog_category_updated",
            headers=_headers(admin_token),
        )
        assert audit.status_code == 200, audit.text
        assert len(audit.json()) == 1
