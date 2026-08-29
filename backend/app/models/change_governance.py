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


class ChangeWindow(Base):
    __tablename__ = "change_windows"
    __table_args__ = (
        CheckConstraint(
            "window_type IN ('MAINTENANCE','BLACKOUT')",
            name="ck_change_windows_type",
        ),
        CheckConstraint(
            "ends_at > starts_at",
            name="ck_change_windows_range",
        ),
        UniqueConstraint(
            "tenant_id",
            "name",
            "starts_at",
            name="uq_change_windows_tenant_name_start",
        ),
        Index(
            "ix_change_windows_calendar",
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
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    window_type: Mapped[str] = mapped_column(String(16), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="UTC",
    )
    services_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    asset_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    environments_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    recurrence_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        nullable=True,
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


class StandardChangeModel(Base):
    __tablename__ = "standard_change_models"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_standard_change_models_tenant_code",
        ),
        Index(
            "ix_standard_change_models_active",
            "tenant_id",
            "is_active",
            "service_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    service_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    environment: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="PRODUCTION",
    )
    default_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
    )
    outage_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    outage_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    implementation_plan: Mapped[str] = mapped_column(Text, nullable=False)
    test_plan: Mapped[str] = mapped_column(Text, nullable=False)
    rollback_plan: Mapped[str] = mapped_column(Text, nullable=False)
    validation_plan: Mapped[str] = mapped_column(Text, nullable=False)
    task_templates_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    scope_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    preauthorized_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    review_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ChangeImplementationTask(Base):
    __tablename__ = "change_implementation_tasks"
    __table_args__ = (
        CheckConstraint(
            "task_type IN ('IMPLEMENTATION','VALIDATION','ROLLBACK')",
            name="ck_change_implementation_tasks_type",
        ),
        CheckConstraint(
            "status IN ('PENDING','IN_PROGRESS','COMPLETED','FAILED','SKIPPED')",
            name="ck_change_implementation_tasks_status",
        ),
        UniqueConstraint(
            "change_id",
            "task_type",
            "sequence",
            name="uq_change_implementation_tasks_sequence",
        ),
        Index(
            "ix_change_implementation_tasks_change",
            "change_id",
            "task_type",
            "sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    change_id: Mapped[str] = mapped_column(
        ForeignKey("change_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
    )
    is_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class ChangePostImplementationReview(Base):
    __tablename__ = "change_post_implementation_reviews"
    __table_args__ = (
        UniqueConstraint(
            "change_id",
            name="uq_change_post_implementation_reviews_change",
        ),
        CheckConstraint(
            "status IN ('DRAFT','SUBMITTED','APPROVED')",
            name="ck_change_post_implementation_reviews_status",
        ),
        CheckConstraint(
            "outcome IN ('SUCCESS','PARTIAL','FAILED','ROLLED_BACK')",
            name="ck_change_post_implementation_reviews_outcome",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    change_id: Mapped[str] = mapped_column(
        ForeignKey("change_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="DRAFT",
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    objectives_met: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actual_impact: Mapped[str] = mapped_column(Text, nullable=False)
    actual_outage_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    incidents_caused: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    lessons_learned: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_actions_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    prepared_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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
    approval_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class CABMeeting(Base):
    __tablename__ = "cab_meetings"
    __table_args__ = (
        CheckConstraint(
            "meeting_type IN ('CAB','ECAB')",
            name="ck_cab_meetings_type",
        ),
        CheckConstraint(
            "status IN ('DRAFT','PUBLISHED','IN_PROGRESS','COMPLETED','CANCELLED')",
            name="ck_cab_meetings_status",
        ),
        Index(
            "ix_cab_meetings_schedule",
            "tenant_id",
            "status",
            "scheduled_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="DRAFT",
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
    )
    location_or_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    chair_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    participant_user_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    minutes: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class CABAgendaItem(Base):
    __tablename__ = "cab_agenda_items"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "change_id",
            name="uq_cab_agenda_items_meeting_change",
        ),
        UniqueConstraint(
            "meeting_id",
            "sequence",
            name="uq_cab_agenda_items_meeting_sequence",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN "
            "('APPROVED','REJECTED','DEFERRED','MORE_INFO')",
            name="ck_cab_agenda_items_decision",
        ),
        Index(
            "ix_cab_agenda_items_meeting",
            "meeting_id",
            "sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("cab_meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    change_id: Mapped[str] = mapped_column(
        ForeignKey("change_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    presenter_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    decided_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
