"""Add typed configuration revision and rollback evidence.

Revision ID: 20260729_0059
Revises: 20260729_0058
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0059"
down_revision: str | None = "20260729_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("configuration_setting_revisions"):
        return
    op.create_table(
        "configuration_setting_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("scope_key", sa.String(48), nullable=False),
        sa.Column("setting_key", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("value_sha256", sa.String(64), nullable=False),
        sa.Column("changed_by_id", sa.String(36), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("rolled_back_from_revision", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
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
            ["changed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "scope_key",
            "setting_key",
            "revision",
            name="uq_configuration_setting_revisions_scope_key_revision",
        ),
    )
    op.create_index(
        "ix_configuration_setting_revisions_scope_created",
        "configuration_setting_revisions",
        ["scope_key", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_configuration_setting_revisions_scope_created",
        table_name="configuration_setting_revisions",
    )
    op.drop_table("configuration_setting_revisions")
