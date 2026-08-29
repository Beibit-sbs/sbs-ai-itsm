"""Add an atomic allocator for human-readable ticket numbers.

Revision ID: 20260814_0074
Revises: 20260814_0073
"""

import re
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0074"
down_revision: str | None = "20260814_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _required_next_value(bind: sa.Connection) -> int:
    max_value = 1000
    for number in bind.execute(sa.text("SELECT ticket_number FROM tickets")).scalars():
        if not number:
            continue
        match = re.search(r"(\d+)$", str(number))
        if match:
            max_value = max(max_value, int(match.group(1)))
    return max_value + 1


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ticket_number_counters" not in inspector.get_table_names():
        op.create_table(
            "ticket_number_counters",
            sa.Column("scope", sa.String(length=32), nullable=False),
            sa.Column("next_value", sa.Integer(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("scope"),
        )

    required_next_value = _required_next_value(bind)
    current_next_value = bind.execute(
        sa.text(
            "SELECT next_value FROM ticket_number_counters WHERE scope = :scope"
        ),
        {"scope": "global"},
    ).scalar_one_or_none()
    if current_next_value is None:
        bind.execute(
            sa.text(
                "INSERT INTO ticket_number_counters (scope, next_value) "
                "VALUES (:scope, :next_value)"
            ),
            {"scope": "global", "next_value": required_next_value},
        )
    elif int(current_next_value) < required_next_value:
        bind.execute(
            sa.text(
                "UPDATE ticket_number_counters "
                "SET next_value = :next_value WHERE scope = :scope"
            ),
            {"scope": "global", "next_value": required_next_value},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "ticket_number_counters" in sa.inspect(bind).get_table_names():
        op.drop_table("ticket_number_counters")
