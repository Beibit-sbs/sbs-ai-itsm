"""Add normalized event operations, correlation, suppression, and escalation.

Revision ID: 20260729_0041
Revises: 20260729_0040
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0041"
down_revision: str | None = "20260729_0040"
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
    if sa.inspect(op.get_bind()).has_table("event_sources"):
        return
    op.create_table(
        "event_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_hint", sa.String(16), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("total_events", sa.Integer(), nullable=False),
        sa.Column("duplicate_events", sa.Integer(), nullable=False),
        sa.Column("suppressed_events", sa.Integer(), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "source_type IN ('ALERTMANAGER','PROMETHEUS','ZABBIX','SENTRY',"
            "'GRAFANA','GENERIC')",
            name="ck_event_sources_type",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_event_sources_tenant_code",
        ),
    )
    op.create_index(
        "ix_event_sources_tenant_enabled",
        "event_sources",
        ["tenant_id", "is_enabled"],
    )

    op.create_table(
        "event_correlation_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("priority_order", sa.Integer(), nullable=False),
        sa.Column("matchers_json", sa.JSON(), nullable=False),
        sa.Column("group_by_json", sa.JSON(), nullable=False),
        sa.Column("correlation_window_minutes", sa.Integer(), nullable=False),
        sa.Column("min_occurrences", sa.Integer(), nullable=False),
        sa.Column("incident_mode", sa.String(24), nullable=False),
        sa.Column("fixed_priority", sa.String(8), nullable=True),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("title_template", sa.String(255), nullable=False),
        sa.Column("resolution_action", sa.String(16), nullable=False),
        sa.Column("primary_user_id", sa.String(36), nullable=True),
        sa.Column("fallback_user_id", sa.String(36), nullable=True),
        sa.Column("acknowledge_within_minutes", sa.Integer(), nullable=False),
        sa.Column("escalate_after_minutes", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "incident_mode IN ('CREATE_UPDATE','CORRELATE_ONLY','IGNORE')",
            name="ck_event_correlation_policies_incident_mode",
        ),
        sa.CheckConstraint(
            "resolution_action IN ('NONE','RESOLVE','CLOSE')",
            name="ck_event_correlation_policies_resolution_action",
        ),
        sa.CheckConstraint(
            "fixed_priority IS NULL OR fixed_priority IN "
            "('CRITICAL','HIGH','MEDIUM','LOW','P1','P2','P3','P4')",
            name="ck_event_correlation_policies_priority",
        ),
        sa.CheckConstraint(
            "min_occurrences >= 1 AND min_occurrences <= 1000",
            name="ck_event_correlation_policies_occurrences",
        ),
        sa.CheckConstraint(
            "correlation_window_minutes >= 1 "
            "AND correlation_window_minutes <= 10080",
            name="ck_event_correlation_policies_window",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["primary_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["fallback_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_event_correlation_policies_tenant_name",
        ),
    )
    op.create_index(
        "ix_event_correlation_policies_order",
        "event_correlation_policies",
        ["tenant_id", "is_active", "priority_order"],
    )

    op.create_table(
        "event_suppression_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("matchers_json", sa.JSON(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at",
            name="ck_event_suppression_rules_window",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_event_suppression_rules_tenant_name",
        ),
    )
    op.create_index(
        "ix_event_suppression_rules_active",
        "event_suppression_rules",
        ["tenant_id", "is_active", "starts_at", "ends_at"],
    )

    op.create_table(
        "event_correlation_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("correlation_key", sa.String(512), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("first_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.String(36), nullable=True),
        sa.Column("assigned_user_id", sa.String(36), nullable=True),
        sa.Column("acknowledged_by_id", sa.String(36), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_escalation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('OPEN','RESOLVED')",
            name="ck_event_correlation_groups_status",
        ),
        sa.CheckConstraint(
            "severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_event_correlation_groups_severity",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["event_correlation_policies.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["assigned_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "uq_event_correlation_groups_open",
        "event_correlation_groups",
        ["tenant_id", "policy_id", "correlation_key"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
        sqlite_where=sa.text("status = 'OPEN'"),
    )
    op.create_index(
        "ix_event_correlation_groups_queue",
        "event_correlation_groups",
        ["tenant_id", "status", "severity", "last_event_at"],
    )

    op.create_table(
        "normalized_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("fingerprint", sa.String(255), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("service", sa.String(200), nullable=True),
        sa.Column("resource", sa.String(255), nullable=True),
        sa.Column("environment", sa.String(80), nullable=True),
        sa.Column("labels_json", sa.JSON(), nullable=False),
        sa.Column("annotations_json", sa.JSON(), nullable=False),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disposition", sa.String(24), nullable=False),
        sa.Column("suppression_rule_id", sa.String(36), nullable=True),
        sa.Column("correlation_policy_id", sa.String(36), nullable=True),
        sa.Column("correlation_group_id", sa.String(36), nullable=True),
        sa.Column("ticket_id", sa.String(36), nullable=True),
        sa.CheckConstraint(
            "state IN ('FIRING','RESOLVED')",
            name="ck_normalized_events_state",
        ),
        sa.CheckConstraint(
            "severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_normalized_events_severity",
        ),
        sa.CheckConstraint(
            "disposition IN ('SUPPRESSED','IGNORED','CORRELATED',"
            "'INCIDENT_CREATED','INCIDENT_UPDATED','RESOLVED')",
            name="ck_normalized_events_disposition",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["event_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["suppression_rule_id"],
            ["event_suppression_rules.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["correlation_policy_id"],
            ["event_correlation_policies.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["correlation_group_id"],
            ["event_correlation_groups.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "source_id",
            "event_key",
            name="uq_normalized_events_source_key",
        ),
    )
    op.create_index(
        "ix_normalized_events_tenant_received",
        "normalized_events",
        ["tenant_id", "received_at"],
    )
    op.create_index(
        "ix_normalized_events_group",
        "normalized_events",
        ["correlation_group_id", "occurred_at"],
    )

    op.create_table(
        "event_group_activities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("correlation_group_id", sa.String(36), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=True),
        sa.Column("activity_type", sa.String(80), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("actor_name", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["correlation_group_id"],
            ["event_correlation_groups.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["normalized_events.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_event_group_activities_timeline",
        "event_group_activities",
        ["correlation_group_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_group_activities_timeline",
        table_name="event_group_activities",
    )
    op.drop_table("event_group_activities")
    op.drop_index("ix_normalized_events_group", table_name="normalized_events")
    op.drop_index(
        "ix_normalized_events_tenant_received",
        table_name="normalized_events",
    )
    op.drop_table("normalized_events")
    op.drop_index(
        "ix_event_correlation_groups_queue",
        table_name="event_correlation_groups",
    )
    op.drop_index(
        "uq_event_correlation_groups_open",
        table_name="event_correlation_groups",
    )
    op.drop_table("event_correlation_groups")
    op.drop_index(
        "ix_event_suppression_rules_active",
        table_name="event_suppression_rules",
    )
    op.drop_table("event_suppression_rules")
    op.drop_index(
        "ix_event_correlation_policies_order",
        table_name="event_correlation_policies",
    )
    op.drop_table("event_correlation_policies")
    op.drop_index(
        "ix_event_sources_tenant_enabled",
        table_name="event_sources",
    )
    op.drop_table("event_sources")
