"""Add enterprise SLA/OLA calendars, targets, pauses, and timeline.

Revision ID: 20260729_0042
Revises: 20260729_0041
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0042"
down_revision: str | None = "20260729_0041"
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
    if sa.inspect(op.get_bind()).has_table("sla_business_calendars"):
        return
    op.create_table(
        "sla_business_calendars",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("weekly_hours_json", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_sla_business_calendars_tenant_name",
        ),
    )
    op.create_index(
        "ix_sla_business_calendars_tenant_active",
        "sla_business_calendars",
        ["tenant_id", "is_active", "is_default"],
    )

    op.create_table(
        "sla_calendar_exceptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("calendar_id", sa.String(36), nullable=False),
        sa.Column("exception_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("intervals_json", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "kind IN ('HOLIDAY','WORKING_DAY')",
            name="ck_sla_calendar_exceptions_kind",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["sla_business_calendars.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "calendar_id",
            "exception_date",
            name="uq_sla_calendar_exceptions_calendar_date",
        ),
    )
    op.create_index(
        "ix_sla_calendar_exceptions_lookup",
        "sla_calendar_exceptions",
        ["calendar_id", "exception_date"],
    )

    op.add_column(
        "sla_policies",
        sa.Column("calendar_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "sla_policies",
        sa.Column(
            "priority_order",
            sa.Integer(),
            server_default="100",
            nullable=False,
        ),
    )
    op.add_column(
        "sla_policies",
        sa.Column(
            "scope_json",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "sla_policies",
        sa.Column(
            "targets_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.add_column(
        "sla_policies",
        sa.Column(
            "pause_statuses_json",
            sa.JSON(),
            server_default=sa.text("'[\"WAITING_USER\",\"WAITING_VENDOR\"]'"),
            nullable=False,
        ),
    )
    op.add_column(
        "sla_policies",
        sa.Column(
            "pause_reasons_json",
            sa.JSON(),
            server_default=sa.text(
                "'[\"WAITING_CUSTOMER\",\"WAITING_VENDOR\",\"APPROVED_HOLD\"]'"
            ),
            nullable=False,
        ),
    )
    op.add_column(
        "sla_policies",
        sa.Column(
            "warning_percent",
            sa.Integer(),
            server_default="80",
            nullable=False,
        ),
    )
    op.add_column(
        "sla_policies",
        sa.Column(
            "escalations_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.add_column(
        "sla_policies",
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite requires a table rebuild when constraints are added after
        # creation. Alembic batch mode performs that rebuild safely.
        with op.batch_alter_table("sla_policies") as batch_op:
            batch_op.create_foreign_key(
                "fk_sla_policies_calendar_id",
                "sla_business_calendars",
                ["calendar_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_check_constraint(
                "ck_sla_policies_warning_percent",
                "warning_percent >= 1 AND warning_percent <= 100",
            )
    else:
        op.create_foreign_key(
            "fk_sla_policies_calendar_id",
            "sla_policies",
            "sla_business_calendars",
            ["calendar_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_check_constraint(
            "ck_sla_policies_warning_percent",
            "sla_policies",
            "warning_percent >= 1 AND warning_percent <= 100",
        )
    op.create_index(
        "ix_sla_policies_match",
        "sla_policies",
        ["tenant_id", "is_active", "priority", "priority_order"],
    )

    op.create_table(
        "ticket_sla_instances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("ticket_id", sa.String(36), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("calendar_id", sa.String(36), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("policy_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("calendar_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "total_paused_business_minutes",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('ACTIVE','PAUSED','COMPLETED','BREACHED','CANCELLED')",
            name="ck_ticket_sla_instances_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["sla_policies.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["sla_business_calendars.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "uq_ticket_sla_instances_current",
        "ticket_sla_instances",
        ["ticket_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
        sqlite_where=sa.text("is_current = 1"),
    )
    op.create_index(
        "ix_ticket_sla_instances_queue",
        "ticket_sla_instances",
        ["tenant_id", "is_current", "status", "last_evaluated_at"],
    )

    op.create_table(
        "ticket_sla_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("ticket_id", sa.String(36), nullable=False),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("warning_percent", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("warning_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("owner_type", sa.String(32), nullable=True),
        sa.Column("owner_ref", sa.String(255), nullable=False),
        sa.Column("met_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("breached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("last_escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "target_type IN "
            "('RESPONSE','RESOLUTION','FULFILLMENT','OLA','SUPPLIER')",
            name="ck_ticket_sla_targets_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','WARNING','MET','BREACHED','CANCELLED')",
            name="ck_ticket_sla_targets_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["ticket_sla_instances.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "instance_id",
            "target_type",
            "owner_ref",
            name="uq_ticket_sla_targets_instance_type_owner",
        ),
    )
    op.create_index(
        "ix_ticket_sla_targets_forecast",
        "ticket_sla_targets",
        ["tenant_id", "status", "warning_at", "due_at"],
    )

    op.create_table(
        "ticket_sla_pauses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("business_minutes", sa.Integer(), nullable=True),
        sa.Column("started_by_id", sa.String(36), nullable=True),
        sa.Column("ended_by_id", sa.String(36), nullable=True),
        sa.Column("start_status", sa.String(32), nullable=True),
        sa.Column("end_status", sa.String(32), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["ticket_sla_instances.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["started_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ended_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_ticket_sla_pauses_instance",
        "ticket_sla_pauses",
        ["instance_id", "started_at"],
    )

    op.create_table(
        "ticket_sla_timeline",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("ticket_id", sa.String(36), nullable=False),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("actor_name", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["ticket_sla_instances.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["ticket_sla_targets.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_ticket_sla_timeline_instance_created",
        "ticket_sla_timeline",
        ["instance_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ticket_sla_timeline_instance_created",
        table_name="ticket_sla_timeline",
    )
    op.drop_table("ticket_sla_timeline")
    op.drop_index(
        "ix_ticket_sla_pauses_instance",
        table_name="ticket_sla_pauses",
    )
    op.drop_table("ticket_sla_pauses")
    op.drop_index(
        "ix_ticket_sla_targets_forecast",
        table_name="ticket_sla_targets",
    )
    op.drop_table("ticket_sla_targets")
    op.drop_index(
        "ix_ticket_sla_instances_queue",
        table_name="ticket_sla_instances",
    )
    op.drop_index(
        "uq_ticket_sla_instances_current",
        table_name="ticket_sla_instances",
    )
    op.drop_table("ticket_sla_instances")

    op.drop_index("ix_sla_policies_match", table_name="sla_policies")
    op.drop_constraint(
        "ck_sla_policies_warning_percent",
        "sla_policies",
        type_="check",
    )
    op.drop_constraint(
        "fk_sla_policies_calendar_id",
        "sla_policies",
        type_="foreignkey",
    )
    for column_name in (
        "version",
        "escalations_json",
        "warning_percent",
        "pause_reasons_json",
        "pause_statuses_json",
        "targets_json",
        "scope_json",
        "priority_order",
        "calendar_id",
    ):
        op.drop_column("sla_policies", column_name)

    op.drop_index(
        "ix_sla_calendar_exceptions_lookup",
        table_name="sla_calendar_exceptions",
    )
    op.drop_table("sla_calendar_exceptions")
    op.drop_index(
        "ix_sla_business_calendars_tenant_active",
        table_name="sla_business_calendars",
    )
    op.drop_table("sla_business_calendars")
