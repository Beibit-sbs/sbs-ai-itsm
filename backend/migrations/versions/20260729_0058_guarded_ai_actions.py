"""Add guarded AI action proposals, approvals, execution, and rollback.

Revision ID: 20260729_0058
Revises: 20260729_0057
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0058"
down_revision: str | None = "20260729_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ai_action_policies"):
        return
    op.create_table(
        "ai_action_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allowed_actions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("independent_approval_for_high_risk", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("proposal_ttl_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", name="uq_ai_action_policies_tenant"),
        sa.CheckConstraint(
            "proposal_ttl_minutes >= 5 AND proposal_ttl_minutes <= 10080",
            name="ck_ai_action_policies_ttl",
        ),
    )
    op.create_table(
        "ai_action_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("proposal_number", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(120), nullable=True),
        sa.Column("target_fingerprint", sa.String(64), nullable=True),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("parameters_sha256", sa.String(64), nullable=False),
        sa.Column("source_query_sha256", sa.String(64), nullable=True),
        sa.Column("citation_evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PROPOSED"),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("reviewed_by_id", sa.String(36), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_by_id", sa.String(36), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("proposal_number", name="uq_ai_action_proposals_number"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_ai_action_proposals_idempotency"),
        sa.CheckConstraint(
            "action_type IN ('ticket.update','ticket.classify','knowledge.draft','runbook.draft')",
            name="ck_ai_action_proposals_type",
        ),
        sa.CheckConstraint("risk_level IN ('LOW','MEDIUM','HIGH')", name="ck_ai_action_proposals_risk"),
        sa.CheckConstraint(
            "status IN ('PROPOSED','APPROVED','REJECTED','EXECUTED','FAILED','ROLLED_BACK','EXPIRED')",
            name="ck_ai_action_proposals_status",
        ),
    )
    op.create_index("ix_ai_action_proposals_tenant_status", "ai_action_proposals", ["tenant_id", "status"])
    op.create_index("ix_ai_action_proposals_target", "ai_action_proposals", ["target_type", "target_id"])
    op.create_table(
        "ai_action_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("proposal_id", sa.String(36), nullable=False),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(120), nullable=True),
        sa.Column("before_state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("before_sha256", sa.String(64), nullable=False),
        sa.Column("after_state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("after_sha256", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("rollback_reason", sa.Text(), nullable=True),
        sa.Column("rolled_back_by_id", sa.String(36), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["ai_action_proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rolled_back_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("proposal_id", name="uq_ai_action_executions_proposal"),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED','FAILED','ROLLED_BACK')",
            name="ck_ai_action_executions_status",
        ),
    )
    op.create_index("ix_ai_action_executions_tenant_created", "ai_action_executions", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_action_executions_tenant_created", table_name="ai_action_executions")
    op.drop_table("ai_action_executions")
    op.drop_index("ix_ai_action_proposals_target", table_name="ai_action_proposals")
    op.drop_index("ix_ai_action_proposals_tenant_status", table_name="ai_action_proposals")
    op.drop_table("ai_action_proposals")
    op.drop_table("ai_action_policies")
