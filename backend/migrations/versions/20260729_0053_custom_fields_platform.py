"""Add tenant custom fields platform.

Revision ID: 20260729_0053
Revises: 20260729_0052
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0053"
down_revision: str | None = "20260729_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("custom_field_sets"):
        return
    op.create_table(
        "custom_field_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.String(24), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="PAUSED",
        ),
        sa.Column(
            "applicability_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "latest_version_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("draft_version_number", sa.Integer(), nullable=True),
        sa.Column("published_version_number", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", sa.String(36), nullable=True),
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
            "entity_type IN ('ticket','asset','change','problem','request')",
            name="ck_custom_field_sets_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','PAUSED','ARCHIVED')",
            name="ck_custom_field_sets_status",
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
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_custom_field_sets_tenant_code",
        ),
    )
    op.create_index(
        "ix_custom_field_sets_tenant_entity_status",
        "custom_field_sets",
        ["tenant_id", "entity_type", "status"],
    )

    op.create_table(
        "custom_field_set_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("field_set_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False),
        sa.Column("schema_sha256", sa.String(64), nullable=False),
        sa.Column("validation_status", sa.String(16), nullable=False),
        sa.Column(
            "validation_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("based_on_version_number", sa.Integer(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column(
            "breaking_change",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        sa.Column("published_by_id", sa.String(36), nullable=True),
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
            "status IN ('DRAFT','PUBLISHED','RETIRED')",
            name="ck_custom_field_set_versions_status",
        ),
        sa.CheckConstraint(
            "validation_status IN ('VALID','INVALID')",
            name="ck_custom_field_set_versions_validation",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["field_set_id"],
            ["custom_field_sets.id"],
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
            ["published_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "field_set_id",
            "version_number",
            name="uq_custom_field_set_versions_number",
        ),
    )
    op.create_index(
        "ix_custom_field_set_versions_set_status",
        "custom_field_set_versions",
        ["field_set_id", "status"],
    )

    op.create_table(
        "custom_field_values",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("field_set_id", sa.String(36), nullable=False),
        sa.Column("field_set_version_id", sa.String(36), nullable=False),
        sa.Column("field_set_version_number", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(24), nullable=False),
        sa.Column("entity_id", sa.String(120), nullable=False),
        sa.Column("values_json", sa.Text(), nullable=False),
        sa.Column("values_sha256", sa.String(64), nullable=False),
        sa.Column(
            "search_text",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", sa.String(36), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["field_set_id"],
            ["custom_field_sets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["field_set_version_id"],
            ["custom_field_set_versions.id"],
            ondelete="RESTRICT",
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
        sa.UniqueConstraint(
            "field_set_id",
            "entity_type",
            "entity_id",
            name="uq_custom_field_values_set_entity",
        ),
    )
    op.create_index(
        "ix_custom_field_values_tenant_entity",
        "custom_field_values",
        ["tenant_id", "entity_type", "entity_id"],
    )
    op.create_index(
        "ix_custom_field_values_set_updated",
        "custom_field_values",
        ["field_set_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_custom_field_values_set_updated",
        table_name="custom_field_values",
    )
    op.drop_index(
        "ix_custom_field_values_tenant_entity",
        table_name="custom_field_values",
    )
    op.drop_table("custom_field_values")
    op.drop_index(
        "ix_custom_field_set_versions_set_status",
        table_name="custom_field_set_versions",
    )
    op.drop_table("custom_field_set_versions")
    op.drop_index(
        "ix_custom_field_sets_tenant_entity_status",
        table_name="custom_field_sets",
    )
    op.drop_table("custom_field_sets")
