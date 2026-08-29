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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventSource(Base):
    __tablename__ = "event_sources"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_event_sources_tenant_code",
        ),
        CheckConstraint(
            "source_type IN ('ALERTMANAGER','PROMETHEUS','ZABBIX','SENTRY',"
            "'GRAFANA','GENERIC')",
            name="ck_event_sources_type",
        ),
        CheckConstraint(
            "auth_mode IN ('BEARER','HMAC_SHA256')",
            name="ck_event_sources_auth_mode",
        ),
        Index("ix_event_sources_tenant_enabled", "tenant_id", "is_enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hint: Mapped[str] = mapped_column(String(16), nullable=False)
    auth_mode: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="BEARER",
    )
    hmac_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    hmac_secret_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    replay_window_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=300,
    )
    rate_limit_per_minute: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=120,
    )
    max_payload_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1_048_576,
    )
    allowed_ip_cidrs_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    total_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suppressed_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dead_letter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
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


class MonitoringWebhookReceipt(Base):
    __tablename__ = "monitoring_webhook_receipts"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "request_key",
            name="uq_monitoring_receipts_source_request",
        ),
        CheckConstraint(
            "status IN ('RECEIVED','PROCESSING','PROCESSED','DUPLICATE',"
            "'RETRY','FAILED','DEAD_LETTER','REJECTED')",
            name="ck_monitoring_receipts_status",
        ),
        Index(
            "ix_monitoring_receipts_queue",
            "status",
            "next_attempt_at",
            "received_at",
        ),
        Index(
            "ix_monitoring_receipts_source_received",
            "source_id",
            "received_at",
        ),
        Index(
            "ix_monitoring_receipts_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("event_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    payload_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signature_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    request_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    safe_headers_json: Mapped[dict[str, str]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="RECEIVED",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    normalized_event_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    duplicate_event_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    incident_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
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


class EventCorrelationPolicy(Base):
    __tablename__ = "event_correlation_policies"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_event_correlation_policies_tenant_name",
        ),
        CheckConstraint(
            "incident_mode IN ('CREATE_UPDATE','CORRELATE_ONLY','IGNORE')",
            name="ck_event_correlation_policies_incident_mode",
        ),
        CheckConstraint(
            "resolution_action IN ('NONE','RESOLVE','CLOSE')",
            name="ck_event_correlation_policies_resolution_action",
        ),
        CheckConstraint(
            "fixed_priority IS NULL OR fixed_priority IN "
            "('CRITICAL','HIGH','MEDIUM','LOW','P1','P2','P3','P4')",
            name="ck_event_correlation_policies_priority",
        ),
        CheckConstraint(
            "min_occurrences >= 1 AND min_occurrences <= 1000",
            name="ck_event_correlation_policies_occurrences",
        ),
        CheckConstraint(
            "correlation_window_minutes >= 1 "
            "AND correlation_window_minutes <= 10080",
            name="ck_event_correlation_policies_window",
        ),
        Index(
            "ix_event_correlation_policies_order",
            "tenant_id",
            "is_active",
            "priority_order",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    matchers_json: Mapped[list[dict[str, str]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    group_by_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    correlation_window_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
    )
    min_occurrences: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    incident_mode: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="CREATE_UPDATE",
    )
    fixed_priority: Mapped[str | None] = mapped_column(String(8), nullable=True)
    category: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="Infrastructure",
    )
    title_template: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="Monitoring: {summary}",
    )
    resolution_action: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="RESOLVE",
    )
    primary_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    fallback_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    acknowledge_within_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=15,
    )
    escalate_after_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=15,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
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


class EventSuppressionRule(Base):
    __tablename__ = "event_suppression_rules"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_event_suppression_rules_tenant_name",
        ),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at",
            name="ck_event_suppression_rules_window",
        ),
        Index(
            "ix_event_suppression_rules_active",
            "tenant_id",
            "is_active",
            "starts_at",
            "ends_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    matchers_json: Mapped[list[dict[str, str]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
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


class NormalizedEvent(Base):
    __tablename__ = "normalized_events"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "event_key",
            name="uq_normalized_events_source_key",
        ),
        CheckConstraint(
            "state IN ('FIRING','RESOLVED')",
            name="ck_normalized_events_state",
        ),
        CheckConstraint(
            "severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_normalized_events_severity",
        ),
        CheckConstraint(
            "disposition IN ('SUPPRESSED','IGNORED','CORRELATED',"
            "'INCIDENT_CREATED','INCIDENT_UPDATED','RESOLVED')",
            name="ck_normalized_events_disposition",
        ),
        Index(
            "ix_normalized_events_tenant_received",
            "tenant_id",
            "received_at",
        ),
        Index(
            "ix_normalized_events_group",
            "correlation_group_id",
            "occurred_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("event_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    service: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resource: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(80), nullable=True)
    labels_json: Mapped[dict[str, str]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    annotations_json: Mapped[dict[str, str]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    raw_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    disposition: Mapped[str] = mapped_column(String(24), nullable=False)
    suppression_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("event_suppression_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    correlation_policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("event_correlation_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    correlation_group_id: Mapped[str | None] = mapped_column(
        ForeignKey("event_correlation_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
    )


class EventCorrelationGroup(Base):
    __tablename__ = "event_correlation_groups"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','RESOLVED')",
            name="ck_event_correlation_groups_status",
        ),
        CheckConstraint(
            "severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_event_correlation_groups_severity",
        ),
        Index(
            "uq_event_correlation_groups_open",
            "tenant_id",
            "policy_id",
            "correlation_key",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
        Index(
            "ix_event_correlation_groups_queue",
            "tenant_id",
            "status",
            "severity",
            "last_event_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("event_correlation_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    correlation_key: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    first_event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    acknowledged_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_escalation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    escalation_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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


class EventGroupActivity(Base):
    __tablename__ = "event_group_activities"
    __table_args__ = (
        Index(
            "ix_event_group_activities_timeline",
            "correlation_group_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    correlation_group_id: Mapped[str] = mapped_column(
        ForeignKey("event_correlation_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[str | None] = mapped_column(
        ForeignKey("normalized_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    activity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
