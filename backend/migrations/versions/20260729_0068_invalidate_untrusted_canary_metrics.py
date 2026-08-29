"""Invalidate pre-governance in-progress canary metrics.

Revision ID: 20260729_0068
Revises: 20260729_0067
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0068"
down_revision: str | None = "20260729_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "policy_canary_rollouts" not in inspector.get_table_names():
        return
    op.execute(
        sa.text(
            """
            UPDATE policy_canary_rollouts
            SET metrics_baseline_json = NULL,
                metrics_current_json = NULL,
                error_rate_baseline = NULL,
                error_rate_current = NULL
            WHERE status = 'in_progress'
            """
        )
    )


def downgrade() -> None:
    # Invalidated evidence cannot be safely reconstructed.
    return
