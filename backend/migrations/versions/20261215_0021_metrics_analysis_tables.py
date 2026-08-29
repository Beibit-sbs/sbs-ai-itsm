"""Stage 033: Advanced metrics analysis tables

Revision ID: 20261215_0021
Revises: 20261215_0020
Create Date: 2026-07-13 13:50:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20261215_0021"
down_revision = "20261215_0020_policy_rollout_metrics"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    # Create policy_metrics_alert_rules table
    if not inspector.has_table("policy_metrics_alert_rules"):
        op.create_table(
        "policy_metrics_alert_rules",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("rollout_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("operator", sa.String(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), server_default="60"),
        sa.Column("enabled", sa.Boolean(), server_default="true"),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("is_currently_triggered", sa.Boolean(), server_default="false"),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("severity_level", sa.String(), server_default="medium"),
        sa.Column("notification_channels", sa.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["rollout_id"], ["policy_canary_rollouts.id"]),
        )
        op.create_index("ix_policy_metrics_alert_rules_rollout_id", "policy_metrics_alert_rules", ["rollout_id"])
        op.create_index("ix_policy_metrics_alert_rules_tenant_id", "policy_metrics_alert_rules", ["tenant_id"])
    
    # Create policy_metrics_anomaly_detection table
    if not inspector.has_table("policy_metrics_anomaly_detection"):
        op.create_table(
        "policy_metrics_anomaly_detection",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("rollout_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("detection_method", sa.String(), nullable=False),
        sa.Column("anomaly_score", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("baseline", sa.Float(), nullable=True),
        sa.Column("deviation_percent", sa.Float(), nullable=True),
        sa.Column("anomaly_count", sa.Integer(), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=True),
        sa.Column("analysis_window_minutes", sa.Integer(), server_default="30"),
        sa.Column("raw_analysis", sa.JSON(), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), server_default="false"),
        sa.Column("acknowledged_by", sa.String(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["rollout_id"], ["policy_canary_rollouts.id"]),
        )
        op.create_index("ix_policy_metrics_anomaly_detection_rollout_id", "policy_metrics_anomaly_detection", ["rollout_id"])
        op.create_index("ix_policy_metrics_anomaly_detection_tenant_id", "policy_metrics_anomaly_detection", ["tenant_id"])
        op.create_index("ix_policy_metrics_anomaly_detection_detected_at", "policy_metrics_anomaly_detection", ["detected_at"])
    
    # Create policy_metrics_health_assessment table
    if not inspector.has_table("policy_metrics_health_assessment"):
        op.create_table(
        "policy_metrics_health_assessment",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("rollout_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("health_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_rate_health", sa.Float(), nullable=True),
        sa.Column("latency_health", sa.Float(), nullable=True),
        sa.Column("throughput_health", sa.Float(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("primary_concern", sa.String(), nullable=True),
        sa.Column("secondary_concerns", sa.JSON(), server_default="[]"),
        sa.Column("recommendations", sa.JSON(), server_default="[]"),
        sa.Column("error_rate_current", sa.Float(), nullable=True),
        sa.Column("latency_p99_current", sa.Float(), nullable=True),
        sa.Column("throughput_current", sa.Float(), nullable=True),
        sa.Column("analysis_window_minutes", sa.Integer(), server_default="30"),
        sa.Column("data_points_analyzed", sa.Integer(), server_default="0"),
        sa.Column("assessed_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["rollout_id"], ["policy_canary_rollouts.id"]),
        )
        op.create_index("ix_policy_metrics_health_assessment_rollout_id", "policy_metrics_health_assessment", ["rollout_id"])
        op.create_index("ix_policy_metrics_health_assessment_tenant_id", "policy_metrics_health_assessment", ["tenant_id"])
        op.create_index("ix_policy_metrics_health_assessment_assessed_at", "policy_metrics_health_assessment", ["assessed_at"])


def downgrade():
    op.drop_table("policy_metrics_health_assessment")
    op.drop_table("policy_metrics_anomaly_detection")
    op.drop_table("policy_metrics_alert_rules")
