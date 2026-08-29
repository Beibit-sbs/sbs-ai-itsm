from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.models.event_operations import EventSource
from app.models.tenant import Tenant
from app.services.event_operations import source_token_hash
from app.services.monitoring_connectors import (
    MonitoringAuthenticationError,
    configure_hmac_secret,
    enqueue_monitoring_receipt,
    normalize_monitoring_payload,
    process_monitoring_receipt,
    verify_monitoring_request,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        demo_mode=True,
        credential_encryption_key=(
            "monitoring-tests-use-a-dedicated-credential-encryption-key-2026"
        ),
        monitoring_global_max_payload_bytes=2_097_152,
    )


def _tenant(db_session) -> Tenant:
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Monitoring Test Tenant",
        slug=f"monitoring-test-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db_session.add(tenant)
    db_session.flush()
    return tenant


def _source(
    db_session,
    tenant: Tenant,
    *,
    source_type: str = "GENERIC",
    auth_mode: str = "HMAC_SHA256",
) -> tuple[EventSource, str]:
    secret = "mon_" + "a" * 48
    token = "evt_" + "b" * 48
    source = EventSource(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        code=f"source-{uuid.uuid4().hex[:8]}",
        name="Production monitoring source",
        source_type=source_type,
        token_hash=source_token_hash(token),
        token_hint=token[-8:],
        auth_mode=auth_mode,
        replay_window_seconds=300,
        rate_limit_per_minute=120,
        max_payload_bytes=1_048_576,
        allowed_ip_cidrs_json=[],
        is_enabled=True,
        total_events=0,
        duplicate_events=0,
        suppressed_events=0,
        success_count=0,
        failure_count=0,
        dead_letter_count=0,
        version=1,
    )
    if auth_mode == "HMAC_SHA256":
        configure_hmac_secret(source, secret, settings=_settings())
    db_session.add(source)
    db_session.flush()
    return source, secret if auth_mode == "HMAC_SHA256" else token


