from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.event_operations import EventSource, MonitoringWebhookReceipt
from app.services.credential_crypto import decrypt_credential, encrypt_credential
from app.services.event_operations import ingest_normalized_event, source_token_hash


class MonitoringAuthenticationError(RuntimeError):
    pass


class MonitoringRateLimitError(RuntimeError):
    pass


class MonitoringPayloadError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def issue_hmac_secret() -> str:
    return f"mon_{secrets.token_urlsafe(48)}"


def configure_hmac_secret(
    source: EventSource,
    secret: str,
    *,
    settings: Settings | None = None,
) -> None:
    if len(secret) < 32:
        raise ValueError("Monitoring HMAC secret must be at least 32 characters")
    source.hmac_secret_encrypted = encrypt_credential(
        secret,
        purpose=f"event-source:{source.id}:hmac",
        tenant_id=source.tenant_id,
        settings=settings,
    )
    source.hmac_secret_hint = secret[-8:]


def _source_ip_allowed(source: EventSource, source_ip: str | None) -> bool:
    rules = list(source.allowed_ip_cidrs_json or [])
    if not rules:
        return True
    try:
        address = ipaddress.ip_address(source_ip or "")
    except ValueError:
        return False
    for value in rules:
        try:
            if address in ipaddress.ip_network(value, strict=False):
                return True
        except ValueError:
            continue
    return False


def verify_monitoring_request(
    source: EventSource,
    *,
    raw_body: bytes,
    authorization: str | None,
    signature: str | None,
    timestamp: str | None,
    source_ip: str | None,
    settings: Settings | None = None,
) -> datetime | None:
    runtime = settings or get_settings()
    if not source.is_enabled:
        raise MonitoringAuthenticationError("Monitoring source is disabled")
    if len(raw_body) > min(
        source.max_payload_bytes,
        runtime.monitoring_global_max_payload_bytes,
    ):
        raise MonitoringPayloadError("Monitoring payload exceeds configured limit")
    if not _source_ip_allowed(source, source_ip):
        raise MonitoringAuthenticationError("Monitoring source IP is not allowed")
    if source.auth_mode == "BEARER":
        token = ""
        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
        if not token or not secrets.compare_digest(
            source.token_hash,
            source_token_hash(token),
        ):
            raise MonitoringAuthenticationError("Invalid monitoring credentials")
        return None
    if source.auth_mode != "HMAC_SHA256" or not source.hmac_secret_encrypted:
        raise MonitoringAuthenticationError("Monitoring HMAC is not configured")
    if not signature:
        raise MonitoringAuthenticationError("Monitoring signature is required")
    request_time: datetime | None = None
    if source.source_type != "SENTRY":
        if not timestamp:
            raise MonitoringAuthenticationError("Monitoring timestamp is required")
        try:
            timestamp_value = int(timestamp)
            request_time = datetime.fromtimestamp(timestamp_value, tz=UTC)
        except (ValueError, OSError, OverflowError) as exc:
            raise MonitoringAuthenticationError("Invalid monitoring timestamp") from exc
        if abs((utcnow() - request_time).total_seconds()) > source.replay_window_seconds:
            raise MonitoringAuthenticationError("Monitoring request is outside replay window")
    try:
        secret = decrypt_credential(
            source.hmac_secret_encrypted,
            purpose=f"event-source:{source.id}:hmac",
            tenant_id=source.tenant_id,
            settings=runtime,
        )
    except (RuntimeError, ValueError) as exc:
        raise MonitoringAuthenticationError("Monitoring HMAC is unavailable") from exc
    supplied = signature.strip().lower()
    if supplied.startswith("sha256="):
        supplied = supplied.removeprefix("sha256=")
    if len(supplied) != 64 or any(char not in "0123456789abcdef" for char in supplied):
        raise MonitoringAuthenticationError("Invalid monitoring signature")
    if source.source_type == "GRAFANA":
        assert timestamp is not None
        signed = timestamp.encode("ascii") + b":" + raw_body
    elif source.source_type == "SENTRY":
        signed = raw_body
    else:
        assert timestamp is not None
        signed = timestamp.encode("ascii") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not secrets.compare_digest(supplied, expected):
        raise MonitoringAuthenticationError("Invalid monitoring signature")
    return request_time


