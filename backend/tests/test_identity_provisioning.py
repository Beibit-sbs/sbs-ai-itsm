from __future__ import annotations

from fastapi.testclient import TestClient


ENTERPRISE_USER_SCHEMA = (
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
)


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _admin_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _scim_headers(token: str, request_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/scim+json",
        "X-Request-ID": request_id,
    }


def _tenant_role(client: TestClient, token: str, code: str) -> dict:
    response = client.get("/api/v1/admin/roles", headers=_admin_headers(token))
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["code"] == code)


def _user(client: TestClient, token: str, email: str) -> dict:
    response = client.get("/api/v1/admin/users", headers=_admin_headers(token))
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["email"] == email)


def _connector(
    client: TestClient,
    admin_token: str,
    *,
    name: str = "Test Entra",
) -> tuple[dict, str]:
    default_role = _tenant_role(client, admin_token, "requester")
    fallback = _user(client, admin_token, "admin@sbs.local")
    created = client.post(
        "/api/v1/identity-provisioning/connectors",
        headers=_admin_headers(admin_token),
        json={
            "name": name,
            "provider_type": "ENTRA",
            "external_tenant_id": f"{name.lower().replace(' ', '-')}-tenant",
            "default_role_id": default_role["id"],
            "fallback_owner_id": fallback["id"],
            "retry_max_attempts": 3,
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["bearer_token"].startswith("sbs_scim_")
    connector = payload["connector"]
    activated = client.post(
        f"/api/v1/identity-provisioning/connectors/{connector['id']}/state",
        headers=_admin_headers(admin_token),
        json={
            "expected_version": connector["version"],
            "action": "ACTIVATE",
            "reason": "Integration acceptance test",
        },
    )
    assert activated.status_code == 200, activated.text
    return activated.json(), payload["bearer_token"]


def _scim_user_payload(
    external_id: str,
    email: str,
    full_name: str,
    *,
    department: str = "IT",
    manager: str | None = None,
) -> dict:
    enterprise: dict = {
        "employeeNumber": external_id,
        "department": department,
        "costCenter": "CC-100",
    }
    if manager:
        enterprise["manager"] = {"value": manager}
    return {
        "schemas": [
            "urn:ietf:params:scim:schemas:core:2.0:User",
            ENTERPRISE_USER_SCHEMA,
        ],
        "externalId": external_id,
        "userName": email,
        "displayName": full_name,
        "title": "Engineer",
        "active": True,
        ENTERPRISE_USER_SCHEMA: enterprise,
    }


def test_connector_secret_is_one_time_and_scim_discovery_is_compliant(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        connector, scim_token = _connector(client, admin)

        listed = client.get(
            "/api/v1/identity-provisioning/connectors",
            headers=_admin_headers(admin),
        )
        assert listed.status_code == 200, listed.text
        listed_connector = next(
            item for item in listed.json() if item["id"] == connector["id"]
        )
        assert "bearer_token" not in listed_connector
        assert "token_hash" not in listed_connector
        assert listed_connector["token_hint"]

        discovery = client.get(
            "/api/v1/scim/v2/ServiceProviderConfig",
            headers=_scim_headers(scim_token, "discovery-1"),
        )
        assert discovery.status_code == 200, discovery.text
        assert discovery.headers["content-type"].startswith("application/scim+json")
        assert discovery.json()["patch"]["supported"] is True
        assert discovery.json()["etag"]["supported"] is True

        resource_type = client.get(
            "/api/v1/scim/v2/ResourceTypes/User",
            headers=_scim_headers(scim_token, "discovery-2"),
        )
        assert resource_type.status_code == 200, resource_type.text
        assert resource_type.json()["endpoint"] == "/Users"

        schema = client.get(
            f"/api/v1/scim/v2/Schemas/{ENTERPRISE_USER_SCHEMA}",
            headers=_scim_headers(scim_token, "discovery-3"),
        )
        assert schema.status_code == 200, schema.text
        assert schema.json()["name"] == "EnterpriseUser"

        invalid = client.get(
            "/api/v1/scim/v2/Users",
            headers={"Authorization": "Bearer invalid"},
        )
        assert invalid.status_code == 401
        assert invalid.json()["schemas"] == [
            "urn:ietf:params:scim:api:messages:2.0:Error"
        ]


def test_scim_joiner_mover_etag_and_idempotency(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        _, scim_token = _connector(client, admin, name="JML Entra")

        manager_created = client.post(
            "/api/v1/scim/v2/Users",
            headers=_scim_headers(scim_token, "manager-create"),
            json=_scim_user_payload(
                "manager-external",
                "entra.manager@example.test",
                "Entra Manager",
            ),
        )
        assert manager_created.status_code == 201, manager_created.text
        manager = manager_created.json()

        employee_payload = _scim_user_payload(
            "employee-external",
            "entra.employee@example.test",
            "Entra Employee",
            manager="manager-external",
        )
        employee_created = client.post(
            "/api/v1/scim/v2/Users",
            headers=_scim_headers(scim_token, "employee-create"),
            json=employee_payload,
        )
        assert employee_created.status_code == 201, employee_created.text
        employee = employee_created.json()
        assert employee["active"] is True
        assert employee["meta"]["version"] == 'W/"1"'

        replayed = client.post(
            "/api/v1/scim/v2/Users",
            headers=_scim_headers(scim_token, "employee-create"),
            json=employee_payload,
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["id"] == employee["id"]

        filtered = client.get(
            '/api/v1/scim/v2/Users?filter=userName%20eq%20%22entra.employee@example.test%22',
            headers=_scim_headers(scim_token, "employee-filter"),
        )
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["totalResults"] == 1

        stale = client.patch(
            f"/api/v1/scim/v2/Users/{employee['id']}",
            headers={
                **_scim_headers(scim_token, "employee-stale"),
                "If-Match": 'W/"999"',
            },
            json={
                "schemas": [
                    "urn:ietf:params:scim:api:messages:2.0:PatchOp"
                ],
                "Operations": [
                    {"op": "Replace", "path": "title", "value": "Senior Engineer"}
                ],
            },
        )
        assert stale.status_code == 412

        moved = client.patch(
            f"/api/v1/scim/v2/Users/{employee['id']}",
            headers={
                **_scim_headers(scim_token, "employee-move"),
                "If-Match": employee["meta"]["version"],
            },
            json={
                "schemas": [
                    "urn:ietf:params:scim:api:messages:2.0:PatchOp"
                ],
                "Operations": [
                    {
                        "op": "Replace",
                        "path": f"{ENTERPRISE_USER_SCHEMA}:department",
                        "value": "Platform Engineering",
                    },
                    {
                        "op": "Replace",
                        "path": "title",
                        "value": "Senior Engineer",
                    },
                ],
            },
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()[ENTERPRISE_USER_SCHEMA]["department"] == (
            "Platform Engineering"
        )

        employee_admin = _user(
            client,
            admin,
            "entra.employee@example.test",
        )
        manager_admin = _user(
            client,
            admin,
            "entra.manager@example.test",
        )
        assert employee_admin["identity_source"] == "ENTRA"
        assert employee_admin["manager_id"] == manager_admin["id"]


def test_group_mapping_and_entra_member_filter_removal(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        _, scim_token = _connector(client, admin, name="Group Entra")
        created = client.post(
            "/api/v1/scim/v2/Users",
            headers=_scim_headers(scim_token, "group-user-create"),
            json=_scim_user_payload(
                "group-user",
                "group.user@example.test",
                "Group User",
            ),
        )
        assert created.status_code == 201, created.text
        identity = created.json()

        group_created = client.post(
            "/api/v1/scim/v2/Groups",
            headers=_scim_headers(scim_token, "group-create"),
            json={
                "schemas": [
                    "urn:ietf:params:scim:schemas:core:2.0:Group"
                ],
                "externalId": "entra-it-agents",
                "displayName": "SBS IT Agents",
                "members": [{"value": identity["id"]}],
            },
        )
        assert group_created.status_code == 201, group_created.text
        group = group_created.json()
        role = _tenant_role(client, admin, "it_agent")
        admin_groups = client.get(
            "/api/v1/identity-provisioning/groups",
            headers=_admin_headers(admin),
        )
        assert admin_groups.status_code == 200, admin_groups.text
        admin_group = next(
            item for item in admin_groups.json() if item["id"] == group["id"]
        )
        mapped = client.patch(
            f"/api/v1/identity-provisioning/groups/{group['id']}/role-mapping",
            headers=_admin_headers(admin),
            json={
                "expected_version": admin_group["scim_version"],
                "role_id": role["id"],
            },
        )
        assert mapped.status_code == 200, mapped.text

        user = _user(client, admin, "group.user@example.test")
        roles = client.get(
            f"/api/v1/admin/users/{user['id']}/roles",
            headers=_admin_headers(admin),
        )
        assert roles.status_code == 200, roles.text
        assert "it_agent" in {item["code"] for item in roles.json()}

        group_after_mapping = mapped.json()
        removed = client.patch(
            f"/api/v1/scim/v2/Groups/{group['id']}",
            headers={
                **_scim_headers(scim_token, "group-remove-member"),
                "If-Match": f'W/"{group_after_mapping["scim_version"]}"',
            },
            json={
                "schemas": [
                    "urn:ietf:params:scim:api:messages:2.0:PatchOp"
                ],
                "Operations": [
                    {
                        "op": "Remove",
                        "path": f'members[value eq "{identity["id"]}"]',
                    }
                ],
            },
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["members"] == []

        fallback_roles = client.get(
            f"/api/v1/admin/users/{user['id']}/roles",
            headers=_admin_headers(admin),
        )
        assert fallback_roles.status_code == 200, fallback_roles.text
        assert {item["code"] for item in fallback_roles.json()} == {"requester"}


def test_scim_leaver_transfers_work_and_revokes_access(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        _, scim_token = _connector(client, admin, name="Leaver Entra")
        created = client.post(
            "/api/v1/scim/v2/Users",
            headers=_scim_headers(scim_token, "leaver-create"),
            json=_scim_user_payload(
                "leaver-external",
                "leaver@example.test",
                "Departing Engineer",
            ),
        )
        assert created.status_code == 201, created.text
        identity = created.json()
        leaver = _user(client, admin, "leaver@example.test")
        fallback = _user(client, admin, "admin@sbs.local")

        ticket = client.post(
            "/api/v1/tickets",
            headers=_admin_headers(admin),
            json={
                "title": "Work must survive offboarding",
                "description": "Assigned work is transferred before access is revoked.",
                "requester_name": "Business Requester",
                "requester_email": "requester@sbs.local",
                "on_behalf_reason": "Requester reported work before offboarding",
                "department": "Business",
                "location": "HQ",
                "category": "NETWORK_INTERNET",
                "priority": "MEDIUM",
                "assignee_id": leaver["id"],
            },
        )
        assert ticket.status_code == 201, ticket.text

        preview = client.get(
            (
                "/api/v1/identity-provisioning/identities/"
                f"{identity['id']}/ownership"
            ),
            headers=_admin_headers(admin),
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["counts"]["ticket_assignments"] == 1

        deleted = client.delete(
            f"/api/v1/scim/v2/Users/{identity['id']}",
            headers={
                **_scim_headers(scim_token, "leaver-delete"),
                "If-Match": identity["meta"]["version"],
            },
        )
        assert deleted.status_code == 204, deleted.text

        updated_ticket = client.get(
            f"/api/v1/tickets/{ticket.json()['id']}",
            headers=_admin_headers(admin),
        )
        assert updated_ticket.status_code == 200, updated_ticket.text
        assert updated_ticket.json()["assignee_id"] == fallback["id"]

        leaver_after = _user(client, admin, "leaver@example.test")
        assert leaver_after["is_active"] is False
        assert leaver_after["provisioning_state"] == "DEPROVISIONED"
        assert leaver_after["deactivated_at"] is not None

        transfers = client.get(
            "/api/v1/identity-provisioning/ownership-transfers",
            headers=_admin_headers(admin),
        )
        assert transfers.status_code == 200, transfers.text
        transfer = next(
            item
            for item in transfers.json()["items"]
            if item["from_user_id"] == leaver["id"]
        )
        assert transfer["to_user_id"] == fallback["id"]
        assert transfer["counts"]["ticket_assignments"] == 1


def test_failed_scim_request_rolls_back_resource_and_enters_dead_letter(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        _, scim_token = _connector(client, admin, name="Failure Entra")
        failed = client.post(
            "/api/v1/scim/v2/Groups",
            headers=_scim_headers(scim_token, "unknown-member-group"),
            json={
                "schemas": [
                    "urn:ietf:params:scim:schemas:core:2.0:Group"
                ],
                "externalId": "invalid-group",
                "displayName": "Must Roll Back",
                "members": [{"value": "unknown-user"}],
            },
        )
        assert failed.status_code == 400, failed.text
        assert failed.json()["scimType"] == "invalidValue"

        groups = client.get(
            '/api/v1/scim/v2/Groups?filter=externalId%20eq%20%22invalid-group%22',
            headers=_scim_headers(scim_token, "verify-group-rollback"),
        )
        assert groups.status_code == 200, groups.text
        assert groups.json()["totalResults"] == 0

        events = client.get(
            "/api/v1/identity-provisioning/events?status=DEAD_LETTER",
            headers=_admin_headers(admin),
        )
        assert events.status_code == 200, events.text
        event = next(
            item
            for item in events.json()["items"]
            if item["external_event_id"] == "unknown-member-group"
        )
        assert event["attempts"] == 1
        assert "Unknown group member" in event["error_message"]


def test_identity_admin_and_scim_are_tenant_isolated(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        other_admin = _login(client, "other.admin@sbs.local")
        _, scim_token = _connector(client, admin, name="Isolation Entra")
        created = client.post(
            "/api/v1/scim/v2/Users",
            headers=_scim_headers(scim_token, "isolated-user"),
            json=_scim_user_payload(
                "isolated-external",
                "isolated@example.test",
                "Isolated User",
            ),
        )
        assert created.status_code == 201, created.text

        hidden_connectors = client.get(
            "/api/v1/identity-provisioning/connectors",
            headers=_admin_headers(other_admin),
        )
        assert hidden_connectors.status_code == 200, hidden_connectors.text
        assert hidden_connectors.json() == []

        hidden_identities = client.get(
            "/api/v1/identity-provisioning/identities",
            headers=_admin_headers(other_admin),
        )
        assert hidden_identities.status_code == 200, hidden_identities.text
        assert hidden_identities.json()["total"] == 0
