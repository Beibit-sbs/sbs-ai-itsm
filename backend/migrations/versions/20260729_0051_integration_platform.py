"""Add production integration platform control plane.

Revision ID: 20260729_0051
Revises: 20260729_0050
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0051"
down_revision: str | None = "20260729_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("integration_service_accounts"):
        return
    op.create_table(
        "integration_service_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column(
            "allowed_scopes_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "allowed_ip_cidrs_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "rate_limit_per_minute",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
        sa.Column(
            "max_token_ttl_days",
            sa.Integer(),
            nullable=False,
            server_default="90",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "total_requests",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failed_auth_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.String(36), nullable=True),
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
            "status IN ('ACTIVE','SUSPENDED','REVOKED')",
            name="ck_integration_service_accounts_status",
        ),
        sa.CheckConstraint(
            "rate_limit_per_minute >= 1 AND rate_limit_per_minute <= 10000",
            name="ck_integration_service_accounts_rate_limit",
        ),
        sa.CheckConstraint(
            "max_token_ttl_days >= 1 AND max_token_ttl_days <= 365",
            name="ck_integration_service_accounts_ttl",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_id"],
            ["users.id"],
            ondelete="SET NULL",
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
            "name",
            name="uq_integration_service_accounts_tenant_name",
        ),
        sa.UniqueConstraint(
            "client_id",
            name="uq_integration_service_accounts_client_id",
        ),
    )
    op.create_index(
        "ix_integration_service_accounts_tenant_status",
        "integration_service_accounts",
        ["tenant_id", "status"],
    )

    op.create_table(
        "integration_api_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("service_account_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("token_prefix", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_hint", sa.String(32), nullable=False),
        sa.Column(
            "scopes_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(64), nullable=True),
        sa.Column(
            "rate_window_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "rate_window_requests",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("issued_by_id", sa.String(36), nullable=True),
        sa.Column("revoked_by_id", sa.String(36), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_token_id", sa.String(36), nullable=True),
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
            "status IN ('ACTIVE','REVOKED','EXPIRED')",
            name="ck_integration_api_tokens_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_account_id"],
            ["integration_service_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_token_id"],
            ["integration_api_tokens.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "token_prefix",
            name="uq_integration_api_tokens_prefix",
        ),
    )
    op.create_index(
        "ix_integration_api_tokens_account_status",
        "integration_api_tokens",
        ["service_account_id", "status"],
    )
    op.create_index(
        "ix_integration_api_tokens_tenant_status",
        "integration_api_tokens",
        ["tenant_id", "status"],
    )

    op.create_table(
        "integration_api_request_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("service_account_id", sa.String(36), nullable=False),
        sa.Column("token_id", sa.String(36), nullable=True),
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("source_ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("required_scope", sa.String(120), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "outcome IN ('ALLOWED','DENIED')",
            name="ck_integration_api_request_logs_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_account_id"],
            ["integration_service_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["integration_api_tokens.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_integration_api_request_logs_tenant_created",
        "integration_api_request_logs",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_integration_api_request_logs_account_created",
        "integration_api_request_logs",
        ["service_account_id", "created_at"],
    )

    op.create_table(
        "outbound_webhook_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "event_types_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("target_url_encrypted", sa.Text(), nullable=True),
        sa.Column("target_hint", sa.String(255), nullable=True),
        sa.Column("target_host", sa.String(255), nullable=True),
        sa.Column(
            "target_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("signing_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("signing_secret_hint", sa.String(32), nullable=True),
        sa.Column(
            "signing_secret_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("last_tested_target_version", sa.Integer(), nullable=True),
        sa.Column("last_tested_secret_version", sa.Integer(), nullable=True),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="6",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "success_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "dead_letter_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            "status IN ('DRAFT','ACTIVE','PAUSED','REVOKED')",
            name="ck_outbound_webhook_subscriptions_status",
        ),
        sa.CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 60",
            name="ck_outbound_webhook_subscriptions_timeout",
        ),
        sa.CheckConstraint(
            "max_attempts >= 1 AND max_attempts <= 20",
            name="ck_outbound_webhook_subscriptions_attempts",
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
            "name",
            name="uq_outbound_webhook_subscriptions_tenant_name",
        ),
    )
    op.create_index(
        "ix_outbound_webhook_subscriptions_tenant_status",
        "outbound_webhook_subscriptions",
        ["tenant_id", "status"],
    )

    op.create_table(
        "outbound_webhook_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("replay_of_id", sa.String(36), nullable=True),
        sa.Column("event_id", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=True),
        sa.Column("entity_id", sa.String(120), nullable=True),
        sa.Column("payload_encrypted", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "is_test",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="6",
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("target_version_used", sa.Integer(), nullable=True),
        sa.Column("signing_secret_version_used", sa.Integer(), nullable=True),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ("
            "'PENDING','PROCESSING','RETRY','SUCCEEDED','FAILED',"
            "'DEAD_LETTER','CANCELLED'"
            ")",
            name="ck_outbound_webhook_deliveries_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["outbound_webhook_subscriptions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replay_of_id"],
            ["outbound_webhook_deliveries.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "subscription_id",
            "idempotency_key",
            name="uq_outbound_webhook_deliveries_subscription_key",
        ),
    )
    op.create_index(
        "ix_outbound_webhook_deliveries_queue",
        "outbound_webhook_deliveries",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_outbound_webhook_deliveries_subscription_created",
        "outbound_webhook_deliveries",
        ["subscription_id", "created_at"],
    )
    op.create_index(
        "ix_outbound_webhook_deliveries_tenant_status",
        "outbound_webhook_deliveries",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbound_webhook_deliveries_tenant_status",
        table_name="outbound_webhook_deliveries",
    )
    op.drop_index(
        "ix_outbound_webhook_deliveries_subscription_created",
        table_name="outbound_webhook_deliveries",
    )
    op.drop_index(
        "ix_outbound_webhook_deliveries_queue",
        table_name="outbound_webhook_deliveries",
    )
    op.drop_table("outbound_webhook_deliveries")
    op.drop_index(
        "ix_outbound_webhook_subscriptions_tenant_status",
        table_name="outbound_webhook_subscriptions",
    )
    op.drop_table("outbound_webhook_subscriptions")
    op.drop_index(
        "ix_integration_api_request_logs_account_created",
        table_name="integration_api_request_logs",
    )
    op.drop_index(
        "ix_integration_api_request_logs_tenant_created",
        table_name="integration_api_request_logs",
    )
    op.drop_table("integration_api_request_logs")
    op.drop_index(
        "ix_integration_api_tokens_tenant_status",
        table_name="integration_api_tokens",
    )
    op.drop_index(
        "ix_integration_api_tokens_account_status",
        table_name="integration_api_tokens",
    )
    op.drop_table("integration_api_tokens")
    op.drop_index(
        "ix_integration_service_accounts_tenant_status",
        table_name="integration_service_accounts",
    )
    op.drop_table("integration_service_accounts")
