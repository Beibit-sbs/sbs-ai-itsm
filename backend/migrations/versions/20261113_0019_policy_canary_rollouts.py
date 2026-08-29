"""Create policy_canary_rollouts table.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-13 10:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    version_column = next(
        (item for item in inspector.get_columns("alembic_version") if item["name"] == "version_num"),
        None,
    )
    existing_length = getattr(version_column.get("type"), "length", None) if version_column else None
    # SQLite does not enforce VARCHAR lengths and cannot alter a column type
    # with PostgreSQL's ALTER COLUMN syntax. Keep the widening for production
    # databases while allowing the supported local SQLite upgrade path.
    if (
        bind.dialect.name != "sqlite"
        and existing_length is not None
        and existing_length < 128
    ):
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=existing_length),
            type_=sa.String(length=128),
            existing_nullable=False,
        )
    if inspector.has_table("policy_canary_rollouts"):
        return
    op.create_table(
        "policy_canary_rollouts",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("approval_request_id", sa.String(64), nullable=False),
        sa.Column("policy_type", sa.String(32), nullable=False),
        sa.Column("current_canary_percentage", sa.Integer(), nullable=False),
        sa.Column("affected_consumers_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metrics_baseline_json", sa.Text(), nullable=True),
        sa.Column("metrics_current_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), server_default="in_progress", nullable=False),
        sa.Column("error_rate_baseline", sa.Float(), nullable=True),
        sa.Column("error_rate_current", sa.Float(), nullable=True),
        sa.Column("auto_rollback_triggered", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("auto_rollback_reason", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["approval_request_id"], ["policy_approval_requests.id"]),
    )
    op.create_index("ix_policy_canary_rollouts_approval", "policy_canary_rollouts", ["approval_request_id"])
    op.create_index("ix_policy_canary_rollouts_status", "policy_canary_rollouts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_policy_canary_rollouts_status", table_name="policy_canary_rollouts")
    op.drop_index("ix_policy_canary_rollouts_approval", table_name="policy_canary_rollouts")
    op.drop_table("policy_canary_rollouts")
