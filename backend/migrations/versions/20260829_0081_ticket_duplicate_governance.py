"""Add governed duplicate detection, merge, and split evidence.

Revision ID: 20260829_0081
Revises: 20260814_0080
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0081"
down_revision: str | None = "20260814_0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "tickets" not in tables:
        return

    columns = {item["name"] for item in inspector.get_columns("tickets")}
    additions = (
        ("parent_ticket_id", sa.Column("parent_ticket_id", sa.String(36), nullable=True)),
        ("merged_into_id", sa.Column("merged_into_id", sa.String(36), nullable=True)),
        (
            "governance_version",
            sa.Column("governance_version", sa.Integer(), nullable=False, server_default="1"),
        ),
        ("merge_reason", sa.Column("merge_reason", sa.Text(), nullable=True)),
        ("merged_by_id", sa.Column("merged_by_id", sa.String(36), nullable=True)),
        ("merged_by_name", sa.Column("merged_by_name", sa.String(200), nullable=True)),
        ("merged_at", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True)),
    )
    for column_name, column in additions:
        if column_name not in columns:
            op.add_column("tickets", column)

    if bind.dialect.name != "sqlite":
        foreign_keys = {
            item.get("name") for item in sa.inspect(bind).get_foreign_keys("tickets")
        }
        definitions = (
            ("fk_tickets_parent_ticket_id_tickets", "tickets", ["parent_ticket_id"], ["id"], "SET NULL"),
            ("fk_tickets_merged_into_id_tickets", "tickets", ["merged_into_id"], ["id"], "RESTRICT"),
            ("fk_tickets_merged_by_id_users", "users", ["merged_by_id"], ["id"], "SET NULL"),
        )
        for name, referred_table, local_columns, remote_columns, ondelete in definitions:
            if name not in foreign_keys:
                op.create_foreign_key(
                    name,
                    "tickets",
                    referred_table,
                    local_columns,
                    remote_columns,
                    ondelete=ondelete,
                )
        checks = {
            item.get("name") for item in sa.inspect(bind).get_check_constraints("tickets")
        }
        if "ck_tickets_governance_version" not in checks:
            op.create_check_constraint(
                "ck_tickets_governance_version", "tickets", "governance_version >= 1"
            )
        if "ck_tickets_not_merged_into_self" not in checks:
            op.create_check_constraint(
                "ck_tickets_not_merged_into_self",
                "tickets",
                "merged_into_id IS NULL OR merged_into_id <> id",
            )

    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("tickets")}
    if "ix_tickets_parent_ticket_id" not in indexes:
        op.create_index("ix_tickets_parent_ticket_id", "tickets", ["parent_ticket_id"])
    if "ix_tickets_merged_into_id" not in indexes:
        op.create_index("ix_tickets_merged_into_id", "tickets", ["merged_into_id"])

    if "ticket_governance_actions" not in tables:
        op.create_table(
            "ticket_governance_actions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.String(36),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action_type", sa.String(32), nullable=False),
            sa.Column(
                "source_ticket_id",
                sa.String(36),
                sa.ForeignKey("tickets.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "target_ticket_id",
                sa.String(36),
                sa.ForeignKey("tickets.id", ondelete="RESTRICT"),
                nullable=True,
            ),
            sa.Column(
                "actor_user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("actor_name", sa.String(200), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("pair_key", sa.String(80), nullable=True),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=True),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "action_type IN ('DUPLICATE_DISMISSED','MERGED','SPLIT')",
                name="ck_ticket_governance_actions_type",
            ),
            sa.CheckConstraint(
                "score IS NULL OR (score >= 0 AND score <= 100)",
                name="ck_ticket_governance_actions_score",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "action_type",
                "idempotency_key",
                name="uq_ticket_governance_action_idempotency",
            ),
        )
        op.create_index(
            "ix_ticket_governance_actions_tenant_source",
            "ticket_governance_actions",
            ["tenant_id", "source_ticket_id"],
        )
        op.create_index(
            "ix_ticket_governance_actions_tenant_target",
            "ticket_governance_actions",
            ["tenant_id", "target_ticket_id"],
        )
        op.create_index(
            "ix_ticket_governance_actions_pair",
            "ticket_governance_actions",
            ["tenant_id", "pair_key", "action_type"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "ticket_governance_actions" in tables:
        op.drop_table("ticket_governance_actions")
    if "tickets" not in tables:
        return
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("tickets")}
    for index_name in ("ix_tickets_merged_into_id", "ix_tickets_parent_ticket_id"):
        if index_name in indexes:
            op.drop_index(index_name, table_name="tickets")
    if bind.dialect.name != "sqlite":
        checks = {
            item.get("name") for item in sa.inspect(bind).get_check_constraints("tickets")
        }
        for name in ("ck_tickets_not_merged_into_self", "ck_tickets_governance_version"):
            if name in checks:
                op.drop_constraint(name, "tickets", type_="check")
        foreign_keys = {
            item.get("name") for item in sa.inspect(bind).get_foreign_keys("tickets")
        }
        for name in (
            "fk_tickets_merged_by_id_users",
            "fk_tickets_merged_into_id_tickets",
            "fk_tickets_parent_ticket_id_tickets",
        ):
            if name in foreign_keys:
                op.drop_constraint(name, "tickets", type_="foreignkey")
    columns = {item["name"] for item in sa.inspect(bind).get_columns("tickets")}
    for column_name in (
        "merged_at",
        "merged_by_name",
        "merged_by_id",
        "merge_reason",
        "governance_version",
        "merged_into_id",
        "parent_ticket_id",
    ):
        if column_name in columns:
            op.drop_column("tickets", column_name)
