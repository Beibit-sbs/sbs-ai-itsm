from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EmailChannel(Base):
    __tablename__ = "email_channels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_email_channels_tenant_name"),
        UniqueConstraint(
            "tenant_id",
            "mailbox_address",
            name="uq_email_channels_tenant_mailbox",
        ),
        CheckConstraint(
            "provider_type IN ('MICROSOFT_GRAPH','MOCK')",
            name="ck_email_channels_provider",
        ),
        CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','ERROR','REVOKED')",
            name="ck_email_channels_status",
        ),
        CheckConstraint(
            "default_target IN ('TICKET','REQUEST')",
            name="ck_email_channels_default_target",
        ),
        Index("ix_email_channels_tenant_status", "tenant_id", "status"),
        Index(
            "ix_email_channels_subscription",
            "graph_subscription_id",
            "graph_subscription_expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="MICROSOFT_GRAPH"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    mailbox_address: Mapped[str] = mapped_column(String(255), nullable=False)
    mailbox_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entra_tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    inbound_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    outbound_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    default_target: Mapped[str] = mapped_column(
        String(16), nullable=False, default="TICKET"
    )
    allowed_sender_domains_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    allowed_attachment_extensions_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    max_attachment_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10 * 1024 * 1024
    )
    graph_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    graph_subscription_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    webhook_client_state_encrypted: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    delta_link_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    loop_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EmailConversation(Base):
    __tablename__ = "email_conversations"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "thread_token",
            name="uq_email_conversations_channel_token",
        ),
        UniqueConstraint(
            "channel_id",
            "provider_conversation_id",
            name="uq_email_conversations_provider_thread",
        ),
        CheckConstraint(
            "entity_type IN ('TICKET','REQUEST')",
            name="ck_email_conversations_entity_type",
        ),
        Index("ix_email_conversations_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_email_conversations_last_message", "tenant_id", "last_message_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("email_channels.id", ondelete="CASCADE"), nullable=False
    )
    thread_token: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_conversation_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    root_internet_message_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    related_ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True
    )
    related_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=True
    )
    requester_email: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    last_provider_message_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EmailInboundMessage(Base):
    __tablename__ = "email_inbound_messages"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "provider_message_id",
            name="uq_email_inbound_channel_message",
        ),
        CheckConstraint(
            "status IN "
            "('RECEIVED','PROCESSED','REJECTED','QUARANTINED','DUPLICATE','LOOP','FAILED','DEAD_LETTER')",
            name="ck_email_inbound_status",
        ),
        Index(
            "ix_email_inbound_tenant_status",
            "tenant_id",
            "status",
            "received_at",
        ),
        Index(
            "ix_email_inbound_retry",
            "status",
            "next_retry_at",
        ),
        Index("ix_email_inbound_internet_id", "internet_message_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("email_channels.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("email_conversations.id", ondelete="SET NULL"), nullable=True
    )
    provider_message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    provider_conversation_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    internet_message_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    in_reply_to: Mapped[str | None] = mapped_column(String(512), nullable=True)
    references_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    from_email: Mapped[str] = mapped_column(String(255), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipients_json: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html_sanitized: Mapped[str | None] = mapped_column(Text, nullable=True)
    headers_json: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    authentication_results: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="RECEIVED"
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    related_ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True
    )
    related_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_requests.id", ondelete="SET NULL"), nullable=True
    )
    ticket_comment_id: Mapped[str | None] = mapped_column(
        ForeignKey("ticket_comments.id", ondelete="SET NULL"), nullable=True
    )
    request_activity_id: Mapped[str | None] = mapped_column(
        ForeignKey("request_activities.id", ondelete="SET NULL"), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EmailAttachment(Base):
    __tablename__ = "email_attachments"
    __table_args__ = (
        UniqueConstraint(
            "inbound_message_id",
            "provider_attachment_id",
            name="uq_email_attachments_message_provider",
        ),
        CheckConstraint(
            "scan_status IN ('NOT_REQUIRED','PENDING','CLEAN','INFECTED','ERROR')",
            name="ck_email_attachments_scan_status",
        ),
        CheckConstraint(
            "status IN ('STORED','QUARANTINED','BLOCKED','RELEASED')",
            name="ck_email_attachments_status",
        ),
        Index("ix_email_attachments_tenant_status", "tenant_id", "status"),
        Index("ix_email_attachments_sha256", "sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    inbound_message_id: Mapped[str] = mapped_column(
        ForeignKey("email_inbound_messages.id", ondelete="CASCADE"), nullable=False
    )
    provider_attachment_id: Mapped[str] = mapped_column(
        String(512), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    detected_content_type: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_inline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="QUARANTINED"
    )
    scan_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    security_findings_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    sanitization_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    download_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    reviewed_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailDeliveryEvent(Base):
    __tablename__ = "email_delivery_events"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "provider_event_id",
            name="uq_email_delivery_channel_event",
        ),
        CheckConstraint(
            "event_type IN ('QUEUED','SIMULATED','ACCEPTED','DELIVERED','DELAYED','BOUNCED','COMPLAINT','FAILED')",
            name="ck_email_delivery_event_type",
        ),
        Index("ix_email_delivery_log_occurred", "email_log_id", "occurred_at"),
        Index("ix_email_delivery_tenant_event", "tenant_id", "event_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("email_channels.id", ondelete="CASCADE"), nullable=False
    )
    email_log_id: Mapped[str] = mapped_column(
        ForeignKey("email_message_logs.id", ondelete="CASCADE"), nullable=False
    )
    provider_event_id: Mapped[str] = mapped_column(String(512), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailWebhookEvent(Base):
    __tablename__ = "email_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "provider_event_id",
            name="uq_email_webhook_channel_event",
        ),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','PROCESSED','FAILED','DEAD_LETTER')",
            name="ck_email_webhook_status",
        ),
        Index("ix_email_webhook_due", "status", "next_retry_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("email_channels.id", ondelete="CASCADE"), nullable=False
    )
    provider_event_id: Mapped[str] = mapped_column(String(512), nullable=False)
    subscription_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    resource: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    change_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
