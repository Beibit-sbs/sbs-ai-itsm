from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TenantBrandAsset(Base):
    __tablename__ = "tenant_brand_assets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "kind",
            "sha256",
            name="uq_tenant_brand_assets_tenant_kind_sha256",
        ),
        Index(
            "ix_tenant_brand_assets_tenant_created",
            "tenant_id",
            "created_at",
        ),
        CheckConstraint(
            "kind IN ('LOGO')",
            name="ck_tenant_brand_assets_kind",
        ),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 524288",
            name="ck_tenant_brand_assets_size",
        ),
        CheckConstraint(
            "width >= 32 AND width <= 2048 AND height >= 32 AND height <= 2048",
            name="ck_tenant_brand_assets_dimensions",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class TenantExperienceProfile(Base):
    __tablename__ = "tenant_experience_profiles"
    __table_args__ = (
        CheckConstraint(
            "revision >= 0",
            name="ck_tenant_experience_profiles_revision",
        ),
        CheckConstraint(
            "first_day_of_week IN (1, 7)",
            name="ck_tenant_experience_profiles_first_day",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    product_name: Mapped[str] = mapped_column(String(80), nullable=False)
    short_name: Mapped[str] = mapped_column(String(24), nullable=False)
    logo_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenant_brand_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    primary_color: Mapped[str] = mapped_column(String(7), nullable=False)
    accent_color: Mapped[str] = mapped_column(String(7), nullable=False)
    surface_color: Mapped[str] = mapped_column(String(7), nullable=False)
    text_color: Mapped[str] = mapped_column(String(7), nullable=False)
    ui_locale: Mapped[str] = mapped_column(String(16), nullable=False)
    format_locale: Mapped[str] = mapped_column(String(16), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    date_style: Mapped[str] = mapped_column(String(12), nullable=False)
    hour_cycle: Mapped[str] = mapped_column(String(4), nullable=False)
    first_day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    terminology_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantExperienceRevision(Base):
    __tablename__ = "tenant_experience_revisions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "revision",
            name="uq_tenant_experience_revisions_tenant_revision",
        ),
        Index(
            "ix_tenant_experience_revisions_tenant_created",
            "tenant_id",
            "created_at",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_tenant_experience_revisions_revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
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
