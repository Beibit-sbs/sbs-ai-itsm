from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assets(client: TestClient, token: str) -> list[dict[str, object]]:
    response = client.get("/api/v1/assets?page_size=20", headers=_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _create_product(
    client: TestClient,
    token: str,
    *,
    name: str = "SBS Office Suite",
    prohibited: bool = False,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/software-assets/products",
        headers=_headers(token),
        json={
            "name": name,
            "publisher": "SBS",
            "version": "2026.1",
            "edition": "Enterprise",
            "category": "PRODUCTIVITY",
            "is_prohibited": prohibited,
            "prohibited_reason": "Security policy" if prohibited else None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_sam_catalog_license_installation_and_compliance(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        assets = _assets(client, manager)
        assert len(assets) >= 2
        product = _create_product(client, manager)

        license_response = client.post(
            "/api/v1/software-assets/licenses",
            headers=_headers(manager),
            json={
                "product_id": product["id"],
                "license_reference": "PO-2026-001",
                "license_type": "DEVICE",
                "purchased_quantity": 1,
                "vendor": "SBS Partner",
                "contract_reference": "CTR-001",
                "unit_cost": "75000.00",
                "currency": "KZT",
            },
        )
        assert license_response.status_code == 201, license_response.text

        first_install = client.post(
            "/api/v1/software-assets/installations",
            headers=_headers(manager),
            json={
                "product_id": product["id"],
                "asset_id": assets[0]["id"],
                "detected_version": "2026.1.4",
                "source": "INTUNE",
            },
        )
        assert first_install.status_code == 201, first_install.text

        dashboard = client.get("/api/v1/software-assets/dashboard", headers=_headers(manager))
        assert dashboard.status_code == 200, dashboard.text
        position = next(item for item in dashboard.json()["positions"] if item["product_id"] == product["id"])
        assert position["purchased_quantity"] == 1
        assert position["detected_quantity"] == 1
        assert position["compliance_state"] == "COMPLIANT"
        assert position["purchase_cost_by_currency"] == {"KZT": 75000.0}

        second_install = client.post(
            "/api/v1/software-assets/installations",
            headers=_headers(manager),
            json={"product_id": product["id"], "asset_id": assets[1]["id"], "source": "SCCM"},
        )
        assert second_install.status_code == 201, second_install.text

        reconciled = client.post("/api/v1/software-assets/reconcile", headers=_headers(manager))
        assert reconciled.status_code == 200, reconciled.text
        position = next(
            item
            for item in reconciled.json()["dashboard"]["positions"]
            if item["product_id"] == product["id"]
        )
        assert position["detected_quantity"] == 2
        assert position["shortfall_quantity"] == 1
        assert position["compliance_state"] == "OVER_DEPLOYED"
        assert position["cost_at_risk_by_currency"] == {"KZT": 75000.0}


def test_prohibited_software_is_automatically_unauthorized(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        asset = _assets(client, manager)[0]
        product = _create_product(client, manager, name="Unsafe Remote Tool", prohibited=True)

        installation = client.post(
            "/api/v1/software-assets/installations",
            headers=_headers(manager),
            json={
                "product_id": product["id"],
                "asset_id": asset["id"],
                "authorization_status": "AUTHORIZED",
            },
        )
        assert installation.status_code == 201, installation.text
        assert installation.json()["authorization_status"] == "UNAUTHORIZED"

        cannot_authorize = client.patch(
            f"/api/v1/software-assets/installations/{installation.json()['id']}",
            headers=_headers(manager),
            json={
                "expected_version": installation.json()["version_number"],
                "authorization_status": "AUTHORIZED",
                "reason": "Must remain blocked by product policy",
            },
        )
        assert cannot_authorize.status_code == 422

        dashboard = client.get("/api/v1/software-assets/dashboard", headers=_headers(manager))
        assert dashboard.status_code == 200
        payload = dashboard.json()
        position = next(item for item in payload["positions"] if item["product_id"] == product["id"])
        assert position["compliance_state"] == "PROHIBITED"
        assert payload["summary"]["unauthorized_installations"] == 1
        assert payload["unauthorized_installations"][0]["asset_tag"] == asset["asset_tag"]


def test_reconciliation_expires_license_and_audits(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        admin = _login(client, "admin@sbs.local")
        product = _create_product(client, manager, name="Expired Subscription")
        now = datetime.now(UTC)
        license_response = client.post(
            "/api/v1/software-assets/licenses",
            headers=_headers(manager),
            json={
                "product_id": product["id"],
                "license_reference": "SUB-EXPIRED-1",
                "license_type": "SUBSCRIPTION",
                "purchased_quantity": 5,
                "starts_at": (now - timedelta(days=365)).isoformat(),
                "expires_at": (now - timedelta(days=1)).isoformat(),
                "renewal_at": (now - timedelta(days=15)).isoformat(),
                "unit_cost": "120.00",
                "currency": "USD",
            },
        )
        assert license_response.status_code == 201, license_response.text

        reconciled = client.post("/api/v1/software-assets/reconcile", headers=_headers(manager))
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["expired_licenses_updated"] == 1

        licenses = client.get("/api/v1/software-assets/licenses", headers=_headers(manager))
        assert licenses.status_code == 200
        record = next(item for item in licenses.json() if item["id"] == license_response.json()["id"])
        assert record["status"] == "EXPIRED"

        audit = client.get(
            "/api/v1/admin/audit-logs?action=sam.reconciled",
            headers=_headers(admin),
        )
        assert audit.status_code == 200, audit.text
        assert any(item["entity_type"] == "software_asset_management" for item in audit.json())


def test_sam_rbac_and_optimistic_lock(app) -> None:
    with TestClient(app) as client:
        manager = _login(client, "manager@sbs.local")
        requester = _login(client, "requester@sbs.local")
        product = _create_product(client, manager, name="Managed Browser")

        forbidden = client.get("/api/v1/software-assets/dashboard", headers=_headers(requester))
        assert forbidden.status_code == 403

        updated = client.patch(
            f"/api/v1/software-assets/products/{product['id']}",
            headers=_headers(manager),
            json={
                "expected_version": product["version_number"],
                "category": "BROWSER",
                "reason": "Normalize software category",
            },
        )
        assert updated.status_code == 200, updated.text
        conflict = client.patch(
            f"/api/v1/software-assets/products/{product['id']}",
            headers=_headers(manager),
            json={
                "expected_version": product["version_number"],
                "category": "OTHER",
                "reason": "Stale update must fail",
            },
        )
        assert conflict.status_code == 409


def test_sam_migration_is_current_head() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260814_0078_software_asset_management.py"
    )
    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert 'revision: str = "20260814_0078"' in text
    assert 'down_revision: str | None = "20260814_0077"' in text
