from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class KnowledgeUsageLog(Base):
    __tablename__ = "knowledge_usage_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    article_id: Mapped[str] = mapped_column(ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    article: Mapped["KnowledgeArticle"] = relationship(back_populates="usage_logs")
    ticket: Mapped["Ticket | None"] = relationship()
    user: Mapped["User | None"] = relationship()
