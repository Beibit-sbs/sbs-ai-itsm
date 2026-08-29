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


class AiDataPolicy(Base):
    __tablename__ = "ai_data_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_ai_data_policies_tenant"),
        CheckConstraint(
            "maximum_external_classification IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')",
            name="ck_ai_data_policies_classification",
        ),
        CheckConstraint(
            "retention_days >= 30 AND retention_days <= 2555",
            name="ck_ai_data_policies_retention",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    external_processing_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    allowed_providers_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    provider_regions_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}"
    )
    maximum_external_classification: Mapped[str] = mapped_column(
        String(20), nullable=False, default="INTERNAL"
    )
    pii_redaction_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    allow_reversible_redaction: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AiUsageBudget(Base):
    __tablename__ = "ai_usage_budgets"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_ai_usage_budgets_tenant"),
        CheckConstraint(
            "monthly_request_limit >= 0 AND daily_request_limit >= 0 "
            "AND monthly_cost_limit_usd >= 0",
            name="ck_ai_usage_budgets_nonnegative",
        ),
        CheckConstraint(
            "warning_percent >= 1 AND warning_percent <= 100",
            name="ck_ai_usage_budgets_warning",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    monthly_request_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10_000
    )
    monthly_cost_limit_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=100.0
    )
    daily_request_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1_000
    )
    warning_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    hard_limit_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AiUsageLedger(Base):
    __tablename__ = "ai_usage_ledger"
    __table_args__ = (
        CheckConstraint(
            "data_classification IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')",
            name="ck_ai_usage_ledger_classification",
        ),
        CheckConstraint(
            "outcome IN ('SUCCESS','FALLBACK','BLOCKED','ERROR')",
            name="ck_ai_usage_ledger_outcome",
        ),
        CheckConstraint(
            "input_tokens_estimated >= 0 AND output_tokens_estimated >= 0 "
            "AND estimated_cost_usd >= 0 AND latency_ms >= 0",
            name="ck_ai_usage_ledger_nonnegative",
        ),
        Index("ix_ai_usage_ledger_tenant_created", "tenant_id", "created_at"),
        Index("ix_ai_usage_ledger_provider_created", "provider", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    data_classification: Mapped[str] = mapped_column(String(20), nullable=False)
    pii_redacted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens_estimated: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens_estimated: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_prompt_versions.id", ondelete="SET NULL"), nullable=True
    )
    correlation_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiProviderCircuit(Base):
    __tablename__ = "ai_provider_circuits"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", name="uq_ai_provider_circuits_tenant_provider"
        ),
        CheckConstraint(
            "state IN ('CLOSED','OPEN','HALF_OPEN')",
            name="ck_ai_provider_circuits_state",
        ),
        CheckConstraint(
            "failure_threshold >= 1 AND cooldown_seconds >= 1 "
            "AND consecutive_failures >= 0",
            name="ck_ai_provider_circuits_bounds",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="CLOSED")
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    failure_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    open_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    probe_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_code: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
