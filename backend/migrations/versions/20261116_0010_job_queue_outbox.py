"""job queue outbox for transactional enqueue

Revision ID: 20261116_0010
Revises: 20261115_0009
Create Date: 2026-11-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261116_0010"
down_revision = "20261115_0009"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx.get("name") for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "job_queue_outbox"):
        op.create_table(
            "job_queue_outbox",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("queue_name", sa.String(length=120), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    inspector = inspect(bind)
    if _has_table(inspector, "job_queue_outbox"):
        if not _has_index(inspector, "job_queue_outbox", "ix_job_queue_outbox_job_id"):
            op.create_index("ix_job_queue_outbox_job_id", "job_queue_outbox", ["job_id"])
        if not _has_index(inspector, "job_queue_outbox", "ix_job_queue_outbox_queue_name"):
            op.create_index("ix_job_queue_outbox_queue_name", "job_queue_outbox", ["queue_name"])
        if not _has_index(inspector, "job_queue_outbox", "ix_job_queue_outbox_published_at"):
            op.create_index("ix_job_queue_outbox_published_at", "job_queue_outbox", ["published_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if _has_table(inspector, "job_queue_outbox"):
        for index_name in (
            "ix_job_queue_outbox_published_at",
            "ix_job_queue_outbox_queue_name",
            "ix_job_queue_outbox_job_id",
        ):
            if _has_index(inspector, "job_queue_outbox", index_name):
                op.drop_index(index_name, table_name="job_queue_outbox")
        op.drop_table("job_queue_outbox")
