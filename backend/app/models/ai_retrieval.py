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


class AiRetrievalDocument(Base):
    __tablename__ = "ai_retrieval_documents"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "source_type",
            "source_id",
            name="uq_ai_retrieval_documents_source",
        ),
        CheckConstraint(
            "source_type IN ('knowledge','ticket','problem','change','asset')",
            name="ck_ai_retrieval_documents_source_type",
        ),
        CheckConstraint(
            "visibility IN ('public','internal','restricted')",
            name="ck_ai_retrieval_documents_visibility",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','DELETED')",
            name="ck_ai_retrieval_documents_status",
        ),
        Index(
            "ix_ai_retrieval_documents_scope_status",
            "scope_key",
            "status",
            "source_type",
        ),
        Index(
            "ix_ai_retrieval_documents_tenant_updated",
            "tenant_id",
            "source_updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )
    scope_key: Mapped[str] = mapped_column(String(48), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(320), nullable=False)
    url_path: Mapped[str] = mapped_column(String(500), nullable=False)
    visibility: Mapped[str] = mapped_column(String(24), nullable=False)
    permission_code: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str] = mapped_column(String(120), nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AiRetrievalChunk(Base):
    __tablename__ = "ai_retrieval_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "ordinal",
            name="uq_ai_retrieval_chunks_document_ordinal",
        ),
        Index("ix_ai_retrieval_chunks_document", "document_id", "ordinal"),
        Index("ix_ai_retrieval_chunks_hash", "content_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("ai_retrieval_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AiRetrievalIngestionRun(Base):
    __tablename__ = "ai_retrieval_ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING','COMPLETED','FAILED')",
            name="ck_ai_retrieval_ingestion_runs_status",
        ),
        Index(
            "ix_ai_retrieval_ingestion_runs_tenant_started",
            "tenant_id",
            "started_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_types_json: Mapped[str] = mapped_column(Text, nullable=False)
    scanned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AiRetrievalQueryLog(Base):
    __tablename__ = "ai_retrieval_query_logs"
    __table_args__ = (
        Index(
            "ix_ai_retrieval_query_logs_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_ai_retrieval_query_logs_user_created",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    query_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    query_preview_redacted: Mapped[str] = mapped_column(String(500), nullable=False)
    source_types_json: Mapped[str] = mapped_column(Text, nullable=False)
    citation_evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    answer_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    retrieved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    permission_denied_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stale_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    injection_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    no_result: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
