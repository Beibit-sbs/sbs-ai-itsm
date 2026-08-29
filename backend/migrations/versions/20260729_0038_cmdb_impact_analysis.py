"""Add cached CMDB impact analysis and immutable assessments.

Revision ID: 20260729_0038
Revises: 20260729_0037
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0038"
down_revision: str | None = "20260729_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("cmdb_impact_cache"):
        return
    op.create_table(
        "cmdb_impact_cache",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("root_ci_id", sa.String(length=36), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("graph_hash", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "direction IN ('UPSTREAM', 'DOWNSTREAM', 'BOTH')",
            name="ck_cmdb_impact_cache_direction",
        ),
        sa.ForeignKeyConstraint(
            ["root_ci_id"],
            ["assets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "root_ci_id",
            "direction",
            "max_depth",
            name="uq_cmdb_impact_cache_scope",
        ),
    )
    op.create_index(
        "ix_cmdb_impact_cache_tenant_expires",
        "cmdb_impact_cache",
        ["tenant_id", "expires_at"],
    )

    op.create_table(
        "cmdb_impact_assessments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=True),
        sa.Column("root_ci_ids_json", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("graph_hash", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("impacted_ci_count", sa.Integer(), nullable=False),
        sa.Column("impacted_service_count", sa.Integer(), nullable=False),
        sa.Column("critical_ci_count", sa.Integer(), nullable=False),
        sa.Column("collision_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type IN ('TICKET', 'PROBLEM', 'CHANGE', 'RELEASE')",
            name="ck_cmdb_impact_assessments_entity_type",
        ),
        sa.CheckConstraint(
            "direction IN ('UPSTREAM', 'DOWNSTREAM', 'BOTH')",
            name="ck_cmdb_impact_assessments_direction",
        ),
        sa.CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_cmdb_impact_assessments_severity",
        ),
        sa.CheckConstraint(
            "status IN ('CURRENT', 'SUPERSEDED')",
            name="ck_cmdb_impact_assessments_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cmdb_impact_assessments_entity",
        "cmdb_impact_assessments",
        ["tenant_id", "entity_type", "entity_id", "created_at"],
    )
    op.create_index(
        "ix_cmdb_impact_assessments_status",
        "cmdb_impact_assessments",
        ["tenant_id", "status"],
    )
    op.create_index(
        "uq_cmdb_impact_assessments_current",
        "cmdb_impact_assessments",
        ["tenant_id", "entity_type", "entity_id"],
        unique=True,
        postgresql_where=sa.text("status = 'CURRENT'"),
        sqlite_where=sa.text("status = 'CURRENT'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_cmdb_impact_assessments_current",
        table_name="cmdb_impact_assessments",
    )
    op.drop_index(
        "ix_cmdb_impact_assessments_status",
        table_name="cmdb_impact_assessments",
    )
    op.drop_index(
        "ix_cmdb_impact_assessments_entity",
        table_name="cmdb_impact_assessments",
    )
    op.drop_table("cmdb_impact_assessments")
    op.drop_index(
        "ix_cmdb_impact_cache_tenant_expires",
        table_name="cmdb_impact_cache",
    )
    op.drop_table("cmdb_impact_cache")
