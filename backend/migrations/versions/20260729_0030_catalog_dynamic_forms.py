"""Add versioned dynamic forms for service catalog items.

Revision ID: 20260729_0030
Revises: 20260728_0029
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260729_0030"
down_revision = "20260728_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "catalog_form_versions" in set(inspector.get_table_names()):
        return

    op.create_table(
        "catalog_form_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("catalog_item_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False),
        sa.Column("attachment_rules_json", sa.Text(), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_id", sa.String(length=36), nullable=True),
        sa.Column("published_by_id", sa.String(length=36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
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
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "catalog_item_id",
            "version",
            name="uq_catalog_form_versions_item_version",
        ),
    )
    op.create_index(
        "ix_catalog_form_versions_item_status",
        "catalog_form_versions",
        ["catalog_item_id", "status"],
    )
    op.create_index(
        "ix_catalog_form_versions_tenant_status",
        "catalog_form_versions",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "catalog_form_versions" in set(inspector.get_table_names()):
        op.drop_table("catalog_form_versions")
