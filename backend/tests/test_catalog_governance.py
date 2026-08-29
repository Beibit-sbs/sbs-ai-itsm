from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select


def _login(client: TestClient, email: str) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sbs!2026"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["access_token"], payload["user"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _publish_governed_item(
    client: TestClient,
    manager_token: str,
    manager: dict,
) -> tuple[dict, dict]:
    category_response = client.post(
        "/api/v1/catalog/categories",
        headers=_headers(manager_token),
        json={
            "code": "CAT_GOVERNED_SOFTWARE",
            "name": "Governed software",
            "description": "Restricted and cost-controlled software services.",
        },
    )
    assert category_response.status_code == 201, category_response.text
    category = category_response.json()
    service_response = client.post(
        "/api/v1/catalog/services",
        headers=_headers(manager_token),
        json={
            "category_id": category["id"],
            "code": "SVC_GOVERNED_SOFTWARE",
            "name": "Enterprise software licensing",
            "description": "Software licensing with showback and SLA controls.",
        },
    )
    assert service_response.status_code == 201, service_response.text
    service = service_response.json()
    item_response = client.post(
        "/api/v1/catalog/items",
        headers=_headers(manager_token),
        json={
            "category_id": category["id"],
            "service_id": service["id"],
            "code": "REQ_FINANCE_LICENSE",
            "name": "Финансовая лицензия",
            "short_description": "Лицензия для финансового подразделения.",
            "description": (
                "Платная корпоративная лицензия, доступная только сотрудникам "
                "финансового подразделения в головном офисе."
            ),
            "owner_user_id": manager["id"],
            "support_group": "Workplace Support",
            "expected_delivery_minutes": 120,
            "approval_required": False,
            "entitlement_rules": {
                "match": "ALL",
                "roles": ["requester"],
                "departments": ["Finance"],
                "locations": ["HQ"],
                "cost_centers": ["CC-100"],
            },
            "unit_cost_minor": 150_000,
            "currency": "KZT",
            "cost_type": "MONTHLY",
            "risk_level": "HIGH",
            "approval_policy": {
                "cost_threshold_minor": 200_000,
                "minimum_risk": "HIGH",
                "approver_roles": ["it_manager"],
                "mode": "PARALLEL",
                "due_minutes": 60,
            },
            "sla_policy": {
                "target_minutes": 120,
                "ola_minutes": 60,
                "calendar_code": "24X7",
                "warning_percent": 80,
                "pause_on_waiting": True,
                "escalation_minutes": [0, 30],
            },
        },
    )
    assert item_response.status_code == 201, item_response.text
    item = item_response.json()
    for target in ("IN_REVIEW", "PUBLISHED"):
        transition = client.post(
            f"/api/v1/catalog/items/{item['id']}/transition",
            headers=_headers(manager_token),
            json={
                "expected_version": item["version"],
                "target_status": target,
                "reason": f"Governance acceptance: {target}",
            },
        )
        assert transition.status_code == 200, transition.text
        item = transition.json()

    draft_response = client.post(
        f"/api/v1/catalog/items/{item['id']}/form/draft",
        headers=_headers(manager_token),
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()
    publish_response = client.post(
        f"/api/v1/catalog/items/{item['id']}/form/publish",
        headers=_headers(manager_token),
        json={
            "expected_revision": draft["revision"],
            "reason": "Governed request form is ready.",
        },
    )
    assert publish_response.status_code == 200, publish_response.text
    return item, publish_response.json()


def _request_payload(item: dict, form: dict, *, key: str) -> dict:
    return {
        "catalog_item_id": item["id"],
        "form_version": form["version"],
        "schema_hash": form["schema_hash"],
        "values": {},
        "quantity": 2,
        "idempotency_key": key,
    }


def test_entitlement_cost_approval_sla_and_analytics(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = _login(client, "manager@sbs.local")
        admin_token, _ = _login(client, "admin@sbs.local")
        requester_token, requester = _login(client, "requester@sbs.local")
        agent_token, _ = _login(client, "agent.network@sbs.local")
        item, form = _publish_governed_item(client, manager_token, manager)

        hidden = client.get(
            "/api/v1/catalog/items",
            headers=_headers(requester_token),
        )
        assert hidden.status_code == 200
        assert item["id"] not in {entry["id"] for entry in hidden.json()}
        direct_read = client.get(
            f"/api/v1/catalog/items/{item['id']}",
            headers=_headers(requester_token),
        )
        assert direct_read.status_code == 404
        denied = client.post(
            "/api/v1/requests",
            headers=_headers(requester_token),
            json=_request_payload(item, form, key="governance-denied-001"),
        )
        assert denied.status_code == 403
        assert "entitlement" in str(denied.json()).lower()

        users_response = client.get(
            "/api/v1/admin/users",
            headers=_headers(admin_token),
        )
        assert users_response.status_code == 200, users_response.text
        requester_record = next(
            entry
            for entry in users_response.json()
            if entry["id"] == requester["id"]
        )
        profile_response = client.patch(
            f"/api/v1/admin/users/{requester['id']}",
            headers=_headers(admin_token),
            json={
                "full_name": requester_record["full_name"],
                "department": "Finance",
                "location": "HQ",
                "cost_center": "CC-100",
            },
        )
        assert profile_response.status_code == 200, profile_response.text
        assert profile_response.json()["cost_center"] == "CC-100"

        visible = client.get(
            "/api/v1/catalog/items",
            headers=_headers(requester_token),
        )
        assert visible.status_code == 200
        governed = next(
            entry for entry in visible.json() if entry["id"] == item["id"]
        )
        assert governed["is_entitled"] is True
        assert governed["unit_cost_minor"] == 150_000
        assert governed["risk_level"] == "HIGH"

        created_response = client.post(
            "/api/v1/requests",
            headers=_headers(requester_token),
            json=_request_payload(item, form, key="governance-approved-001"),
        )
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        requested_item = created["items"][0]
        assert created["total_cost_minor"] == 300_000
        assert created["currency"] == "KZT"
        assert created["cost_center"] == "CC-100"
        assert created["risk_level"] == "HIGH"
        assert requested_item["approval_required"] is True
        assert requested_item["approval_mode"] == "PARALLEL"
        assert requested_item["approval_policy_snapshot"]["decision"] is True
        assert requested_item["entitlement_snapshot"]["decision"] == "ALLOWED"
        assert requested_item["sla_status"] == "ACTIVE"
        assert requested_item["sla_due_at"]
        assert created["approvals"]
        assert all(
            approval["approver_name"] != "Назначит менеджер"
            for approval in created["approvals"]
        )

        approval = created["approvals"][0]
        approved_response = client.post(
            f"/api/v1/requests/approvals/{approval['id']}/decision",
            headers=_headers(manager_token),
            json={"decision": "APPROVED", "comment": "Cost and risk approved."},
        )
        assert approved_response.status_code == 200, approved_response.text
        approved = approved_response.json()
        task = approved["tasks"][0]
        assert task["due_at"]

        started_response = client.post(
            f"/api/v1/requests/tasks/{task['id']}/transition",
            headers=_headers(agent_token),
            json={
                "expected_version": task["version"],
                "target_status": "IN_PROGRESS",
                "comment": "Fulfillment started.",
            },
        )
        assert started_response.status_code == 200, started_response.text
        task = started_response.json()["tasks"][0]
        waiting_response = client.post(
            f"/api/v1/requests/tasks/{task['id']}/transition",
            headers=_headers(agent_token),
            json={
                "expected_version": task["version"],
                "target_status": "WAITING",
                "comment": "Waiting for supplier confirmation.",
            },
        )
        assert waiting_response.status_code == 200, waiting_response.text
        waiting = waiting_response.json()
        assert waiting["items"][0]["sla_status"] == "PAUSED"
        assert waiting["items"][0]["sla_paused_at"]

        task = waiting["tasks"][0]
        resumed_response = client.post(
            f"/api/v1/requests/tasks/{task['id']}/transition",
            headers=_headers(agent_token),
            json={
                "expected_version": task["version"],
                "target_status": "IN_PROGRESS",
                "comment": "Supplier confirmed.",
            },
        )
        assert resumed_response.status_code == 200, resumed_response.text
        resumed = resumed_response.json()
        assert resumed["items"][0]["sla_status"] in {"ACTIVE", "AT_RISK"}
        assert resumed["items"][0]["sla_paused_at"] is None

        from app.db.session import SessionLocal
        from app.models.service_request import RequestedItem

        with SessionLocal() as db:
            stored = db.scalar(
                select(RequestedItem).where(RequestedItem.id == requested_item["id"])
            )
            stored.sla_due_at = datetime.now(UTC) - timedelta(minutes=31)
            stored.sla_status = "ACTIVE"
            stored.sla_breached_at = None
            db.commit()

        evaluation_response = client.post(
            "/api/v1/requests/sla/evaluate",
            headers=_headers(manager_token),
        )
        assert evaluation_response.status_code == 200, evaluation_response.text
        evaluation = evaluation_response.json()
        assert evaluation["changed_count"] == 1
        assert evaluation["changed"][0]["status"] == "BREACHED"
        assert evaluation["changed"][0]["escalation_level"] == 2

        analytics_response = client.get(
            "/api/v1/requests/analytics/governance",
            headers=_headers(manager_token),
        )
        assert analytics_response.status_code == 200, analytics_response.text
        analytics = analytics_response.json()
        assert analytics["total_requests"] == 1
        assert analytics["currency_totals"]["KZT"] == 300_000
        assert analytics["cost_centers"][0]["cost_center"] == "CC-100"
        assert analytics["demand_by_item"][0]["item_code"] == "REQ_FINANCE_LICENSE"
        assert analytics["sla"]["BREACHED"] == 1


def test_catalog_governance_policy_validation(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = _login(client, "manager@sbs.local")
        category_response = client.post(
            "/api/v1/catalog/categories",
            headers=_headers(manager_token),
            json={"code": "CAT_INVALID_GOV", "name": "Invalid governance"},
        )
        category = category_response.json()
        service_response = client.post(
            "/api/v1/catalog/services",
            headers=_headers(manager_token),
            json={
                "category_id": category["id"],
                "code": "SVC_INVALID_GOV",
                "name": "Invalid governance service",
            },
        )
        service = service_response.json()
        response = client.post(
            "/api/v1/catalog/items",
            headers=_headers(manager_token),
            json={
                "category_id": category["id"],
                "service_id": service["id"],
                "code": "REQ_INVALID_GOV",
                "name": "Invalid governance request",
                "short_description": "Invalid governance policy acceptance.",
                "description": "This request must reject an unsupported policy field.",
                "owner_user_id": manager["id"],
                "support_group": "Service Desk",
                "entitlement_rules": {"unsupported": ["value"]},
            },
        )
        assert response.status_code == 422
        assert "unsupported entitlement" in str(response.json()).lower()
