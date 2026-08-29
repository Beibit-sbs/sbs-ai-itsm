from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.v1.routes.auth import AuthUserResponse
from app.api.v1.routes.requests import (
    _is_requester_only,
    _request_visibility_scopes,
)


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


def test_custom_request_visibility_scopes_fail_closed_and_compose() -> None:
    bare_reader = AuthUserResponse(
        id="bare-reader",
        email="bare-request-reader@example.invalid",
        full_name="Bare Request Reader",
        role="custom_request_reader",
        tenant_id="tenant-a",
        permissions=["requests.read"],
    )
    requester = AuthUserResponse(
        id="custom-requester",
        email="custom-requester@example.invalid",
        full_name="Custom Requester",
        role="custom_requester",
        tenant_id="tenant-a",
        permissions=["requests.read", "requests.scope.requester"],
    )
    fulfiller = AuthUserResponse(
        id="custom-fulfiller",
        email="custom-fulfiller@example.invalid",
        full_name="Custom Fulfiller",
        role="custom_fulfiller",
        tenant_id="tenant-a",
        permissions=["requests.read", "requests.fulfill"],
    )

    assert _request_visibility_scopes(bare_reader) == frozenset()
    assert _request_visibility_scopes(requester) == frozenset({"requester"})
    assert _is_requester_only(requester) is True
    assert _request_visibility_scopes(fulfiller) == frozenset({"all"})


