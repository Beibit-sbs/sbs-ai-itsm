from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CMDBImpactCache(Base):
    __tablename__ = "cmdb_impact_cache"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "root_ci_id",
            "direction",
            "max_depth",
            name="uq_cmdb_impact_cache_scope",
        ),
        CheckConstraint(
            "direction IN ('UPSTREAM', 'DOWNSTREAM', 'BOTH')",
            name="ck_cmdb_impact_cache_direction",
        ),
        Index(
            "ix_cmdb_impact_cache_tenant_expires",
            "tenant_id",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    root_ci_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
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


class CMDBImpactAssessment(Base):
    __tablename__ = "cmdb_impact_assessments"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('TICKET', 'PROBLEM', 'CHANGE', 'RELEASE')",
            name="ck_cmdb_impact_assessments_entity_type",
        ),
        CheckConstraint(
            "direction IN ('UPSTREAM', 'DOWNSTREAM', 'BOTH')",
            name="ck_cmdb_impact_assessments_direction",
        ),
        CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_cmdb_impact_assessments_severity",
        ),
        CheckConstraint(
            "status IN ('CURRENT', 'SUPERSEDED')",
            name="ck_cmdb_impact_assessments_status",
        ),
        Index(
            "ix_cmdb_impact_assessments_entity",
            "tenant_id",
            "entity_type",
            "entity_id",
            "created_at",
        ),
        Index(
            "ix_cmdb_impact_assessments_status",
            "tenant_id",
            "status",
        ),
        Index(
            "uq_cmdb_impact_assessments_current",
            "tenant_id",
            "entity_type",
            "entity_id",
            unique=True,
            postgresql_where=text("status = 'CURRENT'"),
            sqlite_where=text("status = 'CURRENT'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    root_ci_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    impacted_ci_count: Mapped[int] = mapped_column(Integer, nullable=False)
    impacted_service_count: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_ci_count: Mapped[int] = mapped_column(Integer, nullable=False)
    collision_count: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="CURRENT",
    )
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
