from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AssetHistory(Base):
    __tablename__ = "asset_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    asset: Mapped["Asset"] = relationship(back_populates="histories")
    actor: Mapped["User | None"] = relationship()
