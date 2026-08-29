"""Add governed localized content variants.

Revision ID: 20260729_0064
Revises: 20260729_0063
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0064"
down_revision: str | None = "20260729_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("localized_content_variants"):
        return
    op.create_table(
        "localized_content_variants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        sa.Column("reviewed_by_id", sa.String(36), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
            "resource_type IN ('KNOWLEDGE_ARTICLE', 'NOTIFICATION_TEMPLATE')",
            name="ck_localized_content_resource_type",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'IN_REVIEW', 'PUBLISHED', 'REJECTED', 'RETIRED')",
            name="ck_localized_content_status",
        ),
        sa.CheckConstraint(
            "version > 0 AND revision > 0",
            name="ck_localized_content_versions",
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
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            "locale",
            "version",
            name="uq_localized_content_resource_locale_version",
        ),
    )
    op.create_index(
        "ix_localized_content_resolution",
        "localized_content_variants",
        ["tenant_id", "resource_type", "resource_id", "locale", "status"],
    )
    op.create_index(
        "ix_localized_content_tenant_updated",
        "localized_content_variants",
        ["tenant_id", "updated_at"],
    )
    op.create_index(
        "uq_localized_content_single_published",
        "localized_content_variants",
        ["tenant_id", "resource_type", "resource_id", "locale"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
        sqlite_where=sa.text("status = 'PUBLISHED'"),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("localized_content_variants"):
        return
    op.drop_index(
        "uq_localized_content_single_published",
        table_name="localized_content_variants",
    )
    op.drop_index(
        "ix_localized_content_tenant_updated",
        table_name="localized_content_variants",
    )
    op.drop_index(
        "ix_localized_content_resolution",
        table_name="localized_content_variants",
    )
    op.drop_table("localized_content_variants")
