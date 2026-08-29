"""Add versioned configuration packages and deployment evidence.

Revision ID: 20260729_0054
Revises: 20260729_0053
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0054"
down_revision: str | None = "20260729_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("configuration_packages"):
        return
    op.create_table(
        "configuration_packages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("latest_version_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_configuration_packages_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_configuration_packages_tenant_code"),
    )
    op.create_index(
        "ix_configuration_packages_tenant_status", "configuration_packages", ["tenant_id", "status"]
    )
    op.create_table(
        "configuration_package_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("package_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("source_environment", sa.String(80), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("signature_hmac_sha256", sa.String(64), nullable=True),
        sa.Column("validation_status", sa.String(16), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("component_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dependency_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("imported_from_artifact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        sa.Column("sealed_by_id", sa.String(36), nullable=True),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('DRAFT','SEALED','RETIRED')", name="ck_configuration_package_versions_status"),
        sa.CheckConstraint("validation_status IN ('VALID','INVALID')", name="ck_configuration_package_versions_validation"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["package_id"], ["configuration_packages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sealed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("package_id", "version_number", name="uq_configuration_package_versions_number"),
    )
    op.create_index(
        "ix_configuration_package_versions_package_status",
        "configuration_package_versions",
        ["package_id", "status"],
    )
    op.create_table(
        "configuration_deployments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("package_version_id", sa.String(36), nullable=False),
        sa.Column("target_environment", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="DRAFT"),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("plan_sha256", sa.String(64), nullable=True),
        sa.Column("target_fingerprint_sha256", sa.String(64), nullable=True),
        sa.Column("snapshot_before_json", sa.Text(), nullable=True),
        sa.Column("snapshot_before_sha256", sa.String(64), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_sha256", sa.String(64), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by_id", sa.String(36), nullable=True),
        sa.Column("reviewed_by_id", sa.String(36), nullable=True),
        sa.Column("applied_by_id", sa.String(36), nullable=True),
        sa.Column("rolled_back_by_id", sa.String(36), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('DRAFT','VALIDATED','PENDING_APPROVAL','APPROVED','REJECTED','APPLIED','FAILED','ROLLED_BACK')",
            name="ck_configuration_deployments_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["package_version_id"], ["configuration_package_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["applied_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rolled_back_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_configuration_deployments_idempotency"),
    )
    op.create_index(
        "ix_configuration_deployments_tenant_target_status",
        "configuration_deployments",
        ["tenant_id", "target_environment", "status"],
    )
    op.create_index(
        "ix_configuration_deployments_version_created",
        "configuration_deployments",
        ["package_version_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_configuration_deployments_version_created", table_name="configuration_deployments")
    op.drop_index("ix_configuration_deployments_tenant_target_status", table_name="configuration_deployments")
    op.drop_table("configuration_deployments")
    op.drop_index("ix_configuration_package_versions_package_status", table_name="configuration_package_versions")
    op.drop_table("configuration_package_versions")
    op.drop_index("ix_configuration_packages_tenant_status", table_name="configuration_packages")
    op.drop_table("configuration_packages")
