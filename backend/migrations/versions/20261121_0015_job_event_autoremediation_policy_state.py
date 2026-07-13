"""job event autoremediation policy state

Revision ID: 20261121_0015
Revises: 20261120_0014
Create Date: 2026-11-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261121_0015"
down_revision = "20261120_0014"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "job_event_autoremediation_policy_states"):
        op.create_table(
            "job_event_autoremediation_policy_states",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("updated_by_email", sa.String(length=255), nullable=False, server_default="system@sbs.local"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if _has_table(inspector, "job_event_autoremediation_policy_states"):
        op.drop_table("job_event_autoremediation_policy_states")
