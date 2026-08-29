from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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


class TeamsConnector(Base):
    __tablename__ = "teams_connectors"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_teams_connectors_tenant_name",
        ),
        CheckConstraint(
            "provider_type IN ('WORKFLOW_WEBHOOK','MOCK')",
            name="ck_teams_connectors_provider",
        ),
        CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','ERROR','REVOKED')",
            name="ck_teams_connectors_status",
        ),
        CheckConstraint(
            "purpose IN ('DEFAULT','APPROVALS','MAJOR_INCIDENT','SECURITY')",
            name="ck_teams_connectors_purpose",
        ),
        CheckConstraint(
            "minimum_severity IN ('INFO','WARNING','CRITICAL')",
            name="ck_teams_connectors_severity",
        ),
        Index("ix_teams_connectors_tenant_status", "tenant_id", "status"),
        Index("ix_teams_connectors_tenant_purpose", "tenant_id", "purpose"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="WORKFLOW_WEBHOOK",
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    purpose: Mapped[str] = mapped_column(String(24), nullable=False, default="DEFAULT")
    webhook_url_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    team_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    channel_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    channel_url: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    event_types_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    minimum_severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="INFO",
    )
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
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class TeamsDelivery(Base):
    __tablename__ = "teams_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "connector_id",
            "idempotency_key",
            name="uq_teams_deliveries_connector_idempotency",
        ),
        CheckConstraint(
            "status IN ('QUEUED','RETRY','SIMULATED','SENT','FAILED','DEAD_LETTER','CANCELLED')",
            name="ck_teams_deliveries_status",
        ),
        CheckConstraint(
            "severity IN ('INFO','WARNING','CRITICAL')",
            name="ck_teams_deliveries_severity",
        ),
        Index(
            "ix_teams_deliveries_queue",
            "status",
            "next_attempt_at",
            "created_at",
        ),
        Index(
            "ix_teams_deliveries_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_teams_deliveries_entity",
            "tenant_id",
            "entity_type",
            "entity_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    connector_id: Mapped[str] = mapped_column(
        ForeignKey("teams_connectors.id", ondelete="CASCADE"),
        nullable=False,
    )
    notification_id: Mapped[str | None] = mapped_column(
        ForeignKey("notifications.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    action_url: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    payload_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="QUEUED",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    provider_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class TeamsMajorIncidentRoom(Base):
    __tablename__ = "teams_major_incident_rooms"
    __table_args__ = (
        UniqueConstraint(
            "major_incident_id",
            name="uq_teams_major_incident_rooms_incident",
        ),
        CheckConstraint(
            "status IN ('OPEN','CLOSED')",
            name="ck_teams_major_incident_rooms_status",
        ),
        Index(
            "ix_teams_major_incident_rooms_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    connector_id: Mapped[str] = mapped_column(
        ForeignKey("teams_connectors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    major_incident_id: Mapped[str] = mapped_column(
        ForeignKey("major_incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    channel_url: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    opened_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    closed_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
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
