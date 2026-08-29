"""Stage 034: Alert notifications tables

Revision ID: 20261215_0022
Revises: 20261215_0021
Create Date: 2026-07-13 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20261215_0022"
down_revision = "20261215_0021"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    # Create policy_alert_notifications table
    if not inspector.has_table("policy_alert_notifications"):
        op.create_table(
        "policy_alert_notifications",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("alert_rule_id", sa.String(), nullable=False),
        sa.Column("rollout_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("sent", sa.Boolean(), server_default="false"),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("recipients", sa.JSON(), server_default="[]"),
        sa.Column("alert_metadata", sa.JSON(), nullable=True),
        sa.Column("routing_decision", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["alert_rule_id"], ["policy_metrics_alert_rules.id"]),
        sa.ForeignKeyConstraint(["rollout_id"], ["policy_canary_rollouts.id"]),
        )
        op.create_index("ix_policy_alert_notifications_alert_rule_id", "policy_alert_notifications", ["alert_rule_id"])
        op.create_index("ix_policy_alert_notifications_rollout_id", "policy_alert_notifications", ["rollout_id"])
        op.create_index("ix_policy_alert_notifications_tenant_id", "policy_alert_notifications", ["tenant_id"])
        op.create_index("ix_policy_alert_notifications_created_at", "policy_alert_notifications", ["created_at"])
    
    # Create policy_alert_history table
    if not inspector.has_table("policy_alert_history"):
        op.create_table(
        "policy_alert_history",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("alert_rule_id", sa.String(), nullable=False),
        sa.Column("rollout_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("rule_name", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False),
        sa.Column("operator", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("anomaly_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), server_default="active"),
        sa.Column("triggered_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("notifications_sent", sa.Integer(), server_default="0"),
        sa.Column("notification_channels", sa.JSON(), server_default="[]"),
        sa.Column("breach_count", sa.Integer(), server_default="1"),
        sa.Column("breach_percentage", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("modified_by", sa.String(), nullable=True),
        sa.Column("modified_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["alert_rule_id"], ["policy_metrics_alert_rules.id"]),
        sa.ForeignKeyConstraint(["rollout_id"], ["policy_canary_rollouts.id"]),
        )
        op.create_index("ix_policy_alert_history_alert_rule_id", "policy_alert_history", ["alert_rule_id"])
        op.create_index("ix_policy_alert_history_rollout_id", "policy_alert_history", ["rollout_id"])
        op.create_index("ix_policy_alert_history_tenant_id", "policy_alert_history", ["tenant_id"])
        op.create_index("ix_policy_alert_history_triggered_at", "policy_alert_history", ["triggered_at"])
    
    # Create policy_notification_preferences table
    if not inspector.has_table("policy_notification_preferences"):
        op.create_table(
        "policy_notification_preferences",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), server_default="true"),
        sa.Column("email_address", sa.String(), nullable=True),
        sa.Column("email_critical", sa.Boolean(), server_default="true"),
        sa.Column("email_high", sa.Boolean(), server_default="true"),
        sa.Column("email_medium", sa.Boolean(), server_default="false"),
        sa.Column("email_low", sa.Boolean(), server_default="false"),
        sa.Column("slack_enabled", sa.Boolean(), server_default="false"),
        sa.Column("slack_user_id", sa.String(), nullable=True),
        sa.Column("slack_critical", sa.Boolean(), server_default="true"),
        sa.Column("slack_high", sa.Boolean(), server_default="true"),
        sa.Column("slack_medium", sa.Boolean(), server_default="false"),
        sa.Column("slack_low", sa.Boolean(), server_default="false"),
        sa.Column("webhook_enabled", sa.Boolean(), server_default="false"),
        sa.Column("webhook_url", sa.String(), nullable=True),
        sa.Column("webhook_critical", sa.Boolean(), server_default="true"),
        sa.Column("webhook_high", sa.Boolean(), server_default="true"),
        sa.Column("webhook_medium", sa.Boolean(), server_default="false"),
        sa.Column("webhook_low", sa.Boolean(), server_default="false"),
        sa.Column("quiet_hours_enabled", sa.Boolean(), server_default="false"),
        sa.Column("quiet_hours_start", sa.String(), nullable=True),
        sa.Column("quiet_hours_end", sa.String(), nullable=True),
        sa.Column("quiet_hours_timezone", sa.String(), server_default="UTC"),
        sa.Column("escalation_enabled", sa.Boolean(), server_default="false"),
        sa.Column("escalation_after_minutes", sa.Integer(), server_default="30"),
        sa.Column("escalation_recipients", sa.JSON(), server_default="[]"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_policy_notification_preferences_user_id", "policy_notification_preferences", ["user_id"])
        op.create_index("ix_policy_notification_preferences_tenant_id", "policy_notification_preferences", ["tenant_id"])


def downgrade():
    op.drop_table("policy_notification_preferences")
    op.drop_table("policy_alert_history")
    op.drop_table("policy_alert_notifications")
