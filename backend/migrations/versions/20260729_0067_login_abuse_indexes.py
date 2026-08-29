"""Add bounded login-abuse query indexes.

Revision ID: 20260729_0067
Revises: 20260729_0066
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0067"
down_revision: str | None = "20260729_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EMAIL_INDEX = "ix_audit_login_email_window"
IP_INDEX = "ix_audit_login_ip_window"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {
        str(index["name"])
        for index in inspector.get_indexes("audit_logs")
    }
    if EMAIL_INDEX not in indexes:
        op.create_index(
            EMAIL_INDEX,
            "audit_logs",
            ["action", "actor_email", "created_at"],
        )
    if IP_INDEX not in indexes:
        op.create_index(
            IP_INDEX,
            "audit_logs",
            ["action", "ip_address", "created_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {
        str(index["name"])
        for index in inspector.get_indexes("audit_logs")
    }
    if IP_INDEX in indexes:
        op.drop_index(IP_INDEX, table_name="audit_logs")
    if EMAIL_INDEX in indexes:
        op.drop_index(EMAIL_INDEX, table_name="audit_logs")
