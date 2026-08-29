"""reporting analytics production schema updates

Revision ID: 20261111_0005
Revises: 20261110_0004
Create Date: 2026-11-11 00:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261111_0005"
down_revision = "20261110_0004"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(item["name"] == column_name for item in inspector.get_columns(table_name))


def _has_fk(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    return any(item.get("name") == constraint_name for item in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    with op.batch_alter_table("saved_reports") as batch_op:
        if not _has_column(inspector, "saved_reports", "visibility"):
            batch_op.add_column(sa.Column("visibility", sa.String(length=32), nullable=False, server_default="tenant"))
        if not _has_column(inspector, "saved_reports", "schedule_enabled"):
            batch_op.add_column(sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        if not _has_column(inspector, "saved_reports", "created_by_id"):
            batch_op.add_column(sa.Column("created_by_id", sa.String(length=36), nullable=True))

    inspector = sa.inspect(op.get_bind())
    if not _has_fk(inspector, "saved_reports", "fk_saved_reports_created_by_id_users"):
        with op.batch_alter_table("saved_reports") as batch_op:
            batch_op.create_foreign_key("fk_saved_reports_created_by_id_users", "users", ["created_by_id"], ["id"], ondelete="SET NULL")

    with op.batch_alter_table("report_snapshots") as batch_op:
        if not _has_column(inspector, "report_snapshots", "saved_report_id"):
            batch_op.add_column(sa.Column("saved_report_id", sa.String(length=36), nullable=True))
        if not _has_column(inspector, "report_snapshots", "filters_json"):
            batch_op.add_column(sa.Column("filters_json", sa.Text(), nullable=False, server_default="{}"))
        if not _has_column(inspector, "report_snapshots", "generated_by_id"):
            batch_op.add_column(sa.Column("generated_by_id", sa.String(length=36), nullable=True))
        if not _has_column(inspector, "report_snapshots", "generated_at"):
            batch_op.add_column(sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))

    inspector = sa.inspect(op.get_bind())
    with op.batch_alter_table("report_snapshots") as batch_op:
        if not _has_fk(inspector, "report_snapshots", "fk_report_snapshots_saved_report_id"):
            batch_op.create_foreign_key("fk_report_snapshots_saved_report_id", "saved_reports", ["saved_report_id"], ["id"], ondelete="SET NULL")
        if not _has_fk(inspector, "report_snapshots", "fk_report_snapshots_generated_by_id_users"):
            batch_op.create_foreign_key("fk_report_snapshots_generated_by_id_users", "users", ["generated_by_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("report_snapshots") as batch_op:
        batch_op.drop_constraint("fk_report_snapshots_generated_by_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_report_snapshots_saved_report_id", type_="foreignkey")
        batch_op.drop_column("generated_at")
        batch_op.drop_column("generated_by_id")
        batch_op.drop_column("filters_json")
        batch_op.drop_column("saved_report_id")

    with op.batch_alter_table("saved_reports") as batch_op:
        batch_op.drop_constraint("fk_saved_reports_created_by_id_users", type_="foreignkey")
        batch_op.drop_column("created_by_id")
        batch_op.drop_column("schedule_enabled")
        batch_op.drop_column("visibility")
