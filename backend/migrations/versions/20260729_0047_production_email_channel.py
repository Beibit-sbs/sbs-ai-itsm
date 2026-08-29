"""Add the production Microsoft 365 email channel and delivery pipeline.

Revision ID: 20260729_0047
Revises: 20260729_0046
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0047"
down_revision: str | None = "20260729_0046"
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
    if sa.inspect(op.get_bind()).has_table("email_channels"):
        return
    op.create_table(
        "email_channels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mailbox_address", sa.String(255), nullable=False),
        sa.Column("mailbox_user_id", sa.String(255), nullable=True),
        sa.Column("entra_tenant_id", sa.String(128), nullable=True),
        sa.Column("client_id", sa.String(128), nullable=True),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("secret_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inbound_enabled", sa.Boolean(), nullable=False),
        sa.Column("outbound_enabled", sa.Boolean(), nullable=False),
        sa.Column("default_target", sa.String(16), nullable=False),
        sa.Column("allowed_sender_domains_json", sa.JSON(), nullable=False),
        sa.Column("allowed_attachment_extensions_json", sa.JSON(), nullable=False),
        sa.Column("max_attachment_bytes", sa.Integer(), nullable=False),
        sa.Column("graph_subscription_id", sa.String(255), nullable=True),
        sa.Column(
            "graph_subscription_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("webhook_client_state_encrypted", sa.Text(), nullable=True),
        sa.Column("delta_link_encrypted", sa.Text(), nullable=True),
        sa.Column("loop_token_encrypted", sa.Text(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "provider_type IN ('MICROSOFT_GRAPH','MOCK')",
            name="ck_email_channels_provider",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','ERROR','REVOKED')",
            name="ck_email_channels_status",
        ),
        sa.CheckConstraint(
            "default_target IN ('TICKET','REQUEST')",
            name="ck_email_channels_default_target",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tenant_id", "name", name="uq_email_channels_tenant_name"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "mailbox_address",
            name="uq_email_channels_tenant_mailbox",
        ),
    )
    op.create_index(
        "ix_email_channels_tenant_status",
        "email_channels",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_email_channels_subscription",
        "email_channels",
        ["graph_subscription_id", "graph_subscription_expires_at"],
    )

    op.create_table(
        "email_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=False),
        sa.Column("thread_token", sa.String(64), nullable=False),
        sa.Column("provider_conversation_id", sa.String(512), nullable=True),
        sa.Column("root_internet_message_id", sa.String(512), nullable=True),
        sa.Column("entity_type", sa.String(16), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("related_ticket_id", sa.String(36), nullable=True),
        sa.Column("related_request_id", sa.String(36), nullable=True),
        sa.Column("requester_email", sa.String(255), nullable=False),
        sa.Column("normalized_subject", sa.String(255), nullable=False),
        sa.Column("last_provider_message_id", sa.String(512), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "entity_type IN ('TICKET','REQUEST')",
            name="ck_email_conversations_entity_type",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["email_channels.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["related_ticket_id"], ["tickets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["related_request_id"], ["service_requests.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "channel_id",
            "thread_token",
            name="uq_email_conversations_channel_token",
        ),
        sa.UniqueConstraint(
            "channel_id",
            "provider_conversation_id",
            name="uq_email_conversations_provider_thread",
        ),
    )
    op.create_index(
        "ix_email_conversations_tenant_entity",
        "email_conversations",
        ["tenant_id", "entity_type", "entity_id"],
    )
    op.create_index(
        "ix_email_conversations_last_message",
        "email_conversations",
        ["tenant_id", "last_message_at"],
    )

    with op.batch_alter_table("email_message_logs") as batch:
        batch.add_column(sa.Column("channel_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column(
                "direction",
                sa.String(16),
                server_default="OUTBOUND",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column("internet_message_id", sa.String(512), nullable=True)
        )
        batch.add_column(sa.Column("conversation_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(255), nullable=True))
        batch.add_column(sa.Column("from_email", sa.String(255), nullable=True))
        batch.add_column(sa.Column("from_name", sa.String(255), nullable=True))
        batch.add_column(sa.Column("headers_json", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("related_request_id", sa.String(36), nullable=True)
        )
        batch.add_column(
            sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
        batch.create_foreign_key(
            "fk_email_logs_channel_id",
            "email_channels",
            ["channel_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_email_logs_conversation_id",
            "email_conversations",
            ["conversation_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_email_logs_related_request_id",
            "service_requests",
            ["related_request_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint(
            "uq_email_message_logs_tenant_idempotency",
            ["tenant_id", "idempotency_key"],
        )
        batch.create_index(
            "ix_email_message_logs_delivery_queue",
            ["status", "next_retry_at", "created_at"],
        )
        batch.create_index(
            "ix_email_message_logs_channel_status",
            ["channel_id", "status"],
        )

    op.create_table(
        "email_inbound_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=True),
        sa.Column("provider_message_id", sa.String(512), nullable=False),
        sa.Column("provider_conversation_id", sa.String(512), nullable=True),
        sa.Column("internet_message_id", sa.String(512), nullable=True),
        sa.Column("in_reply_to", sa.String(512), nullable=True),
        sa.Column("references_json", sa.JSON(), nullable=False),
        sa.Column("from_email", sa.String(255), nullable=False),
        sa.Column("from_name", sa.String(255), nullable=True),
        sa.Column("recipients_json", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html_sanitized", sa.Text(), nullable=True),
        sa.Column("headers_json", sa.JSON(), nullable=False),
        sa.Column("authentication_results", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("processing_attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("related_ticket_id", sa.String(36), nullable=True),
        sa.Column("related_request_id", sa.String(36), nullable=True),
        sa.Column("ticket_comment_id", sa.String(36), nullable=True),
        sa.Column("request_activity_id", sa.String(36), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN "
            "('RECEIVED','PROCESSED','REJECTED','QUARANTINED','DUPLICATE','LOOP','FAILED','DEAD_LETTER')",
            name="ck_email_inbound_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["email_channels.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["email_conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["related_ticket_id"], ["tickets.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["related_request_id"], ["service_requests.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["ticket_comment_id"], ["ticket_comments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["request_activity_id"], ["request_activities.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "channel_id",
            "provider_message_id",
            name="uq_email_inbound_channel_message",
        ),
    )
    op.create_index(
        "ix_email_inbound_tenant_status",
        "email_inbound_messages",
        ["tenant_id", "status", "received_at"],
    )
    op.create_index(
        "ix_email_inbound_retry",
        "email_inbound_messages",
        ["status", "next_retry_at"],
    )
    op.create_index(
        "ix_email_inbound_internet_id",
        "email_inbound_messages",
        ["internet_message_id"],
    )

    op.create_table(
        "email_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("inbound_message_id", sa.String(36), nullable=False),
        sa.Column("provider_attachment_id", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("safe_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(160), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("storage_key", sa.String(1024), nullable=True),
        sa.Column("is_inline", sa.Boolean(), nullable=False),
        sa.Column("content_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("scan_status", sa.String(20), nullable=False),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by_id", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "scan_status IN ('NOT_REQUIRED','PENDING','CLEAN','INFECTED','ERROR')",
            name="ck_email_attachments_scan_status",
        ),
        sa.CheckConstraint(
            "status IN ('STORED','QUARANTINED','BLOCKED','RELEASED')",
            name="ck_email_attachments_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"],
            ["email_inbound_messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "inbound_message_id",
            "provider_attachment_id",
            name="uq_email_attachments_message_provider",
        ),
    )
    op.create_index(
        "ix_email_attachments_tenant_status",
        "email_attachments",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_email_attachments_sha256",
        "email_attachments",
        ["sha256"],
    )

    op.create_table(
        "email_delivery_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=False),
        sa.Column("email_log_id", sa.String(36), nullable=False),
        sa.Column("provider_event_id", sa.String(512), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "event_type IN ('QUEUED','ACCEPTED','DELIVERED','DELAYED','BOUNCED','COMPLAINT','FAILED')",
            name="ck_email_delivery_event_type",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["email_channels.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["email_log_id"], ["email_message_logs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "channel_id",
            "provider_event_id",
            name="uq_email_delivery_channel_event",
        ),
    )
    op.create_index(
        "ix_email_delivery_log_occurred",
        "email_delivery_events",
        ["email_log_id", "occurred_at"],
    )
    op.create_index(
        "ix_email_delivery_tenant_event",
        "email_delivery_events",
        ["tenant_id", "event_type"],
    )

    op.create_table(
        "email_webhook_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=False),
        sa.Column("provider_event_id", sa.String(512), nullable=False),
        sa.Column("subscription_id", sa.String(512), nullable=True),
        sa.Column("resource", sa.String(1024), nullable=True),
        sa.Column("change_type", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','PROCESSED','FAILED','DEAD_LETTER')",
            name="ck_email_webhook_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["email_channels.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "channel_id",
            "provider_event_id",
            name="uq_email_webhook_channel_event",
        ),
    )
    op.create_index(
        "ix_email_webhook_due",
        "email_webhook_events",
        ["status", "next_retry_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_webhook_due", table_name="email_webhook_events")
    op.drop_table("email_webhook_events")
    op.drop_index(
        "ix_email_delivery_tenant_event", table_name="email_delivery_events"
    )
    op.drop_index(
        "ix_email_delivery_log_occurred", table_name="email_delivery_events"
    )
    op.drop_table("email_delivery_events")
    op.drop_index("ix_email_attachments_sha256", table_name="email_attachments")
    op.drop_index(
        "ix_email_attachments_tenant_status", table_name="email_attachments"
    )
    op.drop_table("email_attachments")
    op.drop_index(
        "ix_email_inbound_internet_id", table_name="email_inbound_messages"
    )
    op.drop_index("ix_email_inbound_retry", table_name="email_inbound_messages")
    op.drop_index(
        "ix_email_inbound_tenant_status", table_name="email_inbound_messages"
    )
    op.drop_table("email_inbound_messages")

    with op.batch_alter_table("email_message_logs") as batch:
        batch.drop_index("ix_email_message_logs_channel_status")
        batch.drop_index("ix_email_message_logs_delivery_queue")
        batch.drop_constraint(
            "uq_email_message_logs_tenant_idempotency", type_="unique"
        )
        batch.drop_constraint("fk_email_logs_related_request_id", type_="foreignkey")
        batch.drop_constraint("fk_email_logs_conversation_id", type_="foreignkey")
        batch.drop_constraint("fk_email_logs_channel_id", type_="foreignkey")
        batch.drop_column("updated_at")
        batch.drop_column("bounced_at")
        batch.drop_column("delivered_at")
        batch.drop_column("accepted_at")
        batch.drop_column("queued_at")
        batch.drop_column("related_request_id")
        batch.drop_column("headers_json")
        batch.drop_column("from_name")
        batch.drop_column("from_email")
        batch.drop_column("idempotency_key")
        batch.drop_column("conversation_id")
        batch.drop_column("internet_message_id")
        batch.drop_column("direction")
        batch.drop_column("channel_id")

    op.drop_index(
        "ix_email_conversations_last_message", table_name="email_conversations"
    )
    op.drop_index(
        "ix_email_conversations_tenant_entity", table_name="email_conversations"
    )
    op.drop_table("email_conversations")
    op.drop_index("ix_email_channels_subscription", table_name="email_channels")
    op.drop_index("ix_email_channels_tenant_status", table_name="email_channels")
    op.drop_table("email_channels")
