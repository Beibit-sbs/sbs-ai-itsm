from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "creation_channel IN ('SELF_SERVICE','ON_BEHALF','LEGACY')",
            name="ck_tickets_creation_channel",
        ),
        CheckConstraint("governance_version >= 1", name="ck_tickets_governance_version"),
        CheckConstraint("merged_into_id IS NULL OR merged_into_id <> id", name="ck_tickets_not_merged_into_self"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    ticket_number: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    requester_email: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requester_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    sla_policy_id: Mapped[str | None] = mapped_column(ForeignKey("sla_policies.id", ondelete="SET NULL"), nullable=True)
    requester_name: Mapped[str] = mapped_column(String(200), nullable=False)
    requester_contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    creation_channel: Mapped[str] = mapped_column(String(24), nullable=False, default="LEGACY")
    on_behalf_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True
    )
    merged_into_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=True
    )
    governance_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    merge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    merged_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    merged_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    satisfaction_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    tenant: Mapped["Tenant | None"] = relationship()
    requester: Mapped["User | None"] = relationship(foreign_keys=[requester_id])
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assignee_id])
    asset: Mapped["Asset | None"] = relationship()
    sla_policy: Mapped["SlaPolicy | None"] = relationship()
    comments: Mapped[list["TicketComment"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    history: Mapped[list["TicketHistory"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    participants: Mapped[list["TicketParticipant"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )
