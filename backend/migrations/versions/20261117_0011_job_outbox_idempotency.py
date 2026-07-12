"""job outbox idempotency and lock metadata

Revision ID: 20261117_0011
Revises: 20261116_0010
Create Date: 2026-11-17 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261117_0011"
down_revision = "20261116_0010"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx.get("name") for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "job_queue_outbox"):
        return

    if not _has_column(inspector, "job_queue_outbox", "dedup_key"):
        op.add_column("job_queue_outbox", sa.Column("dedup_key", sa.String(length=200), nullable=True))
        op.execute("UPDATE job_queue_outbox SET dedup_key = queue_name || ':' || job_id WHERE dedup_key IS NULL")
        op.alter_column("job_queue_outbox", "dedup_key", nullable=False)

    if not _has_column(inspector, "job_queue_outbox", "publish_attempted_at"):
        op.add_column("job_queue_outbox", sa.Column("publish_attempted_at", sa.DateTime(timezone=True), nullable=True))

    if not _has_column(inspector, "job_queue_outbox", "lock_owner"):
        op.add_column("job_queue_outbox", sa.Column("lock_owner", sa.String(length=80), nullable=True))

    if not _has_column(inspector, "job_queue_outbox", "lock_expires_at"):
        op.add_column("job_queue_outbox", sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True))

    # Historical rows may already contain duplicates of queue_name:job_id.
    # Keep one row per dedup key before enforcing unique index.
    op.execute(
        """
        DELETE FROM job_queue_outbox
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM job_queue_outbox
            GROUP BY dedup_key
        )
        """
    )

    inspector = inspect(bind)
    if not _has_index(inspector, "job_queue_outbox", "ix_job_queue_outbox_dedup_key"):
        op.create_index("ix_job_queue_outbox_dedup_key", "job_queue_outbox", ["dedup_key"], unique=True)
    if not _has_index(inspector, "job_queue_outbox", "ix_job_queue_outbox_lock_owner"):
        op.create_index("ix_job_queue_outbox_lock_owner", "job_queue_outbox", ["lock_owner"])
    if not _has_index(inspector, "job_queue_outbox", "ix_job_queue_outbox_lock_expires_at"):
        op.create_index("ix_job_queue_outbox_lock_expires_at", "job_queue_outbox", ["lock_expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "job_queue_outbox"):
        return

    for index_name in (
        "ix_job_queue_outbox_lock_expires_at",
        "ix_job_queue_outbox_lock_owner",
        "ix_job_queue_outbox_dedup_key",
    ):
        if _has_index(inspector, "job_queue_outbox", index_name):
            op.drop_index(index_name, table_name="job_queue_outbox")

    inspector = inspect(bind)
    for column_name in ("lock_expires_at", "lock_owner", "publish_attempted_at", "dedup_key"):
        if _has_column(inspector, "job_queue_outbox", column_name):
            op.drop_column("job_queue_outbox", column_name)
