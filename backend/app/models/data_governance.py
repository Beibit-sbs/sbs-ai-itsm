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


RETENTION_CATEGORIES = (
    "TICKETS",
    "SERVICE_REQUESTS",
    "COMMENTS",
    "NOTIFICATIONS",
    "LOGIN_EVENTS",
    "AUDIT",
    "EMAIL",
    "ATTACHMENTS",
    "AI_CONVERSATIONS",
    "AI_PROMPTS_RESPONSES",
    "VECTOR_EMBEDDINGS",
    "EXPORTS",
    "BACKGROUND_JOBS",
    "DEAD_LETTER",
)

_CATEGORY_SQL = ",".join(f"'{value}'" for value in RETENTION_CATEGORIES)


class DataRetentionPolicy(Base):
    __tablename__ = "data_retention_policies"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "category",
            name="uq_data_retention_policies_scope_category",
        ),
        CheckConstraint(
            f"category IN ({_CATEGORY_SQL})",
            name="ck_data_retention_policies_category",
        ),
        CheckConstraint(
            "retention_days >= 30 AND retention_days <= 3650",
            name="ck_data_retention_policies_days",
        ),
        Index(
            "ix_data_retention_policies_tenant_category",
            "tenant_id",
            "category",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    archive_before_delete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    anonymize_before_delete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_id: Mapped[str | None] = mapped_column(
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


class DataLegalHold(Base):
    __tablename__ = "data_legal_holds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','RELEASED','EXPIRED')",
            name="ck_data_legal_holds_status",
        ),
        CheckConstraint(
            f"category IS NULL OR category IN ({_CATEGORY_SQL})",
            name="ck_data_legal_holds_category",
        ),
        CheckConstraint(
            "scope_type IN ('TENANT','CATEGORY','ENTITY')",
            name="ck_data_legal_holds_scope_type",
        ),
        Index(
            "ix_data_legal_holds_tenant_status",
            "tenant_id",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    released_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DataDeletionRequest(Base):
    __tablename__ = "data_deletion_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('RETENTION_PURGE','TENANT_DELETION')",
            name="ck_data_deletion_requests_type",
        ),
        CheckConstraint(
            "status IN ('PREVIEWED','PENDING_APPROVAL','APPROVED','REJECTED',"
            "'EXECUTING','COMPLETED','FAILED','CANCELLED','BLOCKED_EXTERNAL')",
            name="ck_data_deletion_requests_status",
        ),
        CheckConstraint(
            f"category IS NULL OR category IN ({_CATEGORY_SQL})",
            name="ck_data_deletion_requests_category",
        ),
        Index(
            "ix_data_deletion_requests_tenant_status",
            "tenant_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Deliberately not a foreign key: deletion evidence must survive tenant removal.
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_type: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cutoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="PREVIEWED"
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    preview_json: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DataDeletionEvidence(Base):
    __tablename__ = "data_deletion_evidence"
    __table_args__ = (
        UniqueConstraint(
            "deletion_request_id",
            name="uq_data_deletion_evidence_request",
        ),
        Index(
            "ix_data_deletion_evidence_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    deletion_request_id: Mapped[str] = mapped_column(
        ForeignKey("data_deletion_requests.id", ondelete="RESTRICT"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_manifest_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
