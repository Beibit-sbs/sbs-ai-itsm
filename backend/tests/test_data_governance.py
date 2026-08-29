from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
import uuid
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.data_governance import DataDeletionEvidence
from app.models.notification import Notification
from app.models.tenant import Tenant


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_retention_requires_preview_legal_hold_and_four_eyes(app) -> None:
    from app.db.session import SessionLocal

    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        security = _login(client, "security@sbs.local")
        dashboard = client.get(
            "/api/v1/data-governance/dashboard",
            headers=_headers(admin),
        )
        assert dashboard.status_code == 200, dashboard.text
        tenant_id = dashboard.json()["tenant_id"]
        assert len(dashboard.json()["policies"]) == 14
        assert dashboard.json()["safety"]["four_eyes_approval"] is True

        with SessionLocal() as db:
            tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
            assert tenant is not None
            expired = Notification(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                type="retention-test",
                title="Expired notification",
                message="Delete after approved retention",
                recipient_name="Test User",
                recipient_email="retention@example.test",
                channel="in_app",
                status="READ",
                created_at=datetime.now(UTC) - timedelta(days=120),
            )
            db.add(expired)
            db.commit()
            notification_id = expired.id

        hold = client.post(
            "/api/v1/data-governance/legal-holds",
            headers=_headers(admin),
            json={
                "name": "Retention acceptance hold",
                "reason": "Preserve notification evidence during acceptance testing",
                "scope_type": "CATEGORY",
                "category": "NOTIFICATIONS",
            },
        )
        assert hold.status_code == 201, hold.text
        hold_id = hold.json()["id"]

        blocked_preview = client.post(
            "/api/v1/data-governance/deletion-requests/preview",
            headers=_headers(admin),
            json={
                "request_type": "RETENTION_PURGE",
                "category": "NOTIFICATIONS",
                "reason": "Remove notifications beyond the approved retention window",
            },
        )
        assert blocked_preview.status_code == 201, blocked_preview.text
        assert blocked_preview.json()["preview"]["blocked_by_legal_hold"] is True
        blocked_submit = client.post(
            f"/api/v1/data-governance/deletion-requests/{blocked_preview.json()['id']}/submit",
            headers=_headers(admin),
        )
        assert blocked_submit.status_code == 409

        self_release = client.post(
            f"/api/v1/data-governance/legal-holds/{hold_id}/release",
            headers=_headers(admin),
            json={"reason": "Acceptance is complete and evidence may be retired"},
        )
        assert self_release.status_code == 409
        released = client.post(
            f"/api/v1/data-governance/legal-holds/{hold_id}/release",
            headers=_headers(security),
            json={"reason": "Independent review confirms the hold may be released"},
        )
        assert released.status_code == 200, released.text
        assert released.json()["status"] == "RELEASED"

        preview = client.post(
            "/api/v1/data-governance/deletion-requests/preview",
            headers=_headers(admin),
            json={
                "request_type": "RETENTION_PURGE",
                "category": "NOTIFICATIONS",
                "reason": "Remove notifications beyond the approved retention window",
            },
        )
        assert preview.status_code == 201, preview.text
        request_id = preview.json()["id"]
        assert preview.json()["estimated_rows"] >= 1
        submitted = client.post(
            f"/api/v1/data-governance/deletion-requests/{request_id}/submit",
            headers=_headers(admin),
        )
        assert submitted.status_code == 200, submitted.text

        self_approval = client.post(
            f"/api/v1/data-governance/deletion-requests/{request_id}/decision",
            headers=_headers(admin),
            json={
                "decision": "APPROVE",
                "reason": "Requester must not be able to self-approve this plan",
            },
        )
        assert self_approval.status_code == 409
        approved = client.post(
            f"/api/v1/data-governance/deletion-requests/{request_id}/decision",
            headers=_headers(security),
            json={
                "decision": "APPROVE",
                "reason": "Independent security review approved the bounded plan",
            },
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "APPROVED"

        wrong_phrase = client.post(
            f"/api/v1/data-governance/deletion-requests/{request_id}/execute",
            headers=_headers(admin),
            json={"confirmation": "EXECUTE"},
        )
        assert wrong_phrase.status_code == 422
        executed = client.post(
            f"/api/v1/data-governance/deletion-requests/{request_id}/execute",
            headers=_headers(admin),
            json={"confirmation": f"EXECUTE {request_id}"},
        )
        assert executed.status_code == 200, executed.text
        assert executed.json()["status"] == "COMPLETED"
        assert executed.json()["evidence"]["result_sha256"]

        with SessionLocal() as db:
            assert db.get(Notification, notification_id) is None
            evidence = db.scalar(
                select(DataDeletionEvidence).where(
                    DataDeletionEvidence.deletion_request_id == request_id
                )
            )
            assert evidence is not None
            assert evidence.result_sha256


def test_tenant_export_is_secret_free_and_integrity_stamped(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        exported = client.get(
            "/api/v1/data-governance/tenant-export",
            headers=_headers(admin),
        )
        assert exported.status_code == 200, exported.text
        assert exported.headers["cache-control"] == "private, no-store, max-age=0"
        assert exported.headers["x-export-sha256"]
        with zipfile.ZipFile(BytesIO(exported.content)) as archive:
            names = set(archive.namelist())
            assert "manifest.json" in names
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["secrets_included"] is False
            assert manifest["table_count"] > 0
            assert manifest["row_count"] > 0
            users = archive.read("tables/users.jsonl").decode("utf-8")
            assert "password_hash" not in users
            assert "Sbs!2026" not in users


def test_direct_ai_purge_is_disabled_in_favor_of_governed_workflow(app) -> None:
    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        response = client.post(
            "/api/v1/ai/runtime-controls/retention/purge",
            headers=_headers(admin),
            json={
                "confirm": True,
                "reason": "Direct purge must not bypass four-eyes approval",
            },
        )
        assert response.status_code == 409
        assert "data-governance" in response.json()["error"]["message"]
