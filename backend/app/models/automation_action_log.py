from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AutomationActionLog(Base):
    __tablename__ = "automation_action_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    automation_run_id: Mapped[str] = mapped_column(ForeignKey("automation_runs.id", ondelete="CASCADE"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    automation_run: Mapped["AutomationRun"] = relationship(back_populates="action_logs")
