"""Add a lock-free PostgreSQL sequence for ticket numbers.

Revision ID: 20260814_0075
Revises: 20260814_0074
"""

import re
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0075"
down_revision: str | None = "20260814_0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _maximum_suffix(bind: sa.Connection) -> int:
    max_value = 1000
    for number in bind.execute(sa.text("SELECT ticket_number FROM tickets")).scalars():
        if not number:
            continue
        match = re.search(r"(\d+)$", str(number))
        if match:
            max_value = max(max_value, int(match.group(1)))
    return max_value


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    bind.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS ticket_number_seq"))
    maximum_suffix = _maximum_suffix(bind)
    current_last_value = int(
        bind.execute(sa.text("SELECT last_value FROM ticket_number_seq")).scalar_one()
    )
    bind.execute(
        sa.text("SELECT setval('ticket_number_seq', :value, true)"),
        {"value": max(maximum_suffix, current_last_value)},
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("DROP SEQUENCE IF EXISTS ticket_number_seq"))
