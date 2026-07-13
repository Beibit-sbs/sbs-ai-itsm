"""Policy approval request model for staged policy rollout."""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PolicyApprovalRequest(Base):
    """Tracks approval requests for policy changes with state machine."""

    __tablename__ = "policy_approval_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "autoremediation", "runbook"
    requested_by_email: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    current_version: Mapped[int] = mapped_column(nullable=False)
    requested_version: Mapped[int] = mapped_column(nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)  # Full proposed payload
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)  # pending, approved, rejected, rolled_out
    approved_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    canary_percentage: Mapped[int] = mapped_column(default=0, nullable=False)  # 0=pending, 5-100=canary active
    metrics_baseline_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # Snapshot at canary start
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