def validate_ip_cidrs(values: list[str]) -> list[str]:
    result: list[str] = []
    for raw in values:
        try:
            network = ipaddress.ip_network(raw.strip(), strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid IP network: {raw}") from exc
        result.append(str(network))
    return list(dict.fromkeys(result))


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    allowed = {
        "content-type",
        "user-agent",
        "x-event-id",
        "x-idempotency-key",
        "x-request-id",
        "sentry-hook-resource",
    }
    return {
        key.lower()[:120]: value[:1_000]
        for key, value in headers.items()
        if key.lower() in allowed
    }


def enqueue_monitoring_receipt(
    db: Session,
    source: EventSource,
    *,
    raw_body: bytes,
    content_type: str | None,
    source_ip: str | None,
    headers: dict[str, str],
    idempotency_key: str | None,
    request_timestamp: datetime | None,
    signature_verified: bool,
    settings: Settings | None = None,
) -> tuple[MonitoringWebhookReceipt, bool]:
    runtime = settings or get_settings()
    if content_type and "application/json" not in content_type.lower():
        raise MonitoringPayloadError("Monitoring webhook requires application/json")
    try:
        decoded = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MonitoringPayloadError("Monitoring payload must be UTF-8") from exc
    body_hash = hashlib.sha256(raw_body).hexdigest()
    raw_request_key = (idempotency_key or body_hash).strip()
    request_key = hashlib.sha256(raw_request_key.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(MonitoringWebhookReceipt).where(
            MonitoringWebhookReceipt.source_id == source.id,
            MonitoringWebhookReceipt.request_key == request_key,
        )
    )
    if existing is not None:
        return existing, True
    since = utcnow() - timedelta(minutes=1)
    recent_count = int(
        db.scalar(
            select(func.count(MonitoringWebhookReceipt.id)).where(
                MonitoringWebhookReceipt.source_id == source.id,
                MonitoringWebhookReceipt.received_at >= since,
            )
        )
        or 0
    )
    if recent_count >= source.rate_limit_per_minute:
        raise MonitoringRateLimitError("Monitoring source rate limit exceeded")
    now = utcnow()
    receipt_id = str(uuid.uuid4())
    receipt = MonitoringWebhookReceipt(
        id=receipt_id,
        tenant_id=source.tenant_id,
        source_id=source.id,
        provider_type=source.source_type,
        request_key=request_key,
        body_hash=body_hash,
        payload_encrypted=encrypt_credential(
            decoded,
            purpose=f"monitoring-receipt:{receipt_id}",
            tenant_id=source.tenant_id,
            settings=runtime,
        ),
        payload_size=len(raw_body),
        content_type=(content_type or "")[:200] or None,
        source_ip=source_ip[:64] if source_ip else None,
        signature_verified=signature_verified,
        request_timestamp=request_timestamp,
        safe_headers_json=_safe_headers(headers),
        status="RECEIVED",
        attempts=0,
        max_attempts=5,
        next_attempt_at=now,
        normalized_event_count=0,
        duplicate_event_count=0,
        incident_count=0,
        received_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(receipt)
    return receipt, False


def _datetime(value: Any, *, fallback: datetime | None = None) -> datetime:
    if value is None or value == "":
        return fallback or utcnow()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    raw = str(value).strip()
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw), tz=UTC)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MonitoringPayloadError(f"Invalid event timestamp: {raw[:80]}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _severity(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    mapping = {
        "0": "INFO",
        "1": "INFO",
        "2": "LOW",
        "3": "MEDIUM",
        "4": "HIGH",
        "5": "CRITICAL",
        "debug": "INFO",
        "info": "INFO",
        "informational": "INFO",
        "notice": "LOW",
        "low": "LOW",
        "warning": "HIGH",
        "warn": "HIGH",
        "medium": "MEDIUM",
        "error": "HIGH",
        "high": "HIGH",
        "critical": "CRITICAL",
        "fatal": "CRITICAL",
        "sev1": "CRITICAL",
        "sev2": "HIGH",
        "p1": "CRITICAL",
        "p2": "HIGH",
        "p3": "MEDIUM",
        "p4": "LOW",
        "disaster": "CRITICAL",
    }
    return mapping.get(normalized, "MEDIUM")


