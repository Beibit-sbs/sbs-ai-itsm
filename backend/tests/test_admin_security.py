from fastapi.testclient import TestClient


def _login(client, email: str, password: str):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _tenant_roles_by_code(roles: list[dict]) -> dict[str, dict]:
    """Return only assignable organization roles, excluding global templates."""
    return {
        role["code"]: role
        for role in roles
        if role.get("tenant_id") is not None
    }


def test_admin_users_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        users = response.json()
        assert len(users) >= 7


def test_create_user(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        roles = client.get("/api/v1/admin/roles", headers={"Authorization": f"Bearer {token}"}).json()
        role_id = _tenant_roles_by_code(roles)["requester"]["id"]

        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "new.requester@sbs.local",
                "full_name": "New Requester",
                "password": "Sbs!2026-Strong",
                "position": "Specialist",
                "department": "Business",
                "phone": "+70000000111",
                "role_id": role_id,
            },
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["email"] == "new.requester@sbs.local"
        assert payload["must_change_password"] is True


def test_update_user(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        user_id = next(item["id"] for item in client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json() if item["email"] == "requester@sbs.local")
        response = client.patch(
            f"/api/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"position": "Senior Specialist"},
        )
        assert response.status_code == 200
        assert response.json()["position"] == "Senior Specialist"


def test_deactivate_user(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        user_id = next(item["id"] for item in client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json() if item["email"] == "agent.support@sbs.local")
        response = client.patch(f"/api/v1/admin/users/{user_id}/deactivate", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["is_active"] is False


def test_roles_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/roles", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert {item["code"] for item in payload} >= {"organization_admin", "it_agent", "requester"}


def test_permissions_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/permissions", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 20
        assert {item["code"] for item in payload} >= {"admin.users.read", "security.audit.read"}


def test_assign_role_to_user(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        users = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json()
        target_user = next(item for item in users if item["email"] == "requester@sbs.local")
        roles = client.get("/api/v1/admin/roles", headers={"Authorization": f"Bearer {token}"}).json()
        requester_role = _tenant_roles_by_code(roles)["requester"]

        response = client.post(
            f"/api/v1/admin/users/{target_user['id']}/roles",
            headers={"Authorization": f"Bearer {token}"},
            json={"role_ids": [requester_role["id"]]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert any(item["code"] == "requester" for item in payload)


def test_multiple_roles_produce_an_effective_permission_union(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        headers = {"Authorization": f"Bearer {admin_token}"}
        users = client.get("/api/v1/admin/users", headers=headers).json()
        requester = next(
            item for item in users if item["email"] == "requester@sbs.local"
        )
        roles = client.get("/api/v1/admin/roles", headers=headers).json()
        roles_by_code = _tenant_roles_by_code(roles)
        selected_roles = [
            roles_by_code["requester"],
            roles_by_code["it_agent"],
        ]

        response = client.post(
            f"/api/v1/admin/users/{requester['id']}/roles",
            headers=headers,
            json={"role_ids": [role["id"] for role in selected_roles]},
        )
        assert response.status_code == 200
        assert {role["code"] for role in response.json()} == {
            "requester",
            "it_agent",
        }

        user_token = _login(client, "requester@sbs.local", "Sbs!2026")
        current_user = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert current_user.status_code == 200
        assert current_user.json()["role"] == "requester"
        assert {
            "requests.create",
            "tickets.update",
        } <= set(current_user.json()["permissions"])


def test_create_user_with_multiple_roles_preserves_primary_order(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        headers = {"Authorization": f"Bearer {admin_token}"}
        roles = client.get("/api/v1/admin/roles", headers=headers).json()
        roles_by_code = _tenant_roles_by_code(roles)

        created = client.post(
            "/api/v1/admin/users",
            headers=headers,
            json={
                "email": "multi.role.user@sbs.local",
                "full_name": "Multi Role User",
                "password": "Strong!Password-2026",
                "role_ids": [
                    roles_by_code["requester"]["id"],
                    roles_by_code["it_agent"]["id"],
                ],
            },
        )
        assert created.status_code == 201

        assigned = client.get(
            f"/api/v1/admin/users/{created.json()['id']}/roles",
            headers=headers,
        )
        assert assigned.status_code == 200
        assert {role["code"] for role in assigned.json()} == {
            "requester",
            "it_agent",
        }

        user_token = _login(
            client,
            "multi.role.user@sbs.local",
            "Strong!Password-2026",
        )
        current_user = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {user_token}"},
        ).json()
        assert current_user["role"] == "requester"
        assert {
            "requests.create",
            "tickets.update",
        } <= set(current_user["permissions"])


def test_organization_admin_cannot_assign_global_root_role(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        users = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        requester = next(item for item in users if item["email"] == "requester@sbs.local")
        roles = client.get(
            "/api/v1/admin/roles",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        root_role = next(item for item in roles if item["code"] == "saas_root")

        response = client.post(
            f"/api/v1/admin/users/{requester['id']}/roles",
            headers={"Authorization": f"Bearer {token}"},
            json={"role_ids": [root_role["id"]]},
        )

        assert response.status_code == 403


def test_root_user_creation_requires_matching_tenant_role(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "saas.root@sbs.local", "Sbs!2026")
        headers = {"Authorization": f"Bearer {token}"}
        tenants = client.get("/api/v1/tenants", headers=headers).json()
        primary_tenant = next(item for item in tenants if item["slug"] == "demo-tenant")
        other_tenant = next(item for item in tenants if item["slug"] == "demo-tenant-2")
        roles = client.get("/api/v1/admin/roles", headers=headers).json()
        requester_role = next(
            item
            for item in roles
            if item["tenant_id"] == primary_tenant["id"] and item["code"] == "requester"
        )
        other_admin_role = next(
            item
            for item in roles
            if item["tenant_id"] == other_tenant["id"]
            and item["code"] == "organization_admin"
        )
        root_role = next(
            item
            for item in roles
            if item["tenant_id"] is None and item["code"] == "saas_root"
        )

        valid = client.post(
            "/api/v1/admin/users",
            headers=headers,
            json={
                "tenant_id": primary_tenant["id"],
                "email": "root.created.user@sbs.local",
                "full_name": "Root Created User",
                "password": "Strong!Password-2026",
                "role_id": requester_role["id"],
            },
        )
        assert valid.status_code == 201, valid.text
        assert valid.json()["tenant_id"] == primary_tenant["id"]

        missing_tenant = client.post(
            "/api/v1/admin/users",
            headers=headers,
            json={
                "email": "missing.tenant@sbs.local",
                "full_name": "Missing Tenant",
                "password": "Strong!Password-2026",
                "role_id": requester_role["id"],
            },
        )
        assert missing_tenant.status_code == 422

        cross_tenant = client.post(
            "/api/v1/admin/users",
            headers=headers,
            json={
                "tenant_id": primary_tenant["id"],
                "email": "cross.tenant.role@sbs.local",
                "full_name": "Cross Tenant Role",
                "password": "Strong!Password-2026",
                "role_id": other_admin_role["id"],
            },
        )
        assert cross_tenant.status_code == 422

        global_role = client.post(
            "/api/v1/admin/users",
            headers=headers,
            json={
                "tenant_id": primary_tenant["id"],
                "email": "global.role@sbs.local",
                "full_name": "Global Role",
                "password": "Strong!Password-2026",
                "role_id": root_role["id"],
            },
        )
        assert global_role.status_code == 403

        user_id = valid.json()["id"]
        cross_assignment = client.post(
            f"/api/v1/admin/users/{user_id}/roles",
            headers=headers,
            json={"role_ids": [other_admin_role["id"]]},
        )
        global_assignment = client.post(
            f"/api/v1/admin/users/{user_id}/roles",
            headers=headers,
            json={"role_ids": [root_role["id"]]},
        )
        assert cross_assignment.status_code == 422
        assert global_assignment.status_code == 403


def test_tenant_role_permissions_can_be_managed(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        created = client.post(
            "/api/v1/admin/roles",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": "service_desk_lead",
                "name": "Service Desk Lead",
                "description": "Tenant support lead",
                "is_system": True,
            },
        )
        assert created.status_code == 201
        role = created.json()
        assert role["is_system"] is False

        permissions = client.get(
            "/api/v1/admin/permissions",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        selected = [
            item
            for item in permissions
            if item["code"] in {
                "tickets.read",
                "tickets.scope.all",
                "tickets.update",
                "analytics.tickets.read",
            }
        ]
        response = client.put(
            f"/api/v1/admin/roles/{role['id']}/permissions",
            headers={"Authorization": f"Bearer {token}"},
            json={"permission_ids": [item["id"] for item in selected]},
        )
        assert response.status_code == 200
        assert {item["code"] for item in response.json()} == {
            "tickets.read",
            "tickets.scope.all",
            "tickets.update",
            "analytics.tickets.read",
        }

        reloaded = client.get(
            f"/api/v1/admin/roles/{role['id']}/permissions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reloaded.status_code == 200
        assert {item["code"] for item in reloaded.json()} == {
            "tickets.read",
            "tickets.scope.all",
            "tickets.update",
            "analytics.tickets.read",
        }

        tickets_read = next(
            item for item in permissions if item["code"] == "tickets.read"
        )
        invalid = client.put(
            f"/api/v1/admin/roles/{role['id']}/permissions",
            headers={"Authorization": f"Bearer {token}"},
            json={"permission_ids": [tickets_read["id"]]},
        )
        assert invalid.status_code == 422
        assert "visibility scope" in invalid.json()["error"]["message"]

        persisted = client.get(
            f"/api/v1/admin/roles/{role['id']}/permissions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert persisted.status_code == 200
        assert "tickets.scope.all" in {
            item["code"] for item in persisted.json()
        }


def test_service_request_read_requires_record_visibility_scope(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        headers = {"Authorization": f"Bearer {token}"}
        role = client.post(
            "/api/v1/admin/roles",
            headers=headers,
            json={
                "code": "request_scope_guard",
                "name": "Request Scope Guard",
                "description": "Regression role for request visibility",
                "is_system": True,
            },
        ).json()
        permissions = client.get(
            "/api/v1/admin/permissions",
            headers=headers,
        ).json()
        requests_read = next(
            item for item in permissions if item["code"] == "requests.read"
        )

        response = client.put(
            f"/api/v1/admin/roles/{role['id']}/permissions",
            headers=headers,
            json={"permission_ids": [requests_read["id"]]},
        )
        assert response.status_code == 422
        assert "visibility scope" in response.json()["error"]["message"]


def test_organization_admin_cannot_amplify_or_delegate_privileges(app) -> None:
    with TestClient(app) as client:
        organization_token = _login(client, "admin@sbs.local", "Sbs!2026")
        organization_headers = {
            "Authorization": f"Bearer {organization_token}"
        }
        created = client.post(
            "/api/v1/admin/roles",
            headers=organization_headers,
            json={
                "code": "bounded_delegate",
                "name": "Bounded Delegate",
            },
        )
        assert created.status_code == 201
        role_id = created.json()["id"]

        visible_permissions = client.get(
            "/api/v1/admin/permissions",
            headers=organization_headers,
        ).json()
        assert "tenant.manage" not in {
            item["code"] for item in visible_permissions
        }

        root_token = _login(client, "saas.root@sbs.local", "Sbs!2026")
        root_headers = {"Authorization": f"Bearer {root_token}"}
        permissions = client.get(
            "/api/v1/admin/permissions",
            headers=root_headers,
        ).json()
        root_only_permission = next(
            item for item in permissions if item["code"] == "tenant.manage"
        )
        amplification = client.put(
            f"/api/v1/admin/roles/{role_id}/permissions",
            headers=organization_headers,
            json={"permission_ids": [root_only_permission["id"]]},
        )
        assert amplification.status_code == 403

        root_grant = client.put(
            f"/api/v1/admin/roles/{role_id}/permissions",
            headers=root_headers,
            json={"permission_ids": [root_only_permission["id"]]},
        )
        assert root_grant.status_code == 200

        users = client.get(
            "/api/v1/admin/users",
            headers=organization_headers,
        ).json()
        requester = next(
            item for item in users if item["email"] == "requester@sbs.local"
        )
        assignment = client.post(
            f"/api/v1/admin/users/{requester['id']}/roles",
            headers=organization_headers,
            json={"role_ids": [role_id]},
        )
        assert assignment.status_code == 403

        creation = client.post(
            "/api/v1/admin/users",
            headers=organization_headers,
            json={
                "email": "privilege.escalation@sbs.local",
                "full_name": "Privilege Escalation",
                "password": "Strong!Password-2026",
                "role_id": role_id,
            },
        )
        assert creation.status_code == 403


def test_global_role_is_read_only_for_organization_admin(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        roles = client.get(
            "/api/v1/admin/roles",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        root_role = next(item for item in roles if item["code"] == "saas_root")

        response = client.patch(
            f"/api/v1/admin/roles/{root_role['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Escalated root"},
        )

        assert response.status_code == 403


def test_system_tenant_roles_are_read_only_for_organization_admin(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        headers = {"Authorization": f"Bearer {token}"}
        roles = client.get("/api/v1/admin/roles", headers=headers).json()
        organization_role = next(
            item for item in roles if item["code"] == "organization_admin"
        )
        permissions_before = client.get(
            f"/api/v1/admin/roles/{organization_role['id']}/permissions",
            headers=headers,
        ).json()

        patch_response = client.patch(
            f"/api/v1/admin/roles/{organization_role['id']}",
            headers=headers,
            json={"name": "Unsafe renamed administrator"},
        )
        permission_response = client.put(
            f"/api/v1/admin/roles/{organization_role['id']}/permissions",
            headers=headers,
            json={"permission_ids": []},
        )

        assert patch_response.status_code == 403
        assert permission_response.status_code == 403
        permissions_after = client.get(
            f"/api/v1/admin/roles/{organization_role['id']}/permissions",
            headers=headers,
        ).json()
        assert permissions_after == permissions_before


def test_last_active_organization_admin_cannot_remove_own_admin_role(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        headers = {"Authorization": f"Bearer {token}"}
        users = client.get("/api/v1/admin/users", headers=headers).json()
        current_admin = next(
            item for item in users if item["email"] == "admin@sbs.local"
        )
        roles = client.get("/api/v1/admin/roles", headers=headers).json()
        organization_role = next(
            item for item in roles if item["code"] == "organization_admin"
        )
        requester_role = next(
            item for item in roles if item["code"] == "requester"
        )
        requester = next(
            item for item in users if item["email"] == "requester@sbs.local"
        )

        blocked = client.post(
            f"/api/v1/admin/users/{current_admin['id']}/roles",
            headers=headers,
            json={"role_ids": [requester_role["id"]]},
        )
        assert blocked.status_code == 409

        root_token = _login(client, "saas.root@sbs.local", "Sbs!2026")
        lifecycle_blocked = client.post(
            (
                "/api/v1/identity-provisioning/users/"
                f"{current_admin['id']}/safe-deactivate"
            ),
            headers={"Authorization": f"Bearer {root_token}"},
            json={
                "fallback_owner_id": requester["id"],
                "reason": "Continuity regression",
            },
        )
        assert lifecycle_blocked.status_code == 409

        replacement = client.post(
            "/api/v1/admin/users",
            headers=headers,
            json={
                "email": "replacement.admin@sbs.local",
                "full_name": "Replacement Administrator",
                "password": "Strong!Password-2026",
                "role_id": organization_role["id"],
            },
        )
        assert replacement.status_code == 201

        allowed = client.post(
            f"/api/v1/admin/users/{current_admin['id']}/roles",
            headers=headers,
            json={"role_ids": [requester_role["id"]]},
        )
        assert allowed.status_code == 200
        assert [item["code"] for item in allowed.json()] == ["requester"]


def test_audit_logs_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "security@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/audit-logs", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 1


def test_settings_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/settings", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        payload = response.json()
        assert {item["key"] for item in payload} >= {"password_min_length", "ai_copilot_enabled"}
        keys = [item["key"] for item in payload]
        assert len(keys) == len(set(keys))


def test_update_setting(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.patch(
            "/api/v1/admin/configuration-center/settings/session_timeout_minutes",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "expected_revision": 0,
                "value": 75,
                "reason": "Validated session policy update",
            },
        )
        assert response.status_code == 200
        assert response.json()["value"] == 75


def test_ai_provider_config_read_and_update(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        initial = client.get("/api/v1/admin/ai-provider-config", headers={"Authorization": f"Bearer {token}"})
        assert initial.status_code == 200
        assert initial.json()["provider"] in {"mock", "openai", "gemini"}

        updated = client.patch(
            "/api/v1/admin/ai-provider-config",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "provider": "openai",
                "openai_model": "gpt-4o-mini",
                "openai_base_url": "https://api.openai.com/v1",
                "pii_redaction_enabled": True,
                "request_timeout_seconds": 22,
                "openai_api_key": "sk-demo-test",
            },
        )
        assert updated.status_code == 200
        payload = updated.json()
        assert payload["provider"] == "openai"
        assert payload["openai_model"] == "gpt-4o-mini"
        assert payload["openai_api_key_configured"] is True
        assert payload["request_timeout_seconds"] == 22
        assert "sk-demo-test" not in updated.text

        reloaded = client.get(
            "/api/v1/admin/ai-provider-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reloaded.status_code == 200
        assert reloaded.json()["openai_api_key_configured"] is True
        assert "sk-demo-test" not in reloaded.text
        from app.db.session import SessionLocal
        from app.models.system_setting import SystemSetting
        from sqlalchemy import select

        with SessionLocal() as db:
            stored = db.scalar(
                select(SystemSetting).where(
                    SystemSetting.tenant_id.is_(None),
                    SystemSetting.key == "openai_api_key",
                )
            )
            assert stored is not None
            assert stored.value.startswith("v1.")
            assert "sk-demo-test" not in stored.value


def test_ai_provider_config_test_endpoint_reports_mock_simulation(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/admin/ai-provider-config/test",
            headers={"Authorization": f"Bearer {token}"},
            json={"provider": "mock", "sample_text": "Не работает интернет в аудитории"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is False
        assert payload["simulation"] is True
        assert payload["reason"] == "local_mock_simulation"
        assert payload["effective_provider"] == "mock"


def test_ai_provider_config_test_endpoint_reports_missing_openai_key(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/admin/ai-provider-config/test",
            headers={"Authorization": f"Bearer {token}"},
            json={"provider": "openai", "openai_api_key": ""},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is False
        assert payload["reason"] == "openai_api_key_missing"


def test_organization_admin_cannot_mutate_global_ai_provider(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.patch(
            "/api/v1/admin/ai-provider-config",
            headers={"Authorization": f"Bearer {token}"},
            json={"provider": "mock"},
        )
        connection_test = client.post(
            "/api/v1/admin/ai-provider-config/test",
            headers={"Authorization": f"Bearer {token}"},
            json={"provider": "mock"},
        )
    assert response.status_code == 403
    assert connection_test.status_code == 403


def test_organization_admin_cannot_see_other_tenant_users(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        users = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json()
        assert all(item["email"] != "other.admin@sbs.local" for item in users)


def test_requester_cannot_access_admin_endpoints(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "requester@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def test_it_agent_cannot_access_admin_endpoints(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "agent.support@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def test_requester_cannot_access_security_endpoints(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "requester@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/security/risk-summary", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def test_security_sessions_can_be_listed_and_revoked(app) -> None:
    with TestClient(app) as client:
        requester_token = _login(client, "requester@sbs.local", "Sbs!2026")
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")

        sessions_response = client.get(
            "/api/v1/security/sessions",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert sessions_response.status_code == 200
        requester_session = next(
            item
            for item in sessions_response.json()
            if item["user_email"] == "requester@sbs.local" and item["is_active"]
        )

        revoke_response = client.post(
            f"/api/v1/security/sessions/{requester_session['id']}/revoke",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert revoke_response.status_code == 200
        assert revoke_response.json()["revoked"] is True

        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        assert me_response.status_code == 401


def test_security_session_overview_uses_real_session_counts(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get(
            "/api/v1/security/session-overview",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["active_sessions"] >= 1
        assert payload["logged_in_last_24h"] >= 1
        assert payload["refresh_ttl_minutes"] >= payload["session_timeout_minutes"]


def test_admin_password_reset_revokes_sessions_and_never_audits_password(app) -> None:
    with TestClient(app) as client:
        requester_token = _login(client, "requester@sbs.local", "Sbs!2026")
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        users = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        ).json()
        requester = next(item for item in users if item["email"] == "requester@sbs.local")
        new_password = "New!Secure-2026"

        response = client.post(
            f"/api/v1/admin/users/{requester['id']}/reset-password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"new_password": new_password, "revoke_sessions": False},
        )
        assert response.status_code == 422

        response = client.post(
            f"/api/v1/admin/users/{requester['id']}/reset-password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"new_password": new_password, "revoke_sessions": True},
        )
        assert response.status_code == 200
        assert response.json()["sessions_revoked"] >= 1
        assert response.json()["password_change_required"] is True
        assert new_password not in response.text

        old_session = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        assert old_session.status_code == 401
        new_login = client.post(
            "/api/v1/auth/login",
            json={"email": "requester@sbs.local", "password": new_password},
        )
        assert new_login.status_code == 200
        assert new_login.json()["user"]["must_change_password"] is True
        forced_token = new_login.json()["access_token"]

        blocked = client.get(
            "/api/v1/tickets",
            headers={"Authorization": f"Bearer {forced_token}"},
        )
        assert blocked.status_code == 403
        assert (
            blocked.json()["error"]["message"]
            == "Password change required before accessing this resource"
        )
        account = client.get(
            "/api/v1/auth/account",
            headers={"Authorization": f"Bearer {forced_token}"},
        )
        assert account.status_code == 200
        assert account.json()["must_change_password"] is True
        sessions = client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {forced_token}"},
        )
        assert sessions.status_code == 200

        final_password = "Requester!Private-2027"
        changed = client.post(
            "/api/v1/auth/password/change",
            headers={"Authorization": f"Bearer {forced_token}"},
            json={
                "current_password": new_password,
                "new_password": final_password,
            },
        )
        assert changed.status_code == 200
        final_login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "requester@sbs.local",
                "password": final_password,
            },
        )
        assert final_login.status_code == 200
        assert final_login.json()["user"]["must_change_password"] is False
        restored = client.get(
            "/api/v1/tickets",
            headers={
                "Authorization": f"Bearer {final_login.json()['access_token']}"
            },
        )
        assert restored.status_code != 403

        audit = client.get(
            "/api/v1/admin/audit-logs?action=user_password_reset",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert audit.status_code == 200
        assert new_password not in audit.text


def test_audit_log_created_on_user_update(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        users = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json()
        target_user = next(item for item in users if item["email"] == "requester@sbs.local")
        patch_response = client.patch(
            f"/api/v1/admin/users/{target_user['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"department": "Updated Department"},
        )
        assert patch_response.status_code == 200

        logs = client.get("/api/v1/admin/audit-logs?action=user_updated", headers={"Authorization": f"Bearer {token}"}).json()
        assert any(item["entity_id"] == target_user["id"] for item in logs)


def test_login_creates_audit_event(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post("/api/v1/auth/login", json={"email": "manager@sbs.local", "password": "Sbs!2026"})
        assert login_response.status_code == 200
        token = _login(client, "security@sbs.local", "Sbs!2026")

        logs_response = client.get("/api/v1/security/login-events", headers={"Authorization": f"Bearer {token}"})
        assert logs_response.status_code == 200
        logs = logs_response.json()
        assert any(item["action"] == "login_success" and item["actor_email"] == "manager@sbs.local" for item in logs)


def test_identity_provider_status_is_safe_and_tenant_scoped(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get(
            "/api/v1/admin/identity-provider",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["enabled"] is False
        assert payload["ready"] is False
        assert payload["client_secret_configured"] is False
        assert payload["configuration_source"] == "environment_and_secret_manager"
        assert "client_secret" not in payload
        assert all("secret" not in key or key.endswith("_configured") for key in payload)
        assert payload["linked_identities"] == 0
        assert payload["linked_users"] == 0
        assert "OIDC is disabled" in payload["readiness_issues"]


def test_identity_provider_test_is_audited_when_disabled(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post("/api/v1/admin/identity-provider/test", headers=headers)

        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["reason"] == "OIDC is disabled"

        audit = client.get(
            "/api/v1/admin/audit-logs?action=identity_provider_tested",
            headers=headers,
        )
        assert audit.status_code == 200
        assert any(
            item["entity_type"] == "identity_provider"
            and item["metadata"]["success"] is False
            for item in audit.json()
        )


def test_admin_can_prelink_and_unlink_oidc_identity(app) -> None:
    import app.api.v1.routes.admin as admin_route

    admin_route.settings.oidc_enabled = True
    admin_route.settings.oidc_provider_name = "corporate"
    admin_route.settings.oidc_issuer_url = "https://login.example.com/realms/company"

    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        headers = {"Authorization": f"Bearer {token}"}
        users = client.get("/api/v1/admin/users", headers=headers).json()
        manager = next(item for item in users if item["email"] == "manager@sbs.local")

        linked = client.post(
            f"/api/v1/admin/users/{manager['id']}/external-identities",
            headers=headers,
            json={"subject": "corporate-manager-001"},
        )
        assert linked.status_code == 201
        identity_id = linked.json()["id"]

        identities = client.get(
            f"/api/v1/admin/users/{manager['id']}/external-identities",
            headers=headers,
        )
        assert identities.status_code == 200
        assert identities.json()[0]["subject"] == "corporate-manager-001"

        removed = client.delete(
            f"/api/v1/admin/users/{manager['id']}/external-identities/{identity_id}",
            headers=headers,
        )
        assert removed.status_code == 204


def test_security_user_can_verify_tenant_audit_integrity(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "security@sbs.local", "Sbs!2026")
        response = client.get(
            "/api/v1/admin/audit-logs/integrity",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True
