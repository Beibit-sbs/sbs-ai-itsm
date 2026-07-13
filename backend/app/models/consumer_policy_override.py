"""Consumer-specific policy overrides for targeted tuning."""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConsumerPolicyOverride(Base):
    """Stores per-consumer policy overrides (exceptions to global policy)."""

    __tablename__ = "consumer_policy_overrides"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    consumer_name: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "autoremediation", "runbook"
    policy_version: Mapped[int] = mapped_column(nullable=False)  # Global version this override applies to
    overrides_json: Mapped[str] = mapped_column(Text, nullable=False)  # Partial policy overrides (merged with global)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)  # Why this override exists
    created_by_email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
