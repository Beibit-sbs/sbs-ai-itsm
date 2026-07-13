"""Create consumer_policy_overrides table.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-13 10:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consumer_policy_overrides",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("consumer_name", sa.String(80), nullable=False),
        sa.Column("policy_type", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("overrides_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("created_by_email", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consumer_name", "policy_type", name="uq_consumer_policy_override"),
    )
    op.create_index("ix_consumer_policy_overrides_consumer", "consumer_policy_overrides", ["consumer_name"])
    op.create_index("ix_consumer_policy_overrides_policy_type", "consumer_policy_overrides", ["policy_type"])


def downgrade() -> None:
    op.drop_index("ix_consumer_policy_overrides_policy_type", table_name="consumer_policy_overrides")
    op.drop_index("ix_consumer_policy_overrides_consumer", table_name="consumer_policy_overrides")
    op.drop_table("consumer_policy_overrides")
