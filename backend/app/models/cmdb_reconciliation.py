from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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


class CMDBSource(Base):
    __tablename__ = "cmdb_sources"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_cmdb_sources_tenant_code",
        ),
        CheckConstraint(
            "source_type IN ('FILE', 'API', 'DISCOVERY', 'MANUAL')",
            name="ck_cmdb_sources_type",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE')",
            name="ck_cmdb_sources_status",
        ),
        CheckConstraint(
            "priority >= 1 AND priority <= 1000",
            name="ck_cmdb_sources_priority",
        ),
        CheckConstraint(
            "stale_after_hours >= 1",
            name="ck_cmdb_sources_stale_hours",
        ),
        Index("ix_cmdb_sources_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_system_id: Mapped[str | None] = mapped_column(
        ForeignKey("external_systems.id", ondelete="SET NULL"),
        nullable=True,
    )
    default_class_id: Mapped[str | None] = mapped_column(
        ForeignKey("ci_classes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    identification_rules_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default='["serial_number","inventory_number","asset_tag"]',
    )
    authoritative_fields_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    claim_unowned_fields: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    stale_after_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=24,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ACTIVE",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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


class CMDBReconciliationRun(Base):
    __tablename__ = "cmdb_reconciliation_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "idempotency_key",
            name="uq_cmdb_reconciliation_runs_source_key",
        ),
        CheckConstraint(
            "mode IN ('PREVIEW', 'APPLY')",
            name="ck_cmdb_reconciliation_runs_mode",
        ),
        CheckConstraint(
            "status IN ("
            "'PENDING','PREVIEWED','RUNNING','COMPLETED',"
            "'COMPLETED_WITH_ERRORS','FAILED'"
            ")",
            name="ck_cmdb_reconciliation_runs_status",
        ),
        Index(
            "ix_cmdb_reconciliation_runs_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_cmdb_reconciliation_runs_source_status",
            "source_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("cmdb_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    create_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    update_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ambiguous_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
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


class CMDBSourceIdentity(Base):
    __tablename__ = "cmdb_source_identities"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "external_id",
            name="uq_cmdb_source_identities_source_external",
        ),
        Index(
            "ix_cmdb_source_identities_tenant_asset",
            "tenant_id",
            "asset_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("cmdb_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_seen_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("asset_discovery_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    discovery_state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ACTIVE",
    )
    missing_run_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    first_missing_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_missing_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CMDBReconciliationRecord(Base):
    __tablename__ = "cmdb_reconciliation_records"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "row_number",
            name="uq_cmdb_reconciliation_records_run_row",
        ),
        UniqueConstraint(
            "run_id",
            "external_id",
            name="uq_cmdb_reconciliation_records_run_external",
        ),
        CheckConstraint(
            "outcome IN ("
            "'CREATE','UPDATE','UNCHANGED','AMBIGUOUS','INVALID','SKIPPED',"
            "'APPLIED_CREATED','APPLIED_UPDATED'"
            ")",
            name="ck_cmdb_reconciliation_records_outcome",
        ),
        Index(
            "ix_cmdb_reconciliation_records_run_outcome",
            "run_id",
            "outcome",
        ),
        Index(
            "ix_cmdb_reconciliation_records_tenant_match",
            "tenant_id",
            "matched_ci_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("cmdb_reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_json: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    matched_ci_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_ids_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    errors_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class CMDBFieldOwnership(Base):
    __tablename__ = "cmdb_field_ownership"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "field_name",
            name="uq_cmdb_field_ownership_asset_field",
        ),
        Index(
            "ix_cmdb_field_ownership_tenant_source",
            "tenant_id",
            "source_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("cmdb_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_priority: Mapped[int] = mapped_column(Integer, nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CIDuplicateCandidate(Base):
    __tablename__ = "ci_duplicate_candidates"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "primary_ci_id",
            "duplicate_ci_id",
            name="uq_ci_duplicate_candidates_run_pair",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'MERGED', 'DISMISSED')",
            name="ck_ci_duplicate_candidates_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_ci_duplicate_candidates_confidence",
        ),
        Index(
            "ix_ci_duplicate_candidates_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("cmdb_reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_id: Mapped[str | None] = mapped_column(
        ForeignKey("cmdb_reconciliation_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    primary_ci_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    duplicate_ci_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="OPEN",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
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
