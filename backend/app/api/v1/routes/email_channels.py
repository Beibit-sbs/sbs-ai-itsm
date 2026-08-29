from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import re
import secrets
import uuid
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.core.security import create_token, decode_token
from app.db.session import get_db
from app.models.email_channel import (
    EmailAttachment,
    EmailChannel,
    EmailConversation,
    EmailDeliveryEvent,
    EmailInboundMessage,
    EmailWebhookEvent,
)
from app.models.email_message_log import EmailMessageLog
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.credential_crypto import decrypt_credential, encrypt_credential
from app.services.email_attachments import (
    DEFAULT_ALLOWED_EXTENSIONS,
    attachment_path,
    delete_attachment_content,
)
from app.services.email_operations import (
    EmailOperationError,
    active_email_channel,
    persist_graph_notifications,
    queue_email,
    reprocess_inbound_message,
    schedule_email_retry,
    sync_email_channel,
    utcnow,
)
from app.services.microsoft_graph_email import (
    GraphEmailError,
    MicrosoftGraphEmailClient,
)
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/email")
webhook_router = APIRouter(prefix="/email/webhooks")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_EXTENSION = re.compile(r"^\.[a-z0-9]{1,12}$")


class EmailChannelCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=3, max_length=160)
    provider_type: Literal["MICROSOFT_GRAPH", "MOCK"] = "MICROSOFT_GRAPH"
    mailbox_address: str = Field(min_length=3, max_length=255)
    mailbox_user_id: str | None = Field(default=None, max_length=255)
    entra_tenant_id: str | None = Field(default=None, max_length=128)
    client_id: str | None = Field(default=None, max_length=128)
    client_secret: str | None = Field(default=None, min_length=12, max_length=4_000)
    inbound_enabled: bool = True
    outbound_enabled: bool = True
    default_target: Literal["TICKET", "REQUEST"] = "TICKET"
    allowed_sender_domains: list[str] = Field(default_factory=list, max_length=100)
    allowed_attachment_extensions: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_EXTENSIONS),
        max_length=100,
    )
    max_attachment_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1_024,
        le=25 * 1024 * 1024,
    )

    @field_validator("mailbox_address")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL.fullmatch(normalized):
            raise ValueError("A valid mailbox email address is required")
        return normalized

    @field_validator("allowed_sender_domains")
    @classmethod
    def validate_domains(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            domain = value.strip().lower().lstrip("@")
            if (
                not domain
                or "." not in domain
                or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-." for char in domain)
            ):
                raise ValueError(f"Invalid sender domain: {value}")
            normalized.append(domain)
        return list(dict.fromkeys(normalized))

    @field_validator("allowed_attachment_extensions")
    @classmethod
    def validate_extensions(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            extension = value.strip().lower()
            if not extension.startswith("."):
                extension = f".{extension}"
            if not _EXTENSION.fullmatch(extension):
                raise ValueError(f"Invalid attachment extension: {value}")
            normalized.append(extension)
        return list(dict.fromkeys(normalized))


class EmailChannelUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=3, max_length=160)
    mailbox_address: str | None = Field(default=None, min_length=3, max_length=255)
    mailbox_user_id: str | None = Field(default=None, max_length=255)
    entra_tenant_id: str | None = Field(default=None, max_length=128)
    client_id: str | None = Field(default=None, max_length=128)
    inbound_enabled: bool | None = None
    outbound_enabled: bool | None = None
    default_target: Literal["TICKET", "REQUEST"] | None = None
    allowed_sender_domains: list[str] | None = Field(default=None, max_length=100)
    allowed_attachment_extensions: list[str] | None = Field(
        default=None, max_length=100
    )
    max_attachment_bytes: int | None = Field(
        default=None,
        ge=1_024,
        le=25 * 1024 * 1024,
    )

    @field_validator("mailbox_address")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _EMAIL.fullmatch(normalized):
            raise ValueError("A valid mailbox email address is required")
        return normalized

    @field_validator("allowed_sender_domains")
    @classmethod
    def validate_domains(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return EmailChannelCreate.validate_domains(values)

    @field_validator("allowed_attachment_extensions")
    @classmethod
    def validate_extensions(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return EmailChannelCreate.validate_extensions(values)


class SecretRotation(BaseModel):
    client_secret: str = Field(min_length=12, max_length=4_000)


class ChannelStateChange(BaseModel):
    expected_version: int = Field(ge=1)
    action: Literal["ACTIVATE", "PAUSE", "REVOKE"]
    reason: str = Field(min_length=3, max_length=2_000)


class TestEmailRequest(BaseModel):
    to_email: str = Field(min_length=3, max_length=255)
    subject: str = Field(default="SBS AI ITSM email channel test", min_length=1, max_length=255)
    body: str = Field(
        default="This message confirms that the SBS AI ITSM outbound email queue is configured.",
        min_length=1,
        max_length=20_000,
    )

    @field_validator("to_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL.fullmatch(normalized):
            raise ValueError("A valid recipient email address is required")
        return normalized


class ReprocessRequest(BaseModel):
    override_sender_authorization: bool = False
    reason: str = Field(min_length=5, max_length=2_000)


class AttachmentDecision(BaseModel):
    decision: Literal["RELEASE", "BLOCK"]
    reason: str = Field(min_length=5, max_length=2_000)


class EmailChannelResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    provider_type: str
    status: str
    mailbox_address: str
    mailbox_user_id: str | None
    entra_tenant_id: str | None
    client_id: str | None
    client_secret_configured: bool
    inbound_enabled: bool
    outbound_enabled: bool
    default_target: str
    allowed_sender_domains: list[str]
    allowed_attachment_extensions: list[str]
    max_attachment_bytes: int
    graph_subscription_id: str | None
    graph_subscription_expires_at: datetime | None
    webhook_configured: bool
    delta_sync_initialized: bool
    last_sync_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    success_count: int
    failure_count: int
    last_error: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class EmailDashboardResponse(BaseModel):
    tenant_id: str
    active_channels: int
    active_production_channels: int
    queued_outbound: int
    failed_outbound: int
    accepted_outbound: int
    simulated_outbound: int
    inbound_received: int
    inbound_quarantined: int
    webhook_dead_letter: int
    attachments_quarantined: int
    channel_health: str
    webhook_public_url_configured: bool
    antivirus_configured: bool
    manual_unscanned_release_enabled: bool
    mock_provider_enabled: bool


class InboundMessageResponse(BaseModel):
    id: str
    tenant_id: str
    channel_id: str
    conversation_id: str | None
    provider_message_id: str
    internet_message_id: str | None
    from_email: str
    from_name: str | None
    subject: str
    body_preview: str
    authentication_results: str | None
    status: str
    rejection_reason: str | None
    processing_attempts: int
    related_ticket_id: str | None
    related_request_id: str | None
    received_at: datetime
    processed_at: datetime | None
    attachment_count: int


class ConversationResponse(BaseModel):
    id: str
    channel_id: str
    thread_token_hint: str
    entity_type: str
    entity_id: str
    requester_email: str
    normalized_subject: str
    last_message_at: datetime | None


class AttachmentResponse(BaseModel):
    id: str
    inbound_message_id: str
    original_filename: str
    safe_filename: str
    content_type: str | None
    detected_content_type: str | None
    size_bytes: int
    sha256: str | None
    status: str
    scan_status: str
    blocked_reason: str | None
    security_findings: list[str]
    sanitization_applied: bool
    download_count: int
    reviewed_at: datetime | None


class AttachmentDownloadTokenResponse(BaseModel):
    token: str
    ttl_seconds: int
    expires_at: datetime


def _attachment_findings(item: EmailAttachment) -> list[str]:
    try:
        parsed = json.loads(item.security_findings_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return ["invalid_security_evidence"]
    return [str(value) for value in parsed] if isinstance(parsed, list) else []


def _attachment_response(item: EmailAttachment) -> AttachmentResponse:
    return AttachmentResponse(
        id=item.id,
        inbound_message_id=item.inbound_message_id,
        original_filename=item.original_filename,
        safe_filename=item.safe_filename,
        content_type=item.content_type,
        detected_content_type=item.detected_content_type,
        size_bytes=item.size_bytes,
        sha256=item.sha256,
        status=item.status,
        scan_status=item.scan_status,
        blocked_reason=item.blocked_reason,
        security_findings=_attachment_findings(item),
        sanitization_applied=item.sanitization_applied,
        download_count=item.download_count,
        reviewed_at=item.reviewed_at,
    )


class DeliveryEventResponse(BaseModel):
    id: str
    email_log_id: str
    event_type: str
    reason: str | None
    metadata: dict[str, object]
    occurred_at: datetime


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context is required",
        )
    if requested_tenant_id and requested_tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant access denied",
        )
    return current_user.tenant_id


def _channel_response(item: EmailChannel) -> EmailChannelResponse:
    return EmailChannelResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        name=item.name,
        provider_type=item.provider_type,
        status=item.status,
        mailbox_address=item.mailbox_address,
        mailbox_user_id=item.mailbox_user_id,
        entra_tenant_id=item.entra_tenant_id,
        client_id=item.client_id,
        client_secret_configured=bool(item.client_secret_encrypted),
        inbound_enabled=item.inbound_enabled,
        outbound_enabled=item.outbound_enabled,
        default_target=item.default_target,
        allowed_sender_domains=list(item.allowed_sender_domains_json or []),
        allowed_attachment_extensions=list(
            item.allowed_attachment_extensions_json or []
        ),
        max_attachment_bytes=item.max_attachment_bytes,
        graph_subscription_id=item.graph_subscription_id,
        graph_subscription_expires_at=item.graph_subscription_expires_at,
        webhook_configured=bool(item.webhook_client_state_encrypted),
        delta_sync_initialized=bool(item.delta_link_encrypted),
        last_sync_at=item.last_sync_at,
        last_success_at=item.last_success_at,
        last_failure_at=item.last_failure_at,
        success_count=item.success_count,
        failure_count=item.failure_count,
        last_error=item.last_error,
        version=item.version,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _channel(
    db: Session,
    current_user: AuthUserResponse,
    channel_id: str,
) -> EmailChannel:
    item = db.get(EmailChannel, channel_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Email channel not found")
    _tenant_scope(current_user, item.tenant_id)
    return item


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.get(User, current_user.id)


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
        actor_user=_actor(db, current_user),
        actor_email=current_user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _require_mock_email_demo(provider_type: str) -> None:
    if provider_type == "MOCK" and not get_settings().demo_mode:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "The mock email provider is disabled outside demo mode. "
                "Configure Microsoft Graph for production email."
            ),
        )


@router.get("/dashboard", response_model=EmailDashboardResponse)
def email_dashboard(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailDashboardResponse:
    require_permissions(current_user, "email.channel.read")
    scope = _tenant_scope(
        current_user,
        tenant_id,
        required_for_root=True,
    )
    assert scope is not None

    def count(model: type[Any], *conditions: Any) -> int:
        return int(db.scalar(select(func.count(model.id)).where(*conditions)) or 0)

    active = count(
        EmailChannel,
        EmailChannel.tenant_id == scope,
        EmailChannel.status == "ACTIVE",
    )
    active_production = count(
        EmailChannel,
        EmailChannel.tenant_id == scope,
        EmailChannel.status == "ACTIVE",
        EmailChannel.provider_type == "MICROSOFT_GRAPH",
    )
    failed = count(
        EmailMessageLog,
        EmailMessageLog.tenant_id == scope,
        EmailMessageLog.status == "FAILED",
    )
    quarantined = count(
        EmailInboundMessage,
        EmailInboundMessage.tenant_id == scope,
        EmailInboundMessage.status == "QUARANTINED",
    )
    settings = get_settings()
    return EmailDashboardResponse(
        tenant_id=scope,
        active_channels=active,
        active_production_channels=active_production,
        queued_outbound=count(
            EmailMessageLog,
            EmailMessageLog.tenant_id == scope,
            EmailMessageLog.status.in_(["QUEUED", "RETRY"]),
        ),
        failed_outbound=failed,
        accepted_outbound=count(
            EmailMessageLog,
            EmailMessageLog.tenant_id == scope,
            EmailMessageLog.status.in_(["ACCEPTED", "DELIVERED", "SENT"]),
        ),
        simulated_outbound=count(
            EmailMessageLog,
            EmailMessageLog.tenant_id == scope,
            EmailMessageLog.status == "SIMULATED",
        ),
        inbound_received=count(
            EmailInboundMessage,
            EmailInboundMessage.tenant_id == scope,
        ),
        inbound_quarantined=quarantined,
        webhook_dead_letter=count(
            EmailWebhookEvent,
            EmailWebhookEvent.tenant_id == scope,
            EmailWebhookEvent.status == "DEAD_LETTER",
        ),
        attachments_quarantined=count(
            EmailAttachment,
            EmailAttachment.tenant_id == scope,
            EmailAttachment.status == "QUARANTINED",
        ),
        channel_health=(
            "NOT_CONFIGURED"
            if active == 0
            else "SIMULATED"
            if active_production == 0
            else "DEGRADED"
            if failed or quarantined
            else "HEALTHY"
        ),
        webhook_public_url_configured=bool(settings.email_public_base_url),
        antivirus_configured=bool(settings.email_clamav_host),
        manual_unscanned_release_enabled=(
            settings.email_attachment_manual_release_without_clean_scan
        ),
        mock_provider_enabled=settings.demo_mode,
    )


@router.get("/channels", response_model=list[EmailChannelResponse])
def list_email_channels(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EmailChannelResponse]:
    require_permissions(current_user, "email.channel.read")
    scope = _tenant_scope(current_user, tenant_id)
    statement = select(EmailChannel)
    if scope:
        statement = statement.where(EmailChannel.tenant_id == scope)
    return [
        _channel_response(item)
        for item in db.scalars(
            statement.order_by(EmailChannel.created_at.desc())
        ).all()
    ]


@router.post(
    "/channels",
    response_model=EmailChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_email_channel(
    payload: EmailChannelCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailChannelResponse:
    require_permissions(current_user, "email.channel.manage")
    _require_mock_email_demo(payload.provider_type)
    tenant_id = _tenant_scope(
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    assert tenant_id is not None
    if db.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if payload.provider_type == "MICROSOFT_GRAPH" and (
        not payload.entra_tenant_id
        or not payload.client_id
        or not payload.client_secret
    ):
        raise HTTPException(
            status_code=422,
            detail="Entra tenant ID, client ID and client secret are required",
        )
    channel_id = str(uuid.uuid4())
    now = utcnow()
    item = EmailChannel(
        id=channel_id,
        tenant_id=tenant_id,
        name=payload.name.strip(),
        provider_type=payload.provider_type,
        status="DRAFT",
        mailbox_address=payload.mailbox_address,
        mailbox_user_id=(payload.mailbox_user_id or "").strip() or None,
        entra_tenant_id=(payload.entra_tenant_id or "").strip() or None,
        client_id=(payload.client_id or "").strip() or None,
        client_secret_encrypted=(
            encrypt_credential(
                payload.client_secret,
                purpose=f"email-channel:{channel_id}:client-secret",
                tenant_id=tenant_id,
            )
            if payload.client_secret
            else None
        ),
        secret_updated_at=now if payload.client_secret else None,
        inbound_enabled=payload.inbound_enabled,
        outbound_enabled=payload.outbound_enabled,
        default_target=payload.default_target,
        allowed_sender_domains_json=payload.allowed_sender_domains,
        allowed_attachment_extensions_json=payload.allowed_attachment_extensions,
        max_attachment_bytes=payload.max_attachment_bytes,
        loop_token_encrypted=encrypt_credential(
            secrets.token_urlsafe(32),
            purpose=f"email-channel:{channel_id}:loop-token",
            tenant_id=tenant_id,
        ),
        success_count=0,
        failure_count=0,
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
        action="email_channel_created",
        entity_type="email_channel",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={
            "provider_type": item.provider_type,
            "mailbox_address": item.mailbox_address,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Channel name or mailbox is already used in this tenant",
        ) from exc
    db.refresh(item)
    return _channel_response(item)


@router.get("/channels/{channel_id}", response_model=EmailChannelResponse)
def get_email_channel(
    channel_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailChannelResponse:
    require_permissions(current_user, "email.channel.read")
    return _channel_response(_channel(db, current_user, channel_id))


@router.patch("/channels/{channel_id}", response_model=EmailChannelResponse)
def update_email_channel(
    channel_id: str,
    payload: EmailChannelUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailChannelResponse:
    require_permissions(current_user, "email.channel.manage")
    item = _channel(db, current_user, channel_id)
    if item.status == "REVOKED":
        raise HTTPException(status_code=409, detail="Revoked channel cannot be edited")
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Email channel version conflict")
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    mapping = {
        "allowed_sender_domains": "allowed_sender_domains_json",
        "allowed_attachment_extensions": "allowed_attachment_extensions_json",
    }
    for field_name, value in changes.items():
        setattr(item, mapping.get(field_name, field_name), value)
    item.version += 1
    item.updated_at = utcnow()
    if item.status == "ACTIVE" and {
        "mailbox_address",
        "mailbox_user_id",
        "entra_tenant_id",
        "client_id",
    }.intersection(changes):
        item.status = "PAUSED"
        item.last_error = "Connection settings changed; validate and activate again"
    _audit(
        db,
        request,
        current_user,
        action="email_channel_updated",
        entity_type="email_channel",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"updated_fields": sorted(changes)},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Channel name or mailbox is already used in this tenant",
        ) from exc
    db.refresh(item)
    return _channel_response(item)


@router.post(
    "/channels/{channel_id}/rotate-secret",
    response_model=EmailChannelResponse,
)
def rotate_email_channel_secret(
    channel_id: str,
    payload: SecretRotation,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailChannelResponse:
    require_permissions(current_user, "email.channel.manage")
    item = _channel(db, current_user, channel_id)
    if item.provider_type != "MICROSOFT_GRAPH" or item.status == "REVOKED":
        raise HTTPException(status_code=409, detail="Secret rotation is not available")
    item.client_secret_encrypted = encrypt_credential(
        payload.client_secret,
        purpose=f"email-channel:{item.id}:client-secret",
        tenant_id=item.tenant_id,
    )
    item.secret_updated_at = utcnow()
    item.status = "PAUSED"
    item.last_error = "Client secret rotated; validate and activate the channel"
    item.version += 1
    _audit(
        db,
        request,
        current_user,
        action="email_channel_secret_rotated",
        entity_type="email_channel",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={},
    )
    db.commit()
    db.refresh(item)
    return _channel_response(item)


@router.post("/channels/{channel_id}/test-connection")
def test_email_channel_connection(
    channel_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "email.channel.manage")
    item = _channel(db, current_user, channel_id)
    _require_mock_email_demo(item.provider_type)
    if item.provider_type == "MOCK":
        _audit(
            db,
            request,
            current_user,
            action="email_channel_connection_simulated",
            entity_type="email_channel",
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
            "mailbox": {
                "provider": "MOCK",
                "mailbox": item.mailbox_address,
            },
        }
    try:
        result = MicrosoftGraphEmailClient(item).test_connection()
        item.last_success_at = utcnow()
        item.last_error = None
    except (GraphEmailError, ValueError, RuntimeError) as exc:
        item.failure_count += 1
        item.last_failure_at = utcnow()
        item.last_error = str(exc)[:2_000]
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="email_channel_connection_tested",
        entity_type="email_channel",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"result": "success"},
    )
    db.commit()
    return {"ok": True, "mailbox": result}


@router.post("/channels/{channel_id}/state", response_model=EmailChannelResponse)
def change_email_channel_state(
    channel_id: str,
    payload: ChannelStateChange,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailChannelResponse:
    require_permissions(current_user, "email.channel.manage")
    item = _channel(db, current_user, channel_id)
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Email channel version conflict")
    if item.status == "REVOKED":
        raise HTTPException(status_code=409, detail="Revoked channel is immutable")
    if payload.action == "ACTIVATE":
        _require_mock_email_demo(item.provider_type)
        if not item.inbound_enabled and not item.outbound_enabled:
            raise HTTPException(
                status_code=409,
                detail="Enable inbound or outbound processing before activation",
            )
        existing = active_email_channel(db, tenant_id=item.tenant_id)
        if existing and existing.id != item.id:
            raise HTTPException(
                status_code=409,
                detail="Pause the existing active channel before activating another",
            )
        try:
            if item.provider_type == "MICROSOFT_GRAPH":
                MicrosoftGraphEmailClient(item).test_connection()
        except (GraphEmailError, ValueError, RuntimeError) as exc:
            item.failure_count += 1
            item.last_failure_at = utcnow()
            item.last_error = str(exc)[:2_000]
            db.commit()
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        item.status = "ACTIVE"
        if item.provider_type == "MICROSOFT_GRAPH":
            item.last_success_at = utcnow()
            item.last_error = None
        else:
            item.last_success_at = None
            item.last_error = (
                "Simulation-only channel; no external transport is configured"
            )
    elif payload.action == "PAUSE":
        item.status = "PAUSED"
    else:
        if item.graph_subscription_id and item.provider_type == "MICROSOFT_GRAPH":
            try:
                MicrosoftGraphEmailClient(item).delete_subscription(
                    item.graph_subscription_id
                )
            except GraphEmailError:
                pass
        item.status = "REVOKED"
        item.client_secret_encrypted = None
        item.webhook_client_state_encrypted = None
        item.delta_link_encrypted = None
        item.graph_subscription_id = None
        item.graph_subscription_expires_at = None
    item.version += 1
    item.updated_at = utcnow()
    _audit(
        db,
        request,
        current_user,
        action=f"email_channel_{payload.action.lower()}",
        entity_type="email_channel",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason": payload.reason},
    )
    db.commit()
    db.refresh(item)
    return _channel_response(item)


@router.post("/channels/{channel_id}/subscription")
def synchronize_graph_subscription(
    channel_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "email.channel.manage")
    item = _channel(db, current_user, channel_id)
    settings = get_settings()
    if (
        item.provider_type != "MICROSOFT_GRAPH"
        or item.status != "ACTIVE"
        or not item.inbound_enabled
    ):
        raise HTTPException(
            status_code=409,
            detail="An active inbound Microsoft Graph channel is required",
        )
    if not settings.email_public_base_url:
        raise HTTPException(
            status_code=409,
            detail=(
                "EMAIL_PUBLIC_BASE_URL is not configured. Delta polling remains "
                "available without a public webhook."
            ),
        )
    client_state = (
        decrypt_credential(
            item.webhook_client_state_encrypted,
            purpose=f"email-channel:{item.id}:webhook-state",
            tenant_id=item.tenant_id,
        )
        if item.webhook_client_state_encrypted
        else secrets.token_urlsafe(32)
    )
    if not item.webhook_client_state_encrypted:
        # Microsoft Graph validates the callback synchronously while the
        # subscription request is in flight, so clientState must be visible
        # to that separate callback transaction before create_subscription.
        item.webhook_client_state_encrypted = encrypt_credential(
            client_state,
            purpose=f"email-channel:{item.id}:webhook-state",
            tenant_id=item.tenant_id,
        )
        db.commit()
    try:
        client = MicrosoftGraphEmailClient(item)
        payload = (
            client.renew_subscription(item.graph_subscription_id)
            if item.graph_subscription_id
            else client.create_subscription(
                notification_url=(
                    settings.email_public_base_url.rstrip("/")
                    + f"{settings.api_v1_prefix}/email/webhooks/microsoft-graph/{item.id}"
                ),
                client_state=client_state,
            )
        )
    except (GraphEmailError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    item.graph_subscription_id = str(payload.get("id") or item.graph_subscription_id)
    item.graph_subscription_expires_at = datetime.fromisoformat(
        str(payload["expirationDateTime"]).replace("Z", "+00:00")
    ).astimezone(UTC)
    item.last_success_at = utcnow()
    item.last_error = None
    _audit(
        db,
        request,
        current_user,
        action="email_channel_subscription_synchronized",
        entity_type="email_channel",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"subscription_id": item.graph_subscription_id},
    )
    db.commit()
    return {
        "subscription_id": item.graph_subscription_id,
        "expires_at": item.graph_subscription_expires_at,
    }


@router.post("/channels/{channel_id}/sync")
def synchronize_email_channel(
    channel_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    require_permissions(current_user, "email.inbound.manage")
    item = _channel(db, current_user, channel_id)
    if item.provider_type != "MICROSOFT_GRAPH":
        raise HTTPException(
            status_code=409,
            detail="Inbound synchronization requires Microsoft Graph",
        )
    try:
        result = sync_email_channel(db, channel=item)
    except (GraphEmailError, ValueError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="email_channel_manual_sync",
        entity_type="email_channel",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata=result,
    )
    db.commit()
    return result


@router.post(
    "/channels/{channel_id}/test-email",
    status_code=status.HTTP_202_ACCEPTED,
)
def send_email_channel_test(
    channel_id: str,
    payload: TestEmailRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "email.channel.manage")
    item = _channel(db, current_user, channel_id)
    _require_mock_email_demo(item.provider_type)
    if item.status != "ACTIVE" or not item.outbound_enabled:
        raise HTTPException(status_code=409, detail="Outbound channel is not active")
    queued = queue_email(
        db,
        to_email=payload.to_email,
        subject=payload.subject,
        body=payload.body,
        tenant_id=item.tenant_id,
        event_type="email_channel_test",
        metadata={"channel_id": item.id, "requested_by": current_user.id},
    )
    _audit(
        db,
        request,
        current_user,
        action="email_channel_test_queued",
        entity_type="email_message_log",
        entity_id=queued.id,
        tenant_id=item.tenant_id,
        metadata={"to_email": payload.to_email},
    )
    db.commit()
    return {"id": queued.id, "status": queued.status}


@router.get("/inbound", response_model=list[InboundMessageResponse])
def list_inbound_email(
    tenant_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    channel_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[InboundMessageResponse]:
    require_permissions(current_user, "email.inbound.read")
    scope = _tenant_scope(current_user, tenant_id)
    statement = select(EmailInboundMessage)
    if scope:
        statement = statement.where(EmailInboundMessage.tenant_id == scope)
    if status_filter:
        statement = statement.where(
            EmailInboundMessage.status == status_filter.upper()
        )
    if channel_id:
        statement = statement.where(EmailInboundMessage.channel_id == channel_id)
    rows = db.scalars(
        statement.order_by(EmailInboundMessage.received_at.desc()).limit(limit)
    ).all()
    attachment_counts = dict(
        db.execute(
            select(
                EmailAttachment.inbound_message_id,
                func.count(EmailAttachment.id),
            )
            .where(EmailAttachment.inbound_message_id.in_([row.id for row in rows]))
            .group_by(EmailAttachment.inbound_message_id)
        ).all()
    ) if rows else {}
    return [
        InboundMessageResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            channel_id=row.channel_id,
            conversation_id=row.conversation_id,
            provider_message_id=row.provider_message_id,
            internet_message_id=row.internet_message_id,
            from_email=row.from_email,
            from_name=row.from_name,
            subject=row.subject,
            body_preview=row.body_text[:500],
            authentication_results=row.authentication_results,
            status=row.status,
            rejection_reason=row.rejection_reason,
            processing_attempts=row.processing_attempts,
            related_ticket_id=row.related_ticket_id,
            related_request_id=row.related_request_id,
            received_at=row.received_at,
            processed_at=row.processed_at,
            attachment_count=int(attachment_counts.get(row.id, 0)),
        )
        for row in rows
    ]


@router.post(
    "/inbound/{message_id}/reprocess",
    response_model=InboundMessageResponse,
)
def reprocess_email_message(
    message_id: str,
    payload: ReprocessRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InboundMessageResponse:
    require_permissions(current_user, "email.inbound.manage")
    item = db.get(EmailInboundMessage, message_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inbound message not found")
    _tenant_scope(current_user, item.tenant_id)
    try:
        with db.begin_nested():
            reprocess_inbound_message(
                db,
                inbound=item,
                override_sender_authorization=payload.override_sender_authorization,
            )
    except (EmailOperationError, GraphEmailError, ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="email_inbound_reprocessed",
        entity_type="email_inbound_message",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "override_sender_authorization": payload.override_sender_authorization,
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(item)
    count = int(
        db.scalar(
            select(func.count(EmailAttachment.id)).where(
                EmailAttachment.inbound_message_id == item.id
            )
        )
        or 0
    )
    return InboundMessageResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        channel_id=item.channel_id,
        conversation_id=item.conversation_id,
        provider_message_id=item.provider_message_id,
        internet_message_id=item.internet_message_id,
        from_email=item.from_email,
        from_name=item.from_name,
        subject=item.subject,
        body_preview=item.body_text[:500],
        authentication_results=item.authentication_results,
        status=item.status,
        rejection_reason=item.rejection_reason,
        processing_attempts=item.processing_attempts,
        related_ticket_id=item.related_ticket_id,
        related_request_id=item.related_request_id,
        received_at=item.received_at,
        processed_at=item.processed_at,
        attachment_count=count,
    )


@router.get("/conversations", response_model=list[ConversationResponse])
def list_email_conversations(
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationResponse]:
    require_permissions(current_user, "email.inbound.read")
    scope = _tenant_scope(current_user, tenant_id)
    statement = select(EmailConversation)
    if scope:
        statement = statement.where(EmailConversation.tenant_id == scope)
    return [
        ConversationResponse(
            id=item.id,
            channel_id=item.channel_id,
            thread_token_hint=f"…{item.thread_token[-6:]}",
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            requester_email=item.requester_email,
            normalized_subject=item.normalized_subject,
            last_message_at=item.last_message_at,
        )
        for item in db.scalars(
            statement.order_by(EmailConversation.last_message_at.desc()).limit(limit)
        ).all()
    ]


@router.get("/attachments", response_model=list[AttachmentResponse])
def list_email_attachments(
    tenant_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AttachmentResponse]:
    require_permissions(current_user, "email.attachments.read")
    scope = _tenant_scope(current_user, tenant_id)
    statement = select(EmailAttachment)
    if scope:
        statement = statement.where(EmailAttachment.tenant_id == scope)
    if status_filter:
        statement = statement.where(EmailAttachment.status == status_filter.upper())
    return [
        _attachment_response(item)
        for item in db.scalars(
            statement.order_by(EmailAttachment.created_at.desc()).limit(limit)
        ).all()
    ]


@router.post("/attachments/{attachment_id}/decision", response_model=AttachmentResponse)
def decide_email_attachment(
    attachment_id: str,
    payload: AttachmentDecision,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttachmentResponse:
    require_permissions(current_user, "email.attachments.manage")
    item = db.get(EmailAttachment, attachment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Email attachment not found")
    _tenant_scope(current_user, item.tenant_id)
    if payload.decision == "RELEASE":
        settings = get_settings()
        if not item.storage_key or item.scan_status == "INFECTED":
            raise HTTPException(
                status_code=409,
                detail="Missing or infected attachment cannot be released",
            )
        if (
            item.scan_status != "CLEAN"
            and not settings.email_attachment_manual_release_without_clean_scan
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Attachment release requires a CLEAN malware scan; "
                    "manual unscanned release is disabled"
                ),
            )
        item.status = "RELEASED"
        content_deleted = False
    else:
        item.status = "BLOCKED"
        content_deleted = delete_attachment_content(item, settings=get_settings())
    item.blocked_reason = payload.reason
    item.reviewed_by_id = current_user.id
    item.reviewed_at = utcnow()
    _audit(
        db,
        request,
        current_user,
        action=f"email_attachment_{payload.decision.lower()}",
        entity_type="email_attachment",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "reason": payload.reason,
            "scan_status": item.scan_status,
            "content_deleted": content_deleted,
        },
    )
    db.commit()
    db.refresh(item)
    return _attachment_response(item)


@router.get("/attachments/{attachment_id}/download")
def download_email_attachment(
    attachment_id: str,
    request: Request,
    download_token: str | None = Query(default=None, alias="token"),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    require_permissions(current_user, "email.attachments.read")
    item = db.get(EmailAttachment, attachment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Email attachment not found")
    _tenant_scope(current_user, item.tenant_id)
    settings = get_settings()
    if settings.app_env.strip().lower() == "production" and not download_token:
        raise HTTPException(
            status_code=403,
            detail="A short-lived signed attachment download token is required",
        )
    if download_token:
        claims = decode_token(download_token, expected_type="attachment_download")
        if (
            claims.get("sub") != current_user.id
            or claims.get("attachment_id") != item.id
            or claims.get("tenant_id") != item.tenant_id
        ):
            raise HTTPException(status_code=403, detail="Invalid attachment download scope")
    if item.status not in {"STORED", "RELEASED"}:
        raise HTTPException(status_code=409, detail="Attachment is not released")
    try:
        path = attachment_path(item, settings=settings)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment content is missing")
    actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if not item.sha256 or not secrets.compare_digest(actual_sha256, item.sha256):
        item.status = "BLOCKED"
        item.blocked_reason = "Stored attachment checksum verification failed"
        _audit(
            db,
            request,
            current_user,
            action="email_attachment_integrity_failed",
            entity_type="email_attachment",
            entity_id=item.id,
            tenant_id=item.tenant_id,
            metadata={"expected_sha256_present": bool(item.sha256)},
        )
        db.commit()
        raise HTTPException(status_code=409, detail="Attachment integrity check failed")
    item.download_count += 1
    _audit(
        db,
        request,
        current_user,
        action="email_attachment_downloaded",
        entity_type="email_attachment",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"sha256": item.sha256, "download_count": item.download_count},
    )
    db.commit()
    return FileResponse(
        path,
        media_type=item.content_type or "application/octet-stream",
        filename=item.safe_filename,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/attachments/{attachment_id}/download-token",
    response_model=AttachmentDownloadTokenResponse,
)
def create_email_attachment_download_token(
    attachment_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttachmentDownloadTokenResponse:
    require_permissions(current_user, "email.attachments.read")
    item = db.get(EmailAttachment, attachment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Email attachment not found")
    _tenant_scope(current_user, item.tenant_id)
    if item.status not in {"STORED", "RELEASED"} or not item.storage_key:
        raise HTTPException(status_code=409, detail="Attachment is not released")
    settings = get_settings()
    ttl_seconds = settings.email_attachment_download_token_ttl_seconds
    token = create_token(
        {
            "sub": current_user.id,
            "email": current_user.email,
            "tenant_id": item.tenant_id,
            "attachment_id": item.id,
        },
        expires_in_seconds=ttl_seconds,
        token_type="attachment_download",
    )
    return AttachmentDownloadTokenResponse(
        token=token,
        ttl_seconds=ttl_seconds,
        expires_at=datetime.fromtimestamp(
            int(datetime.now(UTC).timestamp()) + ttl_seconds,
            tz=UTC,
        ),
    )


@router.get("/delivery-events", response_model=list[DeliveryEventResponse])
def list_email_delivery_events(
    tenant_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DeliveryEventResponse]:
    require_permissions(current_user, "email.delivery.read")
    scope = _tenant_scope(current_user, tenant_id)
    statement = select(EmailDeliveryEvent)
    if scope:
        statement = statement.where(EmailDeliveryEvent.tenant_id == scope)
    if event_type:
        statement = statement.where(
            EmailDeliveryEvent.event_type == event_type.upper()
        )
    return [
        DeliveryEventResponse(
            id=item.id,
            email_log_id=item.email_log_id,
            event_type=item.event_type,
            reason=item.reason,
            metadata=dict(item.metadata_json or {}),
            occurred_at=item.occurred_at,
        )
        for item in db.scalars(
            statement.order_by(EmailDeliveryEvent.occurred_at.desc()).limit(limit)
        ).all()
    ]


@router.post("/outbound/{email_log_id}/retry")
def retry_outbound_email(
    email_log_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "email.delivery.manage")
    item = db.get(EmailMessageLog, email_log_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Email log entry not found")
    if item.tenant_id is None:
        raise HTTPException(status_code=409, detail="Email has no tenant context")
    _tenant_scope(current_user, item.tenant_id)
    try:
        schedule_email_retry(db, item=item)
    except EmailOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="email_outbound_retry_scheduled",
        entity_type="email_message_log",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"attempt_count": item.attempt_count},
    )
    db.commit()
    return {"id": item.id, "status": item.status, "next_retry_at": item.next_retry_at}


@webhook_router.api_route(
    "/microsoft-graph/{channel_id}",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def microsoft_graph_webhook(
    channel_id: str,
    request: Request,
    validation_token: str | None = Query(default=None, alias="validationToken"),
    db: Session = Depends(get_db),
) -> Response:
    channel = db.get(EmailChannel, channel_id)
    if (
        channel is None
        or channel.provider_type != "MICROSOFT_GRAPH"
        or channel.status != "ACTIVE"
        or not channel.inbound_enabled
    ):
        raise HTTPException(status_code=404, detail="Email webhook not found")
    if validation_token is not None:
        if len(validation_token) > 2_000:
            raise HTTPException(status_code=400, detail="Invalid validation token")
        return PlainTextResponse(validation_token, status_code=200)
    if request.method != "POST":
        raise HTTPException(status_code=405, detail="Method not allowed")
    if not channel.webhook_client_state_encrypted:
        raise HTTPException(status_code=404, detail="Email webhook not found")
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    values = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        raise HTTPException(status_code=400, detail="Invalid notification payload")
    expected_state = decrypt_credential(
        channel.webhook_client_state_encrypted,
        purpose=f"email-channel:{channel.id}:webhook-state",
        tenant_id=channel.tenant_id,
    )
    accepted: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        client_state = str(value.get("clientState") or "")
        subscription_id = str(value.get("subscriptionId") or "")
        if not secrets.compare_digest(client_state, expected_state):
            raise HTTPException(status_code=401, detail="Invalid webhook client state")
        if (
            channel.graph_subscription_id
            and subscription_id != channel.graph_subscription_id
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook subscription")
        accepted.append(value)
    persist_graph_notifications(db, channel=channel, notifications=accepted)
    db.commit()
    return Response(status_code=status.HTTP_202_ACCEPTED)
