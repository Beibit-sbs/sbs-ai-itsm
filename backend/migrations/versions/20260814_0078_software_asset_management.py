"""Add governed Software Asset Management domain.

Revision ID: 20260814_0078
Revises: 20260814_0077
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0078"
down_revision: str | None = "20260814_0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "software_products" not in existing:
        op.create_table(
            "software_products",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.String(36),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("catalog_key", sa.String(64), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("publisher", sa.String(200), nullable=False),
            sa.Column("version", sa.String(100), nullable=False),
            sa.Column("edition", sa.String(100), nullable=True),
            sa.Column("category", sa.String(120), nullable=True),
            sa.Column("sku", sa.String(120), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("is_prohibited", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("prohibited_reason", sa.Text(), nullable=True),
            sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("status IN ('ACTIVE','RETIRED')", name="ck_software_products_status"),
            sa.UniqueConstraint("tenant_id", "catalog_key", name="uq_software_products_tenant_catalog_key"),
        )
        op.create_index(
            "ix_software_products_tenant_status",
            "software_products",
            ["tenant_id", "status", "is_prohibited"],
        )

    if "software_licenses" not in existing:
        op.create_table(
            "software_licenses",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.String(36),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "product_id",
                sa.String(36),
                sa.ForeignKey("software_products.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("license_reference", sa.String(160), nullable=False),
            sa.Column("license_type", sa.String(24), nullable=False),
            sa.Column("purchased_quantity", sa.Integer(), nullable=False),
            sa.Column("vendor", sa.String(200), nullable=True),
            sa.Column("contract_reference", sa.String(160), nullable=True),
            sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("renewal_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("unit_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="KZT"),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "license_type IN ('NAMED_USER','DEVICE','CONCURRENT','SUBSCRIPTION','PERPETUAL','OEM','ENTERPRISE')",
                name="ck_software_licenses_type",
            ),
            sa.CheckConstraint(
                "status IN ('ACTIVE','SUSPENDED','EXPIRED','RETIRED')",
                name="ck_software_licenses_status",
            ),
            sa.CheckConstraint("purchased_quantity >= 0", name="ck_software_licenses_quantity"),
            sa.CheckConstraint("unit_cost >= 0", name="ck_software_licenses_unit_cost"),
        )
        op.create_index(
            "ix_software_licenses_tenant_product",
            "software_licenses",
            ["tenant_id", "product_id", "status"],
        )
        op.create_index(
            "ix_software_licenses_tenant_renewal",
            "software_licenses",
            ["tenant_id", "renewal_at", "expires_at"],
        )

    if "software_installations" not in existing:
        op.create_table(
            "software_installations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.String(36),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "product_id",
                sa.String(36),
                sa.ForeignKey("software_products.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "asset_id",
                sa.String(36),
                sa.ForeignKey("assets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "assigned_user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("detected_version", sa.String(100), nullable=True),
            sa.Column("source", sa.String(64), nullable=False, server_default="MANUAL"),
            sa.Column("authorization_status", sa.String(16), nullable=False, server_default="AUTHORIZED"),
            sa.Column("authorization_reason", sa.Text(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "authorization_status IN ('AUTHORIZED','UNAUTHORIZED','EXEMPTED')",
                name="ck_software_installations_authorization",
            ),
            sa.CheckConstraint("status IN ('ACTIVE','REMOVED')", name="ck_software_installations_status"),
            sa.UniqueConstraint(
                "tenant_id",
                "product_id",
                "asset_id",
                name="uq_software_installations_tenant_product_asset",
            ),
        )
        op.create_index(
            "ix_software_installations_tenant_product",
            "software_installations",
            ["tenant_id", "product_id", "status"],
        )
        op.create_index(
            "ix_software_installations_tenant_authorization",
            "software_installations",
            ["tenant_id", "authorization_status", "status"],
        )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in (
        "software_installations",
        "software_licenses",
        "software_products",
    ):
        if table_name in existing:
            op.drop_table(table_name)
