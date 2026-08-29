"""Add production asset discovery connectors and stale review.

Revision ID: 20260729_0050
Revises: 20260729_0049
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0050"
down_revision: str | None = "20260729_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("asset_discovery_connectors"):
        return
    op.create_table(
        "asset_discovery_connectors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("cmdb_source_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("auth_type", sa.String(32), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("credential_encrypted", sa.Text(), nullable=True),
        sa.Column("credential_hint", sa.String(32), nullable=True),
        sa.Column(
            "credential_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "last_tested_credential_version",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "configuration_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "schedule_minutes",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column(
            "auto_apply",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "missing_threshold_runs",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        sa.Column(
            "max_records",
            sa.Integer(),
            nullable=False,
            server_default="5000",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "successful_runs",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failed_runs",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "discovered_records",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
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
            "provider IN ('INTUNE','AZURE_RESOURCE_GRAPH',"
            "'SCCM_ADMIN_SERVICE','LANSWEEPER_DATA_API')",
            name="ck_asset_discovery_connectors_provider",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','REVOKED')",
            name="ck_asset_discovery_connectors_status",
        ),
        sa.CheckConstraint(
            "auth_type IN ('OAUTH_CLIENT_CREDENTIALS','API_TOKEN',"
            "'BASIC','BEARER')",
            name="ck_asset_discovery_connectors_auth_type",
        ),
        sa.CheckConstraint(
            "schedule_minutes >= 5",
            name="ck_asset_discovery_connectors_schedule",
        ),
        sa.CheckConstraint(
            "missing_threshold_runs >= 1",
            name="ck_asset_discovery_connectors_missing_threshold",
        ),
        sa.CheckConstraint(
            "max_records >= 1 AND max_records <= 50000",
            name="ck_asset_discovery_connectors_max_records",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cmdb_source_id"],
            ["cmdb_sources.id"],
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
            "cmdb_source_id",
            name="uq_asset_discovery_connectors_source",
        ),
    )
    op.create_index(
        "ix_asset_discovery_connectors_due",
        "asset_discovery_connectors",
        ["status", "next_run_at"],
    )
    op.create_index(
        "ix_asset_discovery_connectors_tenant_status",
        "asset_discovery_connectors",
        ["tenant_id", "status"],
    )

    op.create_table(
        "asset_discovery_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("trigger_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="4"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("requested_by_id", sa.String(36), nullable=True),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "records_fetched",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "complete_snapshot",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "reconciliation_run_ids_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "unchanged_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "ambiguous_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stale_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_cursor", sa.Text(), nullable=True),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "trigger_type IN ('MANUAL','SCHEDULED','TEST')",
            name="ck_asset_discovery_runs_trigger",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','RETRY','COMPLETED',"
            "'COMPLETED_WITH_ERRORS','FAILED','DEAD_LETTER','CANCELLED')",
            name="ck_asset_discovery_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["asset_discovery_connectors.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "connector_id",
            "idempotency_key",
            name="uq_asset_discovery_runs_connector_key",
        ),
    )
    op.create_index(
        "ix_asset_discovery_runs_queue",
        "asset_discovery_runs",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_asset_discovery_runs_connector_created",
        "asset_discovery_runs",
        ["connector_id", "created_at"],
    )
    op.create_index(
        "ix_asset_discovery_runs_tenant_status",
        "asset_discovery_runs",
        ["tenant_id", "status"],
    )

    op.add_column(
        "cmdb_source_identities",
        sa.Column("last_seen_run_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "cmdb_source_identities",
        sa.Column(
            "discovery_state",
            sa.String(16),
            nullable=False,
            server_default="ACTIVE",
        ),
    )
    op.add_column(
        "cmdb_source_identities",
        sa.Column(
            "missing_run_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "cmdb_source_identities",
        sa.Column("first_missing_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cmdb_source_identities",
        sa.Column("last_missing_at", sa.DateTime(timezone=True), nullable=True),
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("cmdb_source_identities") as batch_op:
            batch_op.create_foreign_key(
                "fk_cmdb_source_identities_last_seen_run",
                "asset_discovery_runs",
                ["last_seen_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        op.create_foreign_key(
            "fk_cmdb_source_identities_last_seen_run",
            "cmdb_source_identities",
            "asset_discovery_runs",
            ["last_seen_run_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "asset_discovery_stale_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector_id", sa.String(36), nullable=False),
        sa.Column("source_identity_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "missing_run_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("first_missing_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_missing_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_by_id", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('OPEN','DISMISSED','RETIRED','RECOVERED')",
            name="ck_asset_discovery_stale_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["asset_discovery_connectors.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_identity_id"],
            ["cmdb_source_identities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "source_identity_id",
            name="uq_asset_discovery_stale_identity",
        ),
    )
    op.create_index(
        "ix_asset_discovery_stale_tenant_status",
        "asset_discovery_stale_candidates",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_asset_discovery_stale_connector_status",
        "asset_discovery_stale_candidates",
        ["connector_id", "status"],
    )

    defaulted_columns = (
        (
            "asset_discovery_connectors",
            (
                "credential_version",
                "configuration_json",
                "schedule_minutes",
                "auto_apply",
                "missing_threshold_runs",
                "max_records",
                "version",
                "successful_runs",
                "failed_runs",
                "discovered_records",
            ),
        ),
        (
            "asset_discovery_runs",
            (
                "attempts",
                "max_attempts",
                "pages_fetched",
                "records_fetched",
                "complete_snapshot",
                "reconciliation_run_ids_json",
                "created_count",
                "updated_count",
                "unchanged_count",
                "ambiguous_count",
                "invalid_count",
                "missing_count",
                "stale_count",
                "result_json",
            ),
        ),
        (
            "asset_discovery_stale_candidates",
            ("missing_run_count", "version"),
        ),
    )
    if bind.dialect.name == "sqlite":
        for table, columns in defaulted_columns:
            with op.batch_alter_table(table) as batch_op:
                for column in columns:
                    batch_op.alter_column(column, server_default=None)
        with op.batch_alter_table("cmdb_source_identities") as batch_op:
            batch_op.alter_column("discovery_state", server_default=None)
            batch_op.alter_column("missing_run_count", server_default=None)
    else:
        for table, columns in defaulted_columns:
            for column in columns:
                op.alter_column(table, column, server_default=None)
        op.alter_column(
            "cmdb_source_identities",
            "discovery_state",
            server_default=None,
        )
        op.alter_column(
            "cmdb_source_identities",
            "missing_run_count",
            server_default=None,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_asset_discovery_stale_connector_status",
        table_name="asset_discovery_stale_candidates",
    )
    op.drop_index(
        "ix_asset_discovery_stale_tenant_status",
        table_name="asset_discovery_stale_candidates",
    )
    op.drop_table("asset_discovery_stale_candidates")
    op.drop_constraint(
        "fk_cmdb_source_identities_last_seen_run",
        "cmdb_source_identities",
        type_="foreignkey",
    )
    for column in (
        "last_missing_at",
        "first_missing_at",
        "missing_run_count",
        "discovery_state",
        "last_seen_run_id",
    ):
        op.drop_column("cmdb_source_identities", column)
    op.drop_index(
        "ix_asset_discovery_runs_tenant_status",
        table_name="asset_discovery_runs",
    )
    op.drop_index(
        "ix_asset_discovery_runs_connector_created",
        table_name="asset_discovery_runs",
    )
    op.drop_index(
        "ix_asset_discovery_runs_queue",
        table_name="asset_discovery_runs",
    )
    op.drop_table("asset_discovery_runs")
    op.drop_index(
        "ix_asset_discovery_connectors_tenant_status",
        table_name="asset_discovery_connectors",
    )
    op.drop_index(
        "ix_asset_discovery_connectors_due",
        table_name="asset_discovery_connectors",
    )
    op.drop_table("asset_discovery_connectors")
