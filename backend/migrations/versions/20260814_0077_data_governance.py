"""Add retention, legal-hold, and controlled-deletion governance.

Revision ID: 20260814_0077
Revises: 20260814_0076
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0077"
down_revision: str | None = "20260814_0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CATEGORIES = (
    "'TICKETS','SERVICE_REQUESTS','COMMENTS','NOTIFICATIONS','LOGIN_EVENTS',"
    "'AUDIT','EMAIL','ATTACHMENTS','AI_CONVERSATIONS','AI_PROMPTS_RESPONSES',"
    "'VECTOR_EMBEDDINGS','EXPORTS','BACKGROUND_JOBS','DEAD_LETTER'"
)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "data_retention_policies" not in existing:
        op.create_table(
            "data_retention_policies",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("scope_key", sa.String(64), nullable=False),
            sa.Column(
                "tenant_id",
                sa.String(36),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("retention_days", sa.Integer(), nullable=False),
            sa.Column(
                "archive_before_delete",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "anonymize_before_delete",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "is_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "updated_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                f"category IN ({_CATEGORIES})",
                name="ck_data_retention_policies_category",
            ),
            sa.CheckConstraint(
                "retention_days >= 30 AND retention_days <= 3650",
                name="ck_data_retention_policies_days",
            ),
            sa.UniqueConstraint(
                "scope_key",
                "category",
                name="uq_data_retention_policies_scope_category",
            ),
        )
        op.create_index(
            "ix_data_retention_policies_tenant_category",
            "data_retention_policies",
            ["tenant_id", "category"],
        )

    if "data_legal_holds" not in existing:
        op.create_table(
            "data_legal_holds",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.String(36),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("scope_type", sa.String(16), nullable=False),
            sa.Column("category", sa.String(40), nullable=True),
            sa.Column("entity_type", sa.String(80), nullable=True),
            sa.Column("entity_id", sa.String(120), nullable=True),
            sa.Column(
                "status", sa.String(16), nullable=False, server_default="ACTIVE"
            ),
            sa.Column(
                "starts_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "released_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("release_reason", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "status IN ('ACTIVE','RELEASED','EXPIRED')",
                name="ck_data_legal_holds_status",
            ),
            sa.CheckConstraint(
                f"category IS NULL OR category IN ({_CATEGORIES})",
                name="ck_data_legal_holds_category",
            ),
            sa.CheckConstraint(
                "scope_type IN ('TENANT','CATEGORY','ENTITY')",
                name="ck_data_legal_holds_scope_type",
            ),
        )
        op.create_index(
            "ix_data_legal_holds_tenant_status",
            "data_legal_holds",
            ["tenant_id", "status", "expires_at"],
        )

    if "data_deletion_requests" not in existing:
        op.create_table(
            "data_deletion_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("request_type", sa.String(24), nullable=False),
            sa.Column("category", sa.String(40), nullable=True),
            sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "status", sa.String(24), nullable=False, server_default="PREVIEWED"
            ),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("preview_json", sa.Text(), nullable=False),
            sa.Column(
                "estimated_rows", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("plan_sha256", sa.String(64), nullable=False),
            sa.Column(
                "requested_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "approved_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("approval_reason", sa.Text(), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "executed_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "request_type IN ('RETENTION_PURGE','TENANT_DELETION')",
                name="ck_data_deletion_requests_type",
            ),
            sa.CheckConstraint(
                "status IN ('PREVIEWED','PENDING_APPROVAL','APPROVED','REJECTED',"
                "'EXECUTING','COMPLETED','FAILED','CANCELLED','BLOCKED_EXTERNAL')",
                name="ck_data_deletion_requests_status",
            ),
            sa.CheckConstraint(
                f"category IS NULL OR category IN ({_CATEGORIES})",
                name="ck_data_deletion_requests_category",
            ),
        )
        op.create_index(
            "ix_data_deletion_requests_tenant_status",
            "data_deletion_requests",
            ["tenant_id", "status", "created_at"],
        )

    if "data_deletion_evidence" not in existing:
        op.create_table(
            "data_deletion_evidence",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "deletion_request_id",
                sa.String(36),
                sa.ForeignKey("data_deletion_requests.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("result_sha256", sa.String(64), nullable=False),
            sa.Column("archive_manifest_sha256", sa.String(64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "deletion_request_id",
                name="uq_data_deletion_evidence_request",
            ),
        )
        op.create_index(
            "ix_data_deletion_evidence_tenant_created",
            "data_deletion_evidence",
            ["tenant_id", "created_at"],
        )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in (
        "data_deletion_evidence",
        "data_deletion_requests",
        "data_legal_holds",
        "data_retention_policies",
    ):
        if table_name in existing:
            op.drop_table(table_name)
