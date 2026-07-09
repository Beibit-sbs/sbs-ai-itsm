"""workflow automation production schema updates

Revision ID: 20261113_0007
Revises: 20261112_0006
Create Date: 2026-11-13 00:07:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261113_0007"
down_revision = "20261112_0006"
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


def _create_automation_rules_table() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("trigger_type", sa.String(length=80), nullable=False),
        sa.Column("conditions_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("actions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_role", sa.String(length=80), nullable=True),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_id", sa.String(length=36), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_runbooks_table() -> None:
    op.create_table(
        "runbooks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("steps_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_approval_requests_table() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=120), nullable=True),
        sa.Column("requested_by_id", sa.String(length=36), nullable=True),
        sa.Column("approver_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("approver_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_automation_runs_table() -> None:
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("runbook_id", sa.String(length=36), nullable=True),
        sa.Column("trigger_type", sa.String(length=80), nullable=False),
        sa.Column("trigger_entity_type", sa.String(length=80), nullable=True),
        sa.Column("trigger_entity_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("input_payload_json", sa.Text(), nullable=True),
        sa.Column("output_payload_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_by_id", sa.String(length=36), nullable=True),
        sa.Column("approval_request_id", sa.String(length=36), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["automation_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["runbook_id"], ["runbooks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approval_request_id"], ["approval_requests.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_automation_action_logs_table() -> None:
    op.create_table(
        "automation_action_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("automation_run_id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=True),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("action_payload_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("result_payload_json", sa.Text(), nullable=True),
        sa.Column("input_json", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["automation_run_id"], ["automation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["automation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_runbook_executions_table() -> None:
    op.create_table(
        "runbook_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("runbook_id", sa.String(length=36), nullable=False),
        sa.Column("ticket_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_by", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["runbook_id"], ["runbooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "automation_rules"):
        _create_automation_rules_table()
    if not _has_table(inspector, "runbooks"):
        _create_runbooks_table()
    if not _has_table(inspector, "approval_requests"):
        _create_approval_requests_table()
    if not _has_table(inspector, "automation_runs"):
        _create_automation_runs_table()
    if not _has_table(inspector, "automation_action_logs"):
        _create_automation_action_logs_table()
    if not _has_table(inspector, "runbook_executions"):
        _create_runbook_executions_table()

    inspector = inspect(bind)

    if _has_table(inspector, "automation_rules"):
        with op.batch_alter_table("automation_rules") as batch_op:
            if not _has_column(inspector, "automation_rules", "requires_approval"):
                batch_op.add_column(sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()))
            if not _has_column(inspector, "automation_rules", "approval_role"):
                batch_op.add_column(sa.Column("approval_role", sa.String(length=80), nullable=True))
            if not _has_column(inspector, "automation_rules", "cooldown_minutes"):
                batch_op.add_column(sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="0"))
            if not _has_column(inspector, "automation_rules", "last_run_at"):
                batch_op.add_column(sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True))
            if not _has_column(inspector, "automation_rules", "run_count"):
                batch_op.add_column(sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"))
            if not _has_column(inspector, "automation_rules", "failure_count"):
                batch_op.add_column(sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"))
            if not _has_column(inspector, "automation_rules", "created_by_id"):
                batch_op.add_column(sa.Column("created_by_id", sa.String(length=36), nullable=True))
            if not _has_column(inspector, "automation_rules", "updated_by_id"):
                batch_op.add_column(sa.Column("updated_by_id", sa.String(length=36), nullable=True))

    inspector = inspect(bind)
    if _has_table(inspector, "automation_rules"):
        with op.batch_alter_table("automation_rules") as batch_op:
            if _has_column(inspector, "automation_rules", "created_by_id") and not _has_fk(inspector, "automation_rules", "fk_automation_rules_created_by_id_users"):
                batch_op.create_foreign_key("fk_automation_rules_created_by_id_users", "users", ["created_by_id"], ["id"], ondelete="SET NULL")
            if _has_column(inspector, "automation_rules", "updated_by_id") and not _has_fk(inspector, "automation_rules", "fk_automation_rules_updated_by_id_users"):
                batch_op.create_foreign_key("fk_automation_rules_updated_by_id_users", "users", ["updated_by_id"], ["id"], ondelete="SET NULL")

    if _has_table(inspector, "runbooks"):
        with op.batch_alter_table("runbooks") as batch_op:
            if not _has_column(inspector, "runbooks", "name"):
                batch_op.add_column(sa.Column("name", sa.String(length=255), nullable=True))
            if not _has_column(inspector, "runbooks", "requires_approval"):
                batch_op.add_column(sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()))
            if not _has_column(inspector, "runbooks", "created_by_id"):
                batch_op.add_column(sa.Column("created_by_id", sa.String(length=36), nullable=True))
            if not _has_column(inspector, "runbooks", "updated_by_id"):
                batch_op.add_column(sa.Column("updated_by_id", sa.String(length=36), nullable=True))

    inspector = inspect(bind)
    if _has_table(inspector, "runbooks"):
        with op.batch_alter_table("runbooks") as batch_op:
            if _has_column(inspector, "runbooks", "created_by_id") and not _has_fk(inspector, "runbooks", "fk_runbooks_created_by_id_users"):
                batch_op.create_foreign_key("fk_runbooks_created_by_id_users", "users", ["created_by_id"], ["id"], ondelete="SET NULL")
            if _has_column(inspector, "runbooks", "updated_by_id") and not _has_fk(inspector, "runbooks", "fk_runbooks_updated_by_id_users"):
                batch_op.create_foreign_key("fk_runbooks_updated_by_id_users", "users", ["updated_by_id"], ["id"], ondelete="SET NULL")

    if _has_table(inspector, "approval_requests"):
        with op.batch_alter_table("approval_requests") as batch_op:
            if not _has_column(inspector, "approval_requests", "requested_by_id"):
                batch_op.add_column(sa.Column("requested_by_id", sa.String(length=36), nullable=True))
            if not _has_column(inspector, "approval_requests", "approver_id"):
                batch_op.add_column(sa.Column("approver_id", sa.String(length=36), nullable=True))
            if not _has_column(inspector, "approval_requests", "reason"):
                batch_op.add_column(sa.Column("reason", sa.Text(), nullable=True))
            if not _has_column(inspector, "approval_requests", "requested_at"):
                batch_op.add_column(sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
            if not _has_column(inspector, "approval_requests", "metadata_json"):
                batch_op.add_column(sa.Column("metadata_json", sa.Text(), nullable=True))

    inspector = inspect(bind)
    if _has_table(inspector, "approval_requests"):
        with op.batch_alter_table("approval_requests") as batch_op:
            if _has_column(inspector, "approval_requests", "requested_by_id") and not _has_fk(inspector, "approval_requests", "fk_approval_requests_requested_by_id_users"):
                batch_op.create_foreign_key("fk_approval_requests_requested_by_id_users", "users", ["requested_by_id"], ["id"], ondelete="SET NULL")
            if _has_column(inspector, "approval_requests", "approver_id") and not _has_fk(inspector, "approval_requests", "fk_approval_requests_approver_id_users"):
                batch_op.create_foreign_key("fk_approval_requests_approver_id_users", "users", ["approver_id"], ["id"], ondelete="SET NULL")

    if _has_table(inspector, "automation_runs"):
        with op.batch_alter_table("automation_runs") as batch_op:
            if not _has_column(inspector, "automation_runs", "runbook_id"):
                batch_op.add_column(sa.Column("runbook_id", sa.String(length=36), nullable=True))
            if not _has_column(inspector, "automation_runs", "input_payload_json"):
                batch_op.add_column(sa.Column("input_payload_json", sa.Text(), nullable=True))
            if not _has_column(inspector, "automation_runs", "output_payload_json"):
                batch_op.add_column(sa.Column("output_payload_json", sa.Text(), nullable=True))
            if not _has_column(inspector, "automation_runs", "executed_by_id"):
                batch_op.add_column(sa.Column("executed_by_id", sa.String(length=36), nullable=True))
            if not _has_column(inspector, "automation_runs", "approval_request_id"):
                batch_op.add_column(sa.Column("approval_request_id", sa.String(length=36), nullable=True))

    inspector = inspect(bind)
    if _has_table(inspector, "automation_runs"):
        with op.batch_alter_table("automation_runs") as batch_op:
            if _has_column(inspector, "automation_runs", "runbook_id") and not _has_fk(inspector, "automation_runs", "fk_automation_runs_runbook_id_runbooks"):
                batch_op.create_foreign_key("fk_automation_runs_runbook_id_runbooks", "runbooks", ["runbook_id"], ["id"], ondelete="SET NULL")
            if _has_column(inspector, "automation_runs", "executed_by_id") and not _has_fk(inspector, "automation_runs", "fk_automation_runs_executed_by_id_users"):
                batch_op.create_foreign_key("fk_automation_runs_executed_by_id_users", "users", ["executed_by_id"], ["id"], ondelete="SET NULL")
            if _has_column(inspector, "automation_runs", "approval_request_id") and not _has_fk(inspector, "automation_runs", "fk_automation_runs_approval_request_id_approval_requests"):
                batch_op.create_foreign_key("fk_automation_runs_approval_request_id_approval_requests", "approval_requests", ["approval_request_id"], ["id"], ondelete="SET NULL")

    if _has_table(inspector, "automation_action_logs"):
        with op.batch_alter_table("automation_action_logs") as batch_op:
            if not _has_column(inspector, "automation_action_logs", "execution_id"):
                batch_op.add_column(sa.Column("execution_id", sa.String(length=36), nullable=True))
            if not _has_column(inspector, "automation_action_logs", "action_payload_json"):
                batch_op.add_column(sa.Column("action_payload_json", sa.Text(), nullable=True))
            if not _has_column(inspector, "automation_action_logs", "result_payload_json"):
                batch_op.add_column(sa.Column("result_payload_json", sa.Text(), nullable=True))

    inspector = inspect(bind)
    if _has_table(inspector, "automation_action_logs") and _has_column(inspector, "automation_action_logs", "execution_id") and not _has_fk(inspector, "automation_action_logs", "fk_automation_action_logs_execution_id_automation_runs"):
        with op.batch_alter_table("automation_action_logs") as batch_op:
            batch_op.create_foreign_key("fk_automation_action_logs_execution_id_automation_runs", "automation_runs", ["execution_id"], ["id"], ondelete="CASCADE")

    if _has_table(inspector, "runbooks"):
        op.execute("UPDATE runbooks SET name = title WHERE name IS NULL")

    if _has_table(inspector, "approval_requests"):
        op.execute("UPDATE approval_requests SET requested_at = created_at WHERE requested_at IS NULL")
        op.execute("UPDATE approval_requests SET status = lower(status)")

    inspector = inspect(bind)
    if _has_table(inspector, "automation_rules") and not _has_index(inspector, "automation_rules", "ix_automation_rules_trigger_type"):
        op.create_index("ix_automation_rules_trigger_type", "automation_rules", ["trigger_type"], unique=False)
    if _has_table(inspector, "automation_rules") and not _has_index(inspector, "automation_rules", "ix_automation_rules_is_active"):
        op.create_index("ix_automation_rules_is_active", "automation_rules", ["is_active"], unique=False)
    if _has_table(inspector, "automation_runs") and not _has_index(inspector, "automation_runs", "ix_automation_runs_rule_id"):
        op.create_index("ix_automation_runs_rule_id", "automation_runs", ["rule_id"], unique=False)
    if _has_table(inspector, "automation_runs") and not _has_index(inspector, "automation_runs", "ix_automation_runs_status"):
        op.create_index("ix_automation_runs_status", "automation_runs", ["status"], unique=False)
    if _has_table(inspector, "automation_runs") and not _has_index(inspector, "automation_runs", "ix_automation_runs_created_at"):
        op.create_index("ix_automation_runs_created_at", "automation_runs", ["created_at"], unique=False)
    if _has_table(inspector, "automation_action_logs") and not _has_index(inspector, "automation_action_logs", "ix_automation_action_logs_execution_id"):
        op.create_index("ix_automation_action_logs_execution_id", "automation_action_logs", ["execution_id"], unique=False)
    if _has_table(inspector, "approval_requests") and not _has_index(inspector, "approval_requests", "ix_approval_requests_status"):
        op.create_index("ix_approval_requests_status", "approval_requests", ["status"], unique=False)
    if _has_table(inspector, "approval_requests") and not _has_index(inspector, "approval_requests", "ix_approval_requests_requested_by_id"):
        op.create_index("ix_approval_requests_requested_by_id", "approval_requests", ["requested_by_id"], unique=False)
    if _has_table(inspector, "approval_requests") and not _has_index(inspector, "approval_requests", "ix_approval_requests_approver_id"):
        op.create_index("ix_approval_requests_approver_id", "approval_requests", ["approver_id"], unique=False)


def downgrade() -> None:
    # Keep downgrade intentionally non-destructive for production safety.
    pass
