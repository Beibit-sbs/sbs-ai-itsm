from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
import hashlib
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.event_operations import (
    EventCorrelationGroup,
    EventCorrelationPolicy,
    EventGroupActivity,
    EventSource,
    EventSuppressionRule,
    MonitoringWebhookReceipt,
    NormalizedEvent,
)
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.user import User
from app.services.audit import log_audit
from app.services.event_operations import (
    acknowledge_group,
    authenticate_source,
    evaluate_escalations,
    ingest_normalized_event,
    issue_source_token,
    now_utc,
    source_token_hash,
    validate_group_by,
    validate_matchers,
)
from app.services.rbac import is_saas_root, require_permissions
from app.services.monitoring_connectors import (
    MonitoringAuthenticationError,
    MonitoringPayloadError,
    MonitoringRateLimitError,
    configure_hmac_secret,
    enqueue_monitoring_receipt,
    issue_hmac_secret,
    validate_ip_cidrs,
    verify_monitoring_request,
)


router = APIRouter(prefix="/event-operations")


class MatcherInput(BaseModel):
    field: str = Field(min_length=1, max_length=160)
    operator: Literal["EQUALS", "NOT_EQUALS", "CONTAINS", "PREFIX", "EXISTS"]
    value: str = Field(default="", max_length=500)


class SourceCreate(BaseModel):
    tenant_id: str | None = None
    code: str = Field(
        min_length=2,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    name: str = Field(min_length=2, max_length=200)
    source_type: Literal[
        "ALERTMANAGER",
        "PROMETHEUS",
        "ZABBIX",
        "SENTRY",
        "GRAFANA",
        "GENERIC",
    ]
    auth_mode: Literal["BEARER", "HMAC_SHA256"] = "BEARER"
    replay_window_seconds: int = Field(default=300, ge=30, le=3_600)
    rate_limit_per_minute: int = Field(default=120, ge=1, le=100_000)
    max_payload_bytes: int = Field(
        default=1_048_576,
        ge=1_024,
        le=2_097_152,
    )
    allowed_ip_cidrs: list[str] = Field(default_factory=list, max_length=100)
    signing_secret: str | None = Field(
        default=None,
        min_length=32,
        max_length=4_000,
    )

    @field_validator("allowed_ip_cidrs")
    @classmethod
    def validate_allowed_ip_cidrs(cls, values: list[str]) -> list[str]:
        return validate_ip_cidrs(values)


class SourceUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    is_enabled: bool | None = None
    replay_window_seconds: int | None = Field(default=None, ge=30, le=3_600)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100_000)
    max_payload_bytes: int | None = Field(
        default=None,
        ge=1_024,
        le=2_097_152,
    )
    allowed_ip_cidrs: list[str] | None = Field(default=None, max_length=100)

    @field_validator("allowed_ip_cidrs")
    @classmethod
    def validate_allowed_ip_cidrs(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return validate_ip_cidrs(values)


class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class HmacSecretRotation(VersionRequest):
    reason: str = Field(min_length=3, max_length=2_000)
    signing_secret: str | None = Field(
        default=None,
        min_length=32,
        max_length=4_000,
    )


class ReceiptReprocessRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2_000)


class PolicyCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)
    is_active: bool = True
    priority_order: int = Field(default=100, ge=1, le=10_000)
    matchers: list[MatcherInput] = Field(default_factory=list, max_length=20)
    group_by: list[str] = Field(
        default_factory=lambda: ["fingerprint"],
        max_length=12,
    )
    correlation_window_minutes: int = Field(default=60, ge=1, le=10_080)
    min_occurrences: int = Field(default=1, ge=1, le=1_000)
    incident_mode: Literal[
        "CREATE_UPDATE",
        "CORRELATE_ONLY",
        "IGNORE",
    ] = "CREATE_UPDATE"
    fixed_priority: Literal[
        "CRITICAL",
        "HIGH",
        "MEDIUM",
        "LOW",
        "P1",
        "P2",
        "P3",
        "P4",
    ] | None = None
    category: str = Field(
        default="Infrastructure",
        min_length=2,
        max_length=120,
    )
    title_template: str = Field(
        default="Monitoring: {summary}",
        min_length=3,
        max_length=255,
    )
    resolution_action: Literal["NONE", "RESOLVE", "CLOSE"] = "RESOLVE"
    primary_user_id: str | None = None
    fallback_user_id: str | None = None
    acknowledge_within_minutes: int = Field(default=15, ge=1, le=1_440)
    escalate_after_minutes: int = Field(default=15, ge=1, le=1_440)


class PolicyUpdate(PolicyCreate):
    tenant_id: str | None = None
    expected_version: int = Field(ge=1)


class SuppressionCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=3, max_length=5_000)
    matchers: list[MatcherInput] = Field(default_factory=list, max_length=20)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True


class SuppressionUpdate(SuppressionCreate):
    tenant_id: str | None = None
    expected_version: int = Field(ge=1)


