from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import httpx
import pytest

from app.core.config import Settings
from app.models.integration_platform import (
    IntegrationServiceAccount,
    OutboundWebhookSubscription,
)
from app.models.tenant import Tenant
from app.services.cmdb_schema import canonical_json
from app.services.integration_platform import (
    ServiceAccountPrincipal,
    ServiceTokenError,
    authenticate_service_token,
    create_sdk_event,
    encrypt_subscription_secret,
    encrypt_subscription_target,
    issue_service_token,
    process_outbound_webhook_delivery,
    queue_outbound_webhook_event,
    replay_outbound_webhook_delivery,
    validate_outbound_target_url,
)


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "demo_mode": False,
        "credential_encryption_key": (
            "integration-platform-tests-dedicated-encryption-key-2026"
        ),
        "integration_outbound_webhook_allowed_hosts": ["hooks.example.test"],
        "integration_platform_max_active_tokens_per_account": 10,
    }
    values.update(overrides)
    return Settings(**values)


def _tenant(db_session) -> Tenant:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Integration Platform Test",
        slug=f"integration-platform-{suffix}",
        status="active",
    )
    db_session.add(tenant)
    db_session.flush()
    return tenant


def _account(
    db_session,
    tenant: Tenant,
    *,
    scopes: list[str] | None = None,
    cidrs: list[str] | None = None,
    rate_limit: int = 120,
) -> IntegrationServiceAccount:
    account = IntegrationServiceAccount(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        client_id=f"svc_{uuid.uuid4().hex}",
        name=f"Connector {uuid.uuid4().hex[:8]}",
        status="ACTIVE",
        allowed_scopes_json=canonical_json(
            scopes or ["integration.events.write", "tickets.read"]
        ),
        allowed_ip_cidrs_json=canonical_json(cidrs or []),
        rate_limit_per_minute=rate_limit,
        max_token_ttl_days=90,
        version=1,
        total_requests=0,
        failed_auth_count=0,
    )
    db_session.add(account)
    db_session.flush()
    return account


def _subscription(
    db_session,
    tenant: Tenant,
    *,
    settings: Settings,
    max_attempts: int = 3,
) -> tuple[OutboundWebhookSubscription, str]:
    subscription = OutboundWebhookSubscription(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name=f"Webhook {uuid.uuid4().hex[:8]}",
        status="ACTIVE",
        event_types_json='["monitoring.alert"]',
        target_hint="https://hooks.example.test/itsm",
        target_host="hooks.example.test",
        target_version=1,
        signing_secret_version=1,
        last_tested_target_version=1,
        last_tested_secret_version=1,
        timeout_seconds=10,
        max_attempts=max_attempts,
        version=1,
        success_count=0,
        failure_count=0,
        dead_letter_count=0,
    )
    secret = "whsec_" + "s" * 48
    subscription.target_url_encrypted = encrypt_subscription_target(
        subscription,
        "https://hooks.example.test/itsm",
        settings=settings,
    )
    subscription.signing_secret_encrypted = encrypt_subscription_secret(
        subscription,
        secret,
        settings=settings,
    )
    subscription.signing_secret_hint = f"whsec_…{secret[-6:]}"
    db_session.add(subscription)
    db_session.flush()
    return subscription, secret


def test_service_tokens_are_hash_only_scoped_ip_bound_and_rate_limited(
    db_session,
) -> None:
    tenant = _tenant(db_session)
    account = _account(
        db_session,
        tenant,
        cidrs=["203.0.113.0/24"],
        rate_limit=1,
    )
    item, raw_token = issue_service_token(
        db_session,
        account,
        name="Monitoring token",
        scopes=["integration.events.write"],
        ttl_days=30,
        actor_id=None,
        settings=_settings(),
    )
    assert raw_token.startswith("sbs_svc_")
    assert raw_token not in item.token_hash
    assert raw_token not in item.token_hint
    assert item.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()

    principal = authenticate_service_token(
        db_session,
        raw_token,
        required_scope="integration.events.write",
        request_id="request-1",
        method="POST",
        path="/sdk/v1/events",
        source_ip="203.0.113.10",
        user_agent="pytest",
    )
    assert principal.tenant_id == tenant.id
    assert principal.scopes == ("integration.events.write",)

    with pytest.raises(ServiceTokenError, match="rate limit"):
        authenticate_service_token(
            db_session,
            raw_token,
            required_scope="integration.events.write",
            request_id="request-2",
            method="POST",
            path="/sdk/v1/events",
            source_ip="203.0.113.10",
            user_agent="pytest",
        )


