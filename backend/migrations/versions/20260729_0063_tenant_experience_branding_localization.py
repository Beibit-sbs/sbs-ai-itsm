"""Add versioned tenant branding and localization profiles.

Revision ID: 20260729_0063
Revises: 20260729_0062
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0063"
down_revision: str | None = "20260729_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tenant_brand_assets"):
        op.create_table(
            "tenant_brand_assets",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("kind", sa.String(24), nullable=False),
            sa.Column("content_type", sa.String(80), nullable=False),
            sa.Column("payload", sa.LargeBinary(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.String(36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "kind IN ('LOGO')",
                name="ck_tenant_brand_assets_kind",
            ),
            sa.CheckConstraint(
                "size_bytes > 0 AND size_bytes <= 524288",
                name="ck_tenant_brand_assets_size",
            ),
            sa.CheckConstraint(
                "width >= 32 AND width <= 2048 AND height >= 32 AND height <= 2048",
                name="ck_tenant_brand_assets_dimensions",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "kind",
                "sha256",
                name="uq_tenant_brand_assets_tenant_kind_sha256",
            ),
        )
        op.create_index(
            "ix_tenant_brand_assets_tenant_created",
            "tenant_brand_assets",
            ["tenant_id", "created_at"],
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tenant_experience_profiles"):
        op.create_table(
            "tenant_experience_profiles",
            sa.Column("tenant_id", sa.String(36), primary_key=True),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("product_name", sa.String(80), nullable=False),
            sa.Column("short_name", sa.String(24), nullable=False),
            sa.Column("logo_asset_id", sa.String(36), nullable=True),
            sa.Column("primary_color", sa.String(7), nullable=False),
            sa.Column("accent_color", sa.String(7), nullable=False),
            sa.Column("surface_color", sa.String(7), nullable=False),
            sa.Column("text_color", sa.String(7), nullable=False),
            sa.Column("ui_locale", sa.String(16), nullable=False),
            sa.Column("format_locale", sa.String(16), nullable=False),
            sa.Column("timezone", sa.String(80), nullable=False),
            sa.Column("currency_code", sa.String(3), nullable=False),
            sa.Column("date_style", sa.String(12), nullable=False),
            sa.Column("hour_cycle", sa.String(4), nullable=False),
            sa.Column("first_day_of_week", sa.Integer(), nullable=False),
            sa.Column("terminology_json", sa.Text(), nullable=False),
            sa.Column("updated_by_id", sa.String(36), nullable=True),
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
            sa.CheckConstraint(
                "revision >= 0",
                name="ck_tenant_experience_profiles_revision",
            ),
            sa.CheckConstraint(
                "first_day_of_week IN (1, 7)",
                name="ck_tenant_experience_profiles_first_day",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["logo_asset_id"],
                ["tenant_brand_assets.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["updated_by_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tenant_experience_revisions"):
        op.create_table(
            "tenant_experience_revisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column("snapshot_sha256", sa.String(64), nullable=False),
            sa.Column("changed_by_id", sa.String(36), nullable=True),
            sa.Column("change_reason", sa.Text(), nullable=False),
            sa.Column("rolled_back_from_revision", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "revision > 0",
                name="ck_tenant_experience_revisions_revision",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["changed_by_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "revision",
                name="uq_tenant_experience_revisions_tenant_revision",
            ),
        )
        op.create_index(
            "ix_tenant_experience_revisions_tenant_created",
            "tenant_experience_revisions",
            ["tenant_id", "created_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("tenant_experience_revisions"):
        op.drop_index(
            "ix_tenant_experience_revisions_tenant_created",
            table_name="tenant_experience_revisions",
        )
        op.drop_table("tenant_experience_revisions")
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("tenant_experience_profiles"):
        op.drop_table("tenant_experience_profiles")
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("tenant_brand_assets"):
        op.drop_index(
            "ix_tenant_brand_assets_tenant_created",
            table_name="tenant_brand_assets",
        )
        op.drop_table("tenant_brand_assets")
