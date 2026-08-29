"""Add CMDB quality findings, snapshots, and certification campaigns.

Revision ID: 20260729_0039
Revises: 20260729_0038
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0039"
down_revision: str | None = "20260729_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("cmdb_quality_snapshots"):
        return
    op.create_table(
        "cmdb_quality_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("completeness_score", sa.Float(), nullable=False),
        sa.Column("correctness_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("duplicate_score", sa.Float(), nullable=False),
        sa.Column("orphan_score", sa.Float(), nullable=False),
        sa.Column("ci_count", sa.Integer(), nullable=False),
        sa.Column("open_finding_count", sa.Integer(), nullable=False),
        sa.Column("critical_finding_count", sa.Integer(), nullable=False),
        sa.Column("resolved_finding_count", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
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
        "ix_cmdb_quality_snapshots_tenant_created",
        "cmdb_quality_snapshots",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "cmdb_quality_findings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("rule_code", sa.String(length=80), nullable=False),
        sa.Column("dimension", sa.String(length=24), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
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
            "dimension IN ('COMPLETENESS','CORRECTNESS','FRESHNESS',"
            "'DUPLICATE','ORPHAN','CERTIFICATION')",
            name="ck_cmdb_quality_findings_dimension",
        ),
        sa.CheckConstraint(
            "severity IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_cmdb_quality_findings_severity",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','IN_PROGRESS','RESOLVED','WAIVED')",
            name="ck_cmdb_quality_findings_status",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_snapshot_id"],
            ["cmdb_quality_snapshots.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "rule_code",
            "subject_type",
            "subject_id",
            name="uq_cmdb_quality_findings_subject_rule",
        ),
    )
    op.create_index(
        "ix_cmdb_quality_findings_tenant_queue",
        "cmdb_quality_findings",
        ["tenant_id", "status", "severity", "due_at"],
    )
    op.create_index(
        "ix_cmdb_quality_findings_owner",
        "cmdb_quality_findings",
        ["tenant_id", "owner_user_id", "status"],
    )

    op.create_table(
        "cmdb_certification_campaigns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
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
            "status IN ('DRAFT','ACTIVE','COMPLETED','CANCELLED')",
            name="ck_cmdb_certification_campaigns_status",
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
        "ix_cmdb_certification_campaigns_tenant_status",
        "cmdb_certification_campaigns",
        ["tenant_id", "status", "due_at"],
    )

    op.create_table(
        "cmdb_certification_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("asset_version", sa.Integer(), nullable=False),
        sa.Column("asset_snapshot_json", sa.Text(), nullable=False),
        sa.Column("asset_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("certifier_user_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_by_id", sa.String(length=36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
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
            "status IN ('PENDING','CERTIFIED','REJECTED')",
            name="ck_cmdb_certification_items_status",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["cmdb_certification_campaigns.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["certifier_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "asset_id",
            name="uq_cmdb_certification_items_campaign_asset",
        ),
    )
    op.create_index(
        "ix_cmdb_certification_items_campaign_status",
        "cmdb_certification_items",
        ["campaign_id", "status"],
    )
    op.create_index(
        "ix_cmdb_certification_items_certifier",
        "cmdb_certification_items",
        ["tenant_id", "certifier_user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cmdb_certification_items_certifier",
        table_name="cmdb_certification_items",
    )
    op.drop_index(
        "ix_cmdb_certification_items_campaign_status",
        table_name="cmdb_certification_items",
    )
    op.drop_table("cmdb_certification_items")
    op.drop_index(
        "ix_cmdb_certification_campaigns_tenant_status",
        table_name="cmdb_certification_campaigns",
    )
    op.drop_table("cmdb_certification_campaigns")
    op.drop_index(
        "ix_cmdb_quality_findings_owner",
        table_name="cmdb_quality_findings",
    )
    op.drop_index(
        "ix_cmdb_quality_findings_tenant_queue",
        table_name="cmdb_quality_findings",
    )
    op.drop_table("cmdb_quality_findings")
    op.drop_index(
        "ix_cmdb_quality_snapshots_tenant_created",
        table_name="cmdb_quality_snapshots",
    )
    op.drop_table("cmdb_quality_snapshots")
