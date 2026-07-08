"""asset inventory production fields

Revision ID: 20261109_0003
Revises: 20261109_0002
Create Date: 2026-11-09 00:03:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20261109_0003"
down_revision = "20261109_0002"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name) if index.get("name")}


def _table_names(inspector: sa.Inspector) -> set[str]:
    return set(inspector.get_table_names())


def _fk_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {fk["name"] for fk in inspector.get_foreign_keys(table_name) if fk.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    asset_columns = _column_names(inspector, "assets")
    ddl_columns: list[tuple[str, sa.Column]] = [
        ("building", sa.Column("building", sa.String(length=120), nullable=True)),
        ("floor", sa.Column("floor", sa.String(length=64), nullable=True)),
        ("room", sa.Column("room", sa.String(length=120), nullable=True)),
        ("location_label", sa.Column("location_label", sa.String(length=255), nullable=True)),
        ("location_verified_at", sa.Column("location_verified_at", sa.DateTime(timezone=True), nullable=True)),
        ("responsible_person_name", sa.Column("responsible_person_name", sa.String(length=200), nullable=True)),
        ("responsible_person_position", sa.Column("responsible_person_position", sa.String(length=200), nullable=True)),
        ("responsible_department", sa.Column("responsible_department", sa.String(length=200), nullable=True)),
        ("mol_name", sa.Column("mol_name", sa.String(length=200), nullable=True)),
        ("mol_department", sa.Column("mol_department", sa.String(length=200), nullable=True)),
        ("initial_cost", sa.Column("initial_cost", sa.Float(), nullable=True)),
        ("residual_cost", sa.Column("residual_cost", sa.Float(), nullable=True)),
        ("writeoff_date", sa.Column("writeoff_date", sa.DateTime(timezone=True), nullable=True)),
        ("writeoff_reason", sa.Column("writeoff_reason", sa.Text(), nullable=True)),
        ("assigned_at", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True)),
        ("moved_at", sa.Column("moved_at", sa.DateTime(timezone=True), nullable=True)),
        ("disposed_at", sa.Column("disposed_at", sa.DateTime(timezone=True), nullable=True)),
        ("last_inventory_at", sa.Column("last_inventory_at", sa.DateTime(timezone=True), nullable=True)),
        ("last_verified_at", sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True)),
        ("notes", sa.Column("notes", sa.Text(), nullable=True)),
    ]

    for column_name, column in ddl_columns:
        if column_name not in asset_columns:
            op.add_column("assets", column)

    table_names = _table_names(inspector)
    if "asset_history" not in table_names:
        op.create_table(
            "asset_history",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("asset_id", sa.String(length=36), nullable=False),
            sa.Column("actor_id", sa.String(length=36), nullable=True),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column("old_value", sa.JSON(), nullable=True),
            sa.Column("new_value", sa.JSON(), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE", name="fk_asset_history_asset_id_assets"),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL", name="fk_asset_history_actor_id_users"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    asset_indexes = _index_names(inspector, "assets")
    for index_name, columns in [
        ("ix_assets_inventory_number", ["inventory_number"]),
        ("ix_assets_asset_type", ["asset_type"]),
        ("ix_assets_status", ["status"]),
        ("ix_assets_source", ["source"]),
        ("ix_assets_verification_status", ["verification_status"]),
        ("ix_assets_room", ["room"]),
        ("ix_assets_responsible_person_name", ["responsible_person_name"]),
        ("ix_assets_mol_name", ["mol_name"]),
        ("ix_assets_purchase_year", ["purchase_year"]),
    ]:
        if index_name not in asset_indexes:
            op.create_index(index_name, "assets", columns, unique=False)

    if "asset_history" in _table_names(inspector):
        history_indexes = _index_names(inspector, "asset_history")
        for index_name, columns in [
            ("ix_asset_history_asset_id", ["asset_id"]),
            ("ix_asset_history_action", ["action"]),
            ("ix_asset_history_created_at", ["created_at"]),
        ]:
            if index_name not in history_indexes:
                op.create_index(index_name, "asset_history", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "asset_history" in _table_names(inspector):
        history_indexes = _index_names(inspector, "asset_history")
        for index_name in ["ix_asset_history_created_at", "ix_asset_history_action", "ix_asset_history_asset_id"]:
            if index_name in history_indexes:
                op.drop_index(index_name, table_name="asset_history")
        fk_names = _fk_names(inspector, "asset_history")
        if "fk_asset_history_actor_id_users" in fk_names:
            op.drop_constraint("fk_asset_history_actor_id_users", "asset_history", type_="foreignkey")
        if "fk_asset_history_asset_id_assets" in fk_names:
            op.drop_constraint("fk_asset_history_asset_id_assets", "asset_history", type_="foreignkey")
        op.drop_table("asset_history")

    asset_indexes = _index_names(inspector, "assets")
    for index_name in [
        "ix_assets_purchase_year",
        "ix_assets_mol_name",
        "ix_assets_responsible_person_name",
        "ix_assets_room",
        "ix_assets_verification_status",
        "ix_assets_source",
        "ix_assets_status",
        "ix_assets_asset_type",
        "ix_assets_inventory_number",
    ]:
        if index_name in asset_indexes:
            op.drop_index(index_name, table_name="assets")

    asset_columns = _column_names(inspector, "assets")
    for column_name in [
        "notes",
        "last_verified_at",
        "last_inventory_at",
        "disposed_at",
        "moved_at",
        "assigned_at",
        "writeoff_reason",
        "writeoff_date",
        "residual_cost",
        "initial_cost",
        "mol_department",
        "mol_name",
        "responsible_department",
        "responsible_person_position",
        "responsible_person_name",
        "location_verified_at",
        "location_label",
        "room",
        "floor",
        "building",
    ]:
        if column_name in asset_columns:
            op.drop_column("assets", column_name)
