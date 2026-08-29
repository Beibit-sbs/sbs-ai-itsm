"""Add permission-aware global-search saved views.

Revision ID: 20260729_0060
Revises: 20260729_0059
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0060"
down_revision: str | None = "20260729_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("saved_search_views"):
        return
    op.create_table(
        "saved_search_views",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("query_json", sa.Text(), nullable=False),
        sa.Column("query_sha256", sa.String(64), nullable=False),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("shared_role_codes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
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
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "owner_user_id",
            "name",
            name="uq_saved_search_views_owner_name",
        ),
    )
    op.create_index(
        "ix_saved_search_views_tenant_shared",
        "saved_search_views",
        ["tenant_id", "is_shared"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_saved_search_views_tenant_shared",
        table_name="saved_search_views",
    )
    op.drop_table("saved_search_views")
