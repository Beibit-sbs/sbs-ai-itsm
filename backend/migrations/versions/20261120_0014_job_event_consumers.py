"""job event consumer state tables

Revision ID: 20261120_0014
Revises: 20261119_0013
Create Date: 2026-11-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261120_0014"
down_revision = "20261119_0013"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "job_event_consumer_offsets"):
        op.create_table(
            "job_event_consumer_offsets",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("consumer_name", sa.String(length=80), nullable=False),
            sa.Column("stream_name", sa.String(length=120), nullable=False),
            sa.Column("last_stream_id", sa.String(length=64), nullable=False, server_default="0-0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("consumer_name", "stream_name", name="uq_job_event_consumer_offset"),
        )
        op.create_index("ix_job_event_consumer_offsets_consumer_name", "job_event_consumer_offsets", ["consumer_name"])
        op.create_index("ix_job_event_consumer_offsets_stream_name", "job_event_consumer_offsets", ["stream_name"])

    inspector = inspect(bind)
    if not _has_table(inspector, "job_event_consumer_deliveries"):
        op.create_table(
            "job_event_consumer_deliveries",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("consumer_name", sa.String(length=80), nullable=False),
            sa.Column("event_id", sa.String(length=36), nullable=False),
            sa.Column("stream_name", sa.String(length=120), nullable=False),
            sa.Column("stream_entry_id", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["event_id"], ["job_lifecycle_events.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("consumer_name", "event_id", name="uq_job_event_consumer_delivery"),
        )
        op.create_index(
            "ix_job_event_consumer_deliveries_consumer_name", "job_event_consumer_deliveries", ["consumer_name"]
        )
        op.create_index("ix_job_event_consumer_deliveries_event_id", "job_event_consumer_deliveries", ["event_id"])
        op.create_index("ix_job_event_consumer_deliveries_stream_name", "job_event_consumer_deliveries", ["stream_name"])
        op.create_index("ix_job_event_consumer_deliveries_status", "job_event_consumer_deliveries", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_table(inspector, "job_event_consumer_deliveries"):
        for index_name in (
            "ix_job_event_consumer_deliveries_status",
            "ix_job_event_consumer_deliveries_stream_name",
            "ix_job_event_consumer_deliveries_event_id",
            "ix_job_event_consumer_deliveries_consumer_name",
        ):
            op.drop_index(index_name, table_name="job_event_consumer_deliveries")
        op.drop_table("job_event_consumer_deliveries")

    inspector = inspect(bind)
    if _has_table(inspector, "job_event_consumer_offsets"):
        for index_name in (
            "ix_job_event_consumer_offsets_stream_name",
            "ix_job_event_consumer_offsets_consumer_name",
        ):
            op.drop_index(index_name, table_name="job_event_consumer_offsets")
        op.drop_table("job_event_consumer_offsets")
