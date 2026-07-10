from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IntegrationCredential(Base):
    __tablename__ = "integration_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    external_system_id: Mapped[str] = mapped_column(ForeignKey("external_systems.id", ondelete="CASCADE"), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(80), nullable=False, default="api_token")
    masked_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Legacy compatibility fields from integration foundation stage.
    auth_type: Mapped[str] = mapped_column(String(80), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
