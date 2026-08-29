"""Add tenant-safe service catalog lifecycle foundation.

Revision ID: 20260728_0029
Revises: 20260727_0028
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260728_0029"
down_revision = "20260727_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    if "service_categories" not in existing:
        op.create_table(
            "service_categories",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "code", name="uq_service_categories_tenant_code"),
        )
        op.create_index(
            "ix_service_categories_tenant_status",
            "service_categories",
            ["tenant_id", "status"],
        )

    if "catalog_services" not in existing:
        op.create_table(
            "catalog_services",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("category_id", sa.String(length=36), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=180), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("owner_user_id", sa.String(length=36), nullable=True),
            sa.Column("support_group", sa.String(length=160), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["category_id"], ["service_categories.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "code", name="uq_catalog_services_tenant_code"),
        )
        op.create_index("ix_catalog_services_category_id", "catalog_services", ["category_id"])
        op.create_index(
            "ix_catalog_services_tenant_status", "catalog_services", ["tenant_id", "status"]
        )

    if "service_offerings" not in existing:
        op.create_table(
            "service_offerings",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("service_id", sa.String(length=36), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=180), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("support_group", sa.String(length=160), nullable=True),
            sa.Column("expected_fulfillment_minutes", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["service_id"], ["catalog_services.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "code", name="uq_service_offerings_tenant_code"),
        )
        op.create_index("ix_service_offerings_service_id", "service_offerings", ["service_id"])
        op.create_index(
            "ix_service_offerings_tenant_status", "service_offerings", ["tenant_id", "status"]
        )

    if "catalog_items" not in existing:
        op.create_table(
            "catalog_items",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("category_id", sa.String(length=36), nullable=False),
            sa.Column("service_id", sa.String(length=36), nullable=False),
            sa.Column("offering_id", sa.String(length=36), nullable=True),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("short_description", sa.String(length=320), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("lifecycle_status", sa.String(length=24), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("owner_user_id", sa.String(length=36), nullable=True),
            sa.Column("support_group", sa.String(length=160), nullable=True),
            sa.Column("expected_delivery_minutes", sa.Integer(), nullable=False),
            sa.Column("approval_required", sa.Boolean(), nullable=False),
            sa.Column("entitlement_rules_json", sa.Text(), nullable=False),
            sa.Column("created_by_id", sa.String(length=36), nullable=True),
            sa.Column("updated_by_id", sa.String(length=36), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["category_id"], ["service_categories.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["offering_id"], ["service_offerings.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["service_id"], ["catalog_services.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "code", name="uq_catalog_items_tenant_code"),
        )
        op.create_index("ix_catalog_items_category_id", "catalog_items", ["category_id"])
        op.create_index("ix_catalog_items_service_id", "catalog_items", ["service_id"])
        op.create_index(
            "ix_catalog_items_tenant_status", "catalog_items", ["tenant_id", "lifecycle_status"]
        )

    if "catalog_item_history" not in existing:
        op.create_table(
            "catalog_item_history",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("catalog_item_id", sa.String(length=36), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("lifecycle_status", sa.String(length=24), nullable=False),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column("actor_user_id", sa.String(length=36), nullable=True),
            sa.Column("actor_name", sa.String(length=200), nullable=False),
            sa.Column("actor_email", sa.String(length=255), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_catalog_item_history_item_version",
            "catalog_item_history",
            ["catalog_item_id", "version"],
        )
        op.create_index(
            "ix_catalog_item_history_tenant_id", "catalog_item_history", ["tenant_id"]
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table_name in (
        "catalog_item_history",
        "catalog_items",
        "service_offerings",
        "catalog_services",
        "service_categories",
    ):
        if table_name in existing:
            op.drop_table(table_name)
