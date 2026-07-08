from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(80), nullable=False)
    conditions_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    actions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    runs: Mapped[list["AutomationRun"]] = relationship(back_populates="rule")