def test_service_token_rejects_wrong_scope_ip_revocation_and_active_token_limit(
    db_session,
) -> None:
    tenant = _tenant(db_session)
    account = _account(
        db_session,
        tenant,
        cidrs=["198.51.100.8/32"],
    )
    item, raw_token = issue_service_token(
        db_session,
        account,
        name="Scoped token",
        scopes=["integration.events.write"],
        ttl_days=7,
        actor_id=None,
        settings=_settings(integration_platform_max_active_tokens_per_account=1),
    )
    with pytest.raises(ServiceTokenError, match="required scope"):
        authenticate_service_token(
            db_session,
            raw_token,
            required_scope="tickets.read",
            request_id="scope-denied",
            method="GET",
            path="/sdk/v1/tickets/1",
            source_ip="198.51.100.8",
            user_agent=None,
        )
    with pytest.raises(ServiceTokenError, match="source IP"):
        authenticate_service_token(
            db_session,
            raw_token,
            required_scope="integration.events.write",
            request_id="ip-denied",
            method="POST",
            path="/sdk/v1/events",
            source_ip="198.51.100.9",
            user_agent=None,
        )
    with pytest.raises(ValueError, match="active-token limit"):
        issue_service_token(
            db_session,
            account,
            name="Second token",
            scopes=["integration.events.write"],
            ttl_days=7,
            actor_id=None,
            settings=_settings(integration_platform_max_active_tokens_per_account=1),
        )
    item.status = "REVOKED"
    with pytest.raises(ServiceTokenError, match="expired or revoked"):
        authenticate_service_token(
            db_session,
            raw_token,
            required_scope=None,
            request_id="revoked",
            method="GET",
            path="/sdk/v1/whoami",
            source_ip="198.51.100.8",
            user_agent=None,
        )


def test_outbound_target_requires_https_and_exact_allowlist() -> None:
    settings = _settings()
    target, host, hint = validate_outbound_target_url(
        "https://hooks.example.test/itsm?tenant=one",
        settings=settings,
    )
    assert target.endswith("?tenant=one")
    assert host == "hooks.example.test"
    assert hint == "https://hooks.example.test/itsm"

    rejected = (
        "http://hooks.example.test/itsm",
        "https://hooks.example.test.evil.invalid/itsm",
        "https://user:password@hooks.example.test/itsm",
        "https://hooks.example.test/itsm#fragment",
    )
    for value in rejected:
        with pytest.raises(ValueError):
            validate_outbound_target_url(value, settings=settings)


