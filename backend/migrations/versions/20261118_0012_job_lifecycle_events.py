"""job lifecycle events

Revision ID: 20261118_0012
Revises: 20261117_0011
Create Date: 2026-11-18 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261118_0012"
down_revision = "20261117_0011"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if _has_table(inspector, "job_lifecycle_events"):
        return

    op.create_table(
        "job_lifecycle_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("task_name", sa.String(length=120), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=True),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("current_status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["job_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_lifecycle_events_job_id", "job_lifecycle_events", ["job_id"])
    op.create_index("ix_job_lifecycle_events_event_type", "job_lifecycle_events", ["event_type"])
    op.create_index("ix_job_lifecycle_events_task_name", "job_lifecycle_events", ["task_name"])
    op.create_index("ix_job_lifecycle_events_correlation_id", "job_lifecycle_events", ["correlation_id"])
    op.create_index("ix_job_lifecycle_events_previous_status", "job_lifecycle_events", ["previous_status"])
    op.create_index("ix_job_lifecycle_events_current_status", "job_lifecycle_events", ["current_status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _has_table(inspector, "job_lifecycle_events"):
        return

    for index_name in (
        "ix_job_lifecycle_events_current_status",
        "ix_job_lifecycle_events_previous_status",
        "ix_job_lifecycle_events_correlation_id",
        "ix_job_lifecycle_events_task_name",
        "ix_job_lifecycle_events_event_type",
        "ix_job_lifecycle_events_job_id",
    ):
        op.drop_index(index_name, table_name="job_lifecycle_events")
    op.drop_table("job_lifecycle_events")
