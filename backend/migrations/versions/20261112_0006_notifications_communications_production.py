"""notifications communications production schema updates

Revision ID: 20261112_0006
Revises: 20261111_0005
Create Date: 2026-11-12 00:06:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "20261112_0006"
down_revision = "20261111_0005"
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

    with op.batch_alter_table("notifications") as batch_op:
        if not _has_column(inspector, "notifications", "user_id"):
            batch_op.add_column(sa.Column("user_id", sa.String(length=36), nullable=True))
        if not _has_column(inspector, "notifications", "tenant_id"):
            batch_op.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))
        if not _has_column(inspector, "notifications", "event_type"):
            batch_op.add_column(sa.Column("event_type", sa.String(length=80), nullable=True))
        if not _has_column(inspector, "notifications", "severity"):
            batch_op.add_column(sa.Column("severity", sa.String(length=32), nullable=False, server_default="info"))
        if not _has_column(inspector, "notifications", "entity_type"):
            batch_op.add_column(sa.Column("entity_type", sa.String(length=80), nullable=True))
        if not _has_column(inspector, "notifications", "entity_id"):
            batch_op.add_column(sa.Column("entity_id", sa.String(length=80), nullable=True))
        if not _has_column(inspector, "notifications", "action_url"):
            batch_op.add_column(sa.Column("action_url", sa.String(length=500), nullable=True))
        if not _has_column(inspector, "notifications", "is_read"):
            batch_op.add_column(sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()))
        if not _has_column(inspector, "notifications", "expires_at"):
            batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        if not _has_column(inspector, "notifications", "metadata_json"):
            batch_op.add_column(sa.Column("metadata_json", sa.Text(), nullable=True))

    inspector = inspect(bind)
    with op.batch_alter_table("notifications") as batch_op:
        if not _has_fk(inspector, "notifications", "fk_notifications_user_id_users"):
            batch_op.create_foreign_key("fk_notifications_user_id_users", "users", ["user_id"], ["id"], ondelete="SET NULL")
        if not _has_fk(inspector, "notifications", "fk_notifications_tenant_id_tenants"):
            batch_op.create_foreign_key("fk_notifications_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("notification_templates") as batch_op:
        if not _has_column(inspector, "notification_templates", "tenant_id"):
            batch_op.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))
        if not _has_column(inspector, "notification_templates", "key"):
            batch_op.add_column(sa.Column("key", sa.String(length=120), nullable=True))
        if not _has_column(inspector, "notification_templates", "event_type"):
            batch_op.add_column(sa.Column("event_type", sa.String(length=120), nullable=True))
        if not _has_column(inspector, "notification_templates", "locale"):
            batch_op.add_column(sa.Column("locale", sa.String(length=20), nullable=False, server_default="ru"))

    with op.batch_alter_table("email_message_logs") as batch_op:
        if not _has_column(inspector, "email_message_logs", "tenant_id"):
            batch_op.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))
        if not _has_column(inspector, "email_message_logs", "notification_id"):
            batch_op.add_column(sa.Column("notification_id", sa.String(length=36), nullable=True))
        if not _has_column(inspector, "email_message_logs", "event_type"):
            batch_op.add_column(sa.Column("event_type", sa.String(length=120), nullable=True))
        if not _has_column(inspector, "email_message_logs", "provider_message_id"):
            batch_op.add_column(sa.Column("provider_message_id", sa.String(length=255), nullable=True))
        if not _has_column(inspector, "email_message_logs", "to_name"):
            batch_op.add_column(sa.Column("to_name", sa.String(length=255), nullable=True))
        if not _has_column(inspector, "email_message_logs", "attempt_count"):
            batch_op.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        if not _has_column(inspector, "email_message_logs", "max_attempts"):
            batch_op.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
        if not _has_column(inspector, "email_message_logs", "next_retry_at"):
            batch_op.add_column(sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
        if not _has_column(inspector, "email_message_logs", "payload_json"):
            batch_op.add_column(sa.Column("payload_json", sa.Text(), nullable=True))
        if not _has_column(inspector, "email_message_logs", "metadata_json"):
            batch_op.add_column(sa.Column("metadata_json", sa.Text(), nullable=True))

    inspector = inspect(bind)
    with op.batch_alter_table("email_message_logs") as batch_op:
        if not _has_fk(inspector, "email_message_logs", "fk_email_logs_tenant_id_tenants"):
            batch_op.create_foreign_key("fk_email_logs_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
        if not _has_fk(inspector, "email_message_logs", "fk_email_logs_notification_id_notifications"):
            batch_op.create_foreign_key("fk_email_logs_notification_id_notifications", "notifications", ["notification_id"], ["id"], ondelete="SET NULL")

    inspector = inspect(bind)
    if not _has_table(inspector, "notification_preferences"):
        op.create_table(
            "notification_preferences",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("event_type", sa.String(length=120), nullable=False),
            sa.Column("channel_in_app", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("channel_email", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_muted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = inspect(bind)
    if not _has_index(inspector, "notifications", "ix_notifications_tenant_event"):
        op.create_index("ix_notifications_tenant_event", "notifications", ["tenant_id", "event_type"], unique=False)
    if not _has_index(inspector, "notifications", "ix_notifications_tenant_read"):
        op.create_index("ix_notifications_tenant_read", "notifications", ["tenant_id", "is_read"], unique=False)
    if not _has_index(inspector, "email_message_logs", "ix_email_logs_tenant_status"):
        op.create_index("ix_email_logs_tenant_status", "email_message_logs", ["tenant_id", "status"], unique=False)
    if _has_table(inspector, "notification_preferences") and not _has_index(inspector, "notification_preferences", "ix_notification_pref_user_event"):
        op.create_index("ix_notification_pref_user_event", "notification_preferences", ["user_id", "event_type"], unique=True)

    op.execute("UPDATE notifications SET event_type = type WHERE event_type IS NULL")
    if bind.dialect.name == "sqlite":
        op.execute("UPDATE notifications SET is_read = CASE WHEN status = 'READ' THEN 1 ELSE 0 END")
    else:
        op.execute("UPDATE notifications SET is_read = CASE WHEN status = 'READ' THEN true ELSE false END")
    op.execute("UPDATE notifications SET severity = 'info' WHERE severity IS NULL")
    op.execute("UPDATE notification_templates SET key = code WHERE key IS NULL")
    op.execute("UPDATE notification_templates SET event_type = code WHERE event_type IS NULL")


def downgrade() -> None:
    op.drop_index("ix_notification_pref_user_event", table_name="notification_preferences")
    op.drop_index("ix_email_logs_tenant_status", table_name="email_message_logs")
    op.drop_index("ix_notifications_tenant_read", table_name="notifications")
    op.drop_index("ix_notifications_tenant_event", table_name="notifications")

    op.drop_table("notification_preferences")

    with op.batch_alter_table("email_message_logs") as batch_op:
        batch_op.drop_constraint("fk_email_logs_notification_id_notifications", type_="foreignkey")
        batch_op.drop_constraint("fk_email_logs_tenant_id_tenants", type_="foreignkey")
        batch_op.drop_column("metadata_json")
        batch_op.drop_column("payload_json")
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("max_attempts")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("to_name")
        batch_op.drop_column("provider_message_id")
        batch_op.drop_column("event_type")
        batch_op.drop_column("notification_id")
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("notification_templates") as batch_op:
        batch_op.drop_column("locale")
        batch_op.drop_column("event_type")
        batch_op.drop_column("key")
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_constraint("fk_notifications_tenant_id_tenants", type_="foreignkey")
        batch_op.drop_constraint("fk_notifications_user_id_users", type_="foreignkey")
        batch_op.drop_column("metadata_json")
        batch_op.drop_column("expires_at")
        batch_op.drop_column("is_read")
        batch_op.drop_column("action_url")
        batch_op.drop_column("entity_id")
        batch_op.drop_column("entity_type")
        batch_op.drop_column("severity")
        batch_op.drop_column("event_type")
        batch_op.drop_column("tenant_id")
        batch_op.drop_column("user_id")
