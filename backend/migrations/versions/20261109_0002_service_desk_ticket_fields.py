"""service desk ticket production fields

Revision ID: 20261109_0002
Revises: 20261108_0001
Create Date: 2026-11-09 00:02:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20261109_0002"
down_revision = "20261108_0001"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _fk_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {fk["name"] for fk in inspector.get_foreign_keys(table_name) if fk.get("name")}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name) if index.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    ticket_columns = _column_names(inspector, "tickets")
    comment_columns = _column_names(inspector, "ticket_comments")

    if "requester_id" not in ticket_columns:
        op.add_column("tickets", sa.Column("requester_id", sa.String(length=36), nullable=True))
    if "assignee_id" not in ticket_columns:
        op.add_column("tickets", sa.Column("assignee_id", sa.String(length=36), nullable=True))
    if "closed_at" not in ticket_columns:
        op.add_column("tickets", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    if "reopened_at" not in ticket_columns:
        op.add_column("tickets", sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True))

    if "author_id" not in comment_columns:
        op.add_column("ticket_comments", sa.Column("author_id", sa.String(length=36), nullable=True))
    if "is_internal" not in comment_columns:
        op.add_column(
            "ticket_comments",
            sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )

    inspector = sa.inspect(bind)
    ticket_fks = _fk_names(inspector, "tickets")
    comment_fks = _fk_names(inspector, "ticket_comments")

    if "fk_tickets_requester_id_users" not in ticket_fks:
        op.create_foreign_key(
            "fk_tickets_requester_id_users",
            "tickets",
            "users",
            ["requester_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "fk_tickets_assignee_id_users" not in ticket_fks:
        op.create_foreign_key(
            "fk_tickets_assignee_id_users",
            "tickets",
            "users",
            ["assignee_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "fk_ticket_comments_author_id_users" not in comment_fks:
        op.create_foreign_key(
            "fk_ticket_comments_author_id_users",
            "ticket_comments",
            "users",
            ["author_id"],
            ["id"],
            ondelete="SET NULL",
        )

    inspector = sa.inspect(bind)
    ticket_indexes = _index_names(inspector, "tickets")
    comment_indexes = _index_names(inspector, "ticket_comments")

    if "ix_tickets_requester_id" not in ticket_indexes:
        op.create_index("ix_tickets_requester_id", "tickets", ["requester_id"], unique=False)
    if "ix_tickets_assignee_id" not in ticket_indexes:
        op.create_index("ix_tickets_assignee_id", "tickets", ["assignee_id"], unique=False)
    if "ix_ticket_comments_author_id" not in comment_indexes:
        op.create_index("ix_ticket_comments_author_id", "ticket_comments", ["author_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    comment_indexes = _index_names(inspector, "ticket_comments")
    if "ix_ticket_comments_author_id" in comment_indexes:
        op.drop_index("ix_ticket_comments_author_id", table_name="ticket_comments")

    ticket_indexes = _index_names(inspector, "tickets")
    if "ix_tickets_assignee_id" in ticket_indexes:
        op.drop_index("ix_tickets_assignee_id", table_name="tickets")
    if "ix_tickets_requester_id" in ticket_indexes:
        op.drop_index("ix_tickets_requester_id", table_name="tickets")

    comment_fks = _fk_names(inspector, "ticket_comments")
    if "fk_ticket_comments_author_id_users" in comment_fks:
        op.drop_constraint("fk_ticket_comments_author_id_users", "ticket_comments", type_="foreignkey")

    ticket_fks = _fk_names(inspector, "tickets")
    if "fk_tickets_assignee_id_users" in ticket_fks:
        op.drop_constraint("fk_tickets_assignee_id_users", "tickets", type_="foreignkey")
    if "fk_tickets_requester_id_users" in ticket_fks:
        op.drop_constraint("fk_tickets_requester_id_users", "tickets", type_="foreignkey")

    comment_columns = _column_names(inspector, "ticket_comments")
    if "is_internal" in comment_columns:
        op.drop_column("ticket_comments", "is_internal")
    if "author_id" in comment_columns:
        op.drop_column("ticket_comments", "author_id")

    ticket_columns = _column_names(inspector, "tickets")
    if "reopened_at" in ticket_columns:
        op.drop_column("tickets", "reopened_at")
    if "closed_at" in ticket_columns:
        op.drop_column("tickets", "closed_at")
    if "assignee_id" in ticket_columns:
        op.drop_column("tickets", "assignee_id")
    if "requester_id" in ticket_columns:
        op.drop_column("tickets", "requester_id")
