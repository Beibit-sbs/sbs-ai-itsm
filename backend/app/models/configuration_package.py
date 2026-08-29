from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class ConfigurationPackage(Base):
    __tablename__ = "configuration_packages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_configuration_packages_tenant_code"),
        CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_configuration_packages_status"),
        Index("ix_configuration_packages_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    latest_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ConfigurationPackageVersion(Base):
    __tablename__ = "configuration_package_versions"
    __table_args__ = (
        UniqueConstraint("package_id", "version_number", name="uq_configuration_package_versions_number"),
        CheckConstraint("status IN ('DRAFT','SEALED','RETIRED')", name="ck_configuration_package_versions_status"),
        CheckConstraint(
            "validation_status IN ('VALID','INVALID')",
            name="ck_configuration_package_versions_validation",
        ),
        Index("ix_configuration_package_versions_package_status", "package_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("configuration_packages.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    source_environment: Mapped[str] = mapped_column(String(80), nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_hmac_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    validation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    component_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dependency_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    imported_from_artifact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sealed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ConfigurationDeployment(Base):
    __tablename__ = "configuration_deployments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_configuration_deployments_idempotency"
        ),
        CheckConstraint(
            "status IN ('DRAFT','VALIDATED','PENDING_APPROVAL','APPROVED','REJECTED','APPLIED','FAILED','ROLLED_BACK')",
            name="ck_configuration_deployments_status",
        ),
        Index(
            "ix_configuration_deployments_tenant_target_status",
            "tenant_id",
            "target_environment",
            "status",
        ),
        Index(
            "ix_configuration_deployments_version_created",
            "package_version_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    package_version_id: Mapped[str] = mapped_column(
        ForeignKey("configuration_package_versions.id", ondelete="RESTRICT"), nullable=False
    )
    target_environment: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    plan_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_fingerprint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_before_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    applied_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rolled_back_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
