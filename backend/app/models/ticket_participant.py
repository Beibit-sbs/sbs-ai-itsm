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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TicketParticipant(Base):
    __tablename__ = "ticket_participants"
    __table_args__ = (
        UniqueConstraint(
            "ticket_id",
            "identity_key",
            name="uq_ticket_participants_ticket_identity",
        ),
        CheckConstraint(
            "participant_role IN ('WATCHER','COLLABORATOR','REQUESTER_REPRESENTATIVE')",
            name="ck_ticket_participants_role",
        ),
        CheckConstraint(
            "notification_scope IN ('ALL','PUBLIC_ONLY','STATUS_ONLY','NONE')",
            name="ck_ticket_participants_notification_scope",
        ),
        Index(
            "ix_ticket_participants_tenant_ticket_active",
            "tenant_id",
            "ticket_id",
            "is_active",
        ),
        Index(
            "ix_ticket_participants_user_active",
            "user_id",
            "is_active",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    identity_key: Mapped[str] = mapped_column(String(280), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    participant_role: Mapped[str] = mapped_column(String(32), nullable=False)
    notification_scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PUBLIC_ONLY"
    )
    notify_in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    added_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    removal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    removed_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    ticket: Mapped["Ticket"] = relationship(back_populates="participants")
