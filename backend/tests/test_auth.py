def test_protected_identity_endpoint_rejects_anonymous_access(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "HTTP_401"


def test_login_and_me_flow(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["token_type"] == "bearer"
        assert payload["user"]["email"] == "admin@sbs.local"
        assert payload["access_token"]
        assert payload["refresh_token"] is None
        assert client.cookies.get("sbs_refresh_token")

        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )

        assert me_response.status_code == 200
        me_payload = me_response.json()
        assert me_payload["email"] == "admin@sbs.local"
        assert me_payload["role"] == "organization_admin"


def test_login_rejects_invalid_credentials(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "wrong-password"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "HTTP_401"


def test_login_is_rate_limited_after_repeated_failures(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        for _ in range(5):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "rate-limit@example.com", "password": "wrong"},
            )
            assert response.status_code == 401

        blocked = client.post(
            "/api/v1/auth/login",
            json={"email": "rate-limit@example.com", "password": "wrong"},
        )
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "300"


def test_login_is_rate_limited_by_ip_across_distinct_accounts(
    app,
    monkeypatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.api.v1.routes import auth as auth_routes

    monkeypatch.setattr(auth_routes.settings, "login_ip_rate_limit_attempts", 3)
    with TestClient(app) as client:
        for attempt in range(3):
            response = client.post(
                "/api/v1/auth/login",
                json={
                    "email": f"distributed-{attempt}@example.com",
                    "password": "wrong",
                },
            )
            assert response.status_code == 401

        blocked = client.post(
            "/api/v1/auth/login",
            json={"email": "another-account@example.com", "password": "wrong"},
        )
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "300"


def test_unknown_account_uses_dummy_password_verification(
    app,
    monkeypatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.api.v1.routes import auth as auth_routes

    verified_hashes: list[str] = []
    real_verify_password = auth_routes.verify_password

    def tracked_verify_password(password: str, password_hash: str) -> bool:
        verified_hashes.append(password_hash)
        return real_verify_password(password, password_hash)

    monkeypatch.setattr(
        auth_routes,
        "verify_password",
        tracked_verify_password,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "does-not-exist@example.com", "password": "wrong"},
        )

    assert response.status_code == 401
    assert verified_hashes == [auth_routes.DUMMY_PASSWORD_HASH]


def test_login_input_is_bounded_before_credential_work(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": f"{'x' * 256}", "password": "wrong"},
        )

    assert response.status_code == 422


def test_failed_login_creates_audit_event(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        failed = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "wrong-password"},
        )
        assert failed.status_code == 401

        token = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        ).json()["access_token"]
        logs = client.get(
            "/api/v1/admin/audit-logs?action=login_failed",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert logs.status_code == 200
        assert any(item["action"] == "login_failed" and item["actor_email"] == "admin@sbs.local" for item in logs.json())


def test_logout_endpoint_returns_ok_and_writes_audit(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )
        assert login.status_code == 200
        tokens = login.json()

        response = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            json={},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

        revoked = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert revoked.status_code == 401

        root_token = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        ).json()["access_token"]
        audit = client.get(
            "/api/v1/admin/audit-logs?action=logout_success",
            headers={"Authorization": f"Bearer {root_token}"},
        )
        assert audit.status_code == 200
        assert any(item["action"] == "logout_success" for item in audit.json())


def test_refresh_token_is_rotated_and_cannot_be_replayed(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )
        first_refresh_token = client.cookies.get("sbs_refresh_token")
        assert first_refresh_token
        refreshed = client.post(
            "/api/v1/auth/refresh",
            json={},
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["refresh_token"] is None
        refreshed_access_token = refreshed.json()["access_token"]
        assert client.cookies.get("sbs_refresh_token") != first_refresh_token

        replay = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": first_refresh_token},
        )
        assert replay.status_code == 401
        assert "session family revoked" in replay.json()["error"]["message"]

        revoked_child = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {refreshed_access_token}"},
        )
        assert revoked_child.status_code == 401

        root_token = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        ).json()["access_token"]
        audit = client.get(
            "/api/v1/admin/audit-logs?action=refresh_token_reuse_detected",
            headers={"Authorization": f"Bearer {root_token}"},
        )
        assert audit.status_code == 200
        assert any(
            item["action"] == "refresh_token_reuse_detected"
            and item["metadata"]["descendant_sessions_revoked"] >= 1
            for item in audit.json()
        )


def test_every_user_can_inspect_and_revoke_only_own_sessions(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        requester_login = client.post(
            "/api/v1/auth/login",
            headers={"User-Agent": "Requester Browser/1.0"},
            json={"email": "requester@sbs.local", "password": "Sbs!2026"},
        )
        requester_token = requester_login.json()["access_token"]
        account = client.get(
            "/api/v1/auth/account",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        assert account.status_code == 200
        assert account.json()["identity_source"] == "LOCAL"
        assert account.json()["local_password_supported"] is True

        requester_sessions = client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        assert requester_sessions.status_code == 200
        current = next(
            item for item in requester_sessions.json() if item["is_current"]
        )
        assert current["is_active"] is True
        assert current["user_agent"] == "Requester Browser/1.0"
        assert current["auth_method"] == "pwd"

        admin_token = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        ).json()["access_token"]
        admin_sessions = client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {admin_token}"},
        ).json()
        admin_session_id = next(
            item["id"] for item in admin_sessions if item["is_current"]
        )

        hidden = client.post(
            f"/api/v1/auth/sessions/{admin_session_id}/revoke",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        assert hidden.status_code == 404

        revoked = client.post(
            f"/api/v1/auth/sessions/{current['id']}/revoke",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        assert revoked.status_code == 200
        assert revoked.json()["current_session_revoked"] is True
        assert client.cookies.get("sbs_refresh_token") is None


def test_self_password_change_revokes_sessions_and_never_exposes_secret(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "requester@sbs.local", "password": "Sbs!2026"},
        )
        old_token = login.json()["access_token"]
        new_password = "Requester!Secure-2027"

        unchanged = client.post(
            "/api/v1/auth/password/change",
            headers={"Authorization": f"Bearer {old_token}"},
            json={"current_password": "Sbs!2026", "new_password": "Sbs!2026"},
        )
        assert unchanged.status_code == 400

        changed = client.post(
            "/api/v1/auth/password/change",
            headers={"Authorization": f"Bearer {old_token}"},
            json={
                "current_password": "Sbs!2026",
                "new_password": new_password,
            },
        )
        assert changed.status_code == 200
        assert changed.json()["sessions_revoked"] >= 1
        assert changed.json()["reauthentication_required"] is True
        assert new_password not in changed.text
        assert client.cookies.get("sbs_refresh_token") is None

        revoked = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert revoked.status_code == 401
        relogin = client.post(
            "/api/v1/auth/login",
            json={"email": "requester@sbs.local", "password": new_password},
        )
        assert relogin.status_code == 200

        admin_token = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        ).json()["access_token"]
        audit = client.get(
            "/api/v1/admin/audit-logs?action=self_password_changed",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert audit.status_code == 200
        assert new_password not in audit.text


def test_external_identity_cannot_change_provider_managed_password(app) -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.user import User

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "requester@sbs.local", "password": "Sbs!2026"},
        )
        token = login.json()["access_token"]
        with SessionLocal() as db:
            requester = db.scalar(
                select(User).where(User.email == "requester@sbs.local")
            )
            assert requester is not None
            requester.identity_source = "SCIM"
            requester.provisioning_state = "ACTIVE"
            db.commit()

        blocked_login = client.post(
            "/api/v1/auth/login",
            json={"email": "requester@sbs.local", "password": "Sbs!2026"},
        )
        assert blocked_login.status_code == 401
        response = client.post(
            "/api/v1/auth/password/change",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "Sbs!2026",
                "new_password": "External!Password-2027",
            },
        )
        assert response.status_code == 409
        assert "external identity provider" in response.json()["error"]["message"]