def _signed(secret: str, body: bytes, timestamp: int) -> str:
    value = hmac.new(
        secret.encode("utf-8"),
        str(timestamp).encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={value}"


def test_hmac_authentication_replay_window_and_ip_allowlist(db_session) -> None:
    tenant = _tenant(db_session)
    source, secret = _source(db_session, tenant)
    source.allowed_ip_cidrs_json = ["203.0.113.0/24"]
    body = b'{"event_id":"evt-1","summary":"CPU high"}'
    timestamp = int(time.time())

    verified_at = verify_monitoring_request(
        source,
        raw_body=body,
        authorization=None,
        signature=_signed(secret, body, timestamp),
        timestamp=str(timestamp),
        source_ip="203.0.113.10",
        settings=_settings(),
    )
    assert verified_at is not None

    invalid_cases = (
        {
            "signature": "sha256=" + "0" * 64,
            "timestamp": str(timestamp),
            "source_ip": "203.0.113.10",
        },
        {
            "signature": _signed(secret, body, timestamp - 1_000),
            "timestamp": str(timestamp - 1_000),
            "source_ip": "203.0.113.10",
        },
        {
            "signature": _signed(secret, body, timestamp),
            "timestamp": str(timestamp),
            "source_ip": "10.0.0.1",
        },
    )
    for case in invalid_cases:
        try:
            verify_monitoring_request(
                source,
                raw_body=body,
                authorization=None,
                settings=_settings(),
                **case,
            )
        except MonitoringAuthenticationError:
            continue
        raise AssertionError("Unsafe monitoring request was accepted")


def test_receipt_is_encrypted_and_idempotent(db_session) -> None:
    tenant = _tenant(db_session)
    source, _ = _source(db_session, tenant)
    body = b'{"event_id":"evt-2","summary":"Memory high"}'
    first, duplicate = enqueue_monitoring_receipt(
        db_session,
        source,
        raw_body=body,
        content_type="application/json",
        source_ip="203.0.113.10",
        headers={
            "content-type": "application/json",
            "authorization": "Bearer must-not-be-stored",
            "x-sbs-signature": "must-not-be-stored",
        },
        idempotency_key="provider-event-2",
        request_timestamp=None,
        signature_verified=True,
        settings=_settings(),
    )
    db_session.flush()
    second, is_duplicate = enqueue_monitoring_receipt(
        db_session,
        source,
        raw_body=body,
        content_type="application/json",
        source_ip="203.0.113.10",
        headers={},
        idempotency_key="provider-event-2",
        request_timestamp=None,
        signature_verified=True,
        settings=_settings(),
    )
    assert duplicate is False
    assert is_duplicate is True
    assert first.id == second.id
    assert body.decode() not in first.payload_encrypted
    assert "authorization" not in first.safe_headers_json
    assert "x-sbs-signature" not in first.safe_headers_json


def test_provider_adapters_normalize_supported_formats() -> None:
    now = "2026-07-29T10:00:00Z"
    payloads = {
        "ALERTMANAGER": {
            "status": "firing",
            "receiver": "itsm",
            "alerts": [{
                "status": "firing",
                "labels": {
                    "alertname": "HighErrorRate",
                    "severity": "critical",
                    "service": "payments",
                    "instance": "api-01",
                },
                "annotations": {"summary": "Payment error rate is high"},
                "startsAt": now,
                "fingerprint": "am-1",
            }],
        },
        "GRAFANA": {
            "ruleId": 42,
            "ruleName": "Latency threshold",
            "state": "alerting",
            "message": "P99 is high",
            "tags": {"severity": "warning", "service": "api"},
            "timestamp": now,
        },
        "ZABBIX": {
            "event_id": "zbx-1",
            "trigger_id": "trigger-1",
            "status": "PROBLEM",
            "severity": "Disaster",
            "name": "Database unavailable",
            "host": "db-01",
            "occurred_at": now,
        },
        "SENTRY": {
            "action": "created",
            "data": {
                "event": {
                    "event_id": "sentry-1",
                    "title": "Unhandled exception",
                    "level": "error",
                    "platform": "python",
                    "timestamp": now,
                    "project": "api",
                }
            },
        },
        "GENERIC": {
            "event_id": "generic-1",
            "state": "FIRING",
            "severity": "HIGH",
            "summary": "Synthetic generic event",
            "timestamp": now,
        },
    }
    for provider, payload in payloads.items():
        events = normalize_monitoring_payload(provider, payload)
        assert len(events) == 1
        assert events[0]["state"] in {"FIRING", "RESOLVED"}
        assert events[0]["severity"] in {
            "INFO",
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }
        assert events[0]["idempotency_key"]
        assert events[0]["fingerprint"]


def test_worker_processes_generic_receipt_without_raw_payload_exposure(
    db_session,
) -> None:
    tenant = _tenant(db_session)
    source, _ = _source(db_session, tenant)
    payload = {
        "event_id": "generic-worker-1",
        "state": "FIRING",
        "severity": "HIGH",
        "summary": "Synthetic worker event",
        "timestamp": "2026-07-29T10:00:00Z",
    }
    receipt, _ = enqueue_monitoring_receipt(
        db_session,
        source,
        raw_body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        source_ip="203.0.113.10",
        headers={},
        idempotency_key="generic-worker-1",
        request_timestamp=None,
        signature_verified=True,
        settings=_settings(),
    )
    db_session.commit()

    result = process_monitoring_receipt(
        db_session,
        receipt,
        settings=_settings(),
    )

    assert result.status == "PROCESSED"
    assert result.normalized_event_count == 1
    assert result.processed_at is not None


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_admin_creates_hmac_source_and_webhook_returns_receipt(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local")
        created = client.post(
            "/api/v1/event-operations/sources",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": f"generic-hmac-{uuid.uuid4().hex[:8]}",
                "name": "Generic HMAC intake",
                "source_type": "GENERIC",
                "auth_mode": "HMAC_SHA256",
                "replay_window_seconds": 300,
                "rate_limit_per_minute": 60,
                "max_payload_bytes": 262_144,
            },
        )
        assert created.status_code == 201, created.text
        source = created.json()
        secret = source["signing_secret"]
        assert secret.startswith("mon_")
        assert "hmac_secret_encrypted" not in source

        body = json.dumps({
            "event_id": "api-hmac-1",
            "state": "FIRING",
            "severity": "HIGH",
            "summary": "API HMAC test event",
            "timestamp": "2026-07-29T10:00:00Z",
        }, separators=(",", ":")).encode("utf-8")
        timestamp = int(time.time())
        accepted = client.post(
            f"/api/v1/event-operations/webhooks/{source['id']}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-SBS-Timestamp": str(timestamp),
                "X-SBS-Signature": _signed(secret, body, timestamp),
                "X-Idempotency-Key": "api-hmac-1",
            },
        )
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["accepted"] is True

        receipts = client.get(
            "/api/v1/event-operations/webhook-receipts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert receipts.status_code == 200, receipts.text
        receipt = next(
            item
            for item in receipts.json()
            if item["id"] == accepted.json()["receipt_id"]
        )
        assert receipt["signature_verified"] is True
        assert "payload_encrypted" not in receipt
