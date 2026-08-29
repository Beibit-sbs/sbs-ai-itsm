from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConfigurationSettingRevision(Base):
    __tablename__ = "configuration_setting_revisions"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "setting_key",
            "revision",
            name="uq_configuration_setting_revisions_scope_key_revision",
        ),
        Index(
            "ix_configuration_setting_revisions_scope_created",
            "scope_key",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )
    scope_key: Mapped[str] = mapped_column(String(48), nullable=False)
    setting_key: Mapped[str] = mapped_column(String(120), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    value_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    rolled_back_from_revision: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
