"""Add catalog entitlement, cost, approval policy, and request SLA snapshots.

Revision ID: 20260729_0033
Revises: 20260729_0032
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260729_0033"
down_revision = "20260729_0032"
branch_labels = None
depends_on = None


def _add_missing(table: str, columns: list[sa.Column]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(table)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def upgrade() -> None:
    _add_missing(
        "users",
        [
            sa.Column("location", sa.String(length=200), nullable=True),
            sa.Column("cost_center", sa.String(length=100), nullable=True),
        ],
    )
    _add_missing(
        "catalog_items",
        [
            sa.Column(
                "unit_cost_minor",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "currency",
                sa.String(length=3),
                nullable=False,
                server_default="KZT",
            ),
            sa.Column(
                "cost_type",
                sa.String(length=24),
                nullable=False,
                server_default="NO_CHARGE",
            ),
            sa.Column(
                "risk_level",
                sa.String(length=16),
                nullable=False,
                server_default="LOW",
            ),
            sa.Column(
                "approval_policy_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "sla_policy_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
        ],
    )
    _add_missing(
        "service_requests",
        [
            sa.Column("requester_department", sa.String(length=200), nullable=True),
            sa.Column("requester_location", sa.String(length=200), nullable=True),
            sa.Column("cost_center", sa.String(length=100), nullable=True),
            sa.Column(
                "total_cost_minor",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "currency",
                sa.String(length=3),
                nullable=False,
                server_default="KZT",
            ),
            sa.Column(
                "risk_level",
                sa.String(length=16),
                nullable=False,
                server_default="LOW",
            ),
        ],
    )
    _add_missing(
        "requested_items",
        [
            sa.Column(
                "unit_cost_minor",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "total_cost_minor",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "currency",
                sa.String(length=3),
                nullable=False,
                server_default="KZT",
            ),
            sa.Column(
                "cost_type",
                sa.String(length=24),
                nullable=False,
                server_default="NO_CHARGE",
            ),
            sa.Column("cost_center", sa.String(length=100), nullable=True),
            sa.Column(
                "risk_level",
                sa.String(length=16),
                nullable=False,
                server_default="LOW",
            ),
            sa.Column(
                "entitlement_snapshot_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "approval_policy_snapshot_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "sla_policy_snapshot_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("sla_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sla_paused_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "sla_paused_seconds",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "sla_status",
                sa.String(length=24),
                nullable=False,
                server_default="NOT_STARTED",
            ),
            sa.Column("sla_breached_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "sla_escalation_level",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        ],
    )
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("requested_items")}
    if "ix_requested_items_tenant_sla" not in indexes:
        op.create_index(
            "ix_requested_items_tenant_sla",
            "requested_items",
            ["tenant_id", "sla_status", "sla_due_at"],
        )
    if "ix_service_requests_tenant_cost_center" not in {
        index["name"] for index in inspector.get_indexes("service_requests")
    }:
        op.create_index(
            "ix_service_requests_tenant_cost_center",
            "service_requests",
            ["tenant_id", "cost_center"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_service_requests_tenant_cost_center",
        table_name="service_requests",
    )
    op.drop_index("ix_requested_items_tenant_sla", table_name="requested_items")
    for name in (
        "sla_escalation_level",
        "sla_breached_at",
        "sla_status",
        "sla_paused_seconds",
        "sla_paused_at",
        "sla_due_at",
        "sla_started_at",
        "sla_policy_snapshot_json",
        "approval_policy_snapshot_json",
        "entitlement_snapshot_json",
        "risk_level",
        "cost_center",
        "cost_type",
        "currency",
        "total_cost_minor",
        "unit_cost_minor",
    ):
        op.drop_column("requested_items", name)
    for name in (
        "risk_level",
        "currency",
        "total_cost_minor",
        "cost_center",
        "requester_location",
        "requester_department",
    ):
        op.drop_column("service_requests", name)
    for name in (
        "sla_policy_json",
        "approval_policy_json",
        "risk_level",
        "cost_type",
        "currency",
        "unit_cost_minor",
    ):
        op.drop_column("catalog_items", name)
    op.drop_column("users", "cost_center")
    op.drop_column("users", "location")
