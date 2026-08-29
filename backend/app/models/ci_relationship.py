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


class ConfigurationItemRelationshipType(Base):
    __tablename__ = "ci_relationship_types"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_ci_relationship_types_tenant_code",
        ),
        CheckConstraint(
            "source_cardinality IN ('ONE', 'MANY')",
            name="ck_ci_relationship_types_source_cardinality",
        ),
        CheckConstraint(
            "target_cardinality IN ('ONE', 'MANY')",
            name="ck_ci_relationship_types_target_cardinality",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE')",
            name="ck_ci_relationship_types_status",
        ),
        Index(
            "ix_ci_relationship_types_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    forward_label: Mapped[str] = mapped_column(String(160), nullable=False)
    reverse_label: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_class_id: Mapped[str | None] = mapped_column(
        ForeignKey("ci_classes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    target_class_id: Mapped[str | None] = mapped_column(
        ForeignKey("ci_classes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_cardinality: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="MANY",
    )
    target_cardinality: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="MANY",
    )
    allow_self_relationship: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    allow_cycles: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ACTIVE",
    )
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


class ConfigurationItemRelationship(Base):
    __tablename__ = "ci_relationships"
    __table_args__ = (
        UniqueConstraint(
            "relationship_type_id",
            "source_ci_id",
            "target_ci_id",
            "status",
            name="uq_ci_relationships_type_pair_status",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'RETIRED')",
            name="ck_ci_relationships_status",
        ),
        Index(
            "ix_ci_relationships_tenant_source_status",
            "tenant_id",
            "source_ci_id",
            "status",
        ),
        Index(
            "ix_ci_relationships_tenant_target_status",
            "tenant_id",
            "target_ci_id",
            "status",
        ),
        Index(
            "ix_ci_relationships_type_status",
            "relationship_type_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type_id: Mapped[str] = mapped_column(
        ForeignKey("ci_relationship_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_ci_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_ci_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ACTIVE",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    retired_by_id: Mapped[str | None] = mapped_column(
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
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
