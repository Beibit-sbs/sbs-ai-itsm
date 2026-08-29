"""knowledge ai production

Revision ID: 20261110_0004
Revises: 20261109_0003
Create Date: 2026-11-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261110_0004"
down_revision = "20261109_0003"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    return column_name in columns


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    return index_name in indexes


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "knowledge_usage_logs" not in existing_tables:
        op.create_table(
            "knowledge_usage_logs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("article_id", sa.String(length=36), nullable=False),
            sa.Column("ticket_id", sa.String(length=36), nullable=True),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("action", sa.String(length=40), nullable=False),
            sa.Column("context", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["article_id"], ["knowledge_articles.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    if "ticket_knowledge_links" not in existing_tables:
        op.create_table(
            "ticket_knowledge_links",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("ticket_id", sa.String(length=36), nullable=False),
            sa.Column("article_id", sa.String(length=36), nullable=False),
            sa.Column("linked_by_id", sa.String(length=36), nullable=True),
            sa.Column("link_type", sa.String(length=32), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["article_id"], ["knowledge_articles.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["linked_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    article_columns = {
        "slug": sa.String(length=255),
        "tags_json": sa.JSON(),
        "source_ticket_id": sa.String(length=36),
        "source_asset_id": sa.String(length=36),
        "created_by_id": sa.String(length=36),
        "updated_by_id": sa.String(length=36),
        "view_count": sa.Integer(),
        "last_used_at": sa.DateTime(timezone=True),
        "archived_at": sa.DateTime(timezone=True),
    }
    for name, type_ in article_columns.items():
        if not _has_column("knowledge_articles", name):
            op.add_column("knowledge_articles", sa.Column(name, type_, nullable=True))

    if _has_column("knowledge_articles", "view_count"):
        op.execute("UPDATE knowledge_articles SET view_count = 0 WHERE view_count IS NULL")
    with op.batch_alter_table("knowledge_articles") as batch_op:
        if _has_column("knowledge_articles", "view_count"):
            batch_op.alter_column(
                "view_count",
                existing_type=sa.Integer(),
                nullable=False,
                server_default="0",
            )
        if _has_column("knowledge_articles", "source_ticket_id"):
            batch_op.create_foreign_key(
                "fk_knowledge_articles_source_ticket_id",
                "tickets",
                ["source_ticket_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if _has_column("knowledge_articles", "source_asset_id"):
            batch_op.create_foreign_key(
                "fk_knowledge_articles_source_asset_id",
                "assets",
                ["source_asset_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if _has_column("knowledge_articles", "created_by_id"):
            batch_op.create_foreign_key(
                "fk_knowledge_articles_created_by_id",
                "users",
                ["created_by_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if _has_column("knowledge_articles", "updated_by_id"):
            batch_op.create_foreign_key(
                "fk_knowledge_articles_updated_by_id",
                "users",
                ["updated_by_id"],
                ["id"],
                ondelete="SET NULL",
            )

    suggestion_columns = {
        "asset_id": sa.String(length=36),
        "article_id": sa.String(length=36),
        "confidence_value": sa.Float(),
        "suggestion_type": sa.String(length=40),
        "rationale": sa.Text(),
        "status": sa.String(length=20),
        "accepted_by_id": sa.String(length=36),
        "accepted_at": sa.DateTime(timezone=True),
        "rejected_by_id": sa.String(length=36),
        "rejected_at": sa.DateTime(timezone=True),
    }
    for name, type_ in suggestion_columns.items():
        if not _has_column("ai_suggestions", name):
            op.add_column("ai_suggestions", sa.Column(name, type_, nullable=True))

    if _has_column("ai_suggestions", "suggestion_type"):
        op.execute("UPDATE ai_suggestions SET suggestion_type = 'resolution' WHERE suggestion_type IS NULL")
    if _has_column("ai_suggestions", "status"):
        op.execute("UPDATE ai_suggestions SET status = 'proposed' WHERE status IS NULL")
    with op.batch_alter_table("ai_suggestions") as batch_op:
        if _has_column("ai_suggestions", "suggestion_type"):
            batch_op.alter_column(
                "suggestion_type",
                existing_type=sa.String(length=40),
                nullable=False,
                server_default="resolution",
            )
        if _has_column("ai_suggestions", "status"):
            batch_op.alter_column(
                "status",
                existing_type=sa.String(length=20),
                nullable=False,
                server_default="proposed",
            )
        if _has_column("ai_suggestions", "asset_id"):
            batch_op.create_foreign_key(
                "fk_ai_suggestions_asset_id",
                "assets",
                ["asset_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if _has_column("ai_suggestions", "article_id"):
            batch_op.create_foreign_key(
                "fk_ai_suggestions_article_id",
                "knowledge_articles",
                ["article_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if _has_column("ai_suggestions", "accepted_by_id"):
            batch_op.create_foreign_key(
                "fk_ai_suggestions_accepted_by_id",
                "users",
                ["accepted_by_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if _has_column("ai_suggestions", "rejected_by_id"):
            batch_op.create_foreign_key(
                "fk_ai_suggestions_rejected_by_id",
                "users",
                ["rejected_by_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if not _has_index("knowledge_articles", "ix_knowledge_articles_slug") and _has_column("knowledge_articles", "slug"):
        op.create_index("ix_knowledge_articles_slug", "knowledge_articles", ["slug"], unique=False)
    if not _has_index("knowledge_articles", "ix_knowledge_articles_status"):
        op.create_index("ix_knowledge_articles_status", "knowledge_articles", ["status"], unique=False)
    if not _has_index("knowledge_articles", "ix_knowledge_articles_last_used_at") and _has_column("knowledge_articles", "last_used_at"):
        op.create_index("ix_knowledge_articles_last_used_at", "knowledge_articles", ["last_used_at"], unique=False)

    if not _has_index("knowledge_usage_logs", "ix_knowledge_usage_logs_article_id"):
        op.create_index("ix_knowledge_usage_logs_article_id", "knowledge_usage_logs", ["article_id"], unique=False)
    if not _has_index("knowledge_usage_logs", "ix_knowledge_usage_logs_ticket_id"):
        op.create_index("ix_knowledge_usage_logs_ticket_id", "knowledge_usage_logs", ["ticket_id"], unique=False)

    if not _has_index("ticket_knowledge_links", "ix_ticket_knowledge_links_ticket_id"):
        op.create_index("ix_ticket_knowledge_links_ticket_id", "ticket_knowledge_links", ["ticket_id"], unique=False)
    if not _has_index("ticket_knowledge_links", "ix_ticket_knowledge_links_article_id"):
        op.create_index("ix_ticket_knowledge_links_article_id", "ticket_knowledge_links", ["article_id"], unique=False)

    if not _has_index("ai_suggestions", "ix_ai_suggestions_ticket_id"):
        op.create_index("ix_ai_suggestions_ticket_id", "ai_suggestions", ["ticket_id"], unique=False)
    if not _has_index("ai_suggestions", "ix_ai_suggestions_status") and _has_column("ai_suggestions", "status"):
        op.create_index("ix_ai_suggestions_status", "ai_suggestions", ["status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "ai_suggestions" in existing_tables:
        indexes = {index["name"] for index in inspector.get_indexes("ai_suggestions")}
        if "ix_ai_suggestions_status" in indexes:
            op.drop_index("ix_ai_suggestions_status", table_name="ai_suggestions")
        if "ix_ai_suggestions_ticket_id" in indexes:
            op.drop_index("ix_ai_suggestions_ticket_id", table_name="ai_suggestions")

        for fk in [
            "fk_ai_suggestions_rejected_by_id",
            "fk_ai_suggestions_accepted_by_id",
            "fk_ai_suggestions_article_id",
            "fk_ai_suggestions_asset_id",
        ]:
            try:
                op.drop_constraint(fk, "ai_suggestions", type_="foreignkey")
            except Exception:
                pass

        for col in [
            "rejected_at",
            "rejected_by_id",
            "accepted_at",
            "accepted_by_id",
            "status",
            "rationale",
            "suggestion_type",
            "confidence_value",
            "article_id",
            "asset_id",
        ]:
            if _has_column("ai_suggestions", col):
                op.drop_column("ai_suggestions", col)

    if "knowledge_articles" in existing_tables:
        indexes = {index["name"] for index in inspector.get_indexes("knowledge_articles")}
        for index_name in [
            "ix_knowledge_articles_last_used_at",
            "ix_knowledge_articles_status",
            "ix_knowledge_articles_slug",
        ]:
            if index_name in indexes:
                op.drop_index(index_name, table_name="knowledge_articles")

        for fk in [
            "fk_knowledge_articles_updated_by_id",
            "fk_knowledge_articles_created_by_id",
            "fk_knowledge_articles_source_asset_id",
            "fk_knowledge_articles_source_ticket_id",
        ]:
            try:
                op.drop_constraint(fk, "knowledge_articles", type_="foreignkey")
            except Exception:
                pass

        for col in [
            "archived_at",
            "last_used_at",
            "view_count",
            "updated_by_id",
            "created_by_id",
            "source_asset_id",
            "source_ticket_id",
            "tags_json",
            "slug",
        ]:
            if _has_column("knowledge_articles", col):
                op.drop_column("knowledge_articles", col)

    if "ticket_knowledge_links" in existing_tables:
        indexes = {index["name"] for index in inspector.get_indexes("ticket_knowledge_links")}
        if "ix_ticket_knowledge_links_article_id" in indexes:
            op.drop_index("ix_ticket_knowledge_links_article_id", table_name="ticket_knowledge_links")
        if "ix_ticket_knowledge_links_ticket_id" in indexes:
            op.drop_index("ix_ticket_knowledge_links_ticket_id", table_name="ticket_knowledge_links")
        op.drop_table("ticket_knowledge_links")

    if "knowledge_usage_logs" in existing_tables:
        indexes = {index["name"] for index in inspector.get_indexes("knowledge_usage_logs")}
        if "ix_knowledge_usage_logs_ticket_id" in indexes:
            op.drop_index("ix_knowledge_usage_logs_ticket_id", table_name="knowledge_usage_logs")
        if "ix_knowledge_usage_logs_article_id" in indexes:
            op.drop_index("ix_knowledge_usage_logs_article_id", table_name="knowledge_usage_logs")
        op.drop_table("knowledge_usage_logs")
