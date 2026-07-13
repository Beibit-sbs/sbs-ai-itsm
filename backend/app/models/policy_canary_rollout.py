"""Policy canary rollout tracking model."""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PolicyCanaryRollout(Base):
    """Tracks canary rollout progress for policy changes."""

    __tablename__ = "policy_canary_rollouts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # crl-{16 hex chars}
    approval_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "autoremediation", "runbook"
    current_canary_percentage: Mapped[int] = mapped_column(nullable=False)  # 5, 25, 50, 100
    affected_consumers_count: Mapped[int] = mapped_column(default=0, nullable=False)
    metrics_baseline_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # Metrics snapshot at canary start
    metrics_current_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # Latest metrics during rollout
    status: Mapped[str] = mapped_column(String(32), default="in_progress", nullable=False)  # "in_progress", "completed", "rolled_back"
    error_rate_baseline: Mapped[float | None] = mapped_column(nullable=True)  # Baseline error rate (%)
    error_rate_current: Mapped[float | None] = mapped_column(nullable=True)  # Current error rate (%)
    auto_rollback_triggered: Mapped[bool] = mapped_column(default=False, nullable=False)
    auto_rollback_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
