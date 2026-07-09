from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=False)
    runbook_id: Mapped[str | None] = mapped_column(ForeignKey("runbooks.id", ondelete="SET NULL"), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(80), nullable=False)
    trigger_entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    trigger_entity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    input_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approval_request_id: Mapped[str | None] = mapped_column(ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    rule: Mapped["AutomationRule"] = relationship(back_populates="runs")
    action_logs: Mapped[list["AutomationActionLog"]] = relationship(
        back_populates="automation_run",
        foreign_keys="AutomationActionLog.automation_run_id",
    )
