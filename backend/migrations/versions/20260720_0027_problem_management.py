"""Add production problem management and Known Error Database tables.

Revision ID: 20260720_0027
Revises: 20260720_0026
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260720_0027"
down_revision = "20260720_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    if "problems" not in existing:
        op.create_table(
            "problems",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("problem_number", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("problem_type", sa.String(length=24), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("service_name", sa.String(length=200), nullable=True),
            sa.Column("category", sa.String(length=120), nullable=True),
            sa.Column("impact_level", sa.String(length=24), nullable=False),
            sa.Column("urgency_level", sa.String(length=24), nullable=False),
            sa.Column("priority", sa.String(length=8), nullable=False),
            sa.Column("detection_source", sa.String(length=120), nullable=True),
            sa.Column("symptoms", sa.Text(), nullable=False),
            sa.Column("root_cause", sa.Text(), nullable=True),
            sa.Column("workaround", sa.Text(), nullable=True),
            sa.Column("workaround_status", sa.String(length=24), nullable=False),
            sa.Column("known_error_title", sa.String(length=255), nullable=True),
            sa.Column("known_error_published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("known_error_published_by_id", sa.String(length=36), nullable=True),
            sa.Column("known_error_published_by_name", sa.String(length=200), nullable=True),
            sa.Column("resolution_summary", sa.Text(), nullable=True),
            sa.Column("validation_summary", sa.Text(), nullable=True),
            sa.Column("created_by_id", sa.String(length=36), nullable=True),
            sa.Column("created_by_name", sa.String(length=200), nullable=False),
            sa.Column("created_by_email", sa.String(length=255), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=True),
            sa.Column("owner_name", sa.String(length=200), nullable=True),
            sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("target_resolution_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["known_error_published_by_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("problem_number"),
        )
        op.create_index("ix_problems_tenant_status", "problems", ["tenant_id", "status"])
        op.create_index("ix_problems_tenant_priority", "problems", ["tenant_id", "priority"])
        op.create_index(
            "ix_problems_known_error", "problems", ["tenant_id", "known_error_published_at"]
        )
        op.create_index(
            "ix_problems_target_resolution", "problems", ["target_resolution_at"]
        )

    if "problem_history" not in existing:
        op.create_table(
            "problem_history",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("problem_id", sa.String(length=36), nullable=False),
            sa.Column("actor_user_id", sa.String(length=36), nullable=True),
            sa.Column("actor_name", sa.String(length=200), nullable=False),
            sa.Column("actor_email", sa.String(length=255), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("from_status", sa.String(length=40), nullable=True),
            sa.Column("to_status", sa.String(length=40), nullable=True),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_problem_history_problem_id", "problem_history", ["problem_id"])
        op.create_index("ix_problem_history_tenant_id", "problem_history", ["tenant_id"])

    link_specs = (
        ("problem_ticket_links", "ticket_id", "tickets.id", "ticket"),
        ("problem_asset_links", "asset_id", "assets.id", "asset"),
        ("problem_change_links", "change_id", "change_requests.id", "change"),
    )
    for table_name, entity_column, target, short_name in link_specs:
        if table_name in existing:
            continue
        op.create_table(
            table_name,
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("problem_id", sa.String(length=36), nullable=False),
            sa.Column(entity_column, sa.String(length=36), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint([entity_column], [target], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "problem_id", entity_column, name=f"uq_{table_name}_pair"
            ),
        )
        op.create_index(f"ix_{table_name}_problem_id", table_name, ["problem_id"])
        op.create_index(f"ix_{table_name}_{short_name}_id", table_name, [entity_column])
        op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table_name in (
        "problem_change_links",
        "problem_asset_links",
        "problem_ticket_links",
        "problem_history",
        "problems",
    ):
        if table_name in existing:
            op.drop_table(table_name)
