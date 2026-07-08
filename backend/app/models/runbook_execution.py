from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RunbookExecution(Base):
    __tablename__ = "runbook_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    runbook_id: Mapped[str] = mapped_column(ForeignKey("runbooks.id", ondelete="CASCADE"), nullable=False)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    runbook: Mapped["Runbook"] = relationship(back_populates="executions")
