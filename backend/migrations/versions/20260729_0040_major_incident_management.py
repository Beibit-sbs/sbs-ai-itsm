"""Add major incident command, communications, PIR, and actions.

Revision ID: 20260729_0040
Revises: 20260729_0039
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0040"
down_revision: str | None = "20260729_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("major_incidents"):
        return
    op.create_table(
        "major_incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("ticket_id", sa.String(36), nullable=False),
        sa.Column("major_number", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("impact_statement", sa.Text(), nullable=False),
        sa.Column("affected_service", sa.String(200), nullable=False),
        sa.Column("service_status", sa.String(32), nullable=False),
        sa.Column("customer_impact", sa.Text(), nullable=False),
        sa.Column("war_room_url", sa.String(2000), nullable=True),
        sa.Column("conference_details", sa.Text(), nullable=True),
        sa.Column("commander_user_id", sa.String(36), nullable=False),
        sa.Column("communications_lead_user_id", sa.String(36), nullable=False),
        sa.Column("declared_by_id", sa.String(36), nullable=True),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_update_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "severity IN ('SEV1','SEV2')",
            name="ck_major_incidents_severity",
        ),
        sa.CheckConstraint(
            "status IN ('DECLARED','MITIGATING','MONITORING','RESOLVED',"
            "'CLOSED','CANCELLED')",
            name="ck_major_incidents_status",
        ),
        sa.CheckConstraint(
            "service_status IN ('MAJOR_OUTAGE','PARTIAL_OUTAGE','DEGRADED',"
            "'OPERATIONAL','UNKNOWN')",
            name="ck_major_incidents_service_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["commander_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["communications_lead_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["declared_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("ticket_id", name="uq_major_incidents_ticket"),
        sa.UniqueConstraint(
            "tenant_id",
            "major_number",
            name="uq_major_incidents_tenant_number",
        ),
    )
    op.create_index(
        "ix_major_incidents_tenant_status",
        "major_incidents",
        ["tenant_id", "status", "declared_at"],
    )
    op.create_table(
        "major_incident_participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("major_incident_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("contact", sa.String(255), nullable=True),
        sa.Column("added_by_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('TECHNICAL_LEAD','SME','SCRIBE','STAKEHOLDER')",
            name="ck_major_incident_participants_role",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["major_incident_id"], ["major_incidents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["added_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_major_incident_participants_incident",
        "major_incident_participants",
        ["major_incident_id", "role"],
    )
    op.create_table(
        "major_incident_child_tickets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("major_incident_id", sa.String(36), nullable=False),
        sa.Column("ticket_id", sa.String(36), nullable=False),
        sa.Column("linked_by_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["major_incident_id"], ["major_incidents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "major_incident_id",
            "ticket_id",
            name="uq_major_incident_child_ticket",
        ),
        sa.UniqueConstraint(
            "ticket_id",
            name="uq_major_incident_child_one_parent",
        ),
    )
    op.create_table(
        "major_incident_updates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("major_incident_id", sa.String(36), nullable=False),
        sa.Column("update_type", sa.String(40), nullable=False),
        sa.Column("audience", sa.String(24), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("service_status", sa.String(32), nullable=True),
        sa.Column("channel", sa.String(80), nullable=True),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("actor_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "update_type IN ('STATUS_UPDATE','STAKEHOLDER_COMMUNICATION',"
            "'TECHNICAL_EVENT','DECISION','MILESTONE')",
            name="ck_major_incident_updates_type",
        ),
        sa.CheckConstraint(
            "audience IN ('INTERNAL','STAKEHOLDERS','PUBLIC')",
            name="ck_major_incident_updates_audience",
        ),
        sa.CheckConstraint(
            "service_status IS NULL OR service_status IN "
            "('MAJOR_OUTAGE','PARTIAL_OUTAGE','DEGRADED','OPERATIONAL','UNKNOWN')",
            name="ck_major_incident_updates_service_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["major_incident_id"], ["major_incidents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_major_incident_updates_timeline",
        "major_incident_updates",
        ["major_incident_id", "created_at"],
    )
    op.create_table(
        "major_incident_pirs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("major_incident_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("contributing_factors", sa.Text(), nullable=False),
        sa.Column("lessons_learned", sa.Text(), nullable=False),
        sa.Column("prevention_plan", sa.Text(), nullable=False),
        sa.Column("prepared_by_id", sa.String(36), nullable=True),
        sa.Column("approved_by_id", sa.String(36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('DRAFT','APPROVED')",
            name="ck_major_incident_pirs_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["major_incident_id"], ["major_incidents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["prepared_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "major_incident_id",
            name="uq_major_incident_pirs_incident",
        ),
    )
    op.create_table(
        "major_incident_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("major_incident_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("completion_evidence", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('OPEN','IN_PROGRESS','DONE','CANCELLED')",
            name="ck_major_incident_actions_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["major_incident_id"], ["major_incidents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_major_incident_actions_queue",
        "major_incident_actions",
        ["tenant_id", "status", "due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_major_incident_actions_queue", table_name="major_incident_actions")
    op.drop_table("major_incident_actions")
    op.drop_table("major_incident_pirs")
    op.drop_index(
        "ix_major_incident_updates_timeline",
        table_name="major_incident_updates",
    )
    op.drop_table("major_incident_updates")
    op.drop_table("major_incident_child_tickets")
    op.drop_index(
        "ix_major_incident_participants_incident",
        table_name="major_incident_participants",
    )
    op.drop_table("major_incident_participants")
    op.drop_index("ix_major_incidents_tenant_status", table_name="major_incidents")
    op.drop_table("major_incidents")
