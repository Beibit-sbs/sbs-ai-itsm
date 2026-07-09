from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AiSuggestion(Base):
    __tablename__ = "ai_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    article_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_articles.id", ondelete="SET NULL"), nullable=True)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_category: Mapped[str] = mapped_column(String(200), nullable=False)
    recommended_priority: Mapped[str] = mapped_column(String(32), nullable=False)
    recommended_asset_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recommended_article_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_articles.id", ondelete="SET NULL"), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    possible_cause: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_solution: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_assignee: Mapped[str] = mapped_column(String(200), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggestion_type: Mapped[str] = mapped_column(String(40), nullable=False, default="resolution")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    accepted_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    ticket: Mapped["Ticket | None"] = relationship()
    article: Mapped["KnowledgeArticle | None"] = relationship(foreign_keys=[recommended_article_id])
    linked_article: Mapped["KnowledgeArticle | None"] = relationship(foreign_keys=[article_id])
    asset: Mapped["Asset | None"] = relationship()
    accepted_by: Mapped["User | None"] = relationship(foreign_keys=[accepted_by_id])
    rejected_by: Mapped["User | None"] = relationship(foreign_keys=[rejected_by_id])