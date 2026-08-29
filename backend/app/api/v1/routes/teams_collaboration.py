from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.major_incident import MajorIncident
from app.models.teams_collaboration import (
    TeamsConnector,
    TeamsDelivery,
    TeamsMajorIncidentRoom,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.credential_crypto import encrypt_credential
from app.services.rbac import is_saas_root, require_permissions
from app.services.teams_collaboration import (
    DEFAULT_TEAMS_EVENTS,
    TeamsDeliveryError,
    build_teams_card,
    deliver_teams_payload,
    ensure_major_incident_room,
    queue_major_incident_event,
    utcnow,
    validate_teams_deep_link,
    validate_workflow_webhook_url,
)


router = APIRouter(prefix="/teams")


class TeamsConnectorCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=3, max_length=160)
    provider_type: Literal["WORKFLOW_WEBHOOK", "MOCK"] = "WORKFLOW_WEBHOOK"
    purpose: Literal["DEFAULT", "APPROVALS", "MAJOR_INCIDENT", "SECURITY"] = "DEFAULT"
    webhook_url: str | None = Field(default=None, min_length=20, max_length=8_000)
    team_name: str | None = Field(default=None, max_length=200)
    channel_name: str | None = Field(default=None, max_length=200)
    channel_url: str | None = Field(default=None, max_length=2_000)
    meeting_url: str | None = Field(default=None, max_length=2_000)
    event_types: list[str] = Field(
        default_factory=lambda: list(DEFAULT_TEAMS_EVENTS),
        min_length=1,
        max_length=100,
    )
    minimum_severity: Literal["INFO", "WARNING", "CRITICAL"] = "INFO"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Teams connector name must contain at least 3 characters")
        return normalized

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            event_type = value.strip().lower()
            if not event_type or len(event_type) > 120 or any(
                char not in "abcdefghijklmnopqrstuvwxyz0123456789._-*" for char in event_type
            ) or ("*" in event_type and event_type != "*"):
                raise ValueError(f"Invalid Teams event type: {value}")
            normalized.append(event_type)
        return list(dict.fromkeys(normalized))


class TeamsConnectorUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=3, max_length=160)
    purpose: Literal["DEFAULT", "APPROVALS", "MAJOR_INCIDENT", "SECURITY"] | None = None
    team_name: str | None = Field(default=None, max_length=200)
    channel_name: str | None = Field(default=None, max_length=200)
    channel_url: str | None = Field(default=None, max_length=2_000)
    meeting_url: str | None = Field(default=None, max_length=2_000)
    event_types: list[str] | None = Field(default=None, min_length=1, max_length=100)
    minimum_severity: Literal["INFO", "WARNING", "CRITICAL"] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return TeamsConnectorCreate.validate_name(value)

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return TeamsConnectorCreate.validate_event_types(values)


class TeamsWebhookRotation(BaseModel):
    webhook_url: str = Field(min_length=20, max_length=8_000)


class TeamsStateChange(BaseModel):
    expected_version: int = Field(ge=1)
    action: Literal["ACTIVATE", "PAUSE", "REVOKE"]
    reason: str = Field(min_length=3, max_length=2_000)


class TeamsTestRequest(BaseModel):
    title: str = Field(
        default="SBS AI ITSM Teams connection test",
        min_length=1,
        max_length=255,
    )
    message: str = Field(
        default="The tenant-safe Microsoft Teams notification channel is ready.",
        min_length=1,
        max_length=2_500,
    )


class TeamsDeliveryRetry(BaseModel):
    reason: str = Field(min_length=3, max_length=2_000)


class TeamsRoomOpen(BaseModel):
    connector_id: str | None = None


class TeamsRoomClose(BaseModel):
    reason: str = Field(min_length=3, max_length=2_000)


class TeamsConnectorResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    provider_type: str
    status: str
    purpose: str
    webhook_configured: bool
    webhook_updated_at: datetime | None
    team_name: str | None
    channel_name: str | None
    channel_url: str | None
    meeting_url: str | None
    event_types: list[str]
    minimum_severity: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    success_count: int
    failure_count: int
    last_error: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class TeamsDeliveryResponse(BaseModel):
    id: str
    tenant_id: str
    connector_id: str
    notification_id: str | None
    event_type: str
    severity: str
    entity_type: str | None
    entity_id: str | None
    title: str
    message: str
    action_url: str | None
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: datetime
    last_attempt_at: datetime | None
    sent_at: datetime | None
    provider_status_code: int | None
    provider_reference: str | None
    last_error: str | None
    created_at: datetime


