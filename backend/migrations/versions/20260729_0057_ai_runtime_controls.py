"""Add AI privacy, residency, budget, usage, and circuit controls.

Revision ID: 20260729_0057
Revises: 20260729_0056
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0057"
down_revision: str | None = "20260729_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ai_data_policies"):
        return
    op.create_table(
        "ai_data_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("external_processing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allowed_providers_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("provider_regions_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("maximum_external_classification", sa.String(20), nullable=False, server_default="INTERNAL"),
        sa.Column("pii_redaction_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_reversible_redaction", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", name="uq_ai_data_policies_tenant"),
        sa.CheckConstraint(
            "maximum_external_classification IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')",
            name="ck_ai_data_policies_classification",
        ),
        sa.CheckConstraint(
            "retention_days >= 30 AND retention_days <= 2555",
            name="ck_ai_data_policies_retention",
        ),
    )
    op.create_table(
        "ai_usage_budgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("monthly_request_limit", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("monthly_cost_limit_usd", sa.Float(), nullable=False, server_default="100"),
        sa.Column("daily_request_limit", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("warning_percent", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("hard_limit_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", name="uq_ai_usage_budgets_tenant"),
        sa.CheckConstraint(
            "monthly_request_limit >= 0 AND daily_request_limit >= 0 "
            "AND monthly_cost_limit_usd >= 0",
            name="ck_ai_usage_budgets_nonnegative",
        ),
        sa.CheckConstraint(
            "warning_percent >= 1 AND warning_percent <= 100",
            name="ck_ai_usage_budgets_warning",
        ),
    )
    op.create_table(
        "ai_usage_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("requested_provider", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("provider_region", sa.String(80), nullable=True),
        sa.Column("data_classification", sa.String(20), nullable=False),
        sa.Column("pii_redacted", sa.Boolean(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=True),
        sa.Column("input_tokens_estimated", sa.Integer(), nullable=False),
        sa.Column("output_tokens_estimated", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("fallback_reason", sa.String(200), nullable=True),
        sa.Column("prompt_version_id", sa.String(36), nullable=True),
        sa.Column("correlation_sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["ai_prompt_versions.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "data_classification IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')",
            name="ck_ai_usage_ledger_classification",
        ),
        sa.CheckConstraint(
            "outcome IN ('SUCCESS','FALLBACK','BLOCKED','ERROR')",
            name="ck_ai_usage_ledger_outcome",
        ),
        sa.CheckConstraint(
            "input_tokens_estimated >= 0 AND output_tokens_estimated >= 0 "
            "AND estimated_cost_usd >= 0 AND latency_ms >= 0",
            name="ck_ai_usage_ledger_nonnegative",
        ),
    )
    op.create_index("ix_ai_usage_ledger_tenant_created", "ai_usage_ledger", ["tenant_id", "created_at"])
    op.create_index("ix_ai_usage_ledger_provider_created", "ai_usage_ledger", ["provider", "created_at"])
    op.create_table(
        "ai_provider_circuits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="CLOSED"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_threshold", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("probe_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_code", sa.String(120), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_ai_provider_circuits_tenant_provider"),
        sa.CheckConstraint("state IN ('CLOSED','OPEN','HALF_OPEN')", name="ck_ai_provider_circuits_state"),
        sa.CheckConstraint(
            "failure_threshold >= 1 AND cooldown_seconds >= 1 "
            "AND consecutive_failures >= 0",
            name="ck_ai_provider_circuits_bounds",
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_provider_circuits")
    op.drop_index("ix_ai_usage_ledger_provider_created", table_name="ai_usage_ledger")
    op.drop_index("ix_ai_usage_ledger_tenant_created", table_name="ai_usage_ledger")
    op.drop_table("ai_usage_ledger")
    op.drop_table("ai_usage_budgets")
    op.drop_table("ai_data_policies")