def _published_catalog_form(
    client: TestClient,
    manager_token: str,
    manager: dict,
) -> tuple[dict, dict]:
    category_response = client.post(
        "/api/v1/catalog/categories",
        headers=_headers(manager_token),
        json={
            "code": "CAT_REQUEST_FULFILLMENT",
            "name": "Request fulfillment",
            "description": "Catalog category for request lifecycle tests.",
        },
    )
    assert category_response.status_code == 201, category_response.text
    category = category_response.json()
    service_response = client.post(
        "/api/v1/catalog/services",
        headers=_headers(manager_token),
        json={
            "category_id": category["id"],
            "code": "SVC_REQUEST_FULFILLMENT",
            "name": "Managed request fulfillment",
            "description": "Service with approval and fulfillment workflow.",
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
            "code": "REQ_LICENSE_ACCESS",
            "name": "Доступ к корпоративной системе",
            "short_description": "Управляемый запрос доступа к корпоративной системе.",
            "description": (
                "Запрос проходит серверную проверку формы, согласование и задачу "
                "исполнения с полной временной шкалой."
            ),
            "owner_user_id": manager["id"],
            "support_group": "Service Desk",
            "expected_delivery_minutes": 480,
            "approval_required": True,
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
                "reason": f"Publish request item: {target}",
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
    schema = {
        "title": "Параметры доступа",
        "introduction": "Опишите деловую необходимость.",
        "sections": [
            {
                "id": "details",
                "title": "Детали запроса",
                "description": "",
                "order": 10,
            }
        ],
        "fields": [
            {
                "key": "justification",
                "label": "Обоснование",
                "type": "textarea",
                "section_id": "details",
                "required": True,
                "help_text": "",
                "placeholder": "Рабочая необходимость",
                "options": [],
                "validations": {"min_length": 5, "max_length": 1000},
            }
        ],
    }
    updated_response = client.put(
        f"/api/v1/catalog/items/{item['id']}/form/draft",
        headers=_headers(manager_token),
        json={
            "expected_revision": draft["revision"],
            "schema": schema,
            "attachment_rules": {
                "enabled": False,
                "required": False,
                "max_files": 3,
                "max_size_mb": 10,
                "allowed_extensions": ["pdf"],
            },
        },
    )
    assert updated_response.status_code == 200, updated_response.text
    updated = updated_response.json()
    publish_response = client.post(
        f"/api/v1/catalog/items/{item['id']}/form/publish",
        headers=_headers(manager_token),
        json={
            "expected_revision": updated["revision"],
            "reason": "Form is ready for production request fulfillment.",
        },
    )
    assert publish_response.status_code == 200, publish_response.text
    return item, publish_response.json()


def _create_request(
    client: TestClient,
    requester_token: str,
    item: dict,
    form: dict,
    *,
    idempotency_key: str,
) -> dict:
    response = client.post(
        "/api/v1/requests",
        headers=_headers(requester_token),
        json={
            "catalog_item_id": item["id"],
            "form_version": form["version"],
            "schema_hash": form["schema_hash"],
            "values": {"justification": "Доступ нужен для рабочих задач"},
            "quantity": 1,
            "idempotency_key": idempotency_key,
            "approval_mode": "SEQUENTIAL",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_request_approval_fulfillment_and_idempotency(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = _login(client, "manager@sbs.local")
        requester_token, _ = _login(client, "requester@sbs.local")
        agent_token, agent = _login(client, "agent.network@sbs.local")
        other_admin_token, _ = _login(client, "other.admin@sbs.local")
        item, form = _published_catalog_form(client, manager_token, manager)

        created = _create_request(
            client,
            requester_token,
            item,
            form,
            idempotency_key="request-fulfillment-001",
        )
        assert created["status"] == "PENDING_APPROVAL"
        assert created["items"][0]["form_version"] == form["version"]
        assert created["items"][0]["schema_hash"] == form["schema_hash"]
        assert created["items"][0]["form_values"] == {
            "justification": "Доступ нужен для рабочих задач"
        }
        assert created["items"][0]["field_labels"] == {
            "justification": "Обоснование"
        }
        assert len(created["approvals"]) >= 1
        assert created["tasks"] == []

        personalized_catalog = client.get(
            "/api/v1/catalog/items?search=REQ_LICENSE_ACCESS",
            headers=_headers(requester_token),
        )
        assert personalized_catalog.status_code == 200, personalized_catalog.text
        assert personalized_catalog.json()[0]["request_count"] == 1
        assert personalized_catalog.json()[0]["last_requested_at"]

        duplicate = _create_request(
            client,
            requester_token,
            item,
            form,
            idempotency_key="request-fulfillment-001",
        )
        assert duplicate["id"] == created["id"]
        personalized_catalog = client.get(
            "/api/v1/catalog/items?search=REQ_LICENSE_ACCESS",
            headers=_headers(requester_token),
        )
        assert personalized_catalog.json()[0]["request_count"] == 1

        hidden = client.get(
            f"/api/v1/requests/{created['id']}",
            headers=_headers(other_admin_token),
        )
        assert hidden.status_code == 404

        denied_approval = client.post(
            f"/api/v1/requests/approvals/{created['approvals'][0]['id']}/decision",
            headers=_headers(agent_token),
            json={"decision": "APPROVED", "comment": "Not permitted"},
        )
        assert denied_approval.status_code == 403

        detail = created
        for approval in created["approvals"]:
            decision = client.post(
                f"/api/v1/requests/approvals/{approval['id']}/decision",
                headers=_headers(manager_token),
                json={"decision": "APPROVED", "comment": "Согласовано"},
            )
            assert decision.status_code == 200, decision.text
            detail = decision.json()

        assert detail["status"] == "IN_FULFILLMENT"
        assert detail["items"][0]["status"] == "IN_FULFILLMENT"
        assert len(detail["tasks"]) == 1
        task = detail["tasks"][0]

        requester_denied = client.post(
            f"/api/v1/requests/tasks/{task['id']}/transition",
            headers=_headers(requester_token),
            json={
                "expected_version": task["version"],
                "target_status": "IN_PROGRESS",
            },
        )
        assert requester_denied.status_code == 403

        assigned_response = client.post(
            f"/api/v1/requests/tasks/{task['id']}/assign",
            headers=_headers(agent_token),
            json={"expected_version": task["version"]},
        )
        assert assigned_response.status_code == 200, assigned_response.text
        task = assigned_response.json()["tasks"][0]
        assert task["assignee_id"] == agent["id"]

        started_response = client.post(
            f"/api/v1/requests/tasks/{task['id']}/transition",
            headers=_headers(agent_token),
            json={
                "expected_version": task["version"],
                "target_status": "IN_PROGRESS",
                "comment": "Работа начата",
            },
        )
        assert started_response.status_code == 200, started_response.text
        task = started_response.json()["tasks"][0]

        completed_response = client.post(
            f"/api/v1/requests/tasks/{task['id']}/transition",
            headers=_headers(agent_token),
            json={
                "expected_version": task["version"],
                "target_status": "COMPLETED",
                "comment": "Доступ предоставлен",
                "evidence": {"account": "provisioned", "verified": True},
            },
        )
        assert completed_response.status_code == 200, completed_response.text
        completed = completed_response.json()
        assert completed["status"] == "COMPLETED"
        assert completed["items"][0]["status"] == "COMPLETED"
        assert completed["tasks"][0]["evidence"]["verified"] is True
        assert any(
            event["event_type"] == "request.status_changed"
            for event in completed["activities"]
        )

        requester_view = client.get(
            f"/api/v1/requests/{created['id']}",
            headers=_headers(requester_token),
        )
        assert requester_view.status_code == 200
        assert requester_view.json()["status"] == "COMPLETED"


def test_request_rejection_rework_cancel_and_validation(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = _login(client, "manager@sbs.local")
        requester_token, _ = _login(client, "requester@sbs.local")
        item, form = _published_catalog_form(client, manager_token, manager)

        invalid = client.post(
            "/api/v1/requests",
            headers=_headers(requester_token),
            json={
                "catalog_item_id": item["id"],
                "form_version": form["version"],
                "schema_hash": form["schema_hash"],
                "values": {"justification": "нет"},
                "idempotency_key": "request-invalid-001",
            },
        )
        assert invalid.status_code == 422
        assert "justification" in str(invalid.json())

        created = _create_request(
            client,
            requester_token,
            item,
            form,
            idempotency_key="request-rework-001",
        )
        rejected_response = client.post(
            f"/api/v1/requests/approvals/{created['approvals'][0]['id']}/decision",
            headers=_headers(manager_token),
            json={
                "decision": "REJECTED",
                "comment": "Нужно уточнить деловую необходимость",
            },
        )
        assert rejected_response.status_code == 200, rejected_response.text
        rejected = rejected_response.json()
        assert rejected["status"] == "REJECTED"
        assert rejected["items"][0]["status"] == "REJECTED"

        rework_response = client.post(
            (
                f"/api/v1/requests/{created['id']}/items/"
                f"{rejected['items'][0]['id']}/rework"
            ),
            headers=_headers(requester_token),
            json={
                "expected_version": rejected["items"][0]["version"],
                "reason": "Обоснование уточнено с руководителем",
            },
        )
        assert rework_response.status_code == 200, rework_response.text
        reworked = rework_response.json()
        assert reworked["status"] == "PENDING_APPROVAL"
        assert max(entry["round"] for entry in reworked["approvals"]) == 2

        cancel_response = client.post(
            f"/api/v1/requests/{created['id']}/cancel",
            headers=_headers(requester_token),
            json={
                "expected_version": reworked["version"],
                "reason": "Потребность больше не актуальна",
            },
        )
        assert cancel_response.status_code == 200, cancel_response.text
        cancelled = cancel_response.json()
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["can_cancel"] is False
        assert all(
            entry["status"] != "PENDING" for entry in cancelled["approvals"]
        )


def test_saas_root_can_create_tenant_scoped_request(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = _login(client, "manager@sbs.local")
        root_token, root = _login(client, "saas.root@sbs.local")
        item, form = _published_catalog_form(client, manager_token, manager)

        created = _create_request(
            client,
            root_token,
            item,
            form,
            idempotency_key="root-request-fulfillment-001",
        )
        assert created["tenant_id"] == item["tenant_id"]
        assert created["requester_id"] == root["id"]
        assert created["requester_email"] == root["email"]
        assert created["status"] == "PENDING_APPROVAL"
