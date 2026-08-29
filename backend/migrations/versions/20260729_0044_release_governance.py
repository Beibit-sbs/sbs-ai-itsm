"""Add release train and deployment governance.

Revision ID: 20260729_0044
Revises: 20260729_0043
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0044"
down_revision: str | None = "20260729_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("release_records"):
        return
    op.create_table(
        "release_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("release_number", sa.String(40), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version_name", sa.String(100), nullable=False),
        sa.Column("release_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("service_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("target_release_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_plan", sa.Text(), nullable=False),
        sa.Column("rollback_plan", sa.Text(), nullable=False),
        sa.Column("communication_plan", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=True),
        sa.Column("owner_name", sa.String(200), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("go_no_go_status", sa.String(20), nullable=False),
        sa.Column("approved_decision_id", sa.String(36), nullable=True),
        sa.Column("actual_released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "release_type IN ('MAJOR','MINOR','PATCH','HOTFIX')",
            name="ck_release_records_type",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'DRAFT','PLANNING','READY','APPROVED','DEPLOYING','VALIDATING',"
            "'RELEASED','FAILED','ROLLED_BACK','CANCELLED')",
            name="ck_release_records_status",
        ),
        sa.CheckConstraint(
            "risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_release_records_risk",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "release_number",
            name="uq_release_records_tenant_number",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "service_name",
            "version_name",
            name="uq_release_records_tenant_service_version",
        ),
    )
    op.create_index(
        "ix_release_records_portfolio",
        "release_records",
        ["tenant_id", "status", "target_release_at"],
    )

    op.create_table(
        "release_environments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("environment_type", sa.String(20), nullable=False),
        sa.Column("promotion_order", sa.Integer(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("requires_smoke_test", sa.Boolean(), nullable=False),
        sa.Column("is_production", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("current_version", sa.String(100), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "environment_type IN ('DEVELOPMENT','TEST','STAGING','PRODUCTION','DR')",
            name="ck_release_environments_type",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_release_environments_tenant_code",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "promotion_order",
            name="uq_release_environments_tenant_order",
        ),
    )
    op.create_index(
        "ix_release_environments_active",
        "release_environments",
        ["tenant_id", "is_active", "promotion_order"],
    )

    op.create_table(
        "release_packages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("component_name", sa.String(200), nullable=False),
        sa.Column("package_type", sa.String(24), nullable=False),
        sa.Column("version_name", sa.String(100), nullable=False),
        sa.Column("artifact_uri", sa.String(1_000), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("build_reference", sa.String(500), nullable=True),
        sa.Column("dependencies_json", sa.JSON(), nullable=False),
        sa.Column("verification_status", sa.String(16), nullable=False),
        sa.Column("verification_evidence", sa.Text(), nullable=True),
        sa.Column("verified_by_id", sa.String(36), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "package_type IN ('APPLICATION','DATABASE','CONFIGURATION','INFRASTRUCTURE','DOCUMENTATION')",
            name="ck_release_packages_type",
        ),
        sa.CheckConstraint(
            "verification_status IN ('PENDING','VERIFIED','FAILED')",
            name="ck_release_packages_verification",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["release_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "release_id",
            "component_name",
            name="uq_release_packages_component",
        ),
    )
    op.create_index(
        "ix_release_packages_release",
        "release_packages",
        ["release_id", "verification_status"],
    )

    op.create_table(
        "release_change_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("change_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("added_by_id", sa.String(36), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["release_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["change_id"],
            ["change_requests.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "release_id",
            "change_id",
            name="uq_release_change_links_release_change",
        ),
        sa.UniqueConstraint(
            "release_id",
            "sequence",
            name="uq_release_change_links_sequence",
        ),
    )
    op.create_index(
        "ix_release_change_links_change",
        "release_change_links",
        ["tenant_id", "change_id"],
    )

    op.create_table(
        "release_dependencies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("dependency_release_id", sa.String(36), nullable=False),
        sa.Column("dependency_type", sa.String(16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "dependency_type IN ('REQUIRES','BLOCKS','FOLLOWS')",
            name="ck_release_dependencies_type",
        ),
        sa.CheckConstraint(
            "release_id <> dependency_release_id",
            name="ck_release_dependencies_not_self",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["release_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dependency_release_id"],
            ["release_records.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "release_id",
            "dependency_release_id",
            name="uq_release_dependencies_pair",
        ),
    )
    op.create_index(
        "ix_release_dependencies_release",
        "release_dependencies",
        ["tenant_id", "release_id"],
    )

    op.create_table(
        "release_gates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("gate_type", sa.String(20), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("decided_by_id", sa.String(36), nullable=True),
        sa.Column("decided_by_name", sa.String(200), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "gate_type IN ("
            "'CHANGES','PACKAGES','DEPENDENCIES','WINDOW','ROLLBACK','TEST',"
            "'SECURITY','BUSINESS','MANUAL')",
            name="ck_release_gates_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PASSED','FAILED','WAIVED')",
            name="ck_release_gates_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["release_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "release_id",
            "code",
            name="uq_release_gates_release_code",
        ),
    )
    op.create_index(
        "ix_release_gates_release",
        "release_gates",
        ["release_id", "status"],
    )

    op.create_table(
        "release_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("conditions_json", sa.JSON(), nullable=False),
        sa.Column("readiness_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("decided_by_id", sa.String(36), nullable=True),
        sa.Column("decided_by_name", sa.String(200), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "decision IN ('GO','NO_GO','CONDITIONAL')",
            name="ck_release_decisions_decision",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["release_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_release_decisions_release",
        "release_decisions",
        ["release_id", "created_at"],
    )

    op.create_table(
        "release_deployments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("environment_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deployed_version", sa.String(100), nullable=False),
        sa.Column("previous_version", sa.String(100), nullable=True),
        sa.Column("deployment_reference", sa.String(1_000), nullable=True),
        sa.Column("deployment_evidence", sa.Text(), nullable=True),
        sa.Column("validation_evidence", sa.Text(), nullable=True),
        sa.Column("smoke_test_status", sa.String(16), nullable=False),
        sa.Column("rollback_evidence", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("operator_id", sa.String(36), nullable=True),
        sa.Column("operator_name", sa.String(200), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('PLANNED','IN_PROGRESS','VALIDATING','SUCCEEDED','FAILED','ROLLED_BACK','CANCELLED')",
            name="ck_release_deployments_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["release_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["release_environments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "release_id",
            "environment_id",
            name="uq_release_deployments_release_environment",
        ),
    )
    op.create_index(
        "ix_release_deployments_operations",
        "release_deployments",
        ["tenant_id", "status", "scheduled_at"],
    )

    op.create_table(
        "release_timeline",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("actor_name", sa.String(200), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["release_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_release_timeline_release",
        "release_timeline",
        ["release_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_release_timeline_release", table_name="release_timeline")
    op.drop_table("release_timeline")
    op.drop_index(
        "ix_release_deployments_operations",
        table_name="release_deployments",
    )
    op.drop_table("release_deployments")
    op.drop_index("ix_release_decisions_release", table_name="release_decisions")
    op.drop_table("release_decisions")
    op.drop_index("ix_release_gates_release", table_name="release_gates")
    op.drop_table("release_gates")
    op.drop_index(
        "ix_release_dependencies_release",
        table_name="release_dependencies",
    )
    op.drop_table("release_dependencies")
    op.drop_index(
        "ix_release_change_links_change",
        table_name="release_change_links",
    )
    op.drop_table("release_change_links")
    op.drop_index("ix_release_packages_release", table_name="release_packages")
    op.drop_table("release_packages")
    op.drop_index(
        "ix_release_environments_active",
        table_name="release_environments",
    )
    op.drop_table("release_environments")
    op.drop_index("ix_release_records_portfolio", table_name="release_records")
    op.drop_table("release_records")
