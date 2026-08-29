from __future__ import annotations

import uuid

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


def _generic_class(client: TestClient, token: str) -> dict:
    response = client.get("/api/v1/cmdb/classes", headers=_headers(token))
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["code"] == "GENERIC_ASSET")


def _create_source(
    client: TestClient,
    token: str,
    *,
    code: str,
    default_class_id: str,
    priority: int,
    identification_rules: list[str],
    authoritative_fields: list[str],
    claim_unowned_fields: bool = False,
) -> dict:
    response = client.post(
        "/api/v1/cmdb/sources",
        headers=_headers(token),
        json={
            "code": code,
            "name": code.replace("_", " ").title(),
            "source_type": "API",
            "priority": priority,
            "default_class_id": default_class_id,
            "identification_rules": identification_rules,
            "authoritative_fields": authoritative_fields,
            "claim_unowned_fields": claim_unowned_fields,
            "stale_after_hours": 24,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _preview(
    client: TestClient,
    token: str,
    source_id: str,
    records: list[dict],
    *,
    key: str | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/cmdb/sources/{source_id}/reconciliation/preview",
        headers=_headers(token),
        json={
            "idempotency_key": key or str(uuid.uuid4()),
            "records": records,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _apply(client: TestClient, token: str, run_id: str) -> dict:
    response = client.post(
        f"/api/v1/cmdb/reconciliation-runs/{run_id}/apply",
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_ci(
    client: TestClient,
    token: str,
    *,
    class_id: str,
    asset_tag: str,
    serial_number: str,
) -> dict:
    response = client.post(
        "/api/v1/cmdb/items",
        headers=_headers(token),
        json={
            "ci_class_id": class_id,
            "asset_tag": asset_tag,
            "name": asset_tag.lower(),
            "serial_number": serial_number,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_reconciliation_identity_idempotency_precedence_and_tenant_isolation(
    app,
) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        requester_token, _ = _login(client, "requester@sbs.local")
        other_token, _ = _login(client, "other.admin@sbs.local")
        generic = _generic_class(client, manager_token)

        denied = client.post(
            "/api/v1/cmdb/sources",
            headers=_headers(requester_token),
            json={
                "code": "DENIED_SOURCE",
                "name": "Denied source",
                "source_type": "API",
                "default_class_id": generic["id"],
                "identification_rules": ["serial_number"],
            },
        )
        assert denied.status_code == 403

        authoritative = _create_source(
            client,
            manager_token,
            code="AUTHORITATIVE_DISCOVERY",
            default_class_id=generic["id"],
            priority=10,
            identification_rules=["serial_number", "asset_tag"],
            authoritative_fields=["name", "location", "criticality"],
            claim_unowned_fields=True,
        )
        record = {
            "external_id": "node-001",
            "asset_tag": "DISC-001",
            "serial_number": "SERIAL-001",
            "name": "discovered-node-001",
            "location": "DC-A",
            "criticality": "HIGH",
        }
        idempotency_key = str(uuid.uuid4())
        preview = _preview(
            client,
            manager_token,
            authoritative["id"],
            [record],
            key=idempotency_key,
        )
        assert preview["status"] == "PREVIEWED"
        assert preview["create_count"] == 1
        assert preview["records"][0]["outcome"] == "CREATE"

        repeated = _preview(
            client,
            manager_token,
            authoritative["id"],
            [record],
            key=idempotency_key,
        )
        assert repeated["id"] == preview["id"]

        conflict = client.post(
            f"/api/v1/cmdb/sources/{authoritative['id']}/reconciliation/preview",
            headers=_headers(manager_token),
            json={
                "idempotency_key": idempotency_key,
                "records": [{**record, "name": "different-payload"}],
            },
        )
        assert conflict.status_code == 409

        applied = _apply(client, manager_token, preview["id"])
        assert applied["status"] == "COMPLETED"
        assert applied["records"][0]["outcome"] == "APPLIED_CREATED"
        asset_id = applied["records"][0]["matched_ci_id"]
        assert asset_id

        identity_update = _preview(
            client,
            manager_token,
            authoritative["id"],
            [
                {
                    **record,
                    "serial_number": "SERIAL-CHANGED",
                    "name": "discovered-node-renamed",
                    "location": "DC-B",
                }
            ],
        )
        assert identity_update["records"][0]["matched_ci_id"] == asset_id
        assert identity_update["records"][0]["outcome"] == "UPDATE"
        updated = _apply(client, manager_token, identity_update["id"])
        assert updated["records"][0]["outcome"] == "APPLIED_UPDATED"

        ownership = client.get(
            f"/api/v1/cmdb/items/{asset_id}/field-ownership",
            headers=_headers(manager_token),
        )
        assert ownership.status_code == 200, ownership.text
        assert {
            row["field_name"]: row["source_priority"]
            for row in ownership.json()
        } == {"criticality": 10, "location": 10, "name": 10}

        weaker = _create_source(
            client,
            manager_token,
            code="WEAK_INVENTORY",
            default_class_id=generic["id"],
            priority=500,
            identification_rules=["asset_tag"],
            authoritative_fields=["location"],
            claim_unowned_fields=True,
        )
        weak_preview = _preview(
            client,
            manager_token,
            weaker["id"],
            [
                {
                    "external_id": "weak-001",
                    "asset_tag": "DISC-001",
                    "location": "UNTRUSTED-LOCATION",
                }
            ],
        )
        assert weak_preview["records"][0]["outcome"] == "SKIPPED"
        assert weak_preview["records"][0]["normalized"]["_blocked_fields"] == [
            "location"
        ]
        _apply(client, manager_token, weak_preview["id"])

        asset = client.get(
            f"/api/v1/assets/{asset_id}",
            headers=_headers(manager_token),
        )
        assert asset.status_code == 200
        assert asset.json()["location"] == "DC-B"

        cross_tenant = client.patch(
            f"/api/v1/cmdb/sources/{authoritative['id']}",
            headers=_headers(other_token),
            json={
                "expected_version": authoritative["version"],
                "status": "INACTIVE",
                "reason": "Cross tenant attempt",
            },
        )
        assert cross_tenant.status_code == 404


def test_payload_duplicate_detection_and_governed_ci_merge(app) -> None:
    with TestClient(app) as client:
        manager_token, _ = _login(client, "manager@sbs.local")
        other_token, _ = _login(client, "other.admin@sbs.local")
        generic = _generic_class(client, manager_token)
        source = _create_source(
            client,
            manager_token,
            code="DUPLICATE_SCANNER",
            default_class_id=generic["id"],
            priority=100,
            identification_rules=["serial_number"],
            authoritative_fields=["name"],
        )

        duplicate_payload = _preview(
            client,
            manager_token,
            source["id"],
            [
                {
                    "external_id": "row-a",
                    "serial_number": "PAYLOAD-DUP",
                    "name": "payload-a",
                },
                {
                    "external_id": "row-b",
                    "serial_number": "PAYLOAD-DUP",
                    "name": "payload-b",
                },
            ],
        )
        assert duplicate_payload["invalid_count"] == 2
        assert all(
            "duplicate_identifier_in_payload:serial_number" in row["errors"]
            for row in duplicate_payload["records"]
        )

        first = _create_ci(
            client,
            manager_token,
            class_id=generic["id"],
            asset_tag="DUP-CI-A",
            serial_number="PHYSICAL-DUP",
        )
        second = _create_ci(
            client,
            manager_token,
            class_id=generic["id"],
            asset_tag="DUP-CI-B",
            serial_number="PHYSICAL-DUP",
        )
        ambiguous = _preview(
            client,
            manager_token,
            source["id"],
            [
                {
                    "external_id": "scanner-physical-dup",
                    "serial_number": "PHYSICAL-DUP",
                }
            ],
        )
        assert ambiguous["ambiguous_count"] == 1
        assert ambiguous["records"][0]["outcome"] == "AMBIGUOUS"
        assert set(ambiguous["records"][0]["candidate_ids"]) == {
            first["id"],
            second["id"],
        }
        blocked_apply = client.post(
            f"/api/v1/cmdb/reconciliation-runs/{ambiguous['id']}/apply",
            headers=_headers(manager_token),
        )
        assert blocked_apply.status_code == 409

        candidates_response = client.get(
            "/api/v1/cmdb/duplicate-candidates",
            headers=_headers(manager_token),
        )
        assert candidates_response.status_code == 200
        candidate = next(
            item
            for item in candidates_response.json()
            if item["run_id"] == ambiguous["id"]
        )
        denied = client.post(
            f"/api/v1/cmdb/duplicate-candidates/{candidate['id']}/merge",
            headers=_headers(other_token),
            json={
                "expected_version": candidate["version"],
                "expected_primary_version": candidate["primary"]["version"],
                "expected_duplicate_version": candidate["duplicate"]["version"],
                "reason": "Cross tenant merge attempt",
            },
        )
        assert denied.status_code == 404

        stale = client.post(
            f"/api/v1/cmdb/duplicate-candidates/{candidate['id']}/merge",
            headers=_headers(manager_token),
            json={
                "expected_version": candidate["version"] + 1,
                "expected_primary_version": candidate["primary"]["version"],
                "expected_duplicate_version": candidate["duplicate"]["version"],
                "reason": "Stale merge must be rejected",
            },
        )
        assert stale.status_code == 409

        merged_response = client.post(
            f"/api/v1/cmdb/duplicate-candidates/{candidate['id']}/merge",
            headers=_headers(manager_token),
            json={
                "expected_version": candidate["version"],
                "expected_primary_version": candidate["primary"]["version"],
                "expected_duplicate_version": candidate["duplicate"]["version"],
                "reason": "Physical serial verified by CMDB owner",
            },
        )
        assert merged_response.status_code == 200, merged_response.text
        merged = merged_response.json()
        assert merged["candidate"]["status"] == "MERGED"
        assert merged["candidate"]["duplicate"]["lifecycle_status"] == "RETIRED"
        assert merged["candidate"]["primary"]["version"] == (
            candidate["primary"]["version"] + 1
        )

        duplicate_detail = client.get(
            f"/api/v1/assets/{candidate['duplicate']['id']}",
            headers=_headers(manager_token),
        )
        assert duplicate_detail.status_code == 200
        assert duplicate_detail.json()["lifecycle_status"] == "RETIRED"

        primary_history = client.get(
            f"/api/v1/assets/{candidate['primary']['id']}/history",
            headers=_headers(manager_token),
        )
        duplicate_history = client.get(
            f"/api/v1/assets/{candidate['duplicate']['id']}/history",
            headers=_headers(manager_token),
        )
        assert "ci_duplicate_absorbed" in {
            row["action"] for row in primary_history.json()
        }
        assert "ci_duplicate_merged" in {
            row["action"] for row in duplicate_history.json()
        }
