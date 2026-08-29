"""Add production change management lifecycle tables.

Revision ID: 20260720_0026
Revises: 20260720_0025
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260720_0026"
down_revision = "20260720_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    if "change_requests" not in existing:
        op.create_table(
            "change_requests",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("change_number", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("change_type", sa.String(length=24), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("service_name", sa.String(length=200), nullable=True),
            sa.Column("impact_level", sa.String(length=24), nullable=False),
            sa.Column("likelihood", sa.Integer(), nullable=False),
            sa.Column("risk_score", sa.Integer(), nullable=False),
            sa.Column("risk_level", sa.String(length=24), nullable=False),
            sa.Column("business_justification", sa.Text(), nullable=True),
            sa.Column("implementation_plan", sa.Text(), nullable=True),
            sa.Column("test_plan", sa.Text(), nullable=True),
            sa.Column("rollback_plan", sa.Text(), nullable=True),
            sa.Column("validation_plan", sa.Text(), nullable=True),
            sa.Column("requested_by_id", sa.String(length=36), nullable=True),
            sa.Column("requested_by_name", sa.String(length=200), nullable=False),
            sa.Column("requested_by_email", sa.String(length=255), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=True),
            sa.Column("owner_name", sa.String(length=200), nullable=True),
            sa.Column("cab_required", sa.Boolean(), nullable=False),
            sa.Column("approval_status", sa.String(length=24), nullable=False),
            sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("actual_start_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("actual_end_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("outage_required", sa.Boolean(), nullable=False),
            sa.Column("outage_minutes", sa.Integer(), nullable=False),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("post_implementation_review", sa.Text(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("change_number"),
        )
        op.create_index(
            "ix_change_requests_tenant_status",
            "change_requests",
            ["tenant_id", "status"],
        )
        op.create_index(
            "ix_change_requests_planned_window",
            "change_requests",
            ["planned_start_at", "planned_end_at"],
        )

    if "change_approvals" not in existing:
        op.create_table(
            "change_approvals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("change_id", sa.String(length=36), nullable=False),
            sa.Column("approver_id", sa.String(length=36), nullable=True),
            sa.Column("approver_name", sa.String(length=200), nullable=False),
            sa.Column("approver_email", sa.String(length=255), nullable=False),
            sa.Column("decision", sa.String(length=24), nullable=False),
            sa.Column("decision_comment", sa.Text(), nullable=False),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["change_id"], ["change_requests.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_change_approvals_change_id", "change_approvals", ["change_id"])
        op.create_index("ix_change_approvals_tenant_id", "change_approvals", ["tenant_id"])

    if "change_history" not in existing:
        op.create_table(
            "change_history",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("change_id", sa.String(length=36), nullable=False),
            sa.Column("actor_user_id", sa.String(length=36), nullable=True),
            sa.Column("actor_name", sa.String(length=200), nullable=False),
            sa.Column("actor_email", sa.String(length=255), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("from_status", sa.String(length=32), nullable=True),
            sa.Column("to_status", sa.String(length=32), nullable=True),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["change_id"], ["change_requests.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_change_history_change_id", "change_history", ["change_id"])
        op.create_index("ix_change_history_tenant_id", "change_history", ["tenant_id"])

    if "change_asset_links" not in existing:
        op.create_table(
            "change_asset_links",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("change_id", sa.String(length=36), nullable=False),
            sa.Column("asset_id", sa.String(length=36), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["change_id"], ["change_requests.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("change_id", "asset_id", name="uq_change_asset_links_pair"),
        )
        op.create_index("ix_change_asset_links_asset_id", "change_asset_links", ["asset_id"])
        op.create_index("ix_change_asset_links_change_id", "change_asset_links", ["change_id"])
        op.create_index("ix_change_asset_links_tenant_id", "change_asset_links", ["tenant_id"])

    if "change_ticket_links" not in existing:
        op.create_table(
            "change_ticket_links",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("change_id", sa.String(length=36), nullable=False),
            sa.Column("ticket_id", sa.String(length=36), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(
                ["change_id"], ["change_requests.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("change_id", "ticket_id", name="uq_change_ticket_links_pair"),
        )
        op.create_index("ix_change_ticket_links_change_id", "change_ticket_links", ["change_id"])
        op.create_index("ix_change_ticket_links_tenant_id", "change_ticket_links", ["tenant_id"])
        op.create_index("ix_change_ticket_links_ticket_id", "change_ticket_links", ["ticket_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table_name in (
        "change_ticket_links",
        "change_asset_links",
        "change_history",
        "change_approvals",
        "change_requests",
    ):
        if table_name in existing:
            op.drop_table(table_name)
