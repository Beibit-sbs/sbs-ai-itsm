"""Add governed on-behalf ticket registration.

Revision ID: 20260814_0080
Revises: 20260814_0079
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0080"
down_revision: str | None = "20260814_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tickets" not in set(inspector.get_table_names()):
        return

    columns = {item["name"] for item in inspector.get_columns("tickets")}
    if "created_by_id" not in columns:
        op.add_column("tickets", sa.Column("created_by_id", sa.String(36), nullable=True))
        if op.get_bind().dialect.name != "sqlite":
            op.create_foreign_key(
                "fk_tickets_created_by_id_users",
                "tickets",
                "users",
                ["created_by_id"],
                ["id"],
                ondelete="SET NULL",
            )
    if "requester_contact" not in columns:
        op.add_column("tickets", sa.Column("requester_contact", sa.String(200), nullable=True))
    if "created_by_name" not in columns:
        op.add_column("tickets", sa.Column("created_by_name", sa.String(200), nullable=True))
    if "creation_channel" not in columns:
        op.add_column(
            "tickets",
            sa.Column("creation_channel", sa.String(24), nullable=False, server_default="LEGACY"),
        )
    if "on_behalf_reason" not in columns:
        op.add_column("tickets", sa.Column("on_behalf_reason", sa.Text(), nullable=True))

    if op.get_bind().dialect.name != "sqlite":
        checks = {item.get("name") for item in sa.inspect(op.get_bind()).get_check_constraints("tickets")}
        if "ck_tickets_creation_channel" not in checks:
            op.create_check_constraint(
                "ck_tickets_creation_channel",
                "tickets",
                "creation_channel IN ('SELF_SERVICE','ON_BEHALF','LEGACY')",
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tickets" not in set(inspector.get_table_names()):
        return
    columns = {item["name"] for item in inspector.get_columns("tickets")}
    if op.get_bind().dialect.name != "sqlite":
        checks = {item.get("name") for item in inspector.get_check_constraints("tickets")}
        if "ck_tickets_creation_channel" in checks:
            op.drop_constraint("ck_tickets_creation_channel", "tickets", type_="check")
    if "created_by_id" in columns and op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_tickets_created_by_id_users", "tickets", type_="foreignkey")
    for column_name in (
        "on_behalf_reason",
        "creation_channel",
        "created_by_name",
        "requester_contact",
        "created_by_id",
    ):
        if column_name in columns:
            op.drop_column("tickets", column_name)
