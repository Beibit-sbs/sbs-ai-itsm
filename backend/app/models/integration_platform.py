from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IntegrationServiceAccount(Base):
    __tablename__ = "integration_service_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_integration_service_accounts_tenant_name",
        ),
        UniqueConstraint(
            "client_id",
            name="uq_integration_service_accounts_client_id",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','SUSPENDED','REVOKED')",
            name="ck_integration_service_accounts_status",
        ),
        CheckConstraint(
            "rate_limit_per_minute >= 1 AND rate_limit_per_minute <= 10000",
            name="ck_integration_service_accounts_rate_limit",
        ),
        CheckConstraint(
            "max_token_ttl_days >= 1 AND max_token_ttl_days <= 365",
            name="ck_integration_service_accounts_ttl",
        ),
        Index(
            "ix_integration_service_accounts_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ACTIVE",
    )
    allowed_scopes_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    allowed_ip_cidrs_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    rate_limit_per_minute: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=120,
    )
    max_token_ttl_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=90,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_requests: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    failed_auth_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IntegrationApiToken(Base):
    __tablename__ = "integration_api_tokens"
    __table_args__ = (
        UniqueConstraint(
            "token_prefix",
            name="uq_integration_api_tokens_prefix",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','REVOKED','EXPIRED')",
            name="ck_integration_api_tokens_status",
        ),
        Index(
            "ix_integration_api_tokens_account_status",
            "service_account_id",
            "status",
        ),
        Index(
            "ix_integration_api_tokens_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    service_account_id: Mapped[str] = mapped_column(
        ForeignKey("integration_service_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hint: Mapped[str] = mapped_column(String(32), nullable=False)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ACTIVE",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rate_window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rate_window_requests: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    issued_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    replaced_by_token_id: Mapped[str | None] = mapped_column(
        ForeignKey("integration_api_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IntegrationApiRequestLog(Base):
    __tablename__ = "integration_api_request_logs"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('ALLOWED','DENIED')",
            name="ck_integration_api_request_logs_outcome",
        ),
        Index(
            "ix_integration_api_request_logs_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_integration_api_request_logs_account_created",
            "service_account_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    service_account_id: Mapped[str] = mapped_column(
        ForeignKey("integration_service_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_id: Mapped[str | None] = mapped_column(
        ForeignKey("integration_api_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    required_scope: Mapped[str | None] = mapped_column(String(120), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class OutboundWebhookSubscription(Base):
    __tablename__ = "outbound_webhook_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_outbound_webhook_subscriptions_tenant_name",
        ),
        CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','REVOKED')",
            name="ck_outbound_webhook_subscriptions_status",
        ),
        CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 60",
            name="ck_outbound_webhook_subscriptions_timeout",
        ),
        CheckConstraint(
            "max_attempts >= 1 AND max_attempts <= 20",
            name="ck_outbound_webhook_subscriptions_attempts",
        ),
        Index(
            "ix_outbound_webhook_subscriptions_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="DRAFT",
    )
    event_types_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    target_url_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_hint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    signing_secret_encrypted: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    signing_secret_hint: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    signing_secret_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    last_tested_target_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    last_tested_secret_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=15,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=6,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    success_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    failure_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    dead_letter_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OutboundWebhookDelivery(Base):
    __tablename__ = "outbound_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "idempotency_key",
            name="uq_outbound_webhook_deliveries_subscription_key",
        ),
        CheckConstraint(
            "status IN ("
            "'PENDING','PROCESSING','RETRY','SUCCEEDED','FAILED',"
            "'DEAD_LETTER','CANCELLED'"
            ")",
            name="ck_outbound_webhook_deliveries_status",
        ),
        Index(
            "ix_outbound_webhook_deliveries_queue",
            "status",
            "next_attempt_at",
            "created_at",
        ),
        Index(
            "ix_outbound_webhook_deliveries_subscription_created",
            "subscription_id",
            "created_at",
        ),
        Index(
            "ix_outbound_webhook_deliveries_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("outbound_webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    replay_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("outbound_webhook_deliveries.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    is_test: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_version_used: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    signing_secret_version_used: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    provider_request_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
