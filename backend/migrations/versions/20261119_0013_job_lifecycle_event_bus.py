"""job lifecycle event bus relay metadata

Revision ID: 20261119_0013
Revises: 20261118_0012
Create Date: 2026-11-19 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261119_0013"
down_revision = "20261118_0012"
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
    if not _has_table(inspector, "job_lifecycle_events"):
        return

    if not _has_column(inspector, "job_lifecycle_events", "relay_stream_name"):
        op.add_column("job_lifecycle_events", sa.Column("relay_stream_name", sa.String(length=120), nullable=True))
        op.execute("UPDATE job_lifecycle_events SET relay_stream_name = 'jobs:lifecycle' WHERE relay_stream_name IS NULL")
        op.alter_column("job_lifecycle_events", "relay_stream_name", nullable=False)
    if not _has_column(inspector, "job_lifecycle_events", "relay_published_at"):
        op.add_column("job_lifecycle_events", sa.Column("relay_published_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(inspector, "job_lifecycle_events", "relay_publish_attempted_at"):
        op.add_column(
            "job_lifecycle_events", sa.Column("relay_publish_attempted_at", sa.DateTime(timezone=True), nullable=True)
        )
    if not _has_column(inspector, "job_lifecycle_events", "relay_failed_attempts"):
        op.add_column("job_lifecycle_events", sa.Column("relay_failed_attempts", sa.Integer(), nullable=False, server_default="0"))
        op.alter_column("job_lifecycle_events", "relay_failed_attempts", server_default=None)
    if not _has_column(inspector, "job_lifecycle_events", "relay_last_error"):
        op.add_column("job_lifecycle_events", sa.Column("relay_last_error", sa.Text(), nullable=True))
    if not _has_column(inspector, "job_lifecycle_events", "relay_lock_owner"):
        op.add_column("job_lifecycle_events", sa.Column("relay_lock_owner", sa.String(length=80), nullable=True))
    if not _has_column(inspector, "job_lifecycle_events", "relay_lock_expires_at"):
        op.add_column("job_lifecycle_events", sa.Column("relay_lock_expires_at", sa.DateTime(timezone=True), nullable=True))

    inspector = inspect(bind)
    for index_name, columns in (
        ("ix_job_lifecycle_events_relay_stream_name", ["relay_stream_name"]),
        ("ix_job_lifecycle_events_relay_published_at", ["relay_published_at"]),
        ("ix_job_lifecycle_events_relay_lock_owner", ["relay_lock_owner"]),
        ("ix_job_lifecycle_events_relay_lock_expires_at", ["relay_lock_expires_at"]),
    ):
        if not _has_index(inspector, "job_lifecycle_events", index_name):
            op.create_index(index_name, "job_lifecycle_events", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _has_table(inspector, "job_lifecycle_events"):
        return

    for index_name in (
        "ix_job_lifecycle_events_relay_lock_expires_at",
        "ix_job_lifecycle_events_relay_lock_owner",
        "ix_job_lifecycle_events_relay_published_at",
        "ix_job_lifecycle_events_relay_stream_name",
    ):
        if _has_index(inspector, "job_lifecycle_events", index_name):
            op.drop_index(index_name, table_name="job_lifecycle_events")

    inspector = inspect(bind)
    for column_name in (
        "relay_lock_expires_at",
        "relay_lock_owner",
        "relay_last_error",
        "relay_failed_attempts",
        "relay_publish_attempted_at",
        "relay_published_at",
        "relay_stream_name",
    ):
        if _has_column(inspector, "job_lifecycle_events", column_name):
            op.drop_column("job_lifecycle_events", column_name)