def test_deactivated_user_cannot_login_and_cannot_use_existing_token(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )
        assert admin_login.status_code == 200
        admin_token = admin_login.json()["access_token"]

        manager_login = client.post(
            "/api/v1/auth/login",
            json={"email": "manager@sbs.local", "password": "Sbs!2026"},
        )
        assert manager_login.status_code == 200
        manager_token = manager_login.json()["access_token"]

        users = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"}).json()
        manager_id = next(item["id"] for item in users if item["email"] == "manager@sbs.local")
        deactivate = client.patch(
            f"/api/v1/admin/users/{manager_id}/deactivate",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert deactivate.status_code == 200

        blocked_login = client.post(
            "/api/v1/auth/login",
            json={"email": "manager@sbs.local", "password": "Sbs!2026"},
        )
        assert blocked_login.status_code == 403

        blocked_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {manager_token}"})
        assert blocked_me.status_code == 401


def test_root_user_can_list_tenants(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        tenants_response = client.get(
            "/api/v1/tenants",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert tenants_response.status_code == 200
        tenants = tenants_response.json()
        assert len(tenants) >= 1
        assert tenants[0]["slug"] == "demo-tenant"


def test_tenant_admin_cannot_list_tenants(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        tenants_response = client.get(
            "/api/v1/tenants",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert tenants_response.status_code == 403
        assert tenants_response.json()["error"]["code"] == "HTTP_403"


def test_tenant_admin_can_read_and_update_only_current_tenant_profile(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )
        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        current = client.get("/api/v1/tenants/current", headers=headers)
        assert current.status_code == 200
        original = current.json()
        assert original["slug"] == "demo-tenant"
        assert original["created_at"]
        assert original["updated_at"]

        updated = client.patch(
            "/api/v1/tenants/current",
            headers=headers,
            json={
                "name": "SBS Production University",
                "description": "Production-ready ITSM tenant",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["id"] == original["id"]
        assert updated.json()["slug"] == original["slug"]
        assert updated.json()["name"] == "SBS Production University"
        assert updated.json()["description"] == "Production-ready ITSM tenant"

        audit = client.get(
            "/api/v1/admin/audit-logs?action=tenant_profile_updated",
            headers=headers,
        )
        assert audit.status_code == 200
        assert any(item["entity_id"] == original["id"] for item in audit.json())


def test_root_current_tenant_profile_is_explicitly_empty(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        ).json()["access_token"]

        response = client.get(
            "/api/v1/tenants/current",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json() is None


def test_tenant_admin_can_list_assets(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        assets_response = client.get(
            "/api/v1/assets",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert assets_response.status_code == 200
        assets = assets_response.json()["items"]
        assert len(assets) >= 3
        assert assets[0]["tenant_name"] == "Demo Tenant"


def test_root_user_can_list_assets(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        assets_response = client.get(
            "/api/v1/assets",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert assets_response.status_code == 200
        assets = assets_response.json()["items"]
        assert len(assets) >= 3
        assert {"in_use", "in_stock", "in_repair"}.issubset({asset["status"] for asset in assets})


def test_tenant_admin_can_list_sla_policies(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        sla_response = client.get(
            "/api/v1/sla",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert sla_response.status_code == 200
        policies = sla_response.json()
        assert len(policies) == 4
        assert {policy["priority"].upper() for policy in policies} == {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }
        assert policies[0]["tenant_name"] == "Demo Tenant"


def test_root_user_can_list_sla_policies(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )

        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        sla_response = client.get(
            "/api/v1/sla",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert sla_response.status_code == 200
        policies = sla_response.json()
        assert len(policies) == 4
        assert {policy["priority"].upper() for policy in policies} == {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }


def test_production_mode_does_not_seed_demo_data(monkeypatch, tmp_path) -> None:
    import sys
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'prod.db'}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("RUN_STARTUP_DDL", "true")
    monkeypatch.setenv("BOOTSTRAP_ROOT_EMAIL", "root@sbs.local")
    monkeypatch.setenv("BOOTSTRAP_ROOT_PASSWORD", "Root!2026")

    reload_prefixes = [
        "app.main",
        "app.db.session",
        "app.core.config",
        "app.services.seed",
        "app.services.service_desk",
        "app.api.v1.router",
        "app.api.v1.routes.",
    ]
    for module_name in list(sys.modules.keys()):
        if any(module_name == prefix or module_name.startswith(prefix) for prefix in reload_prefixes):
            sys.modules.pop(module_name, None)

    from app.main import app as prod_app

    with TestClient(prod_app) as client:
        demo_admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@sbs.local", "password": "Sbs!2026"},
        )
        assert demo_admin_login.status_code == 401

        root_login = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )
        assert root_login.status_code == 200
        root_token = root_login.json()["access_token"]

        tickets = client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {root_token}"})
        assert tickets.status_code == 200
        assert tickets.json()["total"] == 0
