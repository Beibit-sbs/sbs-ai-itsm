from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobLifecycleEvent(Base):
    __tablename__ = "job_lifecycle_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_job_lifecycle_events_job_sequence"),
        Index("ix_job_lifecycle_events_job_sequence", "job_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("job_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    current_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    relay_stream_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    relay_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    relay_publish_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    relay_failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relay_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    relay_lock_owner: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    relay_lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
