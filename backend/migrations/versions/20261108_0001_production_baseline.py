"""production baseline schema

Revision ID: 20261108_0001
Revises:
Create Date: 2026-11-08 00:01:00.000000
"""

from __future__ import annotations

from alembic import op

from app.db.base import Base
import app.models  # noqa: F401

# revision identifiers, used by Alembic.
revision = "20261108_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
