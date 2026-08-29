"""Add change calendar, standard models, execution, CAB, and PIR governance.

Revision ID: 20260729_0043
Revises: 20260729_0042
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0043"
down_revision: str | None = "20260729_0042"
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
    if sa.inspect(op.get_bind()).has_table("change_windows"):
        return
    op.create_table(
        "change_windows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("window_type", sa.String(16), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("services_json", sa.JSON(), nullable=False),
        sa.Column("asset_ids_json", sa.JSON(), nullable=False),
        sa.Column("environments_json", sa.JSON(), nullable=False),
        sa.Column("recurrence_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "window_type IN ('MAINTENANCE','BLACKOUT')",
            name="ck_change_windows_type",
        ),
        sa.CheckConstraint(
            "ends_at > starts_at",
            name="ck_change_windows_range",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            "starts_at",
            name="uq_change_windows_tenant_name_start",
        ),
    )
    op.create_index(
        "ix_change_windows_calendar",
        "change_windows",
        ["tenant_id", "is_active", "starts_at", "ends_at"],
    )

    op.create_table(
        "standard_change_models",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("service_name", sa.String(200), nullable=True),
        sa.Column("environment", sa.String(80), nullable=False),
        sa.Column("default_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("outage_required", sa.Boolean(), nullable=False),
        sa.Column("outage_minutes", sa.Integer(), nullable=False),
        sa.Column("implementation_plan", sa.Text(), nullable=False),
        sa.Column("test_plan", sa.Text(), nullable=False),
        sa.Column("rollback_plan", sa.Text(), nullable=False),
        sa.Column("validation_plan", sa.Text(), nullable=False),
        sa.Column("task_templates_json", sa.JSON(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("preauthorized_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approved_by_id", sa.String(36), nullable=True),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_standard_change_models_tenant_code",
        ),
    )
    op.create_index(
        "ix_standard_change_models_active",
        "standard_change_models",
        ["tenant_id", "is_active", "service_name"],
    )

    op.add_column(
        "change_requests",
        sa.Column(
            "environment",
            sa.String(80),
            server_default="PRODUCTION",
            nullable=False,
        ),
    )
    op.add_column(
        "change_requests",
        sa.Column("standard_model_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "change_requests",
        sa.Column(
            "validation_status",
            sa.String(24),
            server_default="NOT_STARTED",
            nullable=False,
        ),
    )
    op.add_column(
        "change_requests",
        sa.Column(
            "pir_status",
            sa.String(24),
            server_default="NOT_REQUIRED",
            nullable=False,
        ),
    )
    op.add_column(
        "change_requests",
        sa.Column("outcome", sa.String(24), nullable=True),
    )
    op.add_column(
        "change_requests",
        sa.Column("blackout_override_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "change_requests",
        sa.Column("blackout_override_by_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "change_requests",
        sa.Column(
            "blackout_override_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("change_requests") as batch_op:
            batch_op.create_foreign_key(
                "fk_change_requests_standard_model_id",
                "standard_change_models",
                ["standard_model_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_foreign_key(
                "fk_change_requests_blackout_override_by_id",
                "users",
                ["blackout_override_by_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        op.create_foreign_key(
            "fk_change_requests_standard_model_id",
            "change_requests",
            "standard_change_models",
            ["standard_model_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            "fk_change_requests_blackout_override_by_id",
            "change_requests",
            "users",
            ["blackout_override_by_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "change_implementation_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("change_id", sa.String(36), nullable=False),
        sa.Column("task_type", sa.String(20), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=True),
        sa.Column("owner_name", sa.String(200), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "task_type IN ('IMPLEMENTATION','VALIDATION','ROLLBACK')",
            name="ck_change_implementation_tasks_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','IN_PROGRESS','COMPLETED','FAILED','SKIPPED')",
            name="ck_change_implementation_tasks_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["change_id"], ["change_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "change_id",
            "task_type",
            "sequence",
            name="uq_change_implementation_tasks_sequence",
        ),
    )
    op.create_index(
        "ix_change_implementation_tasks_change",
        "change_implementation_tasks",
        ["change_id", "task_type", "sequence"],
    )

    op.create_table(
        "change_post_implementation_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("change_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("objectives_met", sa.Boolean(), nullable=False),
        sa.Column("actual_impact", sa.Text(), nullable=False),
        sa.Column("actual_outage_minutes", sa.Integer(), nullable=False),
        sa.Column("incidents_caused", sa.Integer(), nullable=False),
        sa.Column("lessons_learned", sa.Text(), nullable=False),
        sa.Column("follow_up_actions_json", sa.JSON(), nullable=False),
        sa.Column("prepared_by_id", sa.String(36), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", sa.String(36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_comment", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('DRAFT','SUBMITTED','APPROVED')",
            name="ck_change_post_implementation_reviews_status",
        ),
        sa.CheckConstraint(
            "outcome IN ('SUCCESS','PARTIAL','FAILED','ROLLED_BACK')",
            name="ck_change_post_implementation_reviews_outcome",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["change_id"], ["change_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prepared_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "change_id",
            name="uq_change_post_implementation_reviews_change",
        ),
    )

    op.create_table(
        "cab_meetings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("meeting_type", sa.String(8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("location_or_url", sa.String(500), nullable=True),
        sa.Column("chair_user_id", sa.String(36), nullable=True),
        sa.Column("participant_user_ids_json", sa.JSON(), nullable=False),
        sa.Column("minutes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "meeting_type IN ('CAB','ECAB')",
            name="ck_cab_meetings_type",
        ),
        sa.CheckConstraint(
            "status IN "
            "('DRAFT','PUBLISHED','IN_PROGRESS','COMPLETED','CANCELLED')",
            name="ck_cab_meetings_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chair_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_cab_meetings_schedule",
        "cab_meetings",
        ["tenant_id", "status", "scheduled_at"],
    )

    op.create_table(
        "cab_agenda_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("meeting_id", sa.String(36), nullable=False),
        sa.Column("change_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("presenter_user_id", sa.String(36), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(16), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("decided_by_id", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN "
            "('APPROVED','REJECTED','DEFERRED','MORE_INFO')",
            name="ck_cab_agenda_items_decision",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meeting_id"], ["cab_meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["change_id"], ["change_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["presenter_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "meeting_id",
            "change_id",
            name="uq_cab_agenda_items_meeting_change",
        ),
        sa.UniqueConstraint(
            "meeting_id",
            "sequence",
            name="uq_cab_agenda_items_meeting_sequence",
        ),
    )
    op.create_index(
        "ix_cab_agenda_items_meeting",
        "cab_agenda_items",
        ["meeting_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cab_agenda_items_meeting",
        table_name="cab_agenda_items",
    )
    op.drop_table("cab_agenda_items")
    op.drop_index("ix_cab_meetings_schedule", table_name="cab_meetings")
    op.drop_table("cab_meetings")
    op.drop_table("change_post_implementation_reviews")
    op.drop_index(
        "ix_change_implementation_tasks_change",
        table_name="change_implementation_tasks",
    )
    op.drop_table("change_implementation_tasks")

    op.drop_constraint(
        "fk_change_requests_blackout_override_by_id",
        "change_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_change_requests_standard_model_id",
        "change_requests",
        type_="foreignkey",
    )
    for column_name in (
        "blackout_override_at",
        "blackout_override_by_id",
        "blackout_override_reason",
        "outcome",
        "pir_status",
        "validation_status",
        "standard_model_id",
        "environment",
    ):
        op.drop_column("change_requests", column_name)

    op.drop_index(
        "ix_standard_change_models_active",
        table_name="standard_change_models",
    )
    op.drop_table("standard_change_models")
    op.drop_index("ix_change_windows_calendar", table_name="change_windows")
    op.drop_table("change_windows")
