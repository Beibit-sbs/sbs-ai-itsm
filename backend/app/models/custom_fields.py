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


class CustomFieldSet(Base):
    __tablename__ = "custom_field_sets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_custom_field_sets_tenant_code",
        ),
        CheckConstraint(
            "entity_type IN ('ticket','asset','change','problem','request')",
            name="ck_custom_field_sets_entity_type",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','PAUSED','ARCHIVED')",
            name="ck_custom_field_sets_status",
        ),
        Index(
            "ix_custom_field_sets_tenant_entity_status",
            "tenant_id",
            "entity_type",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PAUSED",
    )
    applicability_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    latest_version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    draft_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    published_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
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


class CustomFieldSetVersion(Base):
    __tablename__ = "custom_field_set_versions"
    __table_args__ = (
        UniqueConstraint(
            "field_set_id",
            "version_number",
            name="uq_custom_field_set_versions_number",
        ),
        CheckConstraint(
            "status IN ('DRAFT','PUBLISHED','RETIRED')",
            name="ck_custom_field_set_versions_status",
        ),
        CheckConstraint(
            "validation_status IN ('VALID','INVALID')",
            name="ck_custom_field_set_versions_validation",
        ),
        Index(
            "ix_custom_field_set_versions_set_status",
            "field_set_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_set_id: Mapped[str] = mapped_column(
        ForeignKey("custom_field_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_json: Mapped[str] = mapped_column(Text, nullable=False)
    schema_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    validation_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    based_on_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    breaking_change: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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


class CustomFieldValue(Base):
    __tablename__ = "custom_field_values"
    __table_args__ = (
        UniqueConstraint(
            "field_set_id",
            "entity_type",
            "entity_id",
            name="uq_custom_field_values_set_entity",
        ),
        Index(
            "ix_custom_field_values_tenant_entity",
            "tenant_id",
            "entity_type",
            "entity_id",
        ),
        Index(
            "ix_custom_field_values_set_updated",
            "field_set_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_set_id: Mapped[str] = mapped_column(
        ForeignKey("custom_field_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_set_version_id: Mapped[str] = mapped_column(
        ForeignKey("custom_field_set_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    field_set_version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    values_json: Mapped[str] = mapped_column(Text, nullable=False)
    values_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
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
