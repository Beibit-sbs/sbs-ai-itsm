"""Add PostgreSQL trigram indexes for bounded global search.

Revision ID: 20260729_0062
Revises: 20260729_0061
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260729_0062"
down_revision: str | None = "20260729_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_EXPRESSIONS = {
    "ix_search_tickets_document_trgm": """
        coalesce(ticket_number, '') || ' ' ||
        coalesce(title, '') || ' ' ||
        coalesce(description, '') || ' ' ||
        coalesce(category, '')
    """,
    "ix_search_requests_document_trgm": """
        coalesce(request_number, '') || ' ' ||
        coalesce(title, '') || ' ' ||
        coalesce(description, '')
    """,
    "ix_search_knowledge_document_trgm": """
        coalesce(article_number, '') || ' ' ||
        coalesce(title, '') || ' ' ||
        coalesce(summary, '') || ' ' ||
        coalesce(content, '') || ' ' ||
        coalesce(tags, '')
    """,
    "ix_search_assets_document_trgm": """
        coalesce(asset_tag, '') || ' ' ||
        coalesce(name, '') || ' ' ||
        coalesce(serial_number, '') || ' ' ||
        coalesce(inventory_number, '') || ' ' ||
        coalesce(description, '')
    """,
    "ix_search_changes_document_trgm": """
        coalesce(change_number, '') || ' ' ||
        coalesce(title, '') || ' ' ||
        coalesce(description, '') || ' ' ||
        coalesce(service_name, '')
    """,
    "ix_search_problems_document_trgm": """
        coalesce(problem_number, '') || ' ' ||
        coalesce(title, '') || ' ' ||
        coalesce(description, '') || ' ' ||
        coalesce(symptoms, '') || ' ' ||
        coalesce(root_cause, '') || ' ' ||
        coalesce(workaround, '')
    """,
    "ix_search_users_document_trgm": """
        coalesce(email, '') || ' ' ||
        coalesce(full_name, '') || ' ' ||
        coalesce(department, '') || ' ' ||
        coalesce(position, '') || ' ' ||
        coalesce(employee_number, '')
    """,
}

INDEX_TABLES = {
    "ix_search_tickets_document_trgm": "tickets",
    "ix_search_requests_document_trgm": "service_requests",
    "ix_search_knowledge_document_trgm": "knowledge_articles",
    "ix_search_assets_document_trgm": "assets",
    "ix_search_changes_document_trgm": "change_requests",
    "ix_search_problems_document_trgm": "problems",
    "ix_search_users_document_trgm": "users",
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for index_name, expression in INDEX_EXPRESSIONS.items():
        table_name = INDEX_TABLES[index_name]
        op.execute(
            f"CREATE INDEX {index_name} ON {table_name} "
            f"USING gin (({expression}) gin_trgm_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for index_name in reversed(INDEX_EXPRESSIONS):
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
