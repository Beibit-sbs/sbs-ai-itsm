"""Add catalog self-service personalization.

Revision ID: 20260729_0032
Revises: 20260729_0031
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260729_0032"
down_revision = "20260729_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "catalog_user_preferences" in set(inspector.get_table_names()):
        return

    op.create_table(
        "catalog_user_preferences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("catalog_item_id", sa.String(length=36), nullable=False),
        sa.Column(
            "is_favorite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"],
            ["catalog_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "catalog_item_id",
            name="uq_catalog_user_preferences_user_item",
        ),
    )
    op.create_index(
        "ix_catalog_user_preferences_user_favorite",
        "catalog_user_preferences",
        ["user_id", "is_favorite"],
    )
    op.create_index(
        "ix_catalog_user_preferences_user_recent",
        "catalog_user_preferences",
        ["user_id", "last_requested_at", "last_viewed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_user_preferences_user_recent",
        table_name="catalog_user_preferences",
    )
    op.drop_index(
        "ix_catalog_user_preferences_user_favorite",
        table_name="catalog_user_preferences",
    )
    op.drop_table("catalog_user_preferences")
