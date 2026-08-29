"""Add bounded ticket bulk-action preview plans.

Revision ID: 20260729_0061
Revises: 20260729_0060
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0061"
down_revision: str | None = "20260729_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ticket_bulk_plans"):
        return
    op.create_table(
        "ticket_bulk_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="PREVIEWED",
        ),
        sa.Column("operation_json", sa.Text(), nullable=False),
        sa.Column("operation_sha256", sa.String(64), nullable=False),
        sa.Column("targets_json", sa.Text(), nullable=False),
        sa.Column("targets_sha256", sa.String(64), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_ticket_bulk_plans_actor_status",
        "ticket_bulk_plans",
        ["actor_user_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_ticket_bulk_plans_tenant_created",
        "ticket_bulk_plans",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ticket_bulk_plans_tenant_created",
        table_name="ticket_bulk_plans",
    )
    op.drop_index(
        "ix_ticket_bulk_plans_actor_status",
        table_name="ticket_bulk_plans",
    )
    op.drop_table("ticket_bulk_plans")
