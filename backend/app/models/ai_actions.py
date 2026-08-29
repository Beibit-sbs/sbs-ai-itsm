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


class AiActionPolicy(Base):
    __tablename__ = "ai_action_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_ai_action_policies_tenant"),
        CheckConstraint(
            "proposal_ttl_minutes >= 5 AND proposal_ttl_minutes <= 10080",
            name="ck_ai_action_policies_ttl",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allowed_actions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    independent_approval_for_high_risk: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    proposal_ttl_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1_440
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AiActionProposal(Base):
    __tablename__ = "ai_action_proposals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_ai_action_proposals_idempotency"
        ),
        CheckConstraint(
            "action_type IN ('ticket.update','ticket.classify','knowledge.draft','runbook.draft')",
            name="ck_ai_action_proposals_type",
        ),
        CheckConstraint(
            "risk_level IN ('LOW','MEDIUM','HIGH')",
            name="ck_ai_action_proposals_risk",
        ),
        CheckConstraint(
            "status IN ('PROPOSED','APPROVED','REJECTED','EXECUTED','FAILED','ROLLED_BACK','EXPIRED')",
            name="ck_ai_action_proposals_status",
        ),
        Index("ix_ai_action_proposals_tenant_status", "tenant_id", "status"),
        Index("ix_ai_action_proposals_target", "target_type", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    proposal_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_query_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    citation_evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PROPOSED")
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AiActionExecution(Base):
    __tablename__ = "ai_action_executions"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_ai_action_executions_proposal"),
        CheckConstraint(
            "status IN ('SUCCEEDED','FAILED','ROLLED_BACK')",
            name="ck_ai_action_executions_status",
        ),
        Index("ix_ai_action_executions_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("ai_action_proposals.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    before_state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    before_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    after_state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    after_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rolled_back_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
