from __future__ import annotations

from sqlalchemy import Engine, inspect, text


def ensure_notifications_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        dialect = engine.dialect.name

        if "notifications" in table_names:
            columns = {column["name"] for column in inspector.get_columns("notifications")}
            missing = {
                "user_id": "VARCHAR(36)",
                "tenant_id": "VARCHAR(36)",
                "event_type": "VARCHAR(80)",
                "severity": "VARCHAR(32) DEFAULT 'info'",
                "entity_type": "VARCHAR(80)",
                "entity_id": "VARCHAR(80)",
                "action_url": "VARCHAR(500)",
                "is_read": "BOOLEAN DEFAULT false" if dialect != "sqlite" else "INTEGER DEFAULT 0",
                "expires_at": "TIMESTAMP",
                "metadata_json": "TEXT",
            }
            for name, ddl in missing.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE notifications ADD COLUMN {name} {ddl}"))

        if "notification_templates" in table_names:
            columns = {column["name"] for column in inspector.get_columns("notification_templates")}
            missing = {
                "tenant_id": "VARCHAR(36)",
                "key": "VARCHAR(120)",
                "event_type": "VARCHAR(120)",
                "locale": "VARCHAR(20) DEFAULT 'ru'",
            }
            for name, ddl in missing.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE notification_templates ADD COLUMN {name} {ddl}"))

        if "email_message_logs" in table_names:
            columns = {column["name"] for column in inspector.get_columns("email_message_logs")}
            missing = {
                "tenant_id": "VARCHAR(36)",
                "notification_id": "VARCHAR(36)",
                "event_type": "VARCHAR(120)",
                "provider_message_id": "VARCHAR(255)",
                "to_name": "VARCHAR(255)",
                "attempt_count": "INTEGER DEFAULT 0",
                "max_attempts": "INTEGER DEFAULT 3",
                "next_retry_at": "TIMESTAMP",
                "payload_json": "TEXT",
                "metadata_json": "TEXT",
            }
            for name, ddl in missing.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE email_message_logs ADD COLUMN {name} {ddl}"))

        if "notification_preferences" not in table_names:
            connection.execute(
                text(
                    "CREATE TABLE notification_preferences ("
                    "id VARCHAR(36) PRIMARY KEY, "
                    "user_id VARCHAR(36) NOT NULL, "
                    "tenant_id VARCHAR(36) NULL, "
                    "event_type VARCHAR(120) NOT NULL, "
                    "channel_in_app BOOLEAN NOT NULL DEFAULT true, "
                    "channel_email BOOLEAN NOT NULL DEFAULT false, "
                    "is_muted BOOLEAN NOT NULL DEFAULT false, "
                    "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                    "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )

        connection.execute(text("UPDATE notifications SET event_type = type WHERE event_type IS NULL"))
        connection.execute(text("UPDATE notifications SET severity = 'info' WHERE severity IS NULL"))
        connection.execute(text("UPDATE notifications SET is_read = CASE WHEN status = 'READ' THEN true ELSE false END WHERE is_read IS NULL"))
        connection.execute(text("UPDATE notification_templates SET key = code WHERE key IS NULL"))
        connection.execute(text("UPDATE notification_templates SET event_type = code WHERE event_type IS NULL"))

        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_tenant_event ON notifications (tenant_id, event_type)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_tenant_read ON notifications (tenant_id, is_read)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_email_logs_tenant_status ON email_message_logs (tenant_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_notification_pref_user_event ON notification_preferences (user_id, event_type)"))
