from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.integration_event_log import IntegrationEventLog
from app.models.integration_platform import (
    IntegrationApiRequestLog,
    IntegrationApiToken,
    IntegrationServiceAccount,
    OutboundWebhookDelivery,
    OutboundWebhookSubscription,
)
from app.services.cmdb_schema import canonical_json
from app.services.credential_crypto import decrypt_credential, encrypt_credential


SERVICE_ACCOUNT_SCOPES: dict[str, str] = {
    "integration.events.write": "Publish governed integration events",
    "tickets.read": "Read ticket records through the connector SDK",
    "assets.read": "Read asset/CI records through the connector SDK",
}
_TOKEN_PATTERN = re.compile(
    r"^sbs_svc_([a-f0-9]{12})_([A-Za-z0-9_-]{32,})$"
)
_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,118}$")
_MAX_RESPONSE_BYTES = 65_536
_SENSITIVE_FIELD_PARTS = {
    "authorization",
    "api_key",
    "apikey",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
}


class ServiceTokenError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


class WebhookDeliveryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class ServiceAccountPrincipal:
    tenant_id: str
    service_account_id: str
    client_id: str
    name: str
    token_id: str
    scopes: tuple[str, ...]


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _assert_no_sensitive_fields(value: Any, *, path: str = "data", depth: int = 0) -> None:
    if depth > 12:
        raise ValueError("Integration event data exceeds the maximum nesting depth")
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(part in normalized for part in _SENSITIVE_FIELD_PARTS):
                raise ValueError(
                    f"Sensitive field {path}.{key} is not allowed in integration events"
                )
            _assert_no_sensitive_fields(
                child,
                path=f"{path}.{key}",
                depth=depth + 1,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_sensitive_fields(
                child,
                path=f"{path}[{index}]",
                depth=depth + 1,
            )


def validate_service_account_scopes(scopes: list[str]) -> list[str]:
    normalized = sorted({str(item).strip() for item in scopes if str(item).strip()})
    unsupported = [item for item in normalized if item not in SERVICE_ACCOUNT_SCOPES]
    if unsupported:
        raise ValueError("Unsupported service-account scopes: " + ", ".join(unsupported))
    if not normalized:
        raise ValueError("At least one service-account scope is required")
    return normalized


def validate_ip_cidrs(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if not value:
            continue
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid IP CIDR: {value}") from exc
        normalized.append(str(network))
    return sorted(set(normalized))


def _ip_allowed(source_ip: str | None, cidrs: list[str]) -> bool:
    if not cidrs:
        return True
    if not source_ip:
        return False
    try:
        address = ipaddress.ip_address(source_ip)
    except ValueError:
        return False
    return any(address in ipaddress.ip_network(value) for value in cidrs)


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_service_token(
    db: Session,
    account: IntegrationServiceAccount,
    *,
    name: str,
    scopes: list[str],
    ttl_days: int,
    actor_id: str | None,
    exclude_token_id: str | None = None,
    settings: Settings | None = None,
) -> tuple[IntegrationApiToken, str]:
    runtime = settings or get_settings()
    if account.status != "ACTIVE":
        raise ValueError("Service account must be active")
    token_name = name.strip()
    if len(token_name) < 2:
        raise ValueError("Token name must contain at least 2 characters")
    requested_scopes = validate_service_account_scopes(scopes)
    allowed_scopes = set(_json_list(account.allowed_scopes_json))
    if not set(requested_scopes).issubset(allowed_scopes):
        raise ValueError("Token scopes must be a subset of service-account scopes")
    if ttl_days < 1 or ttl_days > account.max_token_ttl_days:
        raise ValueError(
            f"Token TTL must be between 1 and {account.max_token_ttl_days} days"
        )
    active_statement = (
        select(func.count())
        .select_from(IntegrationApiToken)
        .where(
            IntegrationApiToken.service_account_id == account.id,
            IntegrationApiToken.status == "ACTIVE",
            IntegrationApiToken.expires_at > utcnow(),
        )
    )
    if exclude_token_id:
        active_statement = active_statement.where(
            IntegrationApiToken.id != exclude_token_id
        )
    active_count = int(db.scalar(active_statement) or 0)
    if active_count >= runtime.integration_platform_max_active_tokens_per_account:
        raise ValueError(
            "The service account has reached its active-token limit "
            f"({runtime.integration_platform_max_active_tokens_per_account})"
        )
    for _ in range(10):
        prefix = secrets.token_hex(6)
        if db.scalar(
            select(IntegrationApiToken.id).where(
                IntegrationApiToken.token_prefix == prefix
            )
        ) is None:
            break
    else:
        raise RuntimeError("Unable to allocate a unique token prefix")
    raw_token = f"sbs_svc_{prefix}_{secrets.token_urlsafe(32)}"
    now = utcnow()
    item = IntegrationApiToken(
        id=str(uuid.uuid4()),
        tenant_id=account.tenant_id,
        service_account_id=account.id,
        name=token_name,
        token_prefix=prefix,
        token_hash=_token_hash(raw_token),
        token_hint=f"sbs_svc_{prefix}_…{raw_token[-6:]}",
        scopes_json=canonical_json(requested_scopes),
        status="ACTIVE",
        version=1,
        expires_at=now + timedelta(days=ttl_days),
        rate_window_requests=0,
        issued_by_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    return item, raw_token


def _request_log(
    db: Session,
    *,
    account: IntegrationServiceAccount,
    token: IntegrationApiToken | None,
    request_id: str,
    method: str,
    path: str,
    source_ip: str | None,
    user_agent: str | None,
    required_scope: str | None,
    outcome: str,
    reason: str | None,
) -> None:
    db.add(
        IntegrationApiRequestLog(
            id=str(uuid.uuid4()),
            tenant_id=account.tenant_id,
            service_account_id=account.id,
            token_id=token.id if token else None,
            request_id=request_id[:120],
            method=method[:16],
            path=path[:500],
            source_ip=source_ip[:64] if source_ip else None,
            user_agent=user_agent[:500] if user_agent else None,
            required_scope=required_scope,
            outcome=outcome,
            reason=reason[:255] if reason else None,
            created_at=utcnow(),
        )
    )


def authenticate_service_token(
    db: Session,
    raw_token: str,
    *,
    required_scope: str | None,
    request_id: str,
    method: str,
    path: str,
    source_ip: str | None,
    user_agent: str | None,
) -> ServiceAccountPrincipal:
    if required_scope is not None and required_scope not in SERVICE_ACCOUNT_SCOPES:
        raise RuntimeError("Route requested an unknown service-account scope")
    match = _TOKEN_PATTERN.fullmatch(raw_token.strip())
    if match is None:
        raise ServiceTokenError("Invalid service token")
    prefix = match.group(1)
    token_statement = select(IntegrationApiToken).where(
        IntegrationApiToken.token_prefix == prefix
    )
    token = db.scalar(token_statement)
    if token is None:
        raise ServiceTokenError("Invalid service token")
    if not hmac.compare_digest(token.token_hash, _token_hash(raw_token)):
        # A lookup prefix is intentionally visible in token metadata. Do not
        # let a forged secret for a known prefix amplify persistent audit
        # writes or acquire account locks.
        raise ServiceTokenError("Invalid service token")
    account_statement = select(IntegrationServiceAccount).where(
        IntegrationServiceAccount.id == token.service_account_id
    )
    if db.get_bind().dialect.name == "postgresql":
        account_statement = account_statement.with_for_update()
    account = db.scalar(account_statement)
    if account is None:
        raise ServiceTokenError("Invalid service token")
    if db.get_bind().dialect.name == "postgresql":
        token = db.scalar(
            select(IntegrationApiToken)
            .where(IntegrationApiToken.id == token.id)
            .with_for_update()
        )
        if token is None:
            raise ServiceTokenError("Invalid service token")

    def deny(message: str, *, status_code: int = 401) -> None:
        account.failed_auth_count += 1
        _request_log(
            db,
            account=account,
            token=token,
            request_id=request_id,
            method=method,
            path=path,
            source_ip=source_ip,
            user_agent=user_agent,
            required_scope=required_scope,
            outcome="DENIED",
            reason=message,
        )
        db.flush()
        raise ServiceTokenError(message, status_code=status_code)

    if not hmac.compare_digest(token.token_hash, _token_hash(raw_token)):
        raise ServiceTokenError("Invalid service token")
    now = utcnow()
    window_started = (
        _aware(token.rate_window_started_at)
        if token.rate_window_started_at
        else None
    )
    if window_started is None or (now - window_started).total_seconds() >= 60:
        token.rate_window_started_at = now
        token.rate_window_requests = 0
    if token.rate_window_requests >= account.rate_limit_per_minute:
        deny("Service-token rate limit exceeded", status_code=429)
    token.rate_window_requests += 1
    if token.status != "ACTIVE" or _aware(token.expires_at) <= now:
        if token.status == "ACTIVE":
            token.status = "EXPIRED"
            token.version += 1
            token.updated_at = now
        deny("Service token is expired or revoked")
    if account.status != "ACTIVE":
        deny("Service account is not active", status_code=403)
    account_scopes = set(_json_list(account.allowed_scopes_json))
    token_scopes = set(_json_list(token.scopes_json))
    effective_scopes = account_scopes.intersection(token_scopes)
    if required_scope is not None and required_scope not in effective_scopes:
        deny("Service token does not grant the required scope", status_code=403)
    if not _ip_allowed(source_ip, _json_list(account.allowed_ip_cidrs_json)):
        deny("Service token source IP is not allowed", status_code=403)

    token.last_used_at = now
    token.last_used_ip = source_ip
    token.updated_at = now
    account.total_requests += 1
    account.last_used_at = now
    account.last_used_ip = source_ip
    account.updated_at = now
    _request_log(
        db,
        account=account,
        token=token,
        request_id=request_id,
        method=method,
        path=path,
        source_ip=source_ip,
        user_agent=user_agent,
        required_scope=required_scope,
        outcome="ALLOWED",
        reason=None,
    )
    db.flush()
    return ServiceAccountPrincipal(
        tenant_id=account.tenant_id,
        service_account_id=account.id,
        client_id=account.client_id,
        name=account.name,
        token_id=token.id,
        scopes=tuple(sorted(effective_scopes)),
    )


def _target_purpose(subscription_id: str) -> str:
    return f"outbound-webhook:{subscription_id}:target"


def _secret_purpose(subscription_id: str) -> str:
    return f"outbound-webhook:{subscription_id}:secret"


def _payload_purpose(subscription_id: str, delivery_id: str) -> str:
    return f"outbound-webhook:{subscription_id}:delivery:{delivery_id}"


def validate_outbound_target_url(
    value: str,
    *,
    settings: Settings | None = None,
) -> tuple[str, str, str]:
    runtime = settings or get_settings()
    target = value.strip()
    parsed = urlsplit(target)
    local_demo = (
        runtime.demo_mode
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )
    if (
        (parsed.scheme != "https" and not local_demo)
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Outbound webhook target must be an explicit HTTPS URL")
    host = parsed.hostname.rstrip(".").lower()
    allowed = {
        str(item).strip().rstrip(".").lower()
        for item in runtime.integration_outbound_webhook_allowed_hosts
        if str(item).strip()
    }
    if host not in allowed:
        raise ValueError(
            "Outbound webhook host is not in "
            "INTEGRATION_OUTBOUND_WEBHOOK_ALLOWED_HOSTS"
        )
    port = f":{parsed.port}" if parsed.port else ""
    hint = f"{parsed.scheme}://{host}{port}{parsed.path or '/'}"
    return target, host, hint[:255]


def encrypt_subscription_target(
    subscription: OutboundWebhookSubscription,
    target_url: str,
    *,
    settings: Settings | None = None,
) -> str:
    return encrypt_credential(
        target_url,
        purpose=_target_purpose(subscription.id),
        tenant_id=subscription.tenant_id,
        settings=settings,
    )


def decrypt_subscription_target(
    subscription: OutboundWebhookSubscription,
    *,
    settings: Settings | None = None,
) -> str:
    if not subscription.target_url_encrypted:
        raise WebhookDeliveryError("Webhook target is unavailable", retryable=False)
    return decrypt_credential(
        subscription.target_url_encrypted,
        purpose=_target_purpose(subscription.id),
        tenant_id=subscription.tenant_id,
        settings=settings,
    )


def new_signing_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(36)


def encrypt_subscription_secret(
    subscription: OutboundWebhookSubscription,
    secret: str,
    *,
    settings: Settings | None = None,
) -> str:
    if len(secret) < 32:
        raise ValueError("Webhook signing secret must contain at least 32 characters")
    return encrypt_credential(
        secret,
        purpose=_secret_purpose(subscription.id),
        tenant_id=subscription.tenant_id,
        settings=settings,
    )


def decrypt_subscription_secret(
    subscription: OutboundWebhookSubscription,
    *,
    settings: Settings | None = None,
) -> str:
    if not subscription.signing_secret_encrypted:
        raise WebhookDeliveryError("Webhook signing secret is unavailable", retryable=False)
    return decrypt_credential(
        subscription.signing_secret_encrypted,
        purpose=_secret_purpose(subscription.id),
        tenant_id=subscription.tenant_id,
        settings=settings,
    )


def validate_event_types(event_types: list[str]) -> list[str]:
    normalized = sorted({str(item).strip().lower() for item in event_types})
    if not normalized or len(normalized) > 100:
        raise ValueError("event_types must contain 1-100 values")
    for value in normalized:
        candidate = value[:-2] if value.endswith(".*") else value
        if not _EVENT_TYPE_PATTERN.fullmatch(candidate):
            raise ValueError(f"Invalid webhook event type: {value}")
    return normalized


def _event_matches(patterns: list[str], event_type: str) -> bool:
    normalized = event_type.lower()
    return any(
        pattern == normalized
        or (
            pattern.endswith(".*")
            and normalized.startswith(pattern[:-1])
        )
        for pattern in patterns
    )


def _cloud_event(
    *,
    tenant_id: str,
    event_id: str,
    event_type: str,
    entity_type: str | None,
    entity_id: str | None,
    data: dict[str, Any],
) -> dict[str, Any]:
    subject = (
        f"{entity_type}/{entity_id}"
        if entity_type and entity_id
        else entity_type or entity_id
    )
    envelope: dict[str, Any] = {
        "specversion": "1.0",
        "id": event_id,
        "source": f"/sbs-ai-itsm/tenants/{tenant_id}",
        "type": f"com.sbs.itsm.{event_type}",
        "time": utcnow().isoformat().replace("+00:00", "Z"),
        "datacontenttype": "application/json",
        "tenantid": tenant_id,
        "data": data,
    }
    if subject:
        envelope["subject"] = subject
    return envelope


def queue_outbound_webhook_event(
    db: Session,
    *,
    tenant_id: str,
    event_id: str,
    event_type: str,
    data: dict[str, Any],
    entity_type: str | None = None,
    entity_id: str | None = None,
    idempotency_key: str | None = None,
    subscription_id: str | None = None,
    is_test: bool = False,
    settings: Settings | None = None,
) -> list[OutboundWebhookDelivery]:
    runtime = settings or get_settings()
    event_type = event_type.strip().lower()
    if not _EVENT_TYPE_PATTERN.fullmatch(event_type):
        raise ValueError("Invalid outbound webhook event type")
    statement = select(OutboundWebhookSubscription).where(
        OutboundWebhookSubscription.tenant_id == tenant_id,
    )
    if subscription_id:
        statement = statement.where(OutboundWebhookSubscription.id == subscription_id)
    else:
        statement = statement.where(
            OutboundWebhookSubscription.status == "ACTIVE"
        )
    subscriptions = db.scalars(statement).all()
    envelope = _cloud_event(
        tenant_id=tenant_id,
        event_id=event_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        data=data,
    )
    payload = canonical_json(envelope)
    payload_bytes = len(payload.encode("utf-8"))
    if payload_bytes > runtime.integration_outbound_webhook_max_payload_bytes:
        raise ValueError("Outbound webhook payload exceeds the configured limit")
    now = utcnow()
    queued: list[OutboundWebhookDelivery] = []
    for subscription in subscriptions:
        if not is_test and not _event_matches(
            _json_list(subscription.event_types_json),
            event_type,
        ):
            continue
        if is_test and subscription.status not in {"DRAFT", "PAUSED", "ACTIVE"}:
            continue
        key = (idempotency_key or event_id).strip()[:200]
        existing = db.scalar(
            select(OutboundWebhookDelivery).where(
                OutboundWebhookDelivery.subscription_id == subscription.id,
                OutboundWebhookDelivery.idempotency_key == key,
            )
        )
        if existing is not None:
            queued.append(existing)
            continue
        delivery_id = str(uuid.uuid4())
        encrypted = encrypt_credential(
            payload,
            purpose=_payload_purpose(subscription.id, delivery_id),
            tenant_id=tenant_id,
            settings=runtime,
        )
        delivery = OutboundWebhookDelivery(
            id=delivery_id,
            tenant_id=tenant_id,
            subscription_id=subscription.id,
            event_id=event_id[:120],
            idempotency_key=key,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_encrypted=encrypted,
            payload_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            payload_bytes=payload_bytes,
            status="PENDING",
            is_test=is_test,
            attempts=0,
            max_attempts=subscription.max_attempts,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(delivery)
        queued.append(delivery)
    db.flush()
    return queued


def queue_notification_webhooks(
    db: Session,
    *,
    tenant_id: str,
    notification_id: str,
    event_type: str,
    title: str,
    message: str,
    severity: str,
    entity_type: str | None,
    entity_id: str | None,
    action_url: str | None,
) -> list[OutboundWebhookDelivery]:
    normalized_event_type = re.sub(
        r"[^a-z0-9_.-]+",
        "_",
        event_type.lower(),
    ).strip("_.-")
    if not normalized_event_type or not normalized_event_type[0].isalpha():
        normalized_event_type = f"event_{normalized_event_type or 'unknown'}"
    return queue_outbound_webhook_event(
        db,
        tenant_id=tenant_id,
        event_id=notification_id,
        event_type=normalized_event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        data={
            "title": title,
            "message": message,
            "severity": severity,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action_url": action_url,
        },
        idempotency_key=f"notification:{notification_id}",
    )


def _retry_after(headers: httpx.Headers) -> int | None:
    value = headers.get("retry-after")
    if not value:
        return None
    try:
        return max(1, min(int(value), 86_400))
    except ValueError:
        return None


def _send_delivery(
    client: httpx.Client,
    *,
    target_url: str,
    body: bytes,
    secret: str,
    subscription: OutboundWebhookSubscription,
    delivery: OutboundWebhookDelivery,
) -> tuple[int, int, str | None, httpx.Headers]:
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    started = time.monotonic()
    try:
        with client.stream(
            "POST",
            target_url,
            headers={
                "Content-Type": "application/cloudevents+json",
                "User-Agent": "SBS-AI-ITSM-Webhooks/1.0",
                "X-SBS-Webhook-ID": subscription.id,
                "X-SBS-Delivery-ID": delivery.id,
                "X-SBS-Timestamp": timestamp,
                "X-SBS-Signature": f"v1={signature}",
                "Idempotency-Key": delivery.idempotency_key,
            },
            content=body,
        ) as response:
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    raise WebhookDeliveryError(
                        "Webhook response exceeded the safety limit",
                        retryable=False,
                    )
            elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            if response.is_redirect:
                raise WebhookDeliveryError(
                    "Webhook redirect was rejected",
                    retryable=False,
                    status_code=response.status_code,
                )
            request_id = (
                response.headers.get("x-request-id")
                or response.headers.get("request-id")
            )
            if not 200 <= response.status_code < 300:
                retryable = response.status_code in {408, 425, 429} or (
                    response.status_code >= 500
                )
                raise WebhookDeliveryError(
                    f"Webhook returned HTTP {response.status_code}",
                    retryable=retryable,
                    status_code=response.status_code,
                    retry_after_seconds=_retry_after(response.headers),
                )
            return response.status_code, elapsed_ms, request_id, response.headers
    except WebhookDeliveryError:
        raise
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise WebhookDeliveryError(
            f"Webhook network failure: {exc.__class__.__name__}",
            retryable=True,
        ) from exc


def process_outbound_webhook_delivery(
    db: Session,
    delivery: OutboundWebhookDelivery,
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> OutboundWebhookDelivery:
    runtime = settings or get_settings()
    subscription_statement = select(OutboundWebhookSubscription).where(
        OutboundWebhookSubscription.id == delivery.subscription_id
    )
    if db.get_bind().dialect.name == "postgresql":
        subscription_statement = subscription_statement.with_for_update()
    subscription = db.scalar(subscription_statement)
    now = utcnow()
    if subscription is None or subscription.status == "REVOKED":
        delivery.status = "CANCELLED"
        delivery.last_error = "Webhook subscription is unavailable or inactive"
        delivery.completed_at = now
        delivery.updated_at = now
        db.flush()
        return delivery
    if (
        subscription.status in {"DRAFT", "PAUSED"}
        and not delivery.is_test
    ):
        delivery.next_attempt_at = now + timedelta(seconds=60)
        delivery.last_error = "Delivery is waiting for webhook activation"
        delivery.updated_at = now
        db.flush()
        return delivery
    delivery.status = "PROCESSING"
    delivery.attempts += 1
    delivery.updated_at = now
    db.flush()
    try:
        target_url = decrypt_subscription_target(subscription, settings=runtime)
        target_url, _, _ = validate_outbound_target_url(target_url, settings=runtime)
        secret = decrypt_subscription_secret(subscription, settings=runtime)
        delivery.target_version_used = subscription.target_version
        delivery.signing_secret_version_used = subscription.signing_secret_version
        payload = decrypt_credential(
            delivery.payload_encrypted,
            purpose=_payload_purpose(subscription.id, delivery.id),
            tenant_id=delivery.tenant_id,
            settings=runtime,
        )
        body = payload.encode("utf-8")
        if len(body) != delivery.payload_bytes or (
            not hmac.compare_digest(
                hashlib.sha256(body).hexdigest(),
                delivery.payload_sha256,
            )
        ):
            raise WebhookDeliveryError(
                "Webhook payload integrity check failed",
                retryable=False,
            )
        own_client = client is None
        active_client = client or httpx.Client(
            timeout=httpx.Timeout(
                min(
                    float(subscription.timeout_seconds),
                    runtime.integration_outbound_webhook_timeout_seconds,
                )
            ),
            follow_redirects=False,
        )
        try:
            response_status, elapsed_ms, request_id, _ = _send_delivery(
                active_client,
                target_url=target_url,
                body=body,
                secret=secret,
                subscription=subscription,
                delivery=delivery,
            )
        finally:
            if own_client:
                active_client.close()
    except Exception as exc:
        if isinstance(exc, WebhookDeliveryError):
            error = exc
        else:
            error = WebhookDeliveryError(
                f"{exc.__class__.__name__}: webhook delivery failed",
                retryable=False,
            )
        failed_at = utcnow()
        delivery.response_status = error.status_code
        delivery.last_error = str(error)[:2_000]
        delivery.updated_at = failed_at
        if error.retryable and delivery.attempts < delivery.max_attempts:
            delay = error.retry_after_seconds or min(
                3_600,
                30 * (2 ** delivery.attempts),
            )
            delivery.status = "RETRY"
            delivery.next_attempt_at = failed_at + timedelta(seconds=delay)
        else:
            delivery.status = "DEAD_LETTER" if error.retryable else "FAILED"
            delivery.completed_at = failed_at
            if delivery.status == "DEAD_LETTER":
                subscription.dead_letter_count += 1
        subscription.failure_count += 1
        subscription.last_failure_at = failed_at
        subscription.last_error = delivery.last_error
        subscription.updated_at = failed_at
        db.flush()
        return delivery

    completed = utcnow()
    delivery.status = "SUCCEEDED"
    delivery.response_status = response_status
    delivery.response_time_ms = elapsed_ms
    delivery.provider_request_id = request_id[:255] if request_id else None
    delivery.last_error = None
    delivery.completed_at = completed
    delivery.updated_at = completed
    subscription.success_count += 1
    subscription.last_success_at = completed
    subscription.last_error = None
    subscription.updated_at = completed
    if delivery.is_test:
        subscription.last_tested_target_version = subscription.target_version
        subscription.last_tested_secret_version = (
            subscription.signing_secret_version
        )
    db.flush()
    return delivery


def replay_outbound_webhook_delivery(
    db: Session,
    original: OutboundWebhookDelivery,
    *,
    settings: Settings | None = None,
) -> OutboundWebhookDelivery:
    runtime = settings or get_settings()
    if original.status not in {"FAILED", "DEAD_LETTER", "CANCELLED"}:
        raise ValueError("Only failed, dead-letter, or cancelled deliveries can replay")
    subscription = db.get(
        OutboundWebhookSubscription,
        original.subscription_id,
    )
    if subscription is None or subscription.status != "ACTIVE":
        raise ValueError("Webhook subscription must be active before replay")
    payload = decrypt_credential(
        original.payload_encrypted,
        purpose=_payload_purpose(original.subscription_id, original.id),
        tenant_id=original.tenant_id,
        settings=runtime,
    )
    now = utcnow()
    delivery_id = str(uuid.uuid4())
    item = OutboundWebhookDelivery(
        id=delivery_id,
        tenant_id=original.tenant_id,
        subscription_id=original.subscription_id,
        replay_of_id=original.id,
        event_id=original.event_id,
        idempotency_key=f"replay:{original.id}:{uuid.uuid4().hex}"[:200],
        event_type=original.event_type,
        entity_type=original.entity_type,
        entity_id=original.entity_id,
        payload_encrypted=encrypt_credential(
            payload,
            purpose=_payload_purpose(original.subscription_id, delivery_id),
            tenant_id=original.tenant_id,
            settings=runtime,
        ),
        payload_sha256=original.payload_sha256,
        payload_bytes=original.payload_bytes,
        status="PENDING",
        is_test=original.is_test,
        attempts=0,
        max_attempts=subscription.max_attempts,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    return item


def run_outbound_webhook_cycle(
    db: Session,
    *,
    settings: Settings | None = None,
) -> dict[str, int]:
    runtime = settings or get_settings()
    now = utcnow()
    delivery_ids = db.scalars(
        select(OutboundWebhookDelivery.id)
        .where(
            OutboundWebhookDelivery.status.in_({"PENDING", "RETRY"}),
            OutboundWebhookDelivery.next_attempt_at <= now,
        )
        .order_by(OutboundWebhookDelivery.created_at)
        .limit(runtime.integration_platform_worker_batch_size)
    ).all()
    db.commit()
    processed = succeeded = retried = dead_lettered = failed = cancelled = deferred = 0
    for delivery_id in delivery_ids:
        statement = select(OutboundWebhookDelivery).where(
            OutboundWebhookDelivery.id == delivery_id,
            OutboundWebhookDelivery.status.in_({"PENDING", "RETRY"}),
            OutboundWebhookDelivery.next_attempt_at <= utcnow(),
        )
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        delivery = db.scalar(statement)
        if delivery is None:
            db.rollback()
            continue
        process_outbound_webhook_delivery(
            db,
            delivery,
            settings=runtime,
        )
        status = delivery.status
        db.commit()
        processed += 1
        succeeded += int(status == "SUCCEEDED")
        retried += int(status == "RETRY")
        dead_lettered += int(status == "DEAD_LETTER")
        failed += int(status == "FAILED")
        cancelled += int(status == "CANCELLED")
        deferred += int(
            status in {"PENDING", "RETRY"}
            and delivery.last_error == "Delivery is waiting for webhook activation"
        )
    return {
        "processed": processed,
        "succeeded": succeeded,
        "retried": retried,
        "dead_lettered": dead_lettered,
        "failed": failed,
        "cancelled": cancelled,
        "deferred": deferred,
    }


def cleanup_integration_platform_records(
    db: Session,
    *,
    settings: Settings | None = None,
) -> dict[str, int]:
    runtime = settings or get_settings()
    now = utcnow()
    request_cutoff = now - timedelta(
        days=runtime.integration_platform_request_log_retention_days
    )
    delivery_cutoff = now - timedelta(
        days=runtime.integration_platform_delivery_retention_days
    )
    request_result = db.execute(
        delete(IntegrationApiRequestLog).where(
            IntegrationApiRequestLog.created_at < request_cutoff
        )
    )
    delivery_result = db.execute(
        delete(OutboundWebhookDelivery).where(
            OutboundWebhookDelivery.status.in_(
                {"SUCCEEDED", "FAILED", "DEAD_LETTER", "CANCELLED"}
            ),
            OutboundWebhookDelivery.completed_at.is_not(None),
            OutboundWebhookDelivery.completed_at < delivery_cutoff,
        )
    )
    db.commit()
    return {
        "request_logs_deleted": int(request_result.rowcount or 0),
        "deliveries_deleted": int(delivery_result.rowcount or 0),
    }


def create_sdk_event(
    db: Session,
    principal: ServiceAccountPrincipal,
    *,
    event_type: str,
    entity_type: str | None,
    entity_id: str | None,
    data: dict[str, Any],
    idempotency_key: str,
) -> IntegrationEventLog:
    event_type = event_type.strip().lower()
    if not _EVENT_TYPE_PATTERN.fullmatch(event_type):
        raise ValueError("Invalid integration event type")
    idempotency_key = idempotency_key.strip()
    if len(idempotency_key) < 8 or len(idempotency_key) > 120:
        raise ValueError("Idempotency key must contain 8-120 characters")
    entity_type = entity_type.strip() if entity_type and entity_type.strip() else None
    entity_id = entity_id.strip() if entity_id and entity_id.strip() else None
    _assert_no_sensitive_fields(data)
    correlation_id = (
        "sdk:"
        + principal.service_account_id
        + ":"
        + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    )
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"{principal.tenant_id}:{correlation_id}"},
        )
    existing = db.scalar(
        select(IntegrationEventLog).where(
            IntegrationEventLog.tenant_id == principal.tenant_id,
            IntegrationEventLog.correlation_id == correlation_id,
            IntegrationEventLog.direction == "inbound",
        )
    )
    if existing is not None:
        return existing
    now = utcnow()
    event = IntegrationEventLog(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        external_system_id=None,
        direction="inbound",
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        status="success",
        payload_json=canonical_json(data),
        response_payload_json="{}",
        request_summary=canonical_json(
            {
                "service_account_id": principal.service_account_id,
                "event_type": event_type,
            }
        ),
        response_summary="{}",
        attempt_count=1,
        processed_at=now,
        correlation_id=correlation_id,
        created_at=now,
    )
    db.add(event)
    db.flush()
    queue_outbound_webhook_event(
        db,
        tenant_id=principal.tenant_id,
        event_id=event.id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        data=data,
        idempotency_key=f"sdk-event:{event.id}",
    )
    return event
