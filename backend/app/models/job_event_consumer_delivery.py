from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobEventConsumerDelivery(Base):
    __tablename__ = "job_event_consumer_deliveries"
    __table_args__ = (UniqueConstraint("consumer_name", "event_id", name="uq_job_event_consumer_delivery"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    consumer_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("job_lifecycle_events.id", ondelete="CASCADE"), nullable=False, index=True)
    stream_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    stream_entry_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
