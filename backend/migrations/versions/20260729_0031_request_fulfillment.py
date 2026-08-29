"""Add service request fulfillment aggregates.

Revision ID: 20260729_0031
Revises: 20260729_0030
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260729_0031"
down_revision = "20260729_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    if "service_requests" not in existing:
        op.create_table(
            "service_requests",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("request_number", sa.String(length=40), nullable=False),
            sa.Column("idempotency_key", sa.String(length=120), nullable=False),
            sa.Column("requester_id", sa.String(length=36), nullable=True),
            sa.Column("requester_name", sa.String(length=200), nullable=False),
            sa.Column("requester_email", sa.String(length=255), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("priority", sa.String(length=24), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "idempotency_key",
                name="uq_service_requests_tenant_idempotency",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "request_number",
                name="uq_service_requests_tenant_number",
            ),
        )
        op.create_index(
            "ix_service_requests_requester_id",
            "service_requests",
            ["requester_id"],
        )
        op.create_index(
            "ix_service_requests_tenant_status",
            "service_requests",
            ["tenant_id", "status"],
        )

    if "requested_items" not in existing:
        op.create_table(
            "requested_items",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("request_id", sa.String(length=36), nullable=False),
            sa.Column("catalog_item_id", sa.String(length=36), nullable=True),
            sa.Column("catalog_form_version_id", sa.String(length=36), nullable=True),
            sa.Column("item_code", sa.String(length=64), nullable=False),
            sa.Column("item_name", sa.String(length=255), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("form_version", sa.Integer(), nullable=True),
            sa.Column("schema_hash", sa.String(length=64), nullable=True),
            sa.Column("form_values_json", sa.Text(), nullable=False),
            sa.Column("support_group", sa.String(length=160), nullable=True),
            sa.Column("approval_required", sa.Boolean(), nullable=False),
            sa.Column("approval_mode", sa.String(length=24), nullable=False),
            sa.Column("expected_delivery_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.ForeignKeyConstraint(
                ["catalog_form_version_id"],
                ["catalog_form_versions.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["catalog_item_id"],
                ["catalog_items.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["request_id"],
                ["service_requests.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_requested_items_catalog_item_id",
            "requested_items",
            ["catalog_item_id"],
        )
        op.create_index(
            "ix_requested_items_request_id",
            "requested_items",
            ["request_id"],
        )
        op.create_index(
            "ix_requested_items_tenant_status",
            "requested_items",
            ["tenant_id", "status"],
        )

    if "request_approvals" not in existing:
        op.create_table(
            "request_approvals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("request_id", sa.String(length=36), nullable=False),
            sa.Column("requested_item_id", sa.String(length=36), nullable=False),
            sa.Column("round", sa.Integer(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("approval_mode", sa.String(length=24), nullable=False),
            sa.Column("approver_id", sa.String(length=36), nullable=True),
            sa.Column("approver_name", sa.String(length=200), nullable=False),
            sa.Column("approver_email", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["request_id"],
                ["service_requests.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["requested_item_id"],
                ["requested_items.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_request_approvals_approver_status",
            "request_approvals",
            ["approver_id", "status"],
        )
        op.create_index(
            "ix_request_approvals_item_round",
            "request_approvals",
            ["requested_item_id", "round"],
        )
        op.create_index(
            "ix_request_approvals_request_status",
            "request_approvals",
            ["request_id", "status"],
        )

    if "fulfillment_tasks" not in existing:
        op.create_table(
            "fulfillment_tasks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("request_id", sa.String(length=36), nullable=False),
            sa.Column("requested_item_id", sa.String(length=36), nullable=False),
            sa.Column("task_number", sa.String(length=48), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("assignee_id", sa.String(length=36), nullable=True),
            sa.Column("assignee_name", sa.String(length=200), nullable=True),
            sa.Column("support_group", sa.String(length=160), nullable=True),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("evidence_json", sa.Text(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["request_id"],
                ["service_requests.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["requested_item_id"],
                ["requested_items.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "task_number",
                name="uq_fulfillment_tasks_tenant_number",
            ),
        )
        op.create_index(
            "ix_fulfillment_tasks_assignee_status",
            "fulfillment_tasks",
            ["assignee_id", "status"],
        )
        op.create_index(
            "ix_fulfillment_tasks_item_status",
            "fulfillment_tasks",
            ["requested_item_id", "status"],
        )
        op.create_index(
            "ix_fulfillment_tasks_request_id",
            "fulfillment_tasks",
            ["request_id"],
        )

    if "request_activities" not in existing:
        op.create_table(
            "request_activities",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("request_id", sa.String(length=36), nullable=False),
            sa.Column("requested_item_id", sa.String(length=36), nullable=True),
            sa.Column("entity_type", sa.String(length=48), nullable=False),
            sa.Column("entity_id", sa.String(length=36), nullable=False),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("actor_user_id", sa.String(length=36), nullable=True),
            sa.Column("actor_name", sa.String(length=200), nullable=False),
            sa.Column("actor_email", sa.String(length=255), nullable=True),
            sa.Column("visibility", sa.String(length=20), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("old_value_json", sa.Text(), nullable=True),
            sa.Column("new_value_json", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["request_id"],
                ["service_requests.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["requested_item_id"],
                ["requested_items.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_request_activities_request_created",
            "request_activities",
            ["request_id", "created_at"],
        )
        op.create_index(
            "ix_request_activities_tenant_id",
            "request_activities",
            ["tenant_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table_name in (
        "request_activities",
        "fulfillment_tasks",
        "request_approvals",
        "requested_items",
        "service_requests",
    ):
        if table_name in existing:
            op.drop_table(table_name)
