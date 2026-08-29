"""Add production monitoring connector security and webhook outbox.

Revision ID: 20260729_0049
Revises: 20260729_0048
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0049"
down_revision: str | None = "20260729_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("event_sources")
    }
    if "auth_mode" in columns:
        return
    op.add_column(
        "event_sources",
        sa.Column(
            "auth_mode",
            sa.String(24),
            nullable=False,
            server_default="BEARER",
        ),
    )
    op.add_column(
        "event_sources",
        sa.Column("hmac_secret_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "event_sources",
        sa.Column("hmac_secret_hint", sa.String(16), nullable=True),
    )
    op.add_column(
        "event_sources",
        sa.Column(
            "replay_window_seconds",
            sa.Integer(),
            nullable=False,
            server_default="300",
        ),
    )
    op.add_column(
        "event_sources",
        sa.Column(
            "rate_limit_per_minute",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
    )
    op.add_column(
        "event_sources",
        sa.Column(
            "max_payload_bytes",
            sa.Integer(),
            nullable=False,
            server_default="1048576",
        ),
    )
    op.add_column(
        "event_sources",
        sa.Column(
            "allowed_ip_cidrs_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "event_sources",
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "event_sources",
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "event_sources",
        sa.Column(
            "success_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "event_sources",
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "event_sources",
        sa.Column(
            "dead_letter_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("event_sources") as batch_op:
            batch_op.create_check_constraint(
                "ck_event_sources_auth_mode",
                "auth_mode IN ('BEARER','HMAC_SHA256')",
            )
    else:
        op.create_check_constraint(
            "ck_event_sources_auth_mode",
            "event_sources",
            "auth_mode IN ('BEARER','HMAC_SHA256')",
        )

    op.create_table(
        "monitoring_webhook_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("body_hash", sa.String(64), nullable=False),
        sa.Column("payload_encrypted", sa.Text(), nullable=False),
        sa.Column("payload_size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(200), nullable=True),
        sa.Column("source_ip", sa.String(64), nullable=True),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("request_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_headers_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("normalized_event_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_event_count", sa.Integer(), nullable=False),
        sa.Column("incident_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('RECEIVED','PROCESSING','PROCESSED','DUPLICATE',"
            "'RETRY','FAILED','DEAD_LETTER','REJECTED')",
            name="ck_monitoring_receipts_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["event_sources.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "source_id",
            "request_key",
            name="uq_monitoring_receipts_source_request",
        ),
    )
    op.create_index(
        "ix_monitoring_receipts_queue",
        "monitoring_webhook_receipts",
        ["status", "next_attempt_at", "received_at"],
    )
    op.create_index(
        "ix_monitoring_receipts_source_received",
        "monitoring_webhook_receipts",
        ["source_id", "received_at"],
    )
    op.create_index(
        "ix_monitoring_receipts_tenant_status",
        "monitoring_webhook_receipts",
        ["tenant_id", "status"],
    )

    defaulted_columns = (
        "auth_mode",
        "replay_window_seconds",
        "rate_limit_per_minute",
        "max_payload_bytes",
        "allowed_ip_cidrs_json",
        "success_count",
        "failure_count",
        "dead_letter_count",
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("event_sources") as batch_op:
            for column_name in defaulted_columns:
                batch_op.alter_column(column_name, server_default=None)
    else:
        for column_name in defaulted_columns:
            op.alter_column(
                "event_sources",
                column_name,
                server_default=None,
            )


def downgrade() -> None:
    op.drop_index(
        "ix_monitoring_receipts_tenant_status",
        table_name="monitoring_webhook_receipts",
    )
    op.drop_index(
        "ix_monitoring_receipts_source_received",
        table_name="monitoring_webhook_receipts",
    )
    op.drop_index(
        "ix_monitoring_receipts_queue",
        table_name="monitoring_webhook_receipts",
    )
    op.drop_table("monitoring_webhook_receipts")
    op.drop_constraint(
        "ck_event_sources_auth_mode",
        "event_sources",
        type_="check",
    )
    for column in (
        "dead_letter_count",
        "failure_count",
        "success_count",
        "last_failure_at",
        "last_success_at",
        "allowed_ip_cidrs_json",
        "max_payload_bytes",
        "rate_limit_per_minute",
        "replay_window_seconds",
        "hmac_secret_hint",
        "hmac_secret_encrypted",
        "auth_mode",
    ):
        op.drop_column("event_sources", column)
