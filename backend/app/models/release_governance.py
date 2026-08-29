from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseRecord(Base):
    __tablename__ = "release_records"
    __table_args__ = (
        CheckConstraint(
            "release_type IN ('MAJOR','MINOR','PATCH','HOTFIX')",
            name="ck_release_records_type",
        ),
        CheckConstraint(
            "status IN ("
            "'DRAFT','PLANNING','READY','APPROVED','DEPLOYING','VALIDATING',"
            "'RELEASED','FAILED','ROLLED_BACK','CANCELLED')",
            name="ck_release_records_status",
        ),
        CheckConstraint(
            "risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_release_records_risk",
        ),
        UniqueConstraint(
            "tenant_id",
            "release_number",
            name="uq_release_records_tenant_number",
        ),
        UniqueConstraint(
            "tenant_id",
            "service_name",
            "version_name",
            name="uq_release_records_tenant_service_version",
        ),
        Index(
            "ix_release_records_portfolio",
            "tenant_id",
            "status",
            "target_release_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_number: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    release_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="DRAFT",
    )
    service_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    release_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="MEDIUM",
    )
    target_release_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    window_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    window_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    validation_plan: Mapped[str] = mapped_column(Text, nullable=False)
    rollback_plan: Mapped[str] = mapped_column(Text, nullable=False)
    communication_plan: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    go_no_go_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
    )
    approved_decision_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    actual_released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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


class ReleaseEnvironment(Base):
    __tablename__ = "release_environments"
    __table_args__ = (
        CheckConstraint(
            "environment_type IN ('DEVELOPMENT','TEST','STAGING','PRODUCTION','DR')",
            name="ck_release_environments_type",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_release_environments_tenant_code",
        ),
        UniqueConstraint(
            "tenant_id",
            "promotion_order",
            name="uq_release_environments_tenant_order",
        ),
        Index(
            "ix_release_environments_active",
            "tenant_id",
            "is_active",
            "promotion_order",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    environment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    promotion_order: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    requires_smoke_test: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    is_production: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    current_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
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


class ReleasePackage(Base):
    __tablename__ = "release_packages"
    __table_args__ = (
        CheckConstraint(
            "package_type IN ('APPLICATION','DATABASE','CONFIGURATION','INFRASTRUCTURE','DOCUMENTATION')",
            name="ck_release_packages_type",
        ),
        CheckConstraint(
            "verification_status IN ('PENDING','VERIFIED','FAILED')",
            name="ck_release_packages_verification",
        ),
        UniqueConstraint(
            "release_id",
            "component_name",
            name="uq_release_packages_component",
        ),
        Index("ix_release_packages_release", "release_id", "verification_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_name: Mapped[str] = mapped_column(String(200), nullable=False)
    package_type: Mapped[str] = mapped_column(String(24), nullable=False)
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    artifact_uri: Mapped[str] = mapped_column(String(1_000), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    build_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dependencies_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    verification_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PENDING",
    )
    verification_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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


class ReleaseChangeLink(Base):
    __tablename__ = "release_change_links"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "change_id",
            name="uq_release_change_links_release_change",
        ),
        UniqueConstraint(
            "release_id",
            "sequence",
            name="uq_release_change_links_sequence",
        ),
        Index("ix_release_change_links_change", "tenant_id", "change_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    change_id: Mapped[str] = mapped_column(
        ForeignKey("change_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ReleaseDependency(Base):
    __tablename__ = "release_dependencies"
    __table_args__ = (
        CheckConstraint(
            "dependency_type IN ('REQUIRES','BLOCKS','FOLLOWS')",
            name="ck_release_dependencies_type",
        ),
        CheckConstraint(
            "release_id <> dependency_release_id",
            name="ck_release_dependencies_not_self",
        ),
        UniqueConstraint(
            "release_id",
            "dependency_release_id",
            name="uq_release_dependencies_pair",
        ),
        Index("ix_release_dependencies_release", "tenant_id", "release_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    dependency_release_id: Mapped[str] = mapped_column(
        ForeignKey("release_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dependency_type: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ReleaseGate(Base):
    __tablename__ = "release_gates"
    __table_args__ = (
        CheckConstraint(
            "gate_type IN ("
            "'CHANGES','PACKAGES','DEPENDENCIES','WINDOW','ROLLBACK','TEST',"
            "'SECURITY','BUSINESS','MANUAL')",
            name="ck_release_gates_type",
        ),
        CheckConstraint(
            "status IN ('PENDING','PASSED','FAILED','WAIVED')",
            name="ck_release_gates_status",
        ),
        UniqueConstraint(
            "release_id",
            "code",
            name="uq_release_gates_release_code",
        ),
        Index("ix_release_gates_release", "release_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    gate_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PENDING",
    )
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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


class ReleaseDecision(Base):
    __tablename__ = "release_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('GO','NO_GO','CONDITIONAL')",
            name="ck_release_decisions_decision",
        ),
        Index("ix_release_decisions_release", "release_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    conditions_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    readiness_snapshot_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    decided_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ReleaseDeployment(Base):
    __tablename__ = "release_deployments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PLANNED','IN_PROGRESS','VALIDATING','SUCCEEDED','FAILED','ROLLED_BACK','CANCELLED')",
            name="ck_release_deployments_status",
        ),
        UniqueConstraint(
            "release_id",
            "environment_id",
            name="uq_release_deployments_release_environment",
        ),
        Index(
            "ix_release_deployments_operations",
            "tenant_id",
            "status",
            "scheduled_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    environment_id: Mapped[str] = mapped_column(
        ForeignKey("release_environments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PLANNED",
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deployed_version: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    deployment_reference: Mapped[str | None] = mapped_column(
        String(1_000),
        nullable=True,
    )
    deployment_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    smoke_test_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PENDING",
    )
    rollback_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    operator_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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


class ReleaseTimeline(Base):
    __tablename__ = "release_timeline"
    __table_args__ = (
        Index("ix_release_timeline_release", "release_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_id: Mapped[str] = mapped_column(
        ForeignKey("release_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
