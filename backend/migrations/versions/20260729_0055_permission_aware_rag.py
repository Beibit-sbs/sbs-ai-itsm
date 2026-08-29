"""Add permission-aware retrieval index and source tenant ownership.

Revision ID: 20260729_0055
Revises: 20260729_0054
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0055"
down_revision: str | None = "20260729_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("knowledge_articles")
    }
    if "tenant_id" in columns:
        return
    with op.batch_alter_table("knowledge_articles") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_knowledge_articles_tenant_id",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_knowledge_articles_tenant_status",
            ["tenant_id", "status", "visibility"],
        )
    op.execute(
        """
        UPDATE knowledge_articles
        SET tenant_id = (
            SELECT tickets.tenant_id
            FROM tickets
            WHERE tickets.id = knowledge_articles.source_ticket_id
        )
        WHERE tenant_id IS NULL AND source_ticket_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE knowledge_articles
        SET tenant_id = (
            SELECT assets.tenant_id
            FROM assets
            WHERE assets.id = knowledge_articles.source_asset_id
        )
        WHERE tenant_id IS NULL AND source_asset_id IS NOT NULL
        """
    )

    with op.batch_alter_table("ai_suggestions") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_ai_suggestions_tenant_id",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_ai_suggestions_tenant_created",
            ["tenant_id", "created_at"],
        )
    op.execute(
        """
        UPDATE ai_suggestions
        SET tenant_id = (
            SELECT tickets.tenant_id
            FROM tickets
            WHERE tickets.id = ai_suggestions.ticket_id
        )
        WHERE tenant_id IS NULL AND ticket_id IS NOT NULL
        """
    )

    op.create_table(
        "ai_retrieval_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("scope_key", sa.String(48), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("source_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(320), nullable=False),
        sa.Column("url_path", sa.String(500), nullable=False),
        sa.Column("visibility", sa.String(24), nullable=False),
        sa.Column("permission_code", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source_version", sa.String(120), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "source_type IN ('knowledge','ticket','problem','change','asset')",
            name="ck_ai_retrieval_documents_source_type",
        ),
        sa.CheckConstraint(
            "visibility IN ('public','internal','restricted')",
            name="ck_ai_retrieval_documents_visibility",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','DELETED')",
            name="ck_ai_retrieval_documents_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "scope_key",
            "source_type",
            "source_id",
            name="uq_ai_retrieval_documents_source",
        ),
    )
    op.create_index(
        "ix_ai_retrieval_documents_scope_status",
        "ai_retrieval_documents",
        ["scope_key", "status", "source_type"],
    )
    op.create_index(
        "ix_ai_retrieval_documents_tenant_updated",
        "ai_retrieval_documents",
        ["tenant_id", "source_updated_at"],
    )

    op.create_table(
        "ai_retrieval_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["ai_retrieval_documents.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id",
            "ordinal",
            name="uq_ai_retrieval_chunks_document_ordinal",
        ),
    )
    op.create_index(
        "ix_ai_retrieval_chunks_document",
        "ai_retrieval_chunks",
        ["document_id", "ordinal"],
    )
    op.create_index(
        "ix_ai_retrieval_chunks_hash",
        "ai_retrieval_chunks",
        ["content_sha256"],
    )

    op.create_table(
        "ai_retrieval_ingestion_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_types_json", sa.Text(), nullable=False),
        sa.Column("scanned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by_id", sa.String(36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('RUNNING','COMPLETED','FAILED')",
            name="ck_ai_retrieval_ingestion_runs_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_ai_retrieval_ingestion_runs_tenant_started",
        "ai_retrieval_ingestion_runs",
        ["tenant_id", "started_at"],
    )

    op.create_table(
        "ai_retrieval_query_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("query_sha256", sa.String(64), nullable=False),
        sa.Column("query_preview_redacted", sa.String(500), nullable=False),
        sa.Column("source_types_json", sa.Text(), nullable=False),
        sa.Column("citation_evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("answer_sha256", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("retrieved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("permission_denied_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stale_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("injection_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("grounded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("no_result", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_ai_retrieval_query_logs_tenant_created",
        "ai_retrieval_query_logs",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_ai_retrieval_query_logs_user_created",
        "ai_retrieval_query_logs",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_retrieval_query_logs_user_created", table_name="ai_retrieval_query_logs")
    op.drop_index("ix_ai_retrieval_query_logs_tenant_created", table_name="ai_retrieval_query_logs")
    op.drop_table("ai_retrieval_query_logs")
    op.drop_index("ix_ai_retrieval_ingestion_runs_tenant_started", table_name="ai_retrieval_ingestion_runs")
    op.drop_table("ai_retrieval_ingestion_runs")
    op.drop_index("ix_ai_retrieval_chunks_hash", table_name="ai_retrieval_chunks")
    op.drop_index("ix_ai_retrieval_chunks_document", table_name="ai_retrieval_chunks")
    op.drop_table("ai_retrieval_chunks")
    op.drop_index("ix_ai_retrieval_documents_tenant_updated", table_name="ai_retrieval_documents")
    op.drop_index("ix_ai_retrieval_documents_scope_status", table_name="ai_retrieval_documents")
    op.drop_table("ai_retrieval_documents")
    with op.batch_alter_table("ai_suggestions") as batch:
        batch.drop_index("ix_ai_suggestions_tenant_created")
        batch.drop_constraint("fk_ai_suggestions_tenant_id", type_="foreignkey")
        batch.drop_column("tenant_id")
    with op.batch_alter_table("knowledge_articles") as batch:
        batch.drop_index("ix_knowledge_articles_tenant_status")
        batch.drop_constraint("fk_knowledge_articles_tenant_id", type_="foreignkey")
        batch.drop_column("tenant_id")
