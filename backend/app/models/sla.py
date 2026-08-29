from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SlaBusinessCalendar(Base):
    __tablename__ = "sla_business_calendars"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_sla_business_calendars_tenant_name",
        ),
        Index(
            "ix_sla_business_calendars_tenant_active",
            "tenant_id",
            "is_active",
            "is_default",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="UTC",
    )
    weekly_hours_json: Mapped[dict[str, list[list[str]]]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
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


class SlaCalendarException(Base):
    __tablename__ = "sla_calendar_exceptions"
    __table_args__ = (
        UniqueConstraint(
            "calendar_id",
            "exception_date",
            name="uq_sla_calendar_exceptions_calendar_date",
        ),
        CheckConstraint(
            "kind IN ('HOLIDAY','WORKING_DAY')",
            name="ck_sla_calendar_exceptions_kind",
        ),
        Index(
            "ix_sla_calendar_exceptions_lookup",
            "calendar_id",
            "exception_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    calendar_id: Mapped[str] = mapped_column(
        ForeignKey("sla_business_calendars.id", ondelete="CASCADE"),
        nullable=False,
    )
    exception_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    intervals_json: Mapped[list[list[str]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class SlaPolicy(Base):
    __tablename__ = "sla_policies"
    __table_args__ = (
        CheckConstraint(
            "warning_percent >= 1 AND warning_percent <= 100",
            name="ck_sla_policies_warning_percent",
        ),
        Index(
            "ix_sla_policies_match",
            "tenant_id",
            "is_active",
            "priority",
            "priority_order",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False)
    target_response_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    target_resolution_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    response_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_minutes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    is_active: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        default=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
    )
    breach_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    calendar_id: Mapped[str | None] = mapped_column(
        ForeignKey("sla_business_calendars.id", ondelete="SET NULL"),
        nullable=True,
    )
    priority_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
    )
    scope_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    targets_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    pause_statuses_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: ["WAITING_USER", "WAITING_VENDOR"],
    )
    pause_reasons_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: ["WAITING_CUSTOMER", "WAITING_VENDOR", "APPROVED_HOLD"],
    )
    warning_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=80,
    )
    escalations_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
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

    tenant: Mapped["Tenant | None"] = relationship()
    calendar: Mapped["SlaBusinessCalendar | None"] = relationship()


class TicketSlaInstance(Base):
    __tablename__ = "ticket_sla_instances"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','PAUSED','COMPLETED','BREACHED','CANCELLED')",
            name="ck_ticket_sla_instances_status",
        ),
        Index(
            "uq_ticket_sla_instances_current",
            "ticket_id",
            unique=True,
            postgresql_where=text("is_current = true"),
            sqlite_where=text("is_current = 1"),
        ),
        Index(
            "ix_ticket_sla_instances_queue",
            "tenant_id",
            "is_current",
            "status",
            "last_evaluated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("sla_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    calendar_id: Mapped[str | None] = mapped_column(
        ForeignKey("sla_business_calendars.id", ondelete="SET NULL"),
        nullable=True,
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_snapshot_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    calendar_snapshot_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ACTIVE",
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    total_paused_business_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
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


class TicketSlaTarget(Base):
    __tablename__ = "ticket_sla_targets"
    __table_args__ = (
        UniqueConstraint(
            "instance_id",
            "target_type",
            "owner_ref",
            name="uq_ticket_sla_targets_instance_type_owner",
        ),
        CheckConstraint(
            "target_type IN ('RESPONSE','RESOLUTION','FULFILLMENT','OLA','SUPPLIER')",
            name="ck_ticket_sla_targets_type",
        ),
        CheckConstraint(
            "status IN ('PENDING','WARNING','MET','BREACHED','CANCELLED')",
            name="ck_ticket_sla_targets_status",
        ),
        Index(
            "ix_ticket_sla_targets_forecast",
            "tenant_id",
            "status",
            "warning_at",
            "due_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    instance_id: Mapped[str] = mapped_column(
        ForeignKey("ticket_sla_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    warning_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PENDING",
    )
    owner_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    met_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    escalation_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_escalated_at: Mapped[datetime | None] = mapped_column(
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


class TicketSlaPause(Base):
    __tablename__ = "ticket_sla_pauses"
    __table_args__ = (
        Index(
            "ix_ticket_sla_pauses_instance",
            "instance_id",
            "started_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    instance_id: Mapped[str] = mapped_column(
        ForeignKey("ticket_sla_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    business_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    ended_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    start_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    end_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class TicketSlaTimeline(Base):
    __tablename__ = "ticket_sla_timeline"
    __table_args__ = (
        Index(
            "ix_ticket_sla_timeline_instance_created",
            "instance_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    instance_id: Mapped[str] = mapped_column(
        ForeignKey("ticket_sla_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[str | None] = mapped_column(
        ForeignKey("ticket_sla_targets.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
