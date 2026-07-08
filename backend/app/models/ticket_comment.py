from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(200), nullable=False)
    author_role: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    ticket: Mapped["Ticket"] = relationship(back_populates="comments")
    author: Mapped["User | None"] = relationship()
