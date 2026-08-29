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


class ProblemRCA(Base):
    __tablename__ = "problem_rcas"
    __table_args__ = (
        CheckConstraint(
            "method IN ('FIVE_WHYS','ISHIKAWA','FAULT_TREE','CUSTOM')",
            name="ck_problem_rcas_method",
        ),
        CheckConstraint(
            "status IN ('DRAFT','SUBMITTED','APPROVED','REJECTED')",
            name="ck_problem_rcas_status",
        ),
        UniqueConstraint("problem_id", name="uq_problem_rcas_problem"),
        Index("ix_problem_rcas_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[str] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    problem_statement: Mapped[str] = mapped_column(Text, nullable=False)
    five_whys_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    ishikawa_json: Mapped[dict[str, list[str]]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    fault_tree_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    contributing_factors_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    evidence_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    prepared_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    prepared_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approval_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProblemCorrectiveAction(Base):
    __tablename__ = "problem_corrective_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('CORRECTIVE','PREVENTIVE','DETECTION')",
            name="ck_problem_corrective_actions_type",
        ),
        CheckConstraint(
            "status IN ('OPEN','IN_PROGRESS','IMPLEMENTED','VERIFIED','INEFFECTIVE','CANCELLED')",
            name="ck_problem_corrective_actions_status",
        ),
        Index(
            "ix_problem_corrective_actions_due",
            "tenant_id",
            "status",
            "due_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[str] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    owner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effectiveness_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    implementation_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    implemented_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effectiveness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effectiveness_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProblemTrendSignal(Base):
    __tablename__ = "problem_trend_signals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','ACKNOWLEDGED','CONVERTED','DISMISSED')",
            name="ck_problem_trend_signals_status",
        ),
        CheckConstraint(
            "signal_type IN ('RECURRENCE','VOLUME_SPIKE','SLA_DEGRADATION')",
            name="ck_problem_trend_signals_type",
        ),
        UniqueConstraint(
            "tenant_id", "signature", name="uq_problem_trend_signals_signature"
        ),
        Index("ix_problem_trend_signals_queue", "tenant_id", "status", "score"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(24), nullable=False)
    signature: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    service_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    window_start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    baseline_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_count: Mapped[int] = mapped_column(Integer, nullable=False)
    growth_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    incident_ids_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    problem_id: Mapped[str | None] = mapped_column(
        ForeignKey("problems.id", ondelete="SET NULL"), nullable=True
    )
    disposition_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    disposition_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    disposition_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    disposition_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class KnownErrorUsage(Base):
    __tablename__ = "known_error_usage"
    __table_args__ = (
        CheckConstraint(
            "usage_type IN ('VIEWED','APPLIED','HELPFUL','NOT_HELPFUL')",
            name="ck_known_error_usage_type",
        ),
        Index("ix_known_error_usage_problem", "problem_id", "created_at"),
        Index("ix_known_error_usage_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[str] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True
    )
    usage_type: Mapped[str] = mapped_column(String(20), nullable=False)
    minutes_saved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avoided_escalation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
