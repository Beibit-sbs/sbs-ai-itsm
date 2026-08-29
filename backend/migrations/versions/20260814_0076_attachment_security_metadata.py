"""Add verified attachment security metadata.

Revision ID: 20260814_0076
Revises: 20260814_0075
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0076"
down_revision: str | None = "20260814_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]
        for column in inspector.get_columns("email_attachments")
    }
    with op.batch_alter_table("email_attachments") as batch_op:
        if "detected_content_type" not in columns:
            batch_op.add_column(
                sa.Column(
                    "detected_content_type",
                    sa.String(length=160),
                    nullable=True,
                )
            )
        if "security_findings_json" not in columns:
            batch_op.add_column(
                sa.Column(
                    "security_findings_json",
                    sa.Text(),
                    nullable=False,
                    server_default="[]",
                )
            )
        if "sanitization_applied" not in columns:
            batch_op.add_column(
                sa.Column(
                    "sanitization_applied",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
        if "download_count" not in columns:
            batch_op.add_column(
                sa.Column(
                    "download_count",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]
        for column in inspector.get_columns("email_attachments")
    }
    with op.batch_alter_table("email_attachments") as batch_op:
        for column_name in (
            "download_count",
            "sanitization_applied",
            "security_findings_json",
            "detected_content_type",
        ):
            if column_name in columns:
                batch_op.drop_column(column_name)
