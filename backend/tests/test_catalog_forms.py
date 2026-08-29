from __future__ import annotations

from fastapi.testclient import TestClient


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


def _published_item(client: TestClient, token: str, user: dict) -> dict:
    category_response = client.post(
        "/api/v1/catalog/categories",
        headers=_headers(token),
        json={
            "code": "CAT_DYNAMIC_FORMS",
            "name": "Dynamic form services",
            "description": "Catalog forms integration test.",
        },
    )
    assert category_response.status_code == 201, category_response.text
    category = category_response.json()
    service_response = client.post(
        "/api/v1/catalog/services",
        headers=_headers(token),
        json={
            "category_id": category["id"],
            "code": "SVC_DYNAMIC_FORMS",
            "name": "Dynamic request management",
            "description": "Service used to verify versioned request forms.",
        },
    )
    assert service_response.status_code == 201, service_response.text
    service = service_response.json()
    item_response = client.post(
        "/api/v1/catalog/items",
        headers=_headers(token),
        json={
            "category_id": category["id"],
            "service_id": service["id"],
            "code": "REQ_DYNAMIC_FORM",
            "name": "Запрос доступа к корпоративной системе",
            "short_description": "Управляемый запрос доступа с динамической формой.",
            "description": (
                "Запрос предоставляет доступ после проверки обязательных данных "
                "и применения правил видимости."
            ),
            "owner_user_id": user["id"],
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
            headers=_headers(token),
            json={
                "expected_version": item["version"],
                "target_status": target,
                "reason": f"Accept catalog item for {target}",
            },
        )
        assert transition.status_code == 200, transition.text
        item = transition.json()
    return item


def _schema() -> dict:
    return {
        "title": "Данные для предоставления доступа",
        "introduction": "Ответьте на вопросы — скрытые поля не требуют заполнения.",
        "sections": [
            {
                "id": "access",
                "title": "Параметры доступа",
                "description": "Основные сведения о запросе.",
                "order": 10,
            }
        ],
        "fields": [
            {
                "key": "access_type",
                "label": "Тип пользователя",
                "type": "select",
                "section_id": "access",
                "required": True,
                "help_text": "",
                "placeholder": "",
                "options": [
                    {"value": "employee", "label": "Сотрудник"},
                    {"value": "vendor", "label": "Подрядчик"},
                ],
                "validations": {},
            },
            {
                "key": "manager_email",
                "label": "Email согласующего",
                "type": "email",
                "section_id": "access",
                "required": True,
                "help_text": "Обязательно только для подрядчика.",
                "placeholder": "manager@example.com",
                "options": [],
                "validations": {},
                "visibility": {
                    "field_key": "access_type",
                    "operator": "eq",
                    "value": "vendor",
                },
            },
            {
                "key": "licenses",
                "label": "Количество лицензий",
                "type": "number",
                "section_id": "access",
                "required": True,
                "help_text": "",
                "placeholder": "",
                "options": [],
                "validations": {"min": 1, "max": 100},
            },
            {
                "key": "justification",
                "label": "Обоснование",
                "type": "textarea",
                "section_id": "access",
                "required": True,
                "help_text": "",
                "placeholder": "Опишите рабочую необходимость",
                "options": [],
                "validations": {"min_length": 5, "max_length": 1000},
            },
        ],
    }


def test_catalog_form_versioning_and_server_validation(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = _login(client, "manager@sbs.local")
        requester_token, _ = _login(client, "requester@sbs.local")
        item = _published_item(client, manager_token, manager)

        standard_form = client.get(
            f"/api/v1/catalog/items/{item['id']}/form",
            headers=_headers(requester_token),
        )
        assert standard_form.status_code == 200
        assert standard_form.json()["version"] == 1
        assert standard_form.json()["status"] == "PUBLISHED"
        assert standard_form.json()["schema"]["fields"] == []

        initialized = client.post(
            f"/api/v1/catalog/items/{item['id']}/form/draft",
            headers=_headers(manager_token),
        )
        assert initialized.status_code == 201, initialized.text
        draft = initialized.json()
        assert draft["version"] == 2
        assert draft["revision"] == 1
        assert draft["status"] == "DRAFT"

        updated = client.put(
            f"/api/v1/catalog/items/{item['id']}/form/draft",
            headers=_headers(manager_token),
            json={
                "expected_revision": draft["revision"],
                "schema": _schema(),
                "attachment_rules": {
                    "enabled": False,
                    "required": False,
                    "max_files": 3,
                    "max_size_mb": 10,
                    "allowed_extensions": ["pdf", "png"],
                },
            },
        )
        assert updated.status_code == 200, updated.text
        draft = updated.json()
        assert draft["revision"] == 2

        stale = client.put(
            f"/api/v1/catalog/items/{item['id']}/form/draft",
            headers=_headers(manager_token),
            json={
                "expected_revision": 1,
                "schema": _schema(),
                "attachment_rules": draft["attachment_rules"],
            },
        )
        assert stale.status_code == 409

        published = client.post(
            f"/api/v1/catalog/items/{item['id']}/form/publish",
            headers=_headers(manager_token),
            json={
                "expected_revision": draft["revision"],
                "reason": "Форма проверена владельцем услуги",
            },
        )
        assert published.status_code == 200, published.text
        form = published.json()
        assert form["status"] == "PUBLISHED"
        assert len(form["schema_hash"]) == 64

        requester_form = client.get(
            f"/api/v1/catalog/items/{item['id']}/form",
            headers=_headers(requester_token),
        )
        assert requester_form.status_code == 200
        assert requester_form.json()["schema_hash"] == form["schema_hash"]

        employee = client.post(
            f"/api/v1/catalog/items/{item['id']}/form/validate",
            headers=_headers(requester_token),
            json={
                "values": {
                    "access_type": "employee",
                    "licenses": 2,
                    "justification": "Для выполнения рабочих задач",
                }
            },
        )
        assert employee.status_code == 200, employee.text
        assert employee.json()["valid"] is True
        assert "manager_email" not in employee.json()["visible_fields"]

        vendor = client.post(
            f"/api/v1/catalog/items/{item['id']}/form/validate",
            headers=_headers(requester_token),
            json={
                "values": {
                    "access_type": "vendor",
                    "licenses": 0,
                    "justification": "нет",
                }
            },
        )
        assert vendor.status_code == 200, vendor.text
        validation = vendor.json()
        assert validation["valid"] is False
        assert {"manager_email", "licenses", "justification"}.issubset(
            validation["errors"]
        )

        second_draft = client.post(
            f"/api/v1/catalog/items/{item['id']}/form/draft",
            headers=_headers(manager_token),
        )
        assert second_draft.status_code == 201
        assert second_draft.json()["version"] == 3
        versions = client.get(
            f"/api/v1/catalog/items/{item['id']}/form/versions",
            headers=_headers(manager_token),
        )
        assert versions.status_code == 200
        assert [(entry["version"], entry["status"]) for entry in versions.json()] == [
            (3, "DRAFT"),
            (2, "PUBLISHED"),
            (1, "RETIRED"),
        ]


def test_catalog_form_definition_rbac_and_tenant_isolation(app) -> None:
    with TestClient(app) as client:
        manager_token, manager = _login(client, "manager@sbs.local")
        agent_token, _ = _login(client, "agent.network@sbs.local")
        other_admin_token, _ = _login(client, "other.admin@sbs.local")
        item = _published_item(client, manager_token, manager)

        denied = client.post(
            f"/api/v1/catalog/items/{item['id']}/form/draft",
            headers=_headers(agent_token),
        )
        assert denied.status_code == 403

        hidden = client.get(
            f"/api/v1/catalog/items/{item['id']}/form?mode=draft",
            headers=_headers(other_admin_token),
        )
        assert hidden.status_code == 404

        draft_response = client.post(
            f"/api/v1/catalog/items/{item['id']}/form/draft",
            headers=_headers(manager_token),
        )
        draft = draft_response.json()
        invalid_schema = _schema()
        invalid_schema["fields"][1]["visibility"]["field_key"] = "missing_field"
        invalid = client.put(
            f"/api/v1/catalog/items/{item['id']}/form/draft",
            headers=_headers(manager_token),
            json={
                "expected_revision": draft["revision"],
                "schema": invalid_schema,
                "attachment_rules": {
                    "enabled": True,
                    "required": True,
                    "max_files": 3,
                    "max_size_mb": 10,
                    "allowed_extensions": ["pdf"],
                },
            },
        )
        assert invalid.status_code == 422
        assert "defined before" in str(invalid.json())
