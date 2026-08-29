from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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


class MajorIncident(Base):
    __tablename__ = "major_incidents"
    __table_args__ = (
        UniqueConstraint("ticket_id", name="uq_major_incidents_ticket"),
        UniqueConstraint(
            "tenant_id",
            "major_number",
            name="uq_major_incidents_tenant_number",
        ),
        CheckConstraint(
            "severity IN ('SEV1','SEV2')",
            name="ck_major_incidents_severity",
        ),
        CheckConstraint(
            "status IN ('DECLARED','MITIGATING','MONITORING','RESOLVED',"
            "'CLOSED','CANCELLED')",
            name="ck_major_incidents_status",
        ),
        CheckConstraint(
            "service_status IN ('MAJOR_OUTAGE','PARTIAL_OUTAGE','DEGRADED',"
            "'OPERATIONAL','UNKNOWN')",
            name="ck_major_incidents_service_status",
        ),
        Index(
            "ix_major_incidents_tenant_status",
            "tenant_id",
            "status",
            "declared_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    major_number: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    impact_statement: Mapped[str] = mapped_column(Text, nullable=False)
    affected_service: Mapped[str] = mapped_column(String(200), nullable=False)
    service_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="MAJOR_OUTAGE",
    )
    customer_impact: Mapped[str] = mapped_column(Text, nullable=False)
    war_room_url: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    conference_details: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    commander_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    communications_lead_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    declared_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    declared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    next_update_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
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


class MajorIncidentParticipant(Base):
    __tablename__ = "major_incident_participants"
    __table_args__ = (
        CheckConstraint(
            "role IN ('TECHNICAL_LEAD','SME','SCRIBE','STAKEHOLDER')",
            name="ck_major_incident_participants_role",
        ),
        Index(
            "ix_major_incident_participants_incident",
            "major_incident_id",
            "role",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    major_incident_id: Mapped[str] = mapped_column(
        ForeignKey("major_incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    added_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class MajorIncidentChildTicket(Base):
    __tablename__ = "major_incident_child_tickets"
    __table_args__ = (
        UniqueConstraint(
            "major_incident_id",
            "ticket_id",
            name="uq_major_incident_child_ticket",
        ),
        UniqueConstraint(
            "ticket_id",
            name="uq_major_incident_child_one_parent",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    major_incident_id: Mapped[str] = mapped_column(
        ForeignKey("major_incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    linked_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class MajorIncidentUpdate(Base):
    __tablename__ = "major_incident_updates"
    __table_args__ = (
        CheckConstraint(
            "update_type IN ('STATUS_UPDATE','STAKEHOLDER_COMMUNICATION',"
            "'TECHNICAL_EVENT','DECISION','MILESTONE')",
            name="ck_major_incident_updates_type",
        ),
        CheckConstraint(
            "audience IN ('INTERNAL','STAKEHOLDERS','PUBLIC')",
            name="ck_major_incident_updates_audience",
        ),
        CheckConstraint(
            "service_status IS NULL OR service_status IN "
            "('MAJOR_OUTAGE','PARTIAL_OUTAGE','DEGRADED','OPERATIONAL','UNKNOWN')",
            name="ck_major_incident_updates_service_status",
        ),
        Index(
            "ix_major_incident_updates_timeline",
            "major_incident_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    major_incident_id: Mapped[str] = mapped_column(
        ForeignKey("major_incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    update_type: Mapped[str] = mapped_column(String(40), nullable=False)
    audience: Mapped[str] = mapped_column(String(24), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    service_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    channel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class MajorIncidentPIR(Base):
    __tablename__ = "major_incident_pirs"
    __table_args__ = (
        UniqueConstraint(
            "major_incident_id",
            name="uq_major_incident_pirs_incident",
        ),
        CheckConstraint(
            "status IN ('DRAFT','APPROVED')",
            name="ck_major_incident_pirs_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    major_incident_id: Mapped[str] = mapped_column(
        ForeignKey("major_incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    contributing_factors: Mapped[str] = mapped_column(Text, nullable=False)
    lessons_learned: Mapped[str] = mapped_column(Text, nullable=False)
    prevention_plan: Mapped[str] = mapped_column(Text, nullable=False)
    prepared_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
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


class MajorIncidentAction(Base):
    __tablename__ = "major_incident_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','IN_PROGRESS','DONE','CANCELLED')",
            name="ck_major_incident_actions_status",
        ),
        Index(
            "ix_major_incident_actions_queue",
            "tenant_id",
            "status",
            "due_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    major_incident_id: Mapped[str] = mapped_column(
        ForeignKey("major_incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="OPEN",
    )
    completion_evidence: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
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
