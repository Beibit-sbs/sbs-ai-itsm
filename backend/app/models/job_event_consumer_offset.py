from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobEventConsumerOffset(Base):
    __tablename__ = "job_event_consumer_offsets"
    __table_args__ = (UniqueConstraint("consumer_name", "stream_name", name="uq_job_event_consumer_offset"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    consumer_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stream_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    last_stream_id: Mapped[str] = mapped_column(String(64), nullable=False, default="0-0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
