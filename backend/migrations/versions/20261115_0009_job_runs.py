"""async job runs foundation

Revision ID: 20261115_0009
Revises: 20261114_0008
Create Date: 2026-11-15 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261115_0009"
down_revision = "20261114_0008"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx.get("name") for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "job_runs"):
        op.create_table(
            "job_runs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("task_name", sa.String(length=120), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
            sa.Column(
                "tenant_id",
                sa.String(length=36),
                sa.ForeignKey("tenants.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "actor_user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("correlation_id", sa.String(length=120), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    inspector = inspect(bind)
    if _has_table(inspector, "job_runs"):
        if not _has_index(inspector, "job_runs", "ix_job_runs_task_name"):
            op.create_index("ix_job_runs_task_name", "job_runs", ["task_name"])
        if not _has_index(inspector, "job_runs", "ix_job_runs_status"):
            op.create_index("ix_job_runs_status", "job_runs", ["status"])
        if not _has_index(inspector, "job_runs", "ix_job_runs_correlation_id"):
            op.create_index("ix_job_runs_correlation_id", "job_runs", ["correlation_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if _has_table(inspector, "job_runs"):
        for index_name in ("ix_job_runs_correlation_id", "ix_job_runs_status", "ix_job_runs_task_name"):
            if _has_index(inspector, "job_runs", index_name):
                op.drop_index(index_name, table_name="job_runs")
        op.drop_table("job_runs")
