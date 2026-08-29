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


class AssetDiscoveryConnector(Base):
    __tablename__ = "asset_discovery_connectors"
    __table_args__ = (
        UniqueConstraint(
            "cmdb_source_id",
            name="uq_asset_discovery_connectors_source",
        ),
        CheckConstraint(
            "provider IN ("
            "'INTUNE','AZURE_RESOURCE_GRAPH','SCCM_ADMIN_SERVICE',"
            "'LANSWEEPER_DATA_API'"
            ")",
            name="ck_asset_discovery_connectors_provider",
        ),
        CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','REVOKED')",
            name="ck_asset_discovery_connectors_status",
        ),
        CheckConstraint(
            "auth_type IN ("
            "'OAUTH_CLIENT_CREDENTIALS','API_TOKEN','BASIC','BEARER'"
            ")",
            name="ck_asset_discovery_connectors_auth_type",
        ),
        CheckConstraint(
            "schedule_minutes >= 5",
            name="ck_asset_discovery_connectors_schedule",
        ),
        CheckConstraint(
            "missing_threshold_runs >= 1",
            name="ck_asset_discovery_connectors_missing_threshold",
        ),
        CheckConstraint(
            "max_records >= 1 AND max_records <= 50000",
            name="ck_asset_discovery_connectors_max_records",
        ),
        Index(
            "ix_asset_discovery_connectors_due",
            "status",
            "next_run_at",
        ),
        Index(
            "ix_asset_discovery_connectors_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    cmdb_source_id: Mapped[str] = mapped_column(
        ForeignKey("cmdb_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="DRAFT",
    )
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    credential_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    last_tested_credential_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    configuration_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    schedule_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
    )
    auto_apply: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    missing_threshold_runs: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
    )
    max_records: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5000,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    successful_runs: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    failed_runs: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    discovered_records: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
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


class AssetDiscoveryRun(Base):
    __tablename__ = "asset_discovery_runs"
    __table_args__ = (
        UniqueConstraint(
            "connector_id",
            "idempotency_key",
            name="uq_asset_discovery_runs_connector_key",
        ),
        CheckConstraint(
            "trigger_type IN ('MANUAL','SCHEDULED','TEST')",
            name="ck_asset_discovery_runs_trigger",
        ),
        CheckConstraint(
            "status IN ("
            "'QUEUED','RUNNING','RETRY','COMPLETED','COMPLETED_WITH_ERRORS',"
            "'FAILED','DEAD_LETTER','CANCELLED'"
            ")",
            name="ck_asset_discovery_runs_status",
        ),
        Index(
            "ix_asset_discovery_runs_queue",
            "status",
            "next_attempt_at",
            "created_at",
        ),
        Index(
            "ix_asset_discovery_runs_connector_created",
            "connector_id",
            "created_at",
        ),
        Index(
            "ix_asset_discovery_runs_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    connector_id: Mapped[str] = mapped_column(
        ForeignKey("asset_discovery_connectors.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    requested_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    complete_snapshot: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    reconciliation_run_ids_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ambiguous_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stale_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class AssetDiscoveryStaleCandidate(Base):
    __tablename__ = "asset_discovery_stale_candidates"
    __table_args__ = (
        UniqueConstraint(
            "source_identity_id",
            name="uq_asset_discovery_stale_identity",
        ),
        CheckConstraint(
            "status IN ('OPEN','DISMISSED','RETIRED','RECOVERED')",
            name="ck_asset_discovery_stale_status",
        ),
        Index(
            "ix_asset_discovery_stale_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_asset_discovery_stale_connector_status",
            "connector_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    connector_id: Mapped[str] = mapped_column(
        ForeignKey("asset_discovery_connectors.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_identity_id: Mapped[str] = mapped_column(
        ForeignKey("cmdb_source_identities.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="OPEN",
    )
    missing_run_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    first_missing_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_missing_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
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