class TeamsRoomResponse(BaseModel):
    id: str
    tenant_id: str
    connector_id: str
    major_incident_id: str
    status: str
    channel_url: str | None
    meeting_url: str | None
    opened_by_id: str | None
    closed_by_id: str | None
    opened_at: datetime
    closed_at: datetime | None


class TeamsDashboardResponse(BaseModel):
    tenant_id: str
    active_connectors: int
    active_production_connectors: int
    queued_deliveries: int
    retrying_deliveries: int
    failed_deliveries: int
    simulated_deliveries: int
    sent_last_24h: int
    open_incident_rooms: int
    channel_health: str
    public_base_url_configured: bool
    mock_provider_enabled: bool


def _tenant_scope(
    current_user: AuthUserResponse,
    requested_tenant_id: str | None,
    *,
    required_for_root: bool = False,
) -> str | None:
    if is_saas_root(current_user):
        if required_for_root and not requested_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tenant_id is required for SaaS root",
            )
        return requested_tenant_id
    if current_user.tenant_id is None:
        raise HTTPException(status_code=403, detail="Tenant context is required")
    if requested_tenant_id and requested_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant access denied")
    return current_user.tenant_id


def _connector(
    db: Session,
    current_user: AuthUserResponse,
    connector_id: str,
) -> TeamsConnector:
    item = db.get(TeamsConnector, connector_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Teams connector not found")
    _tenant_scope(current_user, item.tenant_id)
    return item


def _connector_response(item: TeamsConnector) -> TeamsConnectorResponse:
    return TeamsConnectorResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        name=item.name,
        provider_type=item.provider_type,
        status=item.status,
        purpose=item.purpose,
        webhook_configured=bool(item.webhook_url_encrypted),
        webhook_updated_at=item.webhook_updated_at,
        team_name=item.team_name,
        channel_name=item.channel_name,
        channel_url=item.channel_url,
        meeting_url=item.meeting_url,
        event_types=list(item.event_types_json or []),
        minimum_severity=item.minimum_severity,
        last_success_at=item.last_success_at,
        last_failure_at=item.last_failure_at,
        success_count=item.success_count,
        failure_count=item.failure_count,
        last_error=item.last_error,
        version=item.version,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _delivery_response(item: TeamsDelivery) -> TeamsDeliveryResponse:
    return TeamsDeliveryResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        connector_id=item.connector_id,
        notification_id=item.notification_id,
        event_type=item.event_type,
        severity=item.severity,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        title=item.title,
        message=item.message,
        action_url=item.action_url,
        status=item.status,
        attempts=item.attempts,
        max_attempts=item.max_attempts,
        next_attempt_at=item.next_attempt_at,
        last_attempt_at=item.last_attempt_at,
        sent_at=item.sent_at,
        provider_status_code=item.provider_status_code,
        provider_reference=item.provider_reference,
        last_error=item.last_error,
        created_at=item.created_at,
    )


def _room_response(item: TeamsMajorIncidentRoom) -> TeamsRoomResponse:
    return TeamsRoomResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        connector_id=item.connector_id,
        major_incident_id=item.major_incident_id,
        status=item.status,
        channel_url=item.channel_url,
        meeting_url=item.meeting_url,
        opened_by_id=item.opened_by_id,
        closed_by_id=item.closed_by_id,
        opened_at=item.opened_at,
        closed_at=item.closed_at,
    )


def _audit(
    db: Session,
    request: Request,
    current_user: AuthUserResponse,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None,
    tenant_id: str,
    metadata: dict[str, object],
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


def _require_mock_teams_demo(provider_type: str) -> None:
    if provider_type == "MOCK" and not get_settings().demo_mode:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "The mock Teams connector is disabled outside demo mode. "
                "Configure a Microsoft Teams Workflow webhook."
            ),
        )


