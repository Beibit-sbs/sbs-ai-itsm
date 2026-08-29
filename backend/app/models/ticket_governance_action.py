from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TicketGovernanceAction(Base):
    """Immutable evidence for duplicate, merge, and split decisions."""

    __tablename__ = "ticket_governance_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('DUPLICATE_DISMISSED','MERGED','SPLIT')",
            name="ck_ticket_governance_actions_type",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_ticket_governance_actions_score",
        ),
        UniqueConstraint(
            "tenant_id",
            "action_type",
            "idempotency_key",
            name="uq_ticket_governance_action_idempotency",
        ),
        Index("ix_ticket_governance_actions_tenant_source", "tenant_id", "source_ticket_id"),
        Index("ix_ticket_governance_actions_tenant_target", "tenant_id", "target_ticket_id"),
        Index("ix_ticket_governance_actions_pair", "tenant_id", "pair_key", "action_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=False
    )
    target_ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    pair_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
