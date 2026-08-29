from __future__ import annotations

import json
import struct
import zlib

from fastapi.testclient import TestClient
import pytest

from app.services.tenant_experience import (
    default_experience,
    png_dimensions,
    validate_experience,
)


def _login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sbs!2026"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _settings(profile: dict[str, object]) -> dict[str, object]:
    return {
        key: profile[key]
        for key in (
            "product_name",
            "short_name",
            "primary_color",
            "accent_color",
            "surface_color",
            "text_color",
            "ui_locale",
            "format_locale",
            "timezone",
            "currency_code",
            "date_style",
            "hour_cycle",
            "first_day_of_week",
            "terminology",
        )
    }


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _valid_png(width: int = 32, height: int = 32) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    scanlines = b"".join(
        b"\x00" + (b"\x40\xA8\xFF\xFF" * width)
        for _ in range(height)
    )
    return (
        signature
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(scanlines))
        + _png_chunk(b"IEND", b"")
    )


def test_experience_validation_fails_closed() -> None:
    settings = default_experience()
    assert settings["timezone"] == "Asia/Qyzylorda"

    invalid_contrast = {**settings, "text_color": "#071120"}
    with pytest.raises(ValueError, match="4.5:1"):
        validate_experience(invalid_contrast)

    invalid_timezone = {**settings, "timezone": "Mars/Olympus"}
    with pytest.raises(ValueError, match="Unknown IANA"):
        validate_experience(invalid_timezone)

    invalid_markup = {
        **settings,
        "terminology": {
            **settings["terminology"],
            "incident_singular": "<script>",
        },
    }
    with pytest.raises(ValueError, match="markup"):
        validate_experience(invalid_markup)


def test_png_validation_checks_structure_crc_and_dimensions() -> None:
    payload = _valid_png()
    assert png_dimensions(payload) == (32, 32)

    corrupted = bytearray(payload)
    corrupted[-5] ^= 1
    with pytest.raises(ValueError, match="CRC"):
        png_dimensions(bytes(corrupted))

    with pytest.raises(ValueError, match="dimensions"):
        png_dimensions(_valid_png(width=16, height=32))


def test_tenant_experience_revision_conflict_and_permissions(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local")
        requester_token = _login(client, "requester@sbs.local")
        profile_response = client.get(
            "/api/v1/tenant-experience/current",
            headers=_headers(admin_token),
        )
        assert profile_response.status_code == 200, profile_response.text
        initial = profile_response.json()
        assert initial["revision"] == 0
        assert initial["is_default"] is True
        assert initial["contrast"]["text_on_surface"] >= 4.5
        assert profile_response.headers["etag"].strip('"') == initial["etag"]

        settings = _settings(initial)
        settings["product_name"] = "SBS Service Operations"
        settings["ui_locale"] = "kk-KZ"
        settings["format_locale"] = "kk-KZ"
        settings["timezone"] = "Asia/Almaty"
        updated = client.put(
            "/api/v1/tenant-experience/current",
            headers=_headers(admin_token),
            json={
                "expected_revision": 0,
                "change_reason": "Approved tenant brand baseline",
                "settings": settings,
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 1
        assert updated.json()["ui_locale"] == "kk-KZ"
        assert updated.json()["product_name"] == "SBS Service Operations"

        stale = client.put(
            "/api/v1/tenant-experience/current",
            headers=_headers(admin_token),
            json={
                "expected_revision": 0,
                "change_reason": "Stale overwrite attempt",
                "settings": settings,
            },
        )
        assert stale.status_code == 409

        requester_read = client.get(
            "/api/v1/tenant-experience/current",
            headers=_headers(requester_token),
        )
        assert requester_read.status_code == 200
        assert requester_read.json()["revision"] == 1
        requester_write = client.put(
            "/api/v1/tenant-experience/current",
            headers=_headers(requester_token),
            json={
                "expected_revision": 1,
                "change_reason": "Unauthorized tenant customization",
                "settings": settings,
            },
        )
        assert requester_write.status_code == 403


def test_logo_history_rollback_and_cross_tenant_denial(app) -> None:
    with TestClient(app) as client:
        admin_token = _login(client, "admin@sbs.local")
        root_token = _login(client, "saas.root@sbs.local")
        tenants = client.get(
            "/api/v1/tenants",
            headers=_headers(root_token),
        ).json()
        other_tenant = next(
            item for item in tenants if item["slug"] == "demo-tenant-2"
        )

        denied = client.get(
            f"/api/v1/tenant-experience/current?tenant_id={other_tenant['id']}",
            headers=_headers(admin_token),
        )
        assert denied.status_code == 403

        initial = client.get(
            "/api/v1/tenant-experience/current",
            headers=_headers(admin_token),
        ).json()
        settings = _settings(initial)
        settings["short_name"] = "SVC"
        first = client.put(
            "/api/v1/tenant-experience/current",
            headers=_headers(admin_token),
            json={
                "expected_revision": initial["revision"],
                "change_reason": "Create rollback baseline",
                "settings": settings,
            },
        )
        assert first.status_code == 200, first.text

        logo = client.post(
            "/api/v1/tenant-experience/logo",
            headers=_headers(admin_token),
            data={
                "expected_revision": first.json()["revision"],
                "change_reason": "Publish approved PNG logo",
            },
            files={"file": ("tenant-logo.png", _valid_png(), "image/png")},
        )
        assert logo.status_code == 200, logo.text
        logo_payload = logo.json()
        assert logo_payload["revision"] == first.json()["revision"] + 1
        assert logo_payload["logo"]["data_url"].startswith("data:image/png;base64,")

        history = client.get(
            "/api/v1/tenant-experience/revisions",
            headers=_headers(admin_token),
        )
        assert history.status_code == 200, history.text
        assert all(item["integrity_valid"] for item in history.json())

        rollback = client.post(
            "/api/v1/tenant-experience/rollback",
            headers=_headers(admin_token),
            json={
                "expected_revision": logo_payload["revision"],
                "target_revision": first.json()["revision"],
                "change_reason": "Rollback after brand review",
            },
        )
        assert rollback.status_code == 200, rollback.text
        assert rollback.json()["revision"] == logo_payload["revision"] + 1
        assert rollback.json()["logo"] is None

        audits = client.get(
            "/api/v1/admin/audit-logs?action=tenant_experience.rolled_back",
            headers=_headers(admin_token),
        )
        assert audits.status_code == 200
        assert "Rollback after brand review" not in json.dumps(
            audits.json(),
            ensure_ascii=False,
        )