def _state(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {
        "resolved",
        "resolve",
        "recovered",
        "recovery",
        "ok",
        "closed",
        "normal",
        "0",
    }:
        return "RESOLVED"
    return "FIRING"


def _mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _tags(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return _mapping(value)
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for item in value:
        if isinstance(item, dict):
            key = item.get("key") or item.get("tag")
            if key is not None:
                result[str(key)] = str(item.get("value") or "")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            result[str(item[0])] = str(item[1])
    return result


def _normalized(
    *,
    key: Any,
    external_id: Any,
    fingerprint: Any,
    state: Any,
    severity: Any,
    summary: Any,
    description: Any = None,
    service: Any = None,
    resource: Any = None,
    environment: Any = None,
    occurred_at: Any = None,
    labels: Any = None,
    annotations: Any = None,
) -> dict[str, Any]:
    safe_summary = " ".join(str(summary or "Monitoring event").split())
    if len(safe_summary) < 3:
        safe_summary = f"Monitoring event {safe_summary}".strip()
    external = str(external_id or key or uuid.uuid4())
    fingerprint_value = str(fingerprint or external)
    return {
        "idempotency_key": str(key or external)[:255],
        "external_id": external[:255],
        "fingerprint": fingerprint_value[:255],
        "state": _state(state),
        "severity": _severity(severity),
        "summary": safe_summary[:500],
        "description": str(description).strip()[:20_000] if description else None,
        "service": str(service).strip()[:200] if service else None,
        "resource": str(resource).strip()[:255] if resource else None,
        "environment": str(environment).strip()[:80] if environment else None,
        "occurred_at": _datetime(occurred_at),
        "labels": _mapping(labels),
        "annotations": _mapping(annotations),
    }


def _alertmanager(payload: dict[str, Any]) -> list[dict[str, Any]]:
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        raise MonitoringPayloadError("Alertmanager payload requires non-empty alerts")
    if len(alerts) > 500:
        raise MonitoringPayloadError("Alertmanager payload exceeds 500 alerts")
    result: list[dict[str, Any]] = []
    for raw in alerts:
        if not isinstance(raw, dict):
            raise MonitoringPayloadError("Alertmanager alert must be an object")
        labels = _mapping(raw.get("labels"))
        annotations = _mapping(raw.get("annotations"))
        fingerprint = raw.get("fingerprint") or hashlib.sha256(
            json.dumps(labels, sort_keys=True).encode("utf-8")
        ).hexdigest()
        status = raw.get("status") or payload.get("status")
        started = raw.get("startsAt") or raw.get("starts_at")
        occurred = raw.get("endsAt") if _state(status) == "RESOLVED" else started
        result.append(
            _normalized(
                key=f"{fingerprint}:{_state(status)}:{started}",
                external_id=fingerprint,
                fingerprint=fingerprint,
                state=status,
                severity=labels.get("severity") or labels.get("priority"),
                summary=annotations.get("summary")
                or annotations.get("message")
                or labels.get("alertname")
                or f"Alert {fingerprint}",
                description=annotations.get("description") or annotations.get("message"),
                service=labels.get("service")
                or labels.get("job")
                or labels.get("namespace"),
                resource=labels.get("instance")
                or labels.get("pod")
                or labels.get("device"),
                environment=labels.get("environment") or labels.get("env"),
                occurred_at=occurred or started,
                labels=labels,
                annotations={
                    **annotations,
                    "generator_url": str(raw.get("generatorURL") or ""),
                    "receiver": str(payload.get("receiver") or ""),
                },
            )
        )
    return result


def _grafana(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("alerts"), list):
        return _alertmanager(payload)
    rule_id = payload.get("ruleId") or payload.get("rule_id") or payload.get("uid")
    rule_name = payload.get("ruleName") or payload.get("rule_name") or payload.get("title")
    if not rule_id and not rule_name:
        raise MonitoringPayloadError("Grafana payload has no alert rule identifier")
    state = payload.get("state") or payload.get("status")
    occurred = payload.get("evalMatches") or payload.get("eval_matches")
    matches = occurred if isinstance(occurred, list) else []
    labels = _mapping(payload.get("tags"))
    return [
        _normalized(
            key=f"{rule_id or rule_name}:{_state(state)}:{payload.get('ruleUrl') or ''}",
            external_id=rule_id or rule_name,
            fingerprint=rule_id or rule_name,
            state=state,
            severity=labels.get("severity") or payload.get("severity"),
            summary=rule_name or "Grafana alert",
            description=payload.get("message"),
            service=labels.get("service") or labels.get("folder"),
            resource=(matches[0].get("metric") if matches and isinstance(matches[0], dict) else None),
            environment=labels.get("environment") or labels.get("env"),
            occurred_at=payload.get("timestamp"),
            labels=labels,
            annotations={"rule_url": str(payload.get("ruleUrl") or "")},
        )
    ]


def _sentry(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    event = data.get("event") if isinstance(data.get("event"), dict) else payload.get("event")
    if not isinstance(event, dict):
        event = data.get("issue") if isinstance(data.get("issue"), dict) else payload
    issue = data.get("issue") if isinstance(data.get("issue"), dict) else {}
    event_id = event.get("event_id") or event.get("id") or issue.get("id")
    if not event_id:
        raise MonitoringPayloadError("Sentry payload has no event or issue ID")
    project = event.get("project")
    project_name = (
        project.get("name") or project.get("slug")
        if isinstance(project, dict)
        else project
    )
    labels = {
        **_tags(event.get("tags")),
        "platform": str(event.get("platform") or ""),
        "project": str(project_name or ""),
    }
    action = payload.get("action") or event.get("status") or "triggered"
    return [
        _normalized(
            key=f"{event_id}:{_state(action)}",
            external_id=event_id,
            fingerprint=event.get("groupID")
            or event.get("issue_id")
            or event.get("fingerprint")
            or event_id,
            state=action,
            severity=event.get("level") or labels.get("level"),
            summary=event.get("title")
            or event.get("message")
            or event.get("culprit")
            or "Sentry event",
            description=event.get("message") or event.get("culprit"),
            service=project_name,
            resource=event.get("culprit") or labels.get("server_name"),
            environment=event.get("environment") or labels.get("environment"),
            occurred_at=event.get("dateCreated")
            or event.get("datetime")
            or event.get("timestamp"),
            labels=labels,
            annotations={"web_url": str(event.get("web_url") or "")},
        )
    ]


def _zabbix(payload: dict[str, Any]) -> list[dict[str, Any]]:
    event_id = (
        payload.get("event_id")
        or payload.get("eventid")
        or payload.get("EVENT.ID")
        or payload.get("trigger_id")
    )
    if not event_id:
        raise MonitoringPayloadError("Zabbix payload has no event_id")
    status = payload.get("status") or payload.get("event_status") or payload.get("value")
    labels = {
        **_tags(payload.get("tags")),
        "trigger_id": str(payload.get("trigger_id") or ""),
    }
    return [
        _normalized(
            key=f"{event_id}:{_state(status)}",
            external_id=event_id,
            fingerprint=payload.get("trigger_id") or event_id,
            state=status,
            severity=payload.get("severity") or payload.get("priority"),
            summary=payload.get("name")
            or payload.get("subject")
            or payload.get("trigger_name")
            or f"Zabbix event {event_id}",
            description=payload.get("message") or payload.get("description"),
            service=payload.get("service") or payload.get("host_group"),
            resource=payload.get("host") or payload.get("hostname"),
            environment=payload.get("environment"),
            occurred_at=payload.get("occurred_at")
            or payload.get("clock")
            or payload.get("event_time"),
            labels=labels,
            annotations={"url": str(payload.get("url") or "")},
        )
    ]


def _generic(payload: Any) -> list[dict[str, Any]]:
    raw_events: list[Any]
    if isinstance(payload, list):
        raw_events = payload
    elif isinstance(payload, dict) and isinstance(payload.get("events"), list):
        raw_events = payload["events"]
    else:
        raw_events = [payload]
    if not raw_events or len(raw_events) > 500:
        raise MonitoringPayloadError("Generic payload must contain 1 to 500 events")
    result: list[dict[str, Any]] = []
    for raw in raw_events:
        if not isinstance(raw, dict):
            raise MonitoringPayloadError("Generic event must be an object")
        key = raw.get("idempotency_key") or raw.get("event_id") or raw.get("id")
        if not key:
            key = hashlib.sha256(
                json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
        result.append(
            _normalized(
                key=key,
                external_id=raw.get("external_id") or raw.get("event_id") or raw.get("id") or key,
                fingerprint=raw.get("fingerprint") or raw.get("dedup_key") or key,
                state=raw.get("state") or raw.get("status"),
                severity=raw.get("severity") or raw.get("level"),
                summary=raw.get("summary") or raw.get("title") or raw.get("message"),
                description=raw.get("description") or raw.get("message"),
                service=raw.get("service") or raw.get("component"),
                resource=raw.get("resource") or raw.get("host") or raw.get("instance"),
                environment=raw.get("environment") or raw.get("env"),
                occurred_at=raw.get("occurred_at") or raw.get("timestamp"),
                labels=raw.get("labels") or raw.get("tags"),
                annotations=raw.get("annotations"),
            )
        )
    return result


def normalize_monitoring_payload(
    provider_type: str,
    payload: Any,
) -> list[dict[str, Any]]:
    normalized_provider = provider_type.upper()
    if normalized_provider in {"ALERTMANAGER", "PROMETHEUS"}:
        if not isinstance(payload, dict):
            raise MonitoringPayloadError("Alertmanager payload must be an object")
        return _alertmanager(payload)
    if normalized_provider == "GRAFANA":
        if not isinstance(payload, dict):
            raise MonitoringPayloadError("Grafana payload must be an object")
        return _grafana(payload)
    if normalized_provider == "SENTRY":
        if not isinstance(payload, dict):
            raise MonitoringPayloadError("Sentry payload must be an object")
        return _sentry(payload)
    if normalized_provider == "ZABBIX":
        if not isinstance(payload, dict):
            raise MonitoringPayloadError("Zabbix payload must be an object")
        return _zabbix(payload)
    return _generic(payload)


def _mark_failed(
    db: Session,
    receipt_id: str,
    error: Exception,
    *,
    permanent: bool,
) -> MonitoringWebhookReceipt:
    db.rollback()
    receipt = db.get(MonitoringWebhookReceipt, receipt_id)
    if receipt is None:
        raise RuntimeError("Monitoring receipt disappeared")
    source = db.get(EventSource, receipt.source_id)
    now = utcnow()
    receipt.last_error = f"{error.__class__.__name__}: {error}"[:2_000]
    receipt.updated_at = now
    if permanent:
        receipt.status = "DEAD_LETTER"
        receipt.processed_at = now
        if source:
            source.dead_letter_count += 1
    elif receipt.attempts < receipt.max_attempts:
        receipt.status = "RETRY"
        receipt.next_attempt_at = now + timedelta(
            seconds=min(30 * (2 ** max(receipt.attempts - 1, 0)), 3_600)
        )
    else:
        receipt.status = "DEAD_LETTER"
        receipt.processed_at = now
        if source:
            source.dead_letter_count += 1
    if source:
        source.failure_count += 1
        source.last_failure_at = now
        source.last_error = receipt.last_error
        source.updated_at = now
    db.commit()
    return receipt


def process_monitoring_receipt(
    db: Session,
    receipt: MonitoringWebhookReceipt,
    *,
    settings: Settings | None = None,
) -> MonitoringWebhookReceipt:
    runtime = settings or get_settings()
    receipt_id = receipt.id
    source = db.get(EventSource, receipt.source_id)
    if source is None or not source.is_enabled:
        return _mark_failed(
            db,
            receipt_id,
            RuntimeError("Monitoring source is disabled or unavailable"),
            permanent=False,
        )
    receipt.status = "PROCESSING"
    receipt.attempts += 1
    receipt.processing_started_at = utcnow()
    receipt.updated_at = utcnow()
    db.commit()
    try:
        receipt = db.get(MonitoringWebhookReceipt, receipt_id)
        if receipt is None:
            raise RuntimeError("Monitoring receipt disappeared")
        decoded = decrypt_credential(
            receipt.payload_encrypted,
            purpose=f"monitoring-receipt:{receipt.id}",
            tenant_id=receipt.tenant_id,
            settings=runtime,
        )
        payload = json.loads(decoded)
        events = normalize_monitoring_payload(receipt.provider_type, payload)
        duplicate_count = 0
        incident_count = 0
        for event in events:
            result = ingest_normalized_event(db, source, event)
            duplicate_count += int(bool(result.get("duplicate")))
            incident_count += int(result.get("disposition") == "INCIDENT_CREATED")
        receipt = db.get(MonitoringWebhookReceipt, receipt_id)
        source = db.get(EventSource, source.id)
        if receipt is None or source is None:
            raise RuntimeError("Monitoring processing state disappeared")
        now = utcnow()
        receipt.status = "PROCESSED"
        receipt.normalized_event_count = len(events)
        receipt.duplicate_event_count = duplicate_count
        receipt.incident_count = incident_count
        receipt.last_error = None
        receipt.processed_at = now
        receipt.updated_at = now
        source.success_count += 1
        source.last_success_at = now
        source.last_error = None
        source.updated_at = now
        db.commit()
        return receipt
    except MonitoringPayloadError as exc:
        return _mark_failed(db, receipt_id, exc, permanent=True)
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        return _mark_failed(db, receipt_id, exc, permanent=True)
    except Exception as exc:
        return _mark_failed(db, receipt_id, exc, permanent=False)


def run_monitoring_receipt_cycle(
    db: Session,
    *,
    settings: Settings | None = None,
) -> dict[str, int]:
    runtime = settings or get_settings()
    retention_cutoff = utcnow() - timedelta(
        days=runtime.monitoring_receipt_retention_days
    )
    purged = int(
        db.execute(
            delete(MonitoringWebhookReceipt).where(
                MonitoringWebhookReceipt.status.in_(
                    ["PROCESSED", "DUPLICATE", "REJECTED"]
                ),
                MonitoringWebhookReceipt.received_at < retention_cutoff,
            )
        ).rowcount
        or 0
    )
    rows = list(
        db.scalars(
            select(MonitoringWebhookReceipt)
            .where(
                MonitoringWebhookReceipt.status.in_(["RECEIVED", "RETRY"]),
                MonitoringWebhookReceipt.next_attempt_at <= utcnow(),
            )
            .order_by(MonitoringWebhookReceipt.next_attempt_at.asc())
            .limit(runtime.monitoring_worker_batch_size)
            .with_for_update(skip_locked=True)
        ).all()
    )
    processed = 0
    retried = 0
    failed = 0
    for row in rows:
        result = process_monitoring_receipt(db, row, settings=runtime)
        if result.status == "PROCESSED":
            processed += 1
        elif result.status == "RETRY":
            retried += 1
        else:
            failed += 1
    return {
        "received": len(rows),
        "processed": processed,
        "retried": retried,
        "failed": failed,
        "purged": purged,
    }
