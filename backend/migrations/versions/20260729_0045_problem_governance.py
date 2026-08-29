"""Add structured RCA, corrective actions, trends, and KEDB value.

Revision ID: 20260729_0045
Revises: 20260729_0044
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0045"
down_revision: str | None = "20260729_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("problem_rcas"):
        return
    op.create_table(
        "problem_rcas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("problem_id", sa.String(36), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("problem_statement", sa.Text(), nullable=False),
        sa.Column("five_whys_json", sa.JSON(), nullable=False),
        sa.Column("ishikawa_json", sa.JSON(), nullable=False),
        sa.Column("fault_tree_json", sa.JSON(), nullable=False),
        sa.Column("contributing_factors_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("prepared_by_id", sa.String(36), nullable=True),
        sa.Column("prepared_by_name", sa.String(200), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", sa.String(36), nullable=True),
        sa.Column("approved_by_name", sa.String(200), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_comment", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "method IN ('FIVE_WHYS','ISHIKAWA','FAULT_TREE','CUSTOM')",
            name="ck_problem_rcas_method",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','SUBMITTED','APPROVED','REJECTED')",
            name="ck_problem_rcas_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["prepared_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("problem_id", name="uq_problem_rcas_problem"),
    )
    op.create_index(
        "ix_problem_rcas_tenant_status",
        "problem_rcas",
        ["tenant_id", "status"],
    )

    op.create_table(
        "problem_corrective_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("problem_id", sa.String(36), nullable=False),
        sa.Column("action_type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=True),
        sa.Column("owner_name", sa.String(200), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effectiveness_criteria", sa.Text(), nullable=False),
        sa.Column("implementation_evidence", sa.Text(), nullable=True),
        sa.Column("implemented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effectiveness_score", sa.Integer(), nullable=True),
        sa.Column("effectiveness_evidence", sa.Text(), nullable=True),
        sa.Column("reviewed_by_id", sa.String(36), nullable=True),
        sa.Column("reviewed_by_name", sa.String(200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "action_type IN ('CORRECTIVE','PREVENTIVE','DETECTION')",
            name="ck_problem_corrective_actions_type",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','IN_PROGRESS','IMPLEMENTED','VERIFIED','INEFFECTIVE','CANCELLED')",
            name="ck_problem_corrective_actions_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_problem_corrective_actions_due",
        "problem_corrective_actions",
        ["tenant_id", "status", "due_at"],
    )

    op.create_table(
        "problem_trend_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("signal_type", sa.String(24), nullable=False),
        sa.Column("signature", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("service_name", sa.String(200), nullable=True),
        sa.Column("category", sa.String(120), nullable=True),
        sa.Column("window_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_count", sa.Integer(), nullable=False),
        sa.Column("current_count", sa.Integer(), nullable=False),
        sa.Column("growth_percent", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("incident_ids_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("problem_id", sa.String(36), nullable=True),
        sa.Column("disposition_comment", sa.Text(), nullable=True),
        sa.Column("disposition_by_id", sa.String(36), nullable=True),
        sa.Column("disposition_by_name", sa.String(200), nullable=True),
        sa.Column("disposition_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('OPEN','ACKNOWLEDGED','CONVERTED','DISMISSED')",
            name="ck_problem_trend_signals_status",
        ),
        sa.CheckConstraint(
            "signal_type IN ('RECURRENCE','VOLUME_SPIKE','SLA_DEGRADATION')",
            name="ck_problem_trend_signals_type",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["disposition_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "signature",
            name="uq_problem_trend_signals_signature",
        ),
    )
    op.create_index(
        "ix_problem_trend_signals_queue",
        "problem_trend_signals",
        ["tenant_id", "status", "score"],
    )

    op.create_table(
        "known_error_usage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("problem_id", sa.String(36), nullable=False),
        sa.Column("ticket_id", sa.String(36), nullable=True),
        sa.Column("usage_type", sa.String(20), nullable=False),
        sa.Column("minutes_saved", sa.Integer(), nullable=False),
        sa.Column("avoided_escalation", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("actor_name", sa.String(200), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "usage_type IN ('VIEWED','APPLIED','HELPFUL','NOT_HELPFUL')",
            name="ck_known_error_usage_type",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_known_error_usage_problem",
        "known_error_usage",
        ["problem_id", "created_at"],
    )
    op.create_index(
        "ix_known_error_usage_tenant",
        "known_error_usage",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_known_error_usage_tenant", table_name="known_error_usage")
    op.drop_index("ix_known_error_usage_problem", table_name="known_error_usage")
    op.drop_table("known_error_usage")
    op.drop_index(
        "ix_problem_trend_signals_queue", table_name="problem_trend_signals"
    )
    op.drop_table("problem_trend_signals")
    op.drop_index(
        "ix_problem_corrective_actions_due",
        table_name="problem_corrective_actions",
    )
    op.drop_table("problem_corrective_actions")
    op.drop_index("ix_problem_rcas_tenant_status", table_name="problem_rcas")
    op.drop_table("problem_rcas")
