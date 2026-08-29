"""Add authentication session context.

Revision ID: 20260729_0065
Revises: 20260729_0064
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0065"
down_revision: str | None = "20260729_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]
        for column in inspector.get_columns("auth_sessions")
    }
    with op.batch_alter_table("auth_sessions") as batch_op:
        if "ip_address" not in columns:
            batch_op.add_column(
                sa.Column("ip_address", sa.String(length=64), nullable=True)
            )
        if "user_agent" not in columns:
            batch_op.add_column(sa.Column("user_agent", sa.Text(), nullable=True))
        if "auth_method" not in columns:
            batch_op.add_column(
                sa.Column("auth_method", sa.String(length=32), nullable=True)
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]
        for column in inspector.get_columns("auth_sessions")
    }
    with op.batch_alter_table("auth_sessions") as batch_op:
        if "auth_method" in columns:
            batch_op.drop_column("auth_method")
        if "user_agent" in columns:
            batch_op.drop_column("user_agent")
        if "ip_address" in columns:
            batch_op.drop_column("ip_address")
