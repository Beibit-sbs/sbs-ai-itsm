"""Add governed AI prompts, evaluations, and rollouts.

Revision ID: 20260729_0056
Revises: 20260729_0055
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0056"
down_revision: str | None = "20260729_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ai_prompt_policies"):
        return
    created_at, updated_at = _timestamps()
    op.create_table(
        "ai_prompt_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("use_case", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("active_version_id", sa.String(36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_ai_prompt_policies_tenant_code"),
        sa.CheckConstraint("use_case IN ('ticket_classification','grounded_answer')", name="ck_ai_prompt_policies_use_case"),
        sa.CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_ai_prompt_policies_status"),
    )
    op.create_index("ix_ai_prompt_policies_tenant_status", "ai_prompt_policies", ["tenant_id", "status"])

    op.create_table(
        "ai_prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("evaluation_run_id", sa.String(36), nullable=True),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("reviewed_by_id", sa.String(36), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by_id", sa.String(36), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_id"], ["ai_prompt_policies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["activated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("policy_id", "version_number", name="uq_ai_prompt_versions_number"),
        sa.CheckConstraint("status IN ('DRAFT','EVALUATED','APPROVED','ACTIVE','RETIRED','REJECTED')", name="ck_ai_prompt_versions_status"),
    )
    op.create_index("ix_ai_prompt_versions_tenant_status", "ai_prompt_versions", ["tenant_id", "status"])

    created_at, updated_at = _timestamps()
    op.create_table(
        "ai_evaluation_datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("use_case", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_ai_evaluation_datasets_tenant_code"),
        sa.CheckConstraint("use_case IN ('ticket_classification','grounded_answer')", name="ck_ai_evaluation_datasets_use_case"),
        sa.CheckConstraint("status IN ('DRAFT','ACTIVE','ARCHIVED')", name="ck_ai_evaluation_datasets_status"),
    )
    op.create_table(
        "ai_evaluation_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("dataset_id", sa.String(36), nullable=False),
        sa.Column("case_key", sa.String(120), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("sources_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("expected_json", sa.Text(), nullable=False),
        sa.Column("forbidden_terms_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["ai_evaluation_datasets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("dataset_id", "case_key", name="uq_ai_evaluation_cases_dataset_key"),
    )
    op.create_index("ix_ai_evaluation_cases_dataset_active", "ai_evaluation_cases", ["dataset_id", "is_active"])

    op.create_table(
        "ai_evaluation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("prompt_version_id", sa.String(36), nullable=False),
        sa.Column("dataset_id", sa.String(36), nullable=False),
        sa.Column("baseline_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("thresholds_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("regression_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_sha256", sa.String(64), nullable=True),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requested_by_id", sa.String(36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["ai_prompt_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["ai_evaluation_datasets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["baseline_version_id"], ["ai_prompt_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('RUNNING','PASSED','FAILED','ERROR')", name="ck_ai_evaluation_runs_status"),
    )
    op.create_index("ix_ai_evaluation_runs_tenant_created", "ai_evaluation_runs", ["tenant_id", "created_at"])
    op.create_table(
        "ai_evaluation_case_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("groundedness_score", sa.Float(), nullable=False),
        sa.Column("safety_score", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=False),
        sa.Column("citation_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("failure_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["ai_evaluation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["ai_evaluation_cases.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "case_id", name="uq_ai_evaluation_results_run_case"),
    )
    op.create_index("ix_ai_evaluation_results_run", "ai_evaluation_case_results", ["run_id", "passed"])

    op.create_table(
        "ai_prompt_rollouts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("prompt_version_id", sa.String(36), nullable=False),
        sa.Column("previous_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("canary_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_by_id", sa.String(36), nullable=True),
        sa.Column("approved_by_id", sa.String(36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metrics_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_id"], ["ai_prompt_policies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["ai_prompt_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["previous_version_id"], ["ai_prompt_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('PENDING','CANARY','ACTIVE','ROLLED_BACK','REJECTED')", name="ck_ai_prompt_rollouts_status"),
        sa.CheckConstraint("canary_percent >= 0 AND canary_percent <= 100", name="ck_ai_prompt_rollouts_canary"),
    )
    op.create_index("ix_ai_prompt_rollouts_tenant_created", "ai_prompt_rollouts", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_prompt_rollouts_tenant_created", table_name="ai_prompt_rollouts")
    op.drop_table("ai_prompt_rollouts")
    op.drop_index("ix_ai_evaluation_results_run", table_name="ai_evaluation_case_results")
    op.drop_table("ai_evaluation_case_results")
    op.drop_index("ix_ai_evaluation_runs_tenant_created", table_name="ai_evaluation_runs")
    op.drop_table("ai_evaluation_runs")
    op.drop_index("ix_ai_evaluation_cases_dataset_active", table_name="ai_evaluation_cases")
    op.drop_table("ai_evaluation_cases")
    op.drop_table("ai_evaluation_datasets")
    op.drop_index("ix_ai_prompt_versions_tenant_status", table_name="ai_prompt_versions")
    op.drop_table("ai_prompt_versions")
    op.drop_index("ix_ai_prompt_policies_tenant_status", table_name="ai_prompt_policies")
    op.drop_table("ai_prompt_policies")