def test_cloud_event_is_encrypted_signed_and_delivered_once(db_session) -> None:
    settings = _settings()
    tenant = _tenant(db_session)
    subscription, secret = _subscription(
        db_session,
        tenant,
        settings=settings,
    )
    first = queue_outbound_webhook_event(
        db_session,
        tenant_id=tenant.id,
        event_id="provider-event-1",
        event_type="monitoring.alert",
        entity_type="asset",
        entity_id="asset-1",
        data={"severity": "critical", "summary": "CPU high"},
        idempotency_key="source:event:1",
        settings=settings,
    )[0]
    second = queue_outbound_webhook_event(
        db_session,
        tenant_id=tenant.id,
        event_id="provider-event-1",
        event_type="monitoring.alert",
        entity_type="asset",
        entity_id="asset-1",
        data={"severity": "critical", "summary": "CPU high"},
        idempotency_key="source:event:1",
        settings=settings,
    )[0]
    assert first.id == second.id
    assert "CPU high" not in first.payload_encrypted

    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content
        timestamp = request.headers["X-SBS-Timestamp"]
        expected = hmac.new(
            secret.encode(),
            timestamp.encode("ascii") + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        assert hmac.compare_digest(
            request.headers["X-SBS-Signature"],
            f"v1={expected}",
        )
        assert request.headers["Content-Type"] == "application/cloudevents+json"
        assert request.headers["Idempotency-Key"] == "source:event:1"
        payload = json.loads(body)
        assert payload["specversion"] == "1.0"
        assert payload["type"] == "com.sbs.itsm.monitoring.alert"
        assert payload["tenantid"] == tenant.id
        observed["delivery"] = request.headers["X-SBS-Delivery-ID"]
        return httpx.Response(202, headers={"X-Request-ID": "provider-req-1"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        process_outbound_webhook_delivery(
            db_session,
            first,
            settings=settings,
            client=client,
        )
    assert first.status == "SUCCEEDED"
    assert first.response_status == 202
    assert first.provider_request_id == "provider-req-1"
    assert first.target_version_used == 1
    assert first.signing_secret_version_used == 1
    assert observed["delivery"] == first.id
    assert subscription.success_count == 1


def test_retry_exhaustion_dead_letter_and_governed_replay(db_session) -> None:
    settings = _settings()
    tenant = _tenant(db_session)
    subscription, _ = _subscription(
        db_session,
        tenant,
        settings=settings,
        max_attempts=2,
    )
    delivery = queue_outbound_webhook_event(
        db_session,
        tenant_id=tenant.id,
        event_id="provider-event-2",
        event_type="monitoring.alert",
        data={"severity": "warning"},
        settings=settings,
    )[0]

    def unavailable(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"Retry-After": "1"})

    with httpx.Client(transport=httpx.MockTransport(unavailable)) as client:
        process_outbound_webhook_delivery(
            db_session,
            delivery,
            settings=settings,
            client=client,
        )
        assert delivery.status == "RETRY"
        process_outbound_webhook_delivery(
            db_session,
            delivery,
            settings=settings,
            client=client,
        )
    assert delivery.status == "DEAD_LETTER"
    assert delivery.attempts == 2
    assert subscription.dead_letter_count == 1

    replay = replay_outbound_webhook_delivery(
        db_session,
        delivery,
        settings=settings,
    )
    assert replay.status == "PENDING"
    assert replay.replay_of_id == delivery.id
    assert replay.id != delivery.id
    assert replay.payload_encrypted != delivery.payload_encrypted


def test_paused_subscription_preserves_pending_delivery(db_session) -> None:
    settings = _settings()
    tenant = _tenant(db_session)
    subscription, _ = _subscription(
        db_session,
        tenant,
        settings=settings,
    )
    delivery = queue_outbound_webhook_event(
        db_session,
        tenant_id=tenant.id,
        event_id="provider-event-paused",
        event_type="monitoring.alert",
        data={"severity": "warning"},
        settings=settings,
    )[0]
    subscription.status = "PAUSED"
    process_outbound_webhook_delivery(
        db_session,
        delivery,
        settings=settings,
    )
    assert delivery.status == "PENDING"
    assert delivery.attempts == 0
    assert delivery.completed_at is None
    assert "waiting" in (delivery.last_error or "").lower()


def test_sdk_event_idempotency_is_service_account_scoped_and_secret_safe(
    db_session,
) -> None:
    tenant = _tenant(db_session)
    first_account = _account(db_session, tenant)
    second_account = _account(db_session, tenant)
    first_principal = ServiceAccountPrincipal(
        tenant_id=tenant.id,
        service_account_id=first_account.id,
        client_id=first_account.client_id,
        name=first_account.name,
        token_id=str(uuid.uuid4()),
        scopes=("integration.events.write",),
    )
    second_principal = ServiceAccountPrincipal(
        tenant_id=tenant.id,
        service_account_id=second_account.id,
        client_id=second_account.client_id,
        name=second_account.name,
        token_id=str(uuid.uuid4()),
        scopes=("integration.events.write",),
    )
    first = create_sdk_event(
        db_session,
        first_principal,
        event_type="monitoring.alert",
        entity_type="asset",
        entity_id="asset-1",
        data={"severity": "critical"},
        idempotency_key="source-event-unique-1",
    )
    duplicate = create_sdk_event(
        db_session,
        first_principal,
        event_type="monitoring.alert",
        entity_type="asset",
        entity_id="asset-1",
        data={"severity": "critical"},
        idempotency_key="source-event-unique-1",
    )
    other_account = create_sdk_event(
        db_session,
        second_principal,
        event_type="monitoring.alert",
        entity_type="asset",
        entity_id="asset-1",
        data={"severity": "critical"},
        idempotency_key="source-event-unique-1",
    )
    assert duplicate.id == first.id
    assert other_account.id != first.id
    assert first.correlation_id != other_account.correlation_id

    with pytest.raises(ValueError, match="Sensitive field"):
        create_sdk_event(
            db_session,
            first_principal,
            event_type="monitoring.alert",
            entity_type=None,
            entity_id=None,
            data={"authorization_token": "must-not-be-logged"},
            idempotency_key="source-event-unique-2",
        )
