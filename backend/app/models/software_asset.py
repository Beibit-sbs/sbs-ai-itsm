from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SoftwareProduct(Base):
    __tablename__ = "software_products"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "catalog_key",
            name="uq_software_products_tenant_catalog_key",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','RETIRED')",
            name="ck_software_products_status",
        ),
        Index(
            "ix_software_products_tenant_status",
            "tenant_id",
            "status",
            "is_prohibited",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    catalog_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    publisher: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    edition: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    is_prohibited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prohibited_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftwareLicense(Base):
    __tablename__ = "software_licenses"
    __table_args__ = (
        CheckConstraint(
            "license_type IN ('NAMED_USER','DEVICE','CONCURRENT','SUBSCRIPTION',"
            "'PERPETUAL','OEM','ENTERPRISE')",
            name="ck_software_licenses_type",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','SUSPENDED','EXPIRED','RETIRED')",
            name="ck_software_licenses_status",
        ),
        CheckConstraint(
            "purchased_quantity >= 0",
            name="ck_software_licenses_quantity",
        ),
        CheckConstraint(
            "unit_cost >= 0",
            name="ck_software_licenses_unit_cost",
        ),
        Index(
            "ix_software_licenses_tenant_product",
            "tenant_id",
            "product_id",
            "status",
        ),
        Index(
            "ix_software_licenses_tenant_renewal",
            "tenant_id",
            "renewal_at",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[str] = mapped_column(
        ForeignKey("software_products.id", ondelete="CASCADE"), nullable=False
    )
    license_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    license_type: Mapped[str] = mapped_column(String(24), nullable=False)
    purchased_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contract_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    renewal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KZT")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftwareInstallation(Base):
    __tablename__ = "software_installations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "asset_id",
            name="uq_software_installations_tenant_product_asset",
        ),
        CheckConstraint(
            "authorization_status IN ('AUTHORIZED','UNAUTHORIZED','EXEMPTED')",
            name="ck_software_installations_authorization",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','REMOVED')",
            name="ck_software_installations_status",
        ),
        Index(
            "ix_software_installations_tenant_product",
            "tenant_id",
            "product_id",
            "status",
        ),
        Index(
            "ix_software_installations_tenant_authorization",
            "tenant_id",
            "authorization_status",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[str] = mapped_column(
        ForeignKey("software_products.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    assigned_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    detected_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    authorization_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="AUTHORIZED"
    )
    authorization_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
