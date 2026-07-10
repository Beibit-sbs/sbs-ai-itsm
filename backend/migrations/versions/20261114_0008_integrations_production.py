"""integrations production schema updates

Revision ID: 20261114_0008
Revises: 20261113_0007
Create Date: 2026-11-14 00:08:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261114_0008"
down_revision = "20261113_0007"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _has_fk(inspector, table_name: str, fk_name: str) -> bool:
    return fk_name in {fk.get("name") for fk in inspector.get_foreign_keys(table_name)}


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx.get("name") for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_table(inspector, "external_systems"):
        with op.batch_alter_table("external_systems") as batch_op:
            if not _has_column(inspector, "external_systems", "health_status"):
                batch_op.add_column(sa.Column("health_status", sa.String(length=40), nullable=False, server_default="unknown"))
            if not _has_column(inspector, "external_systems", "is_mock"):
                batch_op.add_column(sa.Column("is_mock", sa.Boolean(), nullable=False, server_default=sa.true()))
            if not _has_column(inspector, "external_systems", "last_health_check_at"):
                batch_op.add_column(sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True))
            if not _has_column(inspector, "external_systems", "last_success_at"):
                batch_op.add_column(sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
            if not _has_column(inspector, "external_systems", "last_error_at"):
                batch_op.add_column(sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True))
            if not _has_column(inspector, "external_systems", "last_error_message"):
                batch_op.add_column(sa.Column("last_error_message", sa.Text(), nullable=True))
            if not _has_column(inspector, "external_systems", "config_json"):
                batch_op.add_column(sa.Column("config_json", sa.Text(), nullable=True))
            if not _has_column(inspector, "external_systems", "created_by_id"):
                batch_op.add_column(sa.Column("created_by_id", sa.String(length=36), nullable=True))

    inspector = inspect(bind)
    if _has_table(inspector, "external_systems") and _has_column(inspector, "external_systems", "created_by_id") and not _has_fk(inspector, "external_systems", "fk_external_systems_created_by_id_users"):
        with op.batch_alter_table("external_systems") as batch_op:
            batch_op.create_foreign_key("fk_external_systems_created_by_id_users", "users", ["created_by_id"], ["id"], ondelete="SET NULL")

    if _has_table(inspector, "integration_credentials"):
        with op.batch_alter_table("integration_credentials") as batch_op:
            if not _has_column(inspector, "integration_credentials", "credential_type"):
                batch_op.add_column(sa.Column("credential_type", sa.String(length=80), nullable=False, server_default="api_token"))
            if not _has_column(inspector, "integration_credentials", "masked_value"):
                batch_op.add_column(sa.Column("masked_value", sa.String(length=255), nullable=True))
            if not _has_column(inspector, "integration_credentials", "created_by_id"):
                batch_op.add_column(sa.Column("created_by_id", sa.String(length=36), nullable=True))
            if not _has_column(inspector, "integration_credentials", "rotated_at"):
                batch_op.add_column(sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True))

    inspector = inspect(bind)
    if _has_table(inspector, "integration_credentials") and _has_column(inspector, "integration_credentials", "created_by_id") and not _has_fk(inspector, "integration_credentials", "fk_integration_credentials_created_by_id_users"):
        with op.batch_alter_table("integration_credentials") as batch_op:
            batch_op.create_foreign_key("fk_integration_credentials_created_by_id_users", "users", ["created_by_id"], ["id"], ondelete="SET NULL")

    if _has_table(inspector, "webhook_endpoints"):
        with op.batch_alter_table("webhook_endpoints") as batch_op:
            if not _has_column(inspector, "webhook_endpoints", "external_system_id"):
                batch_op.add_column(sa.Column("external_system_id", sa.String(length=36), nullable=True))
            if not _has_column(inspector, "webhook_endpoints", "event_type"):
                batch_op.add_column(sa.Column("event_type", sa.String(length=120), nullable=False, server_default="generic"))
            if not _has_column(inspector, "webhook_endpoints", "secret_required"):
                batch_op.add_column(sa.Column("secret_required", sa.Boolean(), nullable=False, server_default=sa.false()))
            if not _has_column(inspector, "webhook_endpoints", "last_received_at"):
                batch_op.add_column(sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=True))
            if not _has_column(inspector, "webhook_endpoints", "success_count"):
                batch_op.add_column(sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"))
            if not _has_column(inspector, "webhook_endpoints", "failure_count"):
                batch_op.add_column(sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"))

    inspector = inspect(bind)
    if _has_table(inspector, "webhook_endpoints") and _has_column(inspector, "webhook_endpoints", "external_system_id") and not _has_fk(inspector, "webhook_endpoints", "fk_webhook_endpoints_external_system_id_external_systems"):
        with op.batch_alter_table("webhook_endpoints") as batch_op:
            batch_op.create_foreign_key("fk_webhook_endpoints_external_system_id_external_systems", "external_systems", ["external_system_id"], ["id"], ondelete="SET NULL")

    if _has_table(inspector, "integration_event_logs"):
        with op.batch_alter_table("integration_event_logs") as batch_op:
            if not _has_column(inspector, "integration_event_logs", "entity_type"):
                batch_op.add_column(sa.Column("entity_type", sa.String(length=80), nullable=True))
            if not _has_column(inspector, "integration_event_logs", "entity_id"):
                batch_op.add_column(sa.Column("entity_id", sa.String(length=120), nullable=True))
            if not _has_column(inspector, "integration_event_logs", "payload_json"):
                batch_op.add_column(sa.Column("payload_json", sa.Text(), nullable=True))
            if not _has_column(inspector, "integration_event_logs", "response_payload_json"):
                batch_op.add_column(sa.Column("response_payload_json", sa.Text(), nullable=True))
            if not _has_column(inspector, "integration_event_logs", "attempt_count"):
                batch_op.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
            if not _has_column(inspector, "integration_event_logs", "next_retry_at"):
                batch_op.add_column(sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
            if not _has_column(inspector, "integration_event_logs", "processed_at"):
                batch_op.add_column(sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))

    if _has_table(inspector, "import_jobs"):
        with op.batch_alter_table("import_jobs") as batch_op:
            if not _has_column(inspector, "import_jobs", "source_filename"):
                batch_op.add_column(sa.Column("source_filename", sa.String(length=255), nullable=True))
            if not _has_column(inspector, "import_jobs", "total_rows"):
                batch_op.add_column(sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"))
            if not _has_column(inspector, "import_jobs", "success_rows"):
                batch_op.add_column(sa.Column("success_rows", sa.Integer(), nullable=False, server_default="0"))
            if not _has_column(inspector, "import_jobs", "failed_rows"):
                batch_op.add_column(sa.Column("failed_rows", sa.Integer(), nullable=False, server_default="0"))
            if not _has_column(inspector, "import_jobs", "error_report_json"):
                batch_op.add_column(sa.Column("error_report_json", sa.Text(), nullable=True))
            if not _has_column(inspector, "import_jobs", "dry_run"):
                batch_op.add_column(sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()))
            if not _has_column(inspector, "import_jobs", "created_by_id"):
                batch_op.add_column(sa.Column("created_by_id", sa.String(length=36), nullable=True))

    inspector = inspect(bind)
    if _has_table(inspector, "import_jobs") and _has_column(inspector, "import_jobs", "created_by_id") and not _has_fk(inspector, "import_jobs", "fk_import_jobs_created_by_id_users"):
        with op.batch_alter_table("import_jobs") as batch_op:
            batch_op.create_foreign_key("fk_import_jobs_created_by_id_users", "users", ["created_by_id"], ["id"], ondelete="SET NULL")

    if _has_table(inspector, "integration_mappings"):
        with op.batch_alter_table("integration_mappings") as batch_op:
            if not _has_column(inspector, "integration_mappings", "mapping_type"):
                batch_op.add_column(sa.Column("mapping_type", sa.String(length=80), nullable=False, server_default="webhook_event"))
            if not _has_column(inspector, "integration_mappings", "source_field"):
                batch_op.add_column(sa.Column("source_field", sa.String(length=255), nullable=True))
            if not _has_column(inspector, "integration_mappings", "target_field"):
                batch_op.add_column(sa.Column("target_field", sa.String(length=255), nullable=True))
            if not _has_column(inspector, "integration_mappings", "transform_rule"):
                batch_op.add_column(sa.Column("transform_rule", sa.Text(), nullable=True))
            if not _has_column(inspector, "integration_mappings", "is_required"):
                batch_op.add_column(sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()))

    inspector = inspect(bind)
    if _has_table(inspector, "external_systems") and not _has_index(inspector, "external_systems", "ix_external_systems_system_type"):
        op.create_index("ix_external_systems_system_type", "external_systems", ["system_type"], unique=False)
    if _has_table(inspector, "external_systems") and not _has_index(inspector, "external_systems", "ix_external_systems_status"):
        op.create_index("ix_external_systems_status", "external_systems", ["status"], unique=False)
    if _has_table(inspector, "external_systems") and not _has_index(inspector, "external_systems", "ix_external_systems_health_status"):
        op.create_index("ix_external_systems_health_status", "external_systems", ["health_status"], unique=False)

    if _has_table(inspector, "integration_event_logs") and not _has_index(inspector, "integration_event_logs", "ix_integration_event_logs_external_system_id"):
        op.create_index("ix_integration_event_logs_external_system_id", "integration_event_logs", ["external_system_id"], unique=False)
    if _has_table(inspector, "integration_event_logs") and not _has_index(inspector, "integration_event_logs", "ix_integration_event_logs_status"):
        op.create_index("ix_integration_event_logs_status", "integration_event_logs", ["status"], unique=False)
    if _has_table(inspector, "integration_event_logs") and not _has_index(inspector, "integration_event_logs", "ix_integration_event_logs_direction"):
        op.create_index("ix_integration_event_logs_direction", "integration_event_logs", ["direction"], unique=False)
    if _has_table(inspector, "integration_event_logs") and not _has_index(inspector, "integration_event_logs", "ix_integration_event_logs_created_at"):
        op.create_index("ix_integration_event_logs_created_at", "integration_event_logs", ["created_at"], unique=False)

    if _has_table(inspector, "webhook_endpoints") and not _has_index(inspector, "webhook_endpoints", "ix_webhook_endpoints_path"):
        op.create_index("ix_webhook_endpoints_path", "webhook_endpoints", ["path"], unique=False)
    if _has_table(inspector, "webhook_endpoints") and not _has_index(inspector, "webhook_endpoints", "ix_webhook_endpoints_event_type"):
        op.create_index("ix_webhook_endpoints_event_type", "webhook_endpoints", ["event_type"], unique=False)

    if _has_table(inspector, "import_jobs") and not _has_index(inspector, "import_jobs", "ix_import_jobs_status"):
        op.create_index("ix_import_jobs_status", "import_jobs", ["status"], unique=False)
    if _has_table(inspector, "import_jobs") and not _has_index(inspector, "import_jobs", "ix_import_jobs_job_type"):
        op.create_index("ix_import_jobs_job_type", "import_jobs", ["job_type"], unique=False)

    if _has_table(inspector, "integration_mappings") and not _has_index(inspector, "integration_mappings", "ix_integration_mappings_external_system_id"):
        op.create_index("ix_integration_mappings_external_system_id", "integration_mappings", ["external_system_id"], unique=False)

    if _has_table(inspector, "integration_credentials") and not _has_index(inspector, "integration_credentials", "ix_integration_credentials_external_system_id"):
        op.create_index("ix_integration_credentials_external_system_id", "integration_credentials", ["external_system_id"], unique=False)


def downgrade() -> None:
    # Keep downgrade intentionally non-destructive for production safety.
    pass