@router.get("/dashboard", response_model=TeamsDashboardResponse)
def teams_dashboard(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamsDashboardResponse:
    require_permissions(current_user, "teams.connectors.read")
    scoped_tenant = _tenant_scope(
        current_user,
        tenant_id,
        required_for_root=True,
    )
    assert scoped_tenant is not None
    statuses = dict(
        db.execute(
            select(TeamsDelivery.status, func.count(TeamsDelivery.id))
            .where(TeamsDelivery.tenant_id == scoped_tenant)
            .group_by(TeamsDelivery.status)
        ).all()
    )
    since = utcnow().timestamp() - 24 * 60 * 60
    sent_last_24h = int(
        db.scalar(
            select(func.count(TeamsDelivery.id)).where(
                TeamsDelivery.tenant_id == scoped_tenant,
                TeamsDelivery.status == "SENT",
                TeamsDelivery.sent_at
                >= datetime.fromtimestamp(since, tz=UTC),
            )
        )
        or 0
    )
    active = int(
        db.scalar(
            select(func.count(TeamsConnector.id)).where(
                TeamsConnector.tenant_id == scoped_tenant,
                TeamsConnector.status == "ACTIVE",
            )
        )
        or 0
    )
    active_production = int(
        db.scalar(
            select(func.count(TeamsConnector.id)).where(
                TeamsConnector.tenant_id == scoped_tenant,
                TeamsConnector.status == "ACTIVE",
                TeamsConnector.provider_type == "WORKFLOW_WEBHOOK",
            )
        )
        or 0
    )
    failed = int(statuses.get("FAILED", 0)) + int(statuses.get("DEAD_LETTER", 0))
    health = (
        "NOT_CONFIGURED"
        if active == 0
        else "SIMULATED"
        if active_production == 0
        else "DEGRADED"
        if failed
        else "HEALTHY"
    )
    runtime = get_settings()
    return TeamsDashboardResponse(
        tenant_id=scoped_tenant,
        active_connectors=active,
        active_production_connectors=active_production,
        queued_deliveries=int(statuses.get("QUEUED", 0)),
        retrying_deliveries=int(statuses.get("RETRY", 0)),
        failed_deliveries=failed,
        simulated_deliveries=int(statuses.get("SIMULATED", 0)),
        sent_last_24h=sent_last_24h,
        open_incident_rooms=int(
            db.scalar(
                select(func.count(TeamsMajorIncidentRoom.id)).where(
                    TeamsMajorIncidentRoom.tenant_id == scoped_tenant,
                    TeamsMajorIncidentRoom.status == "OPEN",
                )
            )
            or 0
        ),
        channel_health=health,
        public_base_url_configured=bool(runtime.teams_public_base_url),
        mock_provider_enabled=runtime.demo_mode,
    )


@router.get("/connectors", response_model=list[TeamsConnectorResponse])
def list_teams_connectors(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TeamsConnectorResponse]:
    require_permissions(current_user, "teams.connectors.read")
    scoped_tenant = _tenant_scope(current_user, tenant_id)
    statement = select(TeamsConnector)
    if scoped_tenant is not None:
        statement = statement.where(TeamsConnector.tenant_id == scoped_tenant)
    return [
        _connector_response(item)
        for item in db.scalars(statement.order_by(TeamsConnector.created_at.desc())).all()
    ]


@router.post(
    "/connectors",
    response_model=TeamsConnectorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_teams_connector(
    payload: TeamsConnectorCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamsConnectorResponse:
    require_permissions(current_user, "teams.connectors.manage")
    _require_mock_teams_demo(payload.provider_type)
    tenant_id = _tenant_scope(
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    assert tenant_id is not None
    if db.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = get_settings()
    try:
        channel_url = validate_teams_deep_link(payload.channel_url)
        meeting_url = validate_teams_deep_link(payload.meeting_url)
        webhook_url = (
            validate_workflow_webhook_url(payload.webhook_url, settings=settings)
            if payload.webhook_url
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = utcnow()
    item = TeamsConnector(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=payload.name.strip(),
        provider_type=payload.provider_type,
        status="DRAFT",
        purpose=payload.purpose,
        webhook_url_encrypted=None,
        webhook_updated_at=now if webhook_url else None,
        team_name=payload.team_name.strip() if payload.team_name else None,
        channel_name=payload.channel_name.strip() if payload.channel_name else None,
        channel_url=channel_url,
        meeting_url=meeting_url,
        event_types_json=payload.event_types,
        minimum_severity=payload.minimum_severity,
        success_count=0,
        failure_count=0,
        version=1,
        created_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    if webhook_url:
        item.webhook_url_encrypted = encrypt_credential(
            webhook_url,
            purpose=f"teams-webhook:{item.id}",
            tenant_id=tenant_id,
            settings=settings,
        )
    db.add(item)
    _audit(
        db,
        request,
        current_user,
        action="teams.connector_created",
        entity_type="teams_connector",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"purpose": item.purpose, "provider_type": item.provider_type},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Teams connector name already exists") from exc
    db.refresh(item)
    return _connector_response(item)


@router.get("/connectors/{connector_id}", response_model=TeamsConnectorResponse)
def get_teams_connector(
    connector_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamsConnectorResponse:
    require_permissions(current_user, "teams.connectors.read")
    return _connector_response(_connector(db, current_user, connector_id))


@router.patch("/connectors/{connector_id}", response_model=TeamsConnectorResponse)
def update_teams_connector(
    connector_id: str,
    payload: TeamsConnectorUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamsConnectorResponse:
    require_permissions(current_user, "teams.connectors.manage")
    item = _connector(db, current_user, connector_id)
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Teams connector was updated")
    updates = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    try:
        if "channel_url" in updates:
            updates["channel_url"] = validate_teams_deep_link(updates["channel_url"])
        if "meeting_url" in updates:
            updates["meeting_url"] = validate_teams_deep_link(updates["meeting_url"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    field_map = {"event_types": "event_types_json"}
    for field, value in updates.items():
        target = field_map.get(field, field)
        if isinstance(value, str) and field in {"name", "team_name", "channel_name"}:
            value = value.strip() or None
        setattr(item, target, value)
    item.version += 1
    item.updated_at = utcnow()
    _audit(
        db,
        request,
        current_user,
        action="teams.connector_updated",
        entity_type="teams_connector",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"fields": sorted(updates)},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Teams connector name already exists") from exc
    db.refresh(item)
    return _connector_response(item)


@router.post(
    "/connectors/{connector_id}/rotate-webhook",
    response_model=TeamsConnectorResponse,
)
def rotate_teams_webhook(
    connector_id: str,
    payload: TeamsWebhookRotation,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamsConnectorResponse:
    require_permissions(current_user, "teams.connectors.manage")
    item = _connector(db, current_user, connector_id)
    if item.provider_type != "WORKFLOW_WEBHOOK":
        raise HTTPException(
            status_code=409,
            detail="Webhook rotation requires a Teams Workflow connector",
        )
    try:
        webhook_url = validate_workflow_webhook_url(payload.webhook_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = utcnow()
    item.webhook_url_encrypted = encrypt_credential(
        webhook_url,
        purpose=f"teams-webhook:{item.id}",
        tenant_id=item.tenant_id,
    )
    item.webhook_updated_at = now
    item.status = "DRAFT"
    item.last_error = None
    item.version += 1
    item.updated_at = now
    _audit(
        db,
        request,
        current_user,
        action="teams.webhook_rotated",
        entity_type="teams_connector",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"secret_value_logged": False},
    )
    db.commit()
    db.refresh(item)
    return _connector_response(item)


@router.post("/connectors/{connector_id}/test")
def test_teams_connector(
    connector_id: str,
    payload: TeamsTestRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "teams.connectors.manage")
    item = _connector(db, current_user, connector_id)
    _require_mock_teams_demo(item.provider_type)
    if item.provider_type == "MOCK":
        _audit(
            db,
            request,
            current_user,
            action="teams.connector_test_simulated",
            entity_type="teams_connector",
            entity_id=item.id,
            tenant_id=item.tenant_id,
            metadata={
                "result": "simulated",
                "delivery_confirmed": False,
            },
        )
        db.commit()
        return {
            "ok": False,
            "status": "SIMULATED",
            "provider_status_code": None,
            "reference": None,
        }
    action_url = None
    settings = get_settings()
    if settings.teams_public_base_url:
        action_url = settings.teams_public_base_url.rstrip("/") + "/teams-collaboration"
    card = build_teams_card(
        event_type="teams.connection_test",
        severity="INFO",
        title=payload.title,
        message=payload.message,
        entity_type="teams_connector",
        entity_id=item.id,
        action_url=action_url,
        channel_url=item.channel_url,
        meeting_url=None,
    )
    try:
        status_code, reference = deliver_teams_payload(item, card)
    except TeamsDeliveryError as exc:
        item.last_failure_at = utcnow()
        item.failure_count += 1
        item.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    item.last_success_at = utcnow()
    item.success_count += 1
    item.last_error = None
    _audit(
        db,
        request,
        current_user,
        action="teams.connector_tested",
        entity_type="teams_connector",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"provider_status_code": status_code},
    )
    db.commit()
    return {"ok": True, "provider_status_code": status_code, "reference": reference}


@router.post(
    "/connectors/{connector_id}/state",
    response_model=TeamsConnectorResponse,
)
def change_teams_connector_state(
    connector_id: str,
    payload: TeamsStateChange,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamsConnectorResponse:
    require_permissions(current_user, "teams.connectors.manage")
    item = _connector(db, current_user, connector_id)
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Teams connector was updated")
    if payload.action == "ACTIVATE":
        _require_mock_teams_demo(item.provider_type)
        if item.status == "REVOKED":
            raise HTTPException(
                status_code=409,
                detail="Revoked connector requires a new webhook before activation",
            )
        if item.provider_type == "WORKFLOW_WEBHOOK" and not item.webhook_url_encrypted:
            raise HTTPException(status_code=409, detail="Teams webhook is not configured")
        runtime = get_settings()
        if not runtime.demo_mode and not runtime.teams_public_base_url:
            raise HTTPException(
                status_code=409,
                detail="TEAMS_PUBLIC_BASE_URL is required before production activation",
            )
        item.status = "ACTIVE"
    elif payload.action == "PAUSE":
        if item.status == "REVOKED":
            raise HTTPException(status_code=409, detail="Revoked connector cannot be paused")
        item.status = "PAUSED"
    else:
        item.status = "REVOKED"
        item.webhook_url_encrypted = None
        item.webhook_updated_at = utcnow()
    item.version += 1
    item.updated_at = utcnow()
    _audit(
        db,
        request,
        current_user,
        action=f"teams.connector_{payload.action.lower()}",
        entity_type="teams_connector",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason": payload.reason},
    )
    db.commit()
    db.refresh(item)
    return _connector_response(item)


@router.get("/deliveries", response_model=list[TeamsDeliveryResponse])
def list_teams_deliveries(
    tenant_id: str | None = Query(default=None),
    connector_id: str | None = Query(default=None),
    delivery_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TeamsDeliveryResponse]:
    require_permissions(current_user, "teams.deliveries.read")
    scoped_tenant = _tenant_scope(current_user, tenant_id)
    statement = select(TeamsDelivery)
    if scoped_tenant is not None:
        statement = statement.where(TeamsDelivery.tenant_id == scoped_tenant)
    if connector_id:
        connector = _connector(db, current_user, connector_id)
        statement = statement.where(
            TeamsDelivery.connector_id == connector.id,
            TeamsDelivery.tenant_id == connector.tenant_id,
        )
    if delivery_status and delivery_status.upper() != "ALL":
        statement = statement.where(TeamsDelivery.status == delivery_status.upper())
    rows = db.scalars(
        statement.order_by(TeamsDelivery.created_at.desc()).limit(limit)
    ).all()
    return [_delivery_response(item) for item in rows]


@router.post(
    "/deliveries/{delivery_id}/retry",
    response_model=TeamsDeliveryResponse,
)
def retry_teams_delivery(
    delivery_id: str,
    payload: TeamsDeliveryRetry,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamsDeliveryResponse:
    require_permissions(current_user, "teams.deliveries.manage")
    item = db.get(TeamsDelivery, delivery_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Teams delivery not found")
    _tenant_scope(current_user, item.tenant_id)
    if item.status not in {"FAILED", "DEAD_LETTER", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Delivery is not retryable")
    connector = _connector(db, current_user, item.connector_id)
    if connector.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Teams connector is not active")
    item.status = "RETRY"
    item.attempts = 0
    item.next_attempt_at = utcnow()
    item.last_error = None
    item.updated_at = utcnow()
    _audit(
        db,
        request,
        current_user,
        action="teams.delivery_retried",
        entity_type="teams_delivery",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason": payload.reason},
    )
    db.commit()
    db.refresh(item)
    return _delivery_response(item)


@router.get("/major-incident-rooms", response_model=list[TeamsRoomResponse])
def list_major_incident_rooms(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TeamsRoomResponse]:
    require_permissions(current_user, "teams.collaboration.read")
    scoped_tenant = _tenant_scope(current_user, tenant_id)
    statement = select(TeamsMajorIncidentRoom)
    if scoped_tenant is not None:
        statement = statement.where(TeamsMajorIncidentRoom.tenant_id == scoped_tenant)
    return [
        _room_response(item)
        for item in db.scalars(
            statement.order_by(TeamsMajorIncidentRoom.opened_at.desc()).limit(500)
        ).all()
    ]


@router.post(
    "/major-incident-rooms/{incident_id}/open",
    response_model=TeamsRoomResponse,
)
def open_major_incident_room(
    incident_id: str,
    payload: TeamsRoomOpen,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamsRoomResponse:
    require_permissions(current_user, "teams.collaboration.manage")
    incident = db.get(MajorIncident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Major incident not found")
    _tenant_scope(current_user, incident.tenant_id)
    existing = db.scalar(
        select(TeamsMajorIncidentRoom).where(
            TeamsMajorIncidentRoom.major_incident_id == incident.id
        )
    )
    if existing is not None:
        if existing.status == "CLOSED":
            raise HTTPException(status_code=409, detail="Incident room is already closed")
        return _room_response(existing)
    if payload.connector_id:
        connector = _connector(db, current_user, payload.connector_id)
        if connector.tenant_id != incident.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant access denied")
        if connector.status != "ACTIVE" or connector.purpose != "MAJOR_INCIDENT":
            raise HTTPException(
                status_code=409,
                detail="An active Major Incident connector is required",
            )
        now = utcnow()
        room = TeamsMajorIncidentRoom(
            id=str(uuid.uuid4()),
            tenant_id=incident.tenant_id,
            connector_id=connector.id,
            major_incident_id=incident.id,
            status="OPEN",
            channel_url=connector.channel_url,
            meeting_url=connector.meeting_url,
            opened_by_id=current_user.id,
            opened_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(room)
    else:
        room = ensure_major_incident_room(
            db,
            incident=incident,
            opened_by_id=current_user.id,
        )
        if room is None:
            raise HTTPException(
                status_code=409,
                detail="No active Major Incident Teams connector is configured",
            )
    queue_major_incident_event(
        db,
        incident=incident,
        event_type="major_incident.declared",
        detail="Incident collaboration room opened manually.",
        actor_user_id=current_user.id,
    )
    _audit(
        db,
        request,
        current_user,
        action="teams.major_incident_room_opened",
        entity_type="major_incident",
        entity_id=incident.id,
        tenant_id=incident.tenant_id,
        metadata={"connector_id": room.connector_id},
    )
    db.commit()
    db.refresh(room)
    return _room_response(room)


@router.post(
    "/major-incident-rooms/{incident_id}/close",
    response_model=TeamsRoomResponse,
)
def close_major_incident_room(
    incident_id: str,
    payload: TeamsRoomClose,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamsRoomResponse:
    require_permissions(current_user, "teams.collaboration.manage")
    room = db.scalar(
        select(TeamsMajorIncidentRoom).where(
            TeamsMajorIncidentRoom.major_incident_id == incident_id
        )
    )
    if room is None:
        raise HTTPException(status_code=404, detail="Teams incident room not found")
    _tenant_scope(current_user, room.tenant_id)
    if room.status == "CLOSED":
        return _room_response(room)
    room.status = "CLOSED"
    room.closed_by_id = current_user.id
    room.closed_at = utcnow()
    room.updated_at = utcnow()
    _audit(
        db,
        request,
        current_user,
        action="teams.major_incident_room_closed",
        entity_type="major_incident",
        entity_id=incident_id,
        tenant_id=room.tenant_id,
        metadata={"reason": payload.reason},
    )
    db.commit()
    db.refresh(room)
    return _room_response(room)