class NormalizedEventInput(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    external_id: str = Field(min_length=1, max_length=255)
    fingerprint: str = Field(min_length=1, max_length=255)
    state: Literal["FIRING", "RESOLVED"]
    severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    summary: str = Field(min_length=3, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    service: str | None = Field(default=None, max_length=200)
    resource: str | None = Field(default=None, max_length=255)
    environment: str | None = Field(default=None, max_length=80)
    occurred_at: datetime
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class AlertmanagerEventInput(BaseModel):
    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str = Field(default="", max_length=2_000)
    fingerprint: str = Field(min_length=1, max_length=255)


class AlertmanagerWebhookInput(BaseModel):
    status: Literal["firing", "resolved"]
    receiver: str = Field(default="", max_length=200)
    alerts: list[AlertmanagerEventInput] = Field(min_length=1, max_length=500)


class AcknowledgeRequest(BaseModel):
    expected_version: int = Field(ge=1)
    note: str = Field(min_length=3, max_length=5_000)


def _tenant_id(
    db: Session,
    current_user: AuthUserResponse,
    requested: str | None = None,
    *,
    required_for_root: bool = False,
) -> str | None:
    if is_saas_root(current_user):
        if required_for_root and not requested:
            raise HTTPException(status_code=422, detail="tenant_id is required")
        if requested and db.get(Tenant, requested) is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return requested
    if requested and requested != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not current_user.tenant_id:
        raise HTTPException(status_code=422, detail="Tenant context is required")
    return current_user.tenant_id


def _actor(db: Session, current_user: AuthUserResponse) -> User:
    actor = db.get(User, current_user.id)
    if actor is None:
        raise HTTPException(status_code=403, detail="User account not found")
    return actor


def _user(db: Session, user_id: str | None, tenant_id: str) -> User | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or user.tenant_id != tenant_id or not user.is_active:
        raise HTTPException(status_code=422, detail="Responder is unavailable")
    return user


def _assert_version(current: int, expected: int, entity: str) -> None:
    if current != expected:
        raise HTTPException(
            status_code=409,
            detail=f"{entity} version conflict; current version is {current}",
        )


def _audit(
    db: Session,
    request: Request,
    current_user: AuthUserResponse,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    tenant_id: str,
    metadata: dict[str, Any],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user=db.get(User, current_user.id),
        actor_email=current_user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _source_response(item: EventSource) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "code": item.code,
        "name": item.name,
        "source_type": item.source_type,
        "auth_mode": item.auth_mode,
        "token_hint": item.token_hint,
        "hmac_secret_hint": item.hmac_secret_hint,
        "hmac_configured": bool(item.hmac_secret_encrypted),
        "replay_window_seconds": item.replay_window_seconds,
        "rate_limit_per_minute": item.rate_limit_per_minute,
        "max_payload_bytes": item.max_payload_bytes,
        "allowed_ip_cidrs": list(item.allowed_ip_cidrs_json or []),
        "is_enabled": item.is_enabled,
        "total_events": item.total_events,
        "duplicate_events": item.duplicate_events,
        "suppressed_events": item.suppressed_events,
        "last_event_at": item.last_event_at,
        "last_error": item.last_error,
        "last_success_at": item.last_success_at,
        "last_failure_at": item.last_failure_at,
        "success_count": item.success_count,
        "failure_count": item.failure_count,
        "dead_letter_count": item.dead_letter_count,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _policy_response(db: Session, item: EventCorrelationPolicy) -> dict[str, Any]:
    primary = db.get(User, item.primary_user_id) if item.primary_user_id else None
    fallback = db.get(User, item.fallback_user_id) if item.fallback_user_id else None
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "name": item.name,
        "description": item.description,
        "is_active": item.is_active,
        "priority_order": item.priority_order,
        "matchers": item.matchers_json,
        "group_by": item.group_by_json,
        "correlation_window_minutes": item.correlation_window_minutes,
        "min_occurrences": item.min_occurrences,
        "incident_mode": item.incident_mode,
        "fixed_priority": item.fixed_priority,
        "category": item.category,
        "title_template": item.title_template,
        "resolution_action": item.resolution_action,
        "primary_user_id": item.primary_user_id,
        "primary_user_name": primary.full_name if primary else None,
        "fallback_user_id": item.fallback_user_id,
        "fallback_user_name": fallback.full_name if fallback else None,
        "acknowledge_within_minutes": item.acknowledge_within_minutes,
        "escalate_after_minutes": item.escalate_after_minutes,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _suppression_response(item: EventSuppressionRule) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "name": item.name,
        "reason": item.reason,
        "matchers": item.matchers_json,
        "starts_at": item.starts_at,
        "ends_at": item.ends_at,
        "is_active": item.is_active,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _event_response(db: Session, item: NormalizedEvent) -> dict[str, Any]:
    source = db.get(EventSource, item.source_id)
    ticket = db.get(Ticket, item.ticket_id) if item.ticket_id else None
    return {
        "id": item.id,
        "source_id": item.source_id,
        "source_name": source.name if source else None,
        "external_id": item.external_id,
        "fingerprint": item.fingerprint,
        "state": item.state,
        "severity": item.severity,
        "summary": item.summary,
        "description": item.description,
        "service": item.service,
        "resource": item.resource,
        "environment": item.environment,
        "labels": item.labels_json,
        "annotations": item.annotations_json,
        "raw_payload_hash": item.raw_payload_hash,
        "occurred_at": item.occurred_at,
        "received_at": item.received_at,
        "disposition": item.disposition,
        "suppression_rule_id": item.suppression_rule_id,
        "correlation_policy_id": item.correlation_policy_id,
        "correlation_group_id": item.correlation_group_id,
        "ticket_id": item.ticket_id,
        "ticket_number": ticket.ticket_number if ticket else None,
    }


def _group_response(
    db: Session,
    item: EventCorrelationGroup,
    *,
    details: bool = False,
) -> dict[str, Any]:
    policy = db.get(EventCorrelationPolicy, item.policy_id)
    ticket = db.get(Ticket, item.ticket_id) if item.ticket_id else None
    assigned = db.get(User, item.assigned_user_id) if item.assigned_user_id else None
    acknowledged = (
        db.get(User, item.acknowledged_by_id)
        if item.acknowledged_by_id
        else None
    )
    response: dict[str, Any] = {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "policy_id": item.policy_id,
        "policy_name": policy.name if policy else None,
        "correlation_key": item.correlation_key,
        "title": item.title,
        "status": item.status,
        "severity": item.severity,
        "first_event_at": item.first_event_at,
        "last_event_at": item.last_event_at,
        "occurrence_count": item.occurrence_count,
        "ticket_id": item.ticket_id,
        "ticket_number": ticket.ticket_number if ticket else None,
        "ticket_status": ticket.status if ticket else None,
        "assigned_user_id": item.assigned_user_id,
        "assigned_user_name": assigned.full_name if assigned else None,
        "acknowledged_by_id": item.acknowledged_by_id,
        "acknowledged_by_name": acknowledged.full_name if acknowledged else None,
        "acknowledged_at": item.acknowledged_at,
        "next_escalation_at": item.next_escalation_at,
        "escalation_level": item.escalation_level,
        "escalated_at": item.escalated_at,
        "resolved_at": item.resolved_at,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    if details:
        events = db.scalars(
            select(NormalizedEvent)
            .where(NormalizedEvent.correlation_group_id == item.id)
            .order_by(NormalizedEvent.occurred_at.desc())
            .limit(500)
        ).all()
        activities = db.scalars(
            select(EventGroupActivity)
            .where(EventGroupActivity.correlation_group_id == item.id)
            .order_by(EventGroupActivity.created_at)
        ).all()
        response["events"] = [_event_response(db, event) for event in events]
        response["activities"] = [
            {
                "id": activity.id,
                "event_id": activity.event_id,
                "activity_type": activity.activity_type,
                "actor_name": activity.actor_name,
                "message": activity.message,
                "metadata": activity.metadata_json,
                "created_at": activity.created_at,
            }
            for activity in activities
        ]
    return response


def _validate_windows(
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> None:
    if starts_at and ends_at and ends_at <= starts_at:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")


def _policy_values(
    db: Session,
    tenant_id: str,
    payload: PolicyCreate,
) -> dict[str, Any]:
    try:
        matchers = validate_matchers(
            [item.model_dump() for item in payload.matchers]
        )
        group_by = validate_group_by(payload.group_by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _user(db, payload.primary_user_id, tenant_id)
    _user(db, payload.fallback_user_id, tenant_id)
    if (
        payload.primary_user_id
        and payload.primary_user_id == payload.fallback_user_id
    ):
        raise HTTPException(
            status_code=422,
            detail="Fallback responder must differ from primary responder",
        )
    return {
        "name": payload.name.strip(),
        "description": payload.description.strip() if payload.description else None,
        "is_active": payload.is_active,
        "priority_order": payload.priority_order,
        "matchers_json": matchers,
        "group_by_json": group_by,
        "correlation_window_minutes": payload.correlation_window_minutes,
        "min_occurrences": payload.min_occurrences,
        "incident_mode": payload.incident_mode,
        "fixed_priority": payload.fixed_priority,
        "category": payload.category.strip(),
        "title_template": payload.title_template.strip(),
        "resolution_action": payload.resolution_action,
        "primary_user_id": payload.primary_user_id,
        "fallback_user_id": payload.fallback_user_id,
        "acknowledge_within_minutes": payload.acknowledge_within_minutes,
        "escalate_after_minutes": payload.escalate_after_minutes,
    }


@router.post("/ingest", include_in_schema=False)
def ingest_event(
    payload: NormalizedEventInput,
    authorization: str | None = Header(default=None),
    source_identifier: str | None = Header(default=None, alias="X-Event-Source"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source = _event_source_credentials(db, source_identifier, authorization)
    return ingest_normalized_event(db, source, payload.model_dump())


def _event_source_credentials(
    db: Session,
    source_identifier: str | None,
    authorization: str | None,
) -> EventSource:
    if not source_identifier:
        raise HTTPException(status_code=401, detail="X-Event-Source is required")
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    return authenticate_source(db, source_identifier, token)


def _receipt_response(item: MonitoringWebhookReceipt) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "source_id": item.source_id,
        "provider_type": item.provider_type,
        "body_hash": item.body_hash,
        "payload_size": item.payload_size,
        "content_type": item.content_type,
        "source_ip": item.source_ip,
        "signature_verified": item.signature_verified,
        "request_timestamp": item.request_timestamp,
        "status": item.status,
        "attempts": item.attempts,
        "max_attempts": item.max_attempts,
        "next_attempt_at": item.next_attempt_at,
        "normalized_event_count": item.normalized_event_count,
        "duplicate_event_count": item.duplicate_event_count,
        "incident_count": item.incident_count,
        "last_error": item.last_error,
        "received_at": item.received_at,
        "processing_started_at": item.processing_started_at,
        "processed_at": item.processed_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _alertmanager_severity(labels: dict[str, str]) -> str:
    value = (
        labels.get("severity")
        or labels.get("priority")
        or labels.get("level")
        or ""
    ).casefold()
    if value in {"critical", "fatal", "sev1", "p1"}:
        return "CRITICAL"
    if value in {"high", "error", "warning", "warn", "sev2", "p2"}:
        return "HIGH"
    if value in {"info", "informational"}:
        return "INFO"
    if value in {"low", "notice"}:
        return "LOW"
    return "MEDIUM"


@router.post("/ingest/alertmanager", include_in_schema=False)
def ingest_alertmanager_events(
    payload: AlertmanagerWebhookInput,
    authorization: str | None = Header(default=None),
    source_identifier: str | None = Header(default=None, alias="X-Event-Source"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source = _event_source_credentials(db, source_identifier, authorization)
    if source.source_type not in {"ALERTMANAGER", "PROMETHEUS", "GENERIC"}:
        raise HTTPException(
            status_code=422,
            detail="Event source is not configured for Alertmanager payloads",
        )
    results: list[dict[str, Any]] = []
    for alert in payload.alerts:
        labels = alert.labels
        annotations = {
            **alert.annotations,
            "generator_url": alert.generatorURL,
            "receiver": payload.receiver,
        }
        occurred_at = (
            alert.endsAt
            if alert.status == "resolved" and alert.endsAt
            else alert.startsAt
        )
        results.append(
            ingest_normalized_event(
                db,
                source,
                {
                    "idempotency_key": (
                        f"{alert.fingerprint}:{alert.status}:"
                        f"{alert.startsAt.isoformat()}"
                    ),
                    "external_id": alert.fingerprint,
                    "fingerprint": alert.fingerprint,
                    "state": (
                        "FIRING" if alert.status == "firing" else "RESOLVED"
                    ),
                    "severity": _alertmanager_severity(labels),
                    "summary": (
                        alert.annotations.get("summary")
                        or alert.annotations.get("message")
                        or labels.get("alertname")
                        or f"Alert {alert.fingerprint}"
                    ),
                    "description": (
                        alert.annotations.get("description")
                        or alert.annotations.get("message")
                    ),
                    "service": (
                        labels.get("service")
                        or labels.get("job")
                        or labels.get("namespace")
                    ),
                    "resource": (
                        labels.get("instance")
                        or labels.get("pod")
                        or labels.get("device")
                    ),
                    "environment": (
                        labels.get("environment")
                        or labels.get("env")
                    ),
                    "occurred_at": occurred_at,
                    "labels": labels,
                    "annotations": annotations,
                },
            )
        )
    return {
        "accepted": len(results),
        "duplicates": sum(bool(item["duplicate"]) for item in results),
        "suppressed": sum(
            item["disposition"] == "SUPPRESSED" for item in results
        ),
        "incidents": sum(
            item["disposition"] == "INCIDENT_CREATED" for item in results
        ),
        "results": results,
    }


@router.post("/webhooks/{source_id}", include_in_schema=False, status_code=202)
async def receive_monitoring_webhook(
    source_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    signature: str | None = Header(default=None, alias="X-SBS-Signature"),
    timestamp: str | None = Header(default=None, alias="X-SBS-Timestamp"),
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
    ),
    event_id: str | None = Header(default=None, alias="X-Event-ID"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source = db.scalar(
        select(EventSource)
        .where(EventSource.id == source_id)
        .with_for_update()
    )
    if source is None:
        raise HTTPException(status_code=401, detail="Invalid monitoring credentials")
    maximum_size = min(
        source.max_payload_bytes,
        get_settings().monitoring_global_max_payload_bytes,
    )
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        if declared_size > maximum_size:
            raise HTTPException(status_code=413, detail="Monitoring payload is too large")
    buffered = bytearray()
    async for chunk in request.stream():
        if len(buffered) + len(chunk) > maximum_size:
            raise HTTPException(status_code=413, detail="Monitoring payload is too large")
        buffered.extend(chunk)
    raw_body = bytes(buffered)
    source_ip = request.client.host if request.client else None
    effective_signature = (
        signature
        or request.headers.get("x-grafana-alerting-signature")
        or request.headers.get("sentry-hook-signature")
    )
    effective_timestamp = (
        timestamp
        or request.headers.get("x-grafana-alerting-timestamp")
    )
    try:
        request_time = verify_monitoring_request(
            source,
            raw_body=raw_body,
            authorization=authorization,
            signature=effective_signature,
            timestamp=effective_timestamp,
            source_ip=source_ip,
        )
        receipt, duplicate = enqueue_monitoring_receipt(
            db,
            source,
            raw_body=raw_body,
            content_type=request.headers.get("content-type"),
            source_ip=source_ip,
            headers=dict(request.headers),
            idempotency_key=idempotency_key or event_id,
            request_timestamp=request_time,
            signature_verified=source.auth_mode == "HMAC_SHA256",
        )
        db.commit()
    except MonitoringAuthenticationError as exc:
        db.rollback()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except MonitoringRateLimitError as exc:
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": "60"},
        ) from exc
    except MonitoringPayloadError as exc:
        db.rollback()
        status_code = 413 if "exceeds" in str(exc) else 415 if "application/json" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except IntegrityError:
        db.rollback()
        body_hash = hashlib.sha256(raw_body).hexdigest()
        existing = db.scalar(
            select(MonitoringWebhookReceipt).where(
                MonitoringWebhookReceipt.source_id == source_id,
                MonitoringWebhookReceipt.body_hash == body_hash,
            )
        )
        if existing is None:
            raise HTTPException(status_code=409, detail="Monitoring request conflict")
        receipt = existing
        duplicate = True
    return {
        "accepted": True,
        "duplicate": duplicate,
        "receipt_id": receipt.id,
        "status": receipt.status,
    }


@router.get("/summary")
def event_operations_summary(
    tenant_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "monitoring.events.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    since = datetime.now(UTC) - timedelta(hours=24)
    event_conditions = [NormalizedEvent.received_at >= since]
    group_conditions: list[Any] = []
    source_conditions: list[Any] = []
    if scoped_tenant:
        event_conditions.append(NormalizedEvent.tenant_id == scoped_tenant)
        group_conditions.append(EventCorrelationGroup.tenant_id == scoped_tenant)
        source_conditions.append(EventSource.tenant_id == scoped_tenant)
    total = int(
        db.scalar(
            select(func.count(NormalizedEvent.id)).where(*event_conditions)
        )
        or 0
    )
    firing = int(
        db.scalar(
            select(func.count(NormalizedEvent.id)).where(
                *event_conditions,
                NormalizedEvent.state == "FIRING",
            )
        )
        or 0
    )
    suppressed = int(
        db.scalar(
            select(func.count(NormalizedEvent.id)).where(
                *event_conditions,
                NormalizedEvent.disposition == "SUPPRESSED",
            )
        )
        or 0
    )
    incidents = int(
        db.scalar(
            select(func.count(func.distinct(NormalizedEvent.ticket_id))).where(
                *event_conditions,
                NormalizedEvent.ticket_id.is_not(None),
            )
        )
        or 0
    )
    open_groups = int(
        db.scalar(
            select(func.count(EventCorrelationGroup.id)).where(
                *group_conditions,
                EventCorrelationGroup.status == "OPEN",
            )
        )
        or 0
    )
    overdue = int(
        db.scalar(
            select(func.count(EventCorrelationGroup.id)).where(
                *group_conditions,
                EventCorrelationGroup.status == "OPEN",
                EventCorrelationGroup.acknowledged_at.is_(None),
                EventCorrelationGroup.next_escalation_at.is_not(None),
                EventCorrelationGroup.next_escalation_at <= datetime.now(UTC),
            )
        )
        or 0
    )
    duplicates = int(
        db.scalar(
            select(func.coalesce(func.sum(EventSource.duplicate_events), 0)).where(
                *source_conditions
            )
        )
        or 0
    )
    groups = db.scalars(
        select(EventCorrelationGroup).where(
            *group_conditions,
            EventCorrelationGroup.acknowledged_at.is_not(None),
            EventCorrelationGroup.created_at >= since,
        )
    ).all()
    mtta_minutes = (
        round(
            sum(
                (item.acknowledged_at - item.created_at).total_seconds()
                for item in groups
                if item.acknowledged_at
            )
            / len(groups)
            / 60,
            1,
        )
        if groups
        else None
    )
    return {
        "events_24h": total,
        "firing_24h": firing,
        "suppressed_24h": suppressed,
        "duplicates_lifetime": duplicates,
        "open_groups": open_groups,
        "ack_overdue": overdue,
        "incidents_24h": incidents,
        "noise_reduction_percent": (
            round(max(0, firing - incidents) / firing * 100, 1) if firing else 0
        ),
        "mtta_minutes_24h": mtta_minutes,
    }


@router.get("/responders")
def list_event_responders(
    tenant_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "monitoring.events.read")
    scoped_tenant = _tenant_id(
        db,
        current_user,
        tenant_id,
        required_for_root=is_saas_root(current_user),
    )
    users = db.scalars(
        select(User)
        .where(User.tenant_id == scoped_tenant, User.is_active.is_(True))
        .order_by(User.full_name)
    ).all()
    return [
        {
            "id": item.id,
            "full_name": item.full_name,
            "position": item.position,
            "department": item.department,
        }
        for item in users
    ]


@router.get("/sources")
def list_event_sources(
    tenant_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "monitoring.connectors.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(EventSource)
    if scoped_tenant:
        statement = statement.where(EventSource.tenant_id == scoped_tenant)
    return [
        _source_response(item)
        for item in db.scalars(statement.order_by(EventSource.name)).all()
    ]


@router.post("/sources", status_code=status.HTTP_201_CREATED)
def create_event_source(
    payload: SourceCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "monitoring.connectors.manage")
    tenant_id = _tenant_id(
        db,
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    if db.scalar(
        select(EventSource.id).where(
            EventSource.tenant_id == tenant_id,
            EventSource.code == payload.code,
        )
    ):
        raise HTTPException(status_code=409, detail="Source code already exists")
    token = issue_source_token()
    hmac_secret = (
        payload.signing_secret or issue_hmac_secret()
        if payload.auth_mode == "HMAC_SHA256"
        else None
    )
    now = now_utc()
    item = EventSource(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=payload.code,
        name=payload.name.strip(),
        source_type=payload.source_type,
        token_hash=source_token_hash(token),
        token_hint=token[-8:],
        auth_mode=payload.auth_mode,
        replay_window_seconds=payload.replay_window_seconds,
        rate_limit_per_minute=payload.rate_limit_per_minute,
        max_payload_bytes=payload.max_payload_bytes,
        allowed_ip_cidrs_json=payload.allowed_ip_cidrs,
        is_enabled=True,
        total_events=0,
        duplicate_events=0,
        suppressed_events=0,
        success_count=0,
        failure_count=0,
        dead_letter_count=0,
        version=1,
        created_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    if hmac_secret:
        configure_hmac_secret(item, hmac_secret)
    db.add(item)
    _audit(
        db,
        request,
        current_user,
        action="event_source.created",
        entity_type="event_source",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"code": item.code, "source_type": item.source_type},
    )
    db.commit()
    db.refresh(item)
    credentials: dict[str, str] = (
        {"signing_secret": hmac_secret}
        if hmac_secret and payload.signing_secret is None
        else {"ingest_token": token}
        if payload.auth_mode == "BEARER"
        else {}
    )
    return {**_source_response(item), **credentials}


@router.patch("/sources/{source_id}")
def update_event_source(
    source_id: str,
    payload: SourceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "monitoring.connectors.manage")
    item = db.get(EventSource, source_id)
    if item is None or (
        not is_saas_root(current_user)
        and item.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Event source not found")
    _assert_version(item.version, payload.expected_version, "Event source")
    if payload.name is not None:
        item.name = payload.name.strip()
    if payload.is_enabled is not None:
        item.is_enabled = payload.is_enabled
    if payload.replay_window_seconds is not None:
        item.replay_window_seconds = payload.replay_window_seconds
    if payload.rate_limit_per_minute is not None:
        item.rate_limit_per_minute = payload.rate_limit_per_minute
    if payload.max_payload_bytes is not None:
        item.max_payload_bytes = payload.max_payload_bytes
    if payload.allowed_ip_cidrs is not None:
        item.allowed_ip_cidrs_json = payload.allowed_ip_cidrs
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="event_source.updated",
        entity_type="event_source",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"enabled": item.is_enabled},
    )
    db.commit()
    db.refresh(item)
    return _source_response(item)


@router.post("/sources/{source_id}/rotate-token")
def rotate_event_source_token(
    source_id: str,
    payload: VersionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "monitoring.connectors.manage")
    item = db.get(EventSource, source_id)
    if item is None or (
        not is_saas_root(current_user)
        and item.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Event source not found")
    _assert_version(item.version, payload.expected_version, "Event source")
    if item.auth_mode != "BEARER":
        raise HTTPException(
            status_code=409,
            detail="Use rotate-hmac-secret for an HMAC monitoring source",
        )
    token = issue_source_token()
    item.token_hash = source_token_hash(token)
    item.token_hint = token[-8:]
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="event_source.token_rotated",
        entity_type="event_source",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={},
    )
    db.commit()
    db.refresh(item)
    return {**_source_response(item), "ingest_token": token}


@router.post("/sources/{source_id}/rotate-hmac-secret")
def rotate_event_source_hmac_secret(
    source_id: str,
    payload: HmacSecretRotation,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "monitoring.connectors.manage")
    item = db.get(EventSource, source_id)
    if item is None or (
        not is_saas_root(current_user)
        and item.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Event source not found")
    _assert_version(item.version, payload.expected_version, "Event source")
    if item.auth_mode != "HMAC_SHA256":
        raise HTTPException(
            status_code=409,
            detail="Source does not use HMAC authentication",
        )
    secret = payload.signing_secret or issue_hmac_secret()
    configure_hmac_secret(item, secret)
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="event_source.hmac_secret_rotated",
        entity_type="event_source",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason": payload.reason, "secret_value_logged": False},
    )
    db.commit()
    db.refresh(item)
    return {
        **_source_response(item),
        **(
            {"signing_secret": secret}
            if payload.signing_secret is None
            else {}
        ),
    }


@router.get("/webhook-receipts")
def list_monitoring_webhook_receipts(
    tenant_id: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    receipt_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "monitoring.receipts.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(MonitoringWebhookReceipt)
    if scoped_tenant:
        statement = statement.where(
            MonitoringWebhookReceipt.tenant_id == scoped_tenant
        )
    if source_id:
        source = db.get(EventSource, source_id)
        if source is None or (
            not is_saas_root(current_user)
            and source.tenant_id != current_user.tenant_id
        ):
            raise HTTPException(status_code=404, detail="Event source not found")
        statement = statement.where(
            MonitoringWebhookReceipt.source_id == source.id
        )
    if receipt_status and receipt_status.upper() != "ALL":
        statement = statement.where(
            MonitoringWebhookReceipt.status == receipt_status.upper()
        )
    rows = db.scalars(
        statement.order_by(
            MonitoringWebhookReceipt.received_at.desc()
        ).limit(limit)
    ).all()
    return [_receipt_response(item) for item in rows]


@router.post("/webhook-receipts/{receipt_id}/reprocess")
def reprocess_monitoring_webhook_receipt(
    receipt_id: str,
    payload: ReceiptReprocessRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "monitoring.receipts.manage")
    item = db.get(MonitoringWebhookReceipt, receipt_id)
    if item is None or (
        not is_saas_root(current_user)
        and item.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Monitoring receipt not found")
    if item.status not in {"FAILED", "DEAD_LETTER"}:
        raise HTTPException(
            status_code=409,
            detail="Only failed or dead-letter receipts can be reprocessed",
        )
    source = db.get(EventSource, item.source_id)
    if source is None or not source.is_enabled:
        raise HTTPException(
            status_code=409,
            detail="Monitoring source must be enabled before reprocessing",
        )
    item.status = "RECEIVED"
    item.attempts = 0
    item.next_attempt_at = now_utc()
    item.processing_started_at = None
    item.processed_at = None
    item.last_error = None
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="monitoring.receipt_reprocessed",
        entity_type="monitoring_webhook_receipt",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason": payload.reason, "source_id": item.source_id},
    )
    db.commit()
    db.refresh(item)
    return _receipt_response(item)


@router.get("/policies")
def list_event_policies(
    tenant_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "monitoring.events.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(EventCorrelationPolicy)
    if scoped_tenant:
        statement = statement.where(
            EventCorrelationPolicy.tenant_id == scoped_tenant
        )
    items = db.scalars(
        statement.order_by(
            EventCorrelationPolicy.priority_order,
            EventCorrelationPolicy.name,
        )
    ).all()
    return [_policy_response(db, item) for item in items]


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def create_event_policy(
    payload: PolicyCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.manage")
    tenant_id = _tenant_id(
        db,
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    if db.scalar(
        select(EventCorrelationPolicy.id).where(
            EventCorrelationPolicy.tenant_id == tenant_id,
            EventCorrelationPolicy.name == payload.name.strip(),
        )
    ):
        raise HTTPException(status_code=409, detail="Policy name already exists")
    now = now_utc()
    item = EventCorrelationPolicy(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        **_policy_values(db, tenant_id, payload),
        version=1,
        created_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    _audit(
        db,
        request,
        current_user,
        action="event_policy.created",
        entity_type="event_policy",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"name": item.name, "incident_mode": item.incident_mode},
    )
    db.commit()
    db.refresh(item)
    return _policy_response(db, item)


@router.put("/policies/{policy_id}")
def update_event_policy(
    policy_id: str,
    payload: PolicyUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.manage")
    item = db.get(EventCorrelationPolicy, policy_id)
    if item is None or (
        not is_saas_root(current_user)
        and item.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Event policy not found")
    _assert_version(item.version, payload.expected_version, "Event policy")
    duplicate = db.scalar(
        select(EventCorrelationPolicy.id).where(
            EventCorrelationPolicy.tenant_id == item.tenant_id,
            EventCorrelationPolicy.name == payload.name.strip(),
            EventCorrelationPolicy.id != item.id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Policy name already exists")
    for key, value in _policy_values(db, item.tenant_id, payload).items():
        setattr(item, key, value)
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="event_policy.updated",
        entity_type="event_policy",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"name": item.name, "incident_mode": item.incident_mode},
    )
    db.commit()
    db.refresh(item)
    return _policy_response(db, item)


@router.get("/suppressions")
def list_event_suppressions(
    tenant_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "monitoring.events.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(EventSuppressionRule)
    if scoped_tenant:
        statement = statement.where(EventSuppressionRule.tenant_id == scoped_tenant)
    return [
        _suppression_response(item)
        for item in db.scalars(
            statement.order_by(EventSuppressionRule.created_at.desc())
        ).all()
    ]


@router.post("/suppressions", status_code=status.HTTP_201_CREATED)
def create_event_suppression(
    payload: SuppressionCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.manage")
    tenant_id = _tenant_id(
        db,
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    _validate_windows(payload.starts_at, payload.ends_at)
    try:
        matchers = validate_matchers(
            [item.model_dump() for item in payload.matchers]
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if db.scalar(
        select(EventSuppressionRule.id).where(
            EventSuppressionRule.tenant_id == tenant_id,
            EventSuppressionRule.name == payload.name.strip(),
        )
    ):
        raise HTTPException(
            status_code=409,
            detail="Suppression name already exists",
        )
    now = now_utc()
    item = EventSuppressionRule(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=payload.name.strip(),
        reason=payload.reason.strip(),
        matchers_json=matchers,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        is_active=payload.is_active,
        version=1,
        created_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    _audit(
        db,
        request,
        current_user,
        action="event_suppression.created",
        entity_type="event_suppression",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"name": item.name, "reason": item.reason},
    )
    db.commit()
    db.refresh(item)
    return _suppression_response(item)


@router.put("/suppressions/{suppression_id}")
def update_event_suppression(
    suppression_id: str,
    payload: SuppressionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.manage")
    item = db.get(EventSuppressionRule, suppression_id)
    if item is None or (
        not is_saas_root(current_user)
        and item.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Suppression rule not found")
    _assert_version(item.version, payload.expected_version, "Suppression rule")
    _validate_windows(payload.starts_at, payload.ends_at)
    try:
        matchers = validate_matchers(
            [matcher.model_dump() for matcher in payload.matchers]
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    duplicate = db.scalar(
        select(EventSuppressionRule.id).where(
            EventSuppressionRule.tenant_id == item.tenant_id,
            EventSuppressionRule.name == payload.name.strip(),
            EventSuppressionRule.id != item.id,
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="Suppression name already exists",
        )
    item.name = payload.name.strip()
    item.reason = payload.reason.strip()
    item.matchers_json = matchers
    item.starts_at = payload.starts_at
    item.ends_at = payload.ends_at
    item.is_active = payload.is_active
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="event_suppression.updated",
        entity_type="event_suppression",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"name": item.name, "enabled": item.is_active},
    )
    db.commit()
    db.refresh(item)
    return _suppression_response(item)


@router.get("/events")
def list_normalized_events(
    tenant_id: str | None = None,
    disposition: str | None = None,
    severity: str | None = None,
    limit: int = Query(default=200, ge=1, le=1_000),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "monitoring.events.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(NormalizedEvent)
    if scoped_tenant:
        statement = statement.where(NormalizedEvent.tenant_id == scoped_tenant)
    if disposition and disposition != "ALL":
        statement = statement.where(NormalizedEvent.disposition == disposition)
    if severity and severity != "ALL":
        statement = statement.where(NormalizedEvent.severity == severity)
    items = db.scalars(
        statement.order_by(NormalizedEvent.received_at.desc()).limit(limit)
    ).all()
    return [_event_response(db, item) for item in items]


@router.get("/groups")
def list_event_groups(
    tenant_id: str | None = None,
    group_status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1_000),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "monitoring.events.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(EventCorrelationGroup)
    if scoped_tenant:
        statement = statement.where(
            EventCorrelationGroup.tenant_id == scoped_tenant
        )
    if group_status and group_status != "ALL":
        statement = statement.where(EventCorrelationGroup.status == group_status)
    items = db.scalars(
        statement.order_by(EventCorrelationGroup.last_event_at.desc()).limit(limit)
    ).all()
    return [_group_response(db, item) for item in items]


@router.get("/groups/{group_id}")
def get_event_group(
    group_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "monitoring.events.read")
    item = db.get(EventCorrelationGroup, group_id)
    if item is None or (
        not is_saas_root(current_user)
        and item.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Event group not found")
    return _group_response(db, item, details=True)


@router.post("/groups/{group_id}/acknowledge")
def acknowledge_event_group(
    group_id: str,
    payload: AcknowledgeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "monitoring.events.manage")
    item = db.scalar(
        select(EventCorrelationGroup)
        .where(EventCorrelationGroup.id == group_id)
        .with_for_update()
    )
    if item is None or (
        not is_saas_root(current_user)
        and item.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Event group not found")
    acknowledge_group(
        db,
        item,
        _actor(db, current_user),
        payload.expected_version,
        payload.note.strip(),
    )
    _audit(
        db,
        request,
        current_user,
        action="event_group.acknowledged",
        entity_type="event_group",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"note": payload.note.strip()},
    )
    db.commit()
    db.refresh(item)
    return _group_response(db, item, details=True)


@router.post("/escalations/evaluate")
def evaluate_event_escalations(
    request: Request,
    tenant_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "monitoring.events.manage")
    scoped_tenant = _tenant_id(
        db,
        current_user,
        tenant_id,
        required_for_root=True,
    )
    changed = evaluate_escalations(db, scoped_tenant)
    for item in changed:
        _audit(
            db,
            request,
            current_user,
            action="event_group.escalated",
            entity_type="event_group",
            entity_id=item.id,
            tenant_id=item.tenant_id,
            metadata={"level": item.escalation_level},
        )
    db.commit()
    return {"evaluated": len(changed), "group_ids": [item.id for item in changed]}
