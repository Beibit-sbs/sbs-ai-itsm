"""Create policy_approval_requests table.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-13 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0017"
down_revision = "20261121_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("policy_approval_requests"):
        return
    op.create_table(
        "policy_approval_requests",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("policy_type", sa.String(32), nullable=False),
        sa.Column("requested_by_email", sa.String(255), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("requested_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("approved_by_email", sa.String(255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("canary_percentage", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metrics_baseline_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_policy_approval_requests_status", "policy_approval_requests", ["status"])
    op.create_index("ix_policy_approval_requests_policy_type", "policy_approval_requests", ["policy_type"])


def downgrade() -> None:
    op.drop_index("ix_policy_approval_requests_policy_type", table_name="policy_approval_requests")
    op.drop_index("ix_policy_approval_requests_status", table_name="policy_approval_requests")
    op.drop_table("policy_approval_requests")
