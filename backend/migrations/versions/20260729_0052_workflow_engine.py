"""Add versioned production workflow engine.

Revision ID: 20260729_0052
Revises: 20260729_0051
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0052"
down_revision: str | None = "20260729_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("workflow_definitions"):
        return
    created_at, updated_at = _timestamps()
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="PAUSED",
        ),
        sa.Column("trigger_type", sa.String(120), nullable=False),
        sa.Column(
            "concurrency_policy",
            sa.String(16),
            nullable=False,
            server_default="ALLOW",
        ),
        sa.Column(
            "max_active_executions",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
        sa.Column(
            "publish_approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "latest_version_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("draft_version_number", sa.Integer(), nullable=True),
        sa.Column("published_version_number", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "total_executions",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failed_executions",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_execution_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "status IN ('ACTIVE','PAUSED','ARCHIVED')",
            name="ck_workflow_definitions_status",
        ),
        sa.CheckConstraint(
            "concurrency_policy IN ('ALLOW','SERIALIZE')",
            name="ck_workflow_definitions_concurrency",
        ),
        sa.CheckConstraint(
            "max_active_executions >= 1 AND max_active_executions <= 1000",
            name="ck_workflow_definitions_max_active",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_workflow_definitions_tenant_code",
        ),
    )
    op.create_index(
        "ix_workflow_definitions_tenant_trigger_status",
        "workflow_definitions",
        ["tenant_id", "trigger_type", "status"],
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column(
            "validation_status",
            sa.String(16),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column(
            "validation_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("based_on_version_number", sa.Integer(), nullable=True),
        sa.Column("rollback_from_version_number", sa.Integer(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column(
            "review_status",
            sa.String(16),
            nullable=False,
            server_default="NOT_REQUIRED",
        ),
        sa.Column("review_requested_by_id", sa.String(36), nullable=True),
        sa.Column("reviewed_by_id", sa.String(36), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column(
            "review_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        sa.Column("published_by_id", sa.String(36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "status IN ('DRAFT','PUBLISHED','RETIRED')",
            name="ck_workflow_versions_status",
        ),
        sa.CheckConstraint(
            "validation_status IN ('UNKNOWN','VALID','INVALID')",
            name="ck_workflow_versions_validation",
        ),
        sa.CheckConstraint(
            "review_status IN ('NOT_REQUIRED','PENDING','APPROVED','REJECTED')",
            name="ck_workflow_versions_review",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflow_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["review_requested_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "version_number",
            name="uq_workflow_versions_number",
        ),
    )
    op.create_index(
        "ix_workflow_versions_workflow_status",
        "workflow_versions",
        ["workflow_id", "status"],
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("workflow_version_id", sa.String(36), nullable=False),
        sa.Column("workflow_version_number", sa.Integer(), nullable=False),
        sa.Column("replay_of_id", sa.String(36), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("trigger_type", sa.String(120), nullable=False),
        sa.Column("trigger_entity_type", sa.String(80), nullable=True),
        sa.Column("trigger_entity_id", sa.String(120), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_node_key", sa.String(80), nullable=True),
        sa.Column(
            "context_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "variables_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "output_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_by_id", sa.String(36), nullable=True),
        sa.Column("correlation_id", sa.String(120), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", sa.String(36), nullable=True),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "status IN ("
            "'QUEUED','RUNNING','WAITING_TIMER','WAITING_APPROVAL',"
            "'WAITING_SUBFLOW','RETRY',"
            "'COMPENSATING','SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER',"
            "'DROPPED'"
            ")",
            name="ck_workflow_executions_status",
        ),
        sa.CheckConstraint(
            "source IN ('AUTOMATIC','MANUAL','REPLAY')",
            name="ck_workflow_executions_source",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflow_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replay_of_id"],
            ["workflow_executions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["started_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "idempotency_key",
            name="uq_workflow_executions_idempotency",
        ),
    )
    op.create_index(
        "ix_workflow_executions_due",
        "workflow_executions",
        ["status", "next_run_at", "created_at"],
    )
    op.create_index(
        "ix_workflow_executions_workflow_status",
        "workflow_executions",
        ["workflow_id", "status"],
    )
    op.create_index(
        "ix_workflow_executions_tenant_created",
        "workflow_executions",
        ["tenant_id", "created_at"],
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "workflow_step_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("workflow_version_id", sa.String(36), nullable=False),
        sa.Column("node_key", sa.String(80), nullable=False),
        sa.Column("node_type", sa.String(24), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "input_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "output_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wait_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("compensation_status", sa.String(24), nullable=True),
        sa.Column("compensation_output_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "status IN ("
            "'PENDING','RUNNING','WAITING','SUCCEEDED','FAILED','SKIPPED',"
            "'COMPENSATED','COMPENSATION_FAILED'"
            ")",
            name="ck_workflow_step_executions_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "execution_id",
            "node_key",
            name="uq_workflow_step_executions_node",
        ),
    )
    op.create_index(
        "ix_workflow_step_executions_execution_sequence",
        "workflow_step_executions",
        ["execution_id", "sequence_number"],
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "workflow_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("step_execution_id", sa.String(36), nullable=False),
        sa.Column("node_key", sa.String(80), nullable=False),
        sa.Column("approver_role", sa.String(80), nullable=False),
        sa.Column(
            "allow_self_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requested_by_id", sa.String(36), nullable=True),
        sa.Column("decided_by_id", sa.String(36), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','EXPIRED','CANCELLED')",
            name="ck_workflow_approvals_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_execution_id"],
            ["workflow_step_executions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "step_execution_id",
            name="uq_workflow_approvals_step",
        ),
    )
    op.create_index(
        "ix_workflow_approvals_tenant_status",
        "workflow_approvals",
        ["tenant_id", "status", "expires_at"],
    )

    op.create_table(
        "workflow_execution_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("node_key", sa.String(80), nullable=True),
        sa.Column("status", sa.String(24), nullable=True),
        sa.Column(
            "details_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("previous_hash", sa.String(64), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "execution_id",
            "sequence_number",
            name="uq_workflow_execution_events_sequence",
        ),
    )
    op.create_index(
        "ix_workflow_execution_events_execution_created",
        "workflow_execution_events",
        ["execution_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_execution_events_execution_created",
        table_name="workflow_execution_events",
    )
    op.drop_table("workflow_execution_events")
    op.drop_index(
        "ix_workflow_approvals_tenant_status",
        table_name="workflow_approvals",
    )
    op.drop_table("workflow_approvals")
    op.drop_index(
        "ix_workflow_step_executions_execution_sequence",
        table_name="workflow_step_executions",
    )
    op.drop_table("workflow_step_executions")
    op.drop_index(
        "ix_workflow_executions_tenant_created",
        table_name="workflow_executions",
    )
    op.drop_index(
        "ix_workflow_executions_workflow_status",
        table_name="workflow_executions",
    )
    op.drop_index(
        "ix_workflow_executions_due",
        table_name="workflow_executions",
    )
    op.drop_table("workflow_executions")
    op.drop_index(
        "ix_workflow_versions_workflow_status",
        table_name="workflow_versions",
    )
    op.drop_table("workflow_versions")
    op.drop_index(
        "ix_workflow_definitions_tenant_trigger_status",
        table_name="workflow_definitions",
    )
    op.drop_table("workflow_definitions")
