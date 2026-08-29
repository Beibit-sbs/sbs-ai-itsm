"""Add tenant-safe Microsoft Teams collaboration and delivery pipeline.

Revision ID: 20260729_0048
Revises: 20260729_0047
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0048"
down_revision: str | None = "20260729_0047"
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
    if sa.inspect(op.get_bind()).has_table("teams_connectors"):
        return
    op.create_table(
        "teams_connectors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("webhook_url_encrypted", sa.Text(), nullable=True),
        sa.Column("webhook_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("team_name", sa.String(200), nullable=True),
        sa.Column("channel_name", sa.String(200), nullable=True),
        sa.Column("channel_url", sa.String(2_000), nullable=True),
        sa.Column("meeting_url", sa.String(2_000), nullable=True),
        sa.Column("event_types_json", sa.JSON(), nullable=False),
        sa.Column("minimum_severity", sa.String(16), nullable=False),
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
            "provider_type IN ('WORKFLOW_WEBHOOK','MOCK')",
            name="ck_teams_connectors_provider",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','ERROR','REVOKED')",
            name="ck_teams_connectors_status",
        ),
        sa.CheckConstraint(
            "purpose IN ('DEFAULT','APPROVALS','MAJOR_INCIDENT','SECURITY')",
            name="ck_teams_connectors_purpose",
        ),
        sa.CheckConstraint(
            "minimum_severity IN ('INFO','WARNING','CRITICAL')",
            name="ck_teams_connectors_severity",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_teams_connectors_tenant_name",
        ),
    )
    op.create_index(
        "ix_teams_connectors_tenant_status",
        "teams_connectors",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_teams_connectors_tenant_purpose",
        "teams_connectors",
        ["tenant_id", "purpose"],
    )

    op.create_table(
        "teams_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector_id", sa.String(36), nullable=False),
        sa.Column("notification_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=True),
        sa.Column("entity_id", sa.String(120), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("action_url", sa.String(2_000), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_status_code", sa.Integer(), nullable=True),
        sa.Column("provider_reference", sa.String(512), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('QUEUED','RETRY','SENT','FAILED','DEAD_LETTER','CANCELLED')",
            name="ck_teams_deliveries_status",
        ),
        sa.CheckConstraint(
            "severity IN ('INFO','WARNING','CRITICAL')",
            name="ck_teams_deliveries_severity",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["teams_connectors.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "connector_id",
            "idempotency_key",
            name="uq_teams_deliveries_connector_idempotency",
        ),
    )
    op.create_index(
        "ix_teams_deliveries_queue",
        "teams_deliveries",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_teams_deliveries_tenant_created",
        "teams_deliveries",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_teams_deliveries_entity",
        "teams_deliveries",
        ["tenant_id", "entity_type", "entity_id"],
    )

    op.create_table(
        "teams_major_incident_rooms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector_id", sa.String(36), nullable=False),
        sa.Column("major_incident_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("channel_url", sa.String(2_000), nullable=True),
        sa.Column("meeting_url", sa.String(2_000), nullable=True),
        sa.Column("opened_by_id", sa.String(36), nullable=True),
        sa.Column("closed_by_id", sa.String(36), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('OPEN','CLOSED')",
            name="ck_teams_major_incident_rooms_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["teams_connectors.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["major_incident_id"],
            ["major_incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["opened_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["closed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "major_incident_id",
            name="uq_teams_major_incident_rooms_incident",
        ),
    )
    op.create_index(
        "ix_teams_major_incident_rooms_tenant_status",
        "teams_major_incident_rooms",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_teams_major_incident_rooms_tenant_status",
        table_name="teams_major_incident_rooms",
    )
    op.drop_table("teams_major_incident_rooms")
    op.drop_index("ix_teams_deliveries_entity", table_name="teams_deliveries")
    op.drop_index(
        "ix_teams_deliveries_tenant_created",
        table_name="teams_deliveries",
    )
    op.drop_index("ix_teams_deliveries_queue", table_name="teams_deliveries")
    op.drop_table("teams_deliveries")
    op.drop_index(
        "ix_teams_connectors_tenant_purpose",
        table_name="teams_connectors",
    )
    op.drop_index(
        "ix_teams_connectors_tenant_status",
        table_name="teams_connectors",
    )
    op.drop_table("teams_connectors")
