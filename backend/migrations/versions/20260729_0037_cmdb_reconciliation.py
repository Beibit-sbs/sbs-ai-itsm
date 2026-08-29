"""Add CMDB source governance and reconciliation ledger.

Revision ID: 20260729_0037
Revises: 20260729_0036
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260729_0037"
down_revision = "20260729_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("cmdb_sources"):
        return
    op.create_table(
        "cmdb_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("external_system_id", sa.String(length=36), nullable=True),
        sa.Column("default_class_id", sa.String(length=36), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("identification_rules_json", sa.Text(), nullable=False),
        sa.Column("authoritative_fields_json", sa.Text(), nullable=False),
        sa.Column("claim_unowned_fields", sa.Boolean(), nullable=False),
        sa.Column("stale_after_hours", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_id", sa.String(length=36), nullable=True),
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
            "source_type IN ('FILE', 'API', 'DISCOVERY', 'MANUAL')",
            name="ck_cmdb_sources_type",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE')",
            name="ck_cmdb_sources_status",
        ),
        sa.CheckConstraint(
            "priority >= 1 AND priority <= 1000",
            name="ck_cmdb_sources_priority",
        ),
        sa.CheckConstraint(
            "stale_after_hours >= 1",
            name="ck_cmdb_sources_stale_hours",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["default_class_id"],
            ["ci_classes.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["external_system_id"],
            ["external_systems.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_cmdb_sources_tenant_code",
        ),
    )
    op.create_index(
        "ix_cmdb_sources_tenant_status",
        "cmdb_sources",
        ["tenant_id", "status"],
    )

    op.create_table(
        "cmdb_reconciliation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_count", sa.Integer(), nullable=False),
        sa.Column("create_count", sa.Integer(), nullable=False),
        sa.Column("update_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("ambiguous_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
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
            "mode IN ('PREVIEW', 'APPLY')",
            name="ck_cmdb_reconciliation_runs_mode",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'PENDING','PREVIEWED','RUNNING','COMPLETED',"
            "'COMPLETED_WITH_ERRORS','FAILED'"
            ")",
            name="ck_cmdb_reconciliation_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["cmdb_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "idempotency_key",
            name="uq_cmdb_reconciliation_runs_source_key",
        ),
    )
    op.create_index(
        "ix_cmdb_reconciliation_runs_tenant_created",
        "cmdb_reconciliation_runs",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_cmdb_reconciliation_runs_source_status",
        "cmdb_reconciliation_runs",
        ["source_id", "status"],
    )

    op.create_table(
        "cmdb_source_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["cmdb_sources.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "external_id",
            name="uq_cmdb_source_identities_source_external",
        ),
    )
    op.create_index(
        "ix_cmdb_source_identities_tenant_asset",
        "cmdb_source_identities",
        ["tenant_id", "asset_id"],
    )

    op.create_table(
        "cmdb_reconciliation_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("normalized_json", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("matched_ci_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_ids_json", sa.Text(), nullable=False),
        sa.Column("errors_json", sa.Text(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ("
            "'CREATE','UPDATE','UNCHANGED','AMBIGUOUS','INVALID','SKIPPED',"
            "'APPLIED_CREATED','APPLIED_UPDATED'"
            ")",
            name="ck_cmdb_reconciliation_records_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["matched_ci_id"],
            ["assets.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["cmdb_reconciliation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "row_number",
            name="uq_cmdb_reconciliation_records_run_row",
        ),
        sa.UniqueConstraint(
            "run_id",
            "external_id",
            name="uq_cmdb_reconciliation_records_run_external",
        ),
    )
    op.create_index(
        "ix_cmdb_reconciliation_records_run_outcome",
        "cmdb_reconciliation_records",
        ["run_id", "outcome"],
    )
    op.create_index(
        "ix_cmdb_reconciliation_records_tenant_match",
        "cmdb_reconciliation_records",
        ["tenant_id", "matched_ci_id"],
    )

    op.create_table(
        "cmdb_field_ownership",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("field_name", sa.String(length=160), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_priority", sa.Integer(), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["cmdb_sources.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_id",
            "field_name",
            name="uq_cmdb_field_ownership_asset_field",
        ),
    )
    op.create_index(
        "ix_cmdb_field_ownership_tenant_source",
        "cmdb_field_ownership",
        ["tenant_id", "source_id"],
    )

    op.create_table(
        "ci_duplicate_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=True),
        sa.Column("primary_ci_id", sa.String(length=36), nullable=False),
        sa.Column("duplicate_ci_id", sa.String(length=36), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("resolved_by_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('OPEN', 'MERGED', 'DISMISSED')",
            name="ck_ci_duplicate_candidates_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_ci_duplicate_candidates_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_ci_id"],
            ["assets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["primary_ci_id"],
            ["assets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["cmdb_reconciliation_records.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["cmdb_reconciliation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "primary_ci_id",
            "duplicate_ci_id",
            name="uq_ci_duplicate_candidates_run_pair",
        ),
    )
    op.create_index(
        "ix_ci_duplicate_candidates_tenant_status",
        "ci_duplicate_candidates",
        ["tenant_id", "status"],
    )

    bind = op.get_bind()
    now = datetime.now(UTC)
    for tenant_id in bind.execute(sa.text("SELECT id FROM tenants")).scalars():
        generic_class_id = bind.execute(
            sa.text(
                """
                SELECT id
                FROM ci_classes
                WHERE tenant_id = :tenant_id AND code = 'GENERIC_ASSET'
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar_one_or_none()
        actor_id = bind.execute(
            sa.text(
                """
                SELECT id
                FROM users
                WHERE tenant_id = :tenant_id AND is_active = :is_active
                ORDER BY created_at, id
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "is_active": True},
        ).scalar_one_or_none()
        bind.execute(
            sa.text(
                """
                INSERT INTO cmdb_sources (
                    id, tenant_id, external_system_id, default_class_id,
                    code, name, description, source_type, priority,
                    identification_rules_json, authoritative_fields_json,
                    claim_unowned_fields, stale_after_hours, status, version,
                    last_run_at, last_success_at, created_by_id, updated_by_id,
                    created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, NULL, :default_class_id,
                    'EXCEL_ASSET_IMPORT', 'Excel Asset Import',
                    'Governed source for the built-in Excel asset import.',
                    'FILE', 300, :identification_rules,
                    :authoritative_fields, :claim_unowned_fields, 720,
                    'ACTIVE', 1, NULL, NULL, :actor_id, :actor_id,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "default_class_id": generic_class_id,
                "identification_rules": json.dumps(
                    ["inventory_number", "serial_number", "asset_tag"],
                    separators=(",", ":"),
                ),
                "authoritative_fields": json.dumps(
                    [
                        "name",
                        "inventory_number",
                        "original_type",
                        "lifecycle_status",
                        "location",
                        "assigned_to_name",
                        "purchase_date",
                        "purchase_cost",
                        "current_cost",
                        "depreciation_amount",
                        "residual_value",
                        "purchase_year",
                        "verification_status",
                    ],
                    separators=(",", ":"),
                ),
                "claim_unowned_fields": False,
                "actor_id": actor_id,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_ci_duplicate_candidates_tenant_status",
        table_name="ci_duplicate_candidates",
    )
    op.drop_table("ci_duplicate_candidates")
    op.drop_index(
        "ix_cmdb_field_ownership_tenant_source",
        table_name="cmdb_field_ownership",
    )
    op.drop_table("cmdb_field_ownership")
    op.drop_index(
        "ix_cmdb_reconciliation_records_tenant_match",
        table_name="cmdb_reconciliation_records",
    )
    op.drop_index(
        "ix_cmdb_reconciliation_records_run_outcome",
        table_name="cmdb_reconciliation_records",
    )
    op.drop_table("cmdb_reconciliation_records")
    op.drop_index(
        "ix_cmdb_source_identities_tenant_asset",
        table_name="cmdb_source_identities",
    )
    op.drop_table("cmdb_source_identities")
    op.drop_index(
        "ix_cmdb_reconciliation_runs_source_status",
        table_name="cmdb_reconciliation_runs",
    )
    op.drop_index(
        "ix_cmdb_reconciliation_runs_tenant_created",
        table_name="cmdb_reconciliation_runs",
    )
    op.drop_table("cmdb_reconciliation_runs")
    op.drop_index(
        "ix_cmdb_sources_tenant_status",
        table_name="cmdb_sources",
    )
    op.drop_table("cmdb_sources")
