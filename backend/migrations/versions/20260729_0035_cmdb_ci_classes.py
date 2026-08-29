"""Add governed CI classes, schema versions, and CI snapshots.

Revision ID: 20260729_0035
Revises: 20260729_0034
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260729_0035"
down_revision = "20260729_0034"
branch_labels = None
depends_on = None


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _add_missing(table: str, columns: list[sa.Column]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(table)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "ci_classes" not in tables:
        op.create_table(
            "ci_classes",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("parent_class_id", sa.String(length=36), nullable=True),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_by_id", sa.String(length=36), nullable=True),
            sa.Column("updated_by_id", sa.String(length=36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["created_by_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["parent_class_id"], ["ci_classes.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"], ["tenants.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["updated_by_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "code",
                name="uq_ci_classes_tenant_code",
            ),
        )
        op.create_index(
            "ix_ci_classes_parent_id",
            "ci_classes",
            ["parent_class_id"],
        )
        op.create_index(
            "ix_ci_classes_tenant_status",
            "ci_classes",
            ["tenant_id", "status"],
        )

    inspector = sa.inspect(bind)
    if "ci_class_versions" not in set(inspector.get_table_names()):
        op.create_table(
            "ci_class_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("ci_class_id", sa.String(length=36), nullable=False),
            sa.Column("parent_version_id", sa.String(length=36), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("schema_json", sa.Text(), nullable=False),
            sa.Column("schema_hash", sa.String(length=64), nullable=False),
            sa.Column("created_by_id", sa.String(length=36), nullable=True),
            sa.Column("updated_by_id", sa.String(length=36), nullable=True),
            sa.Column("published_by_id", sa.String(length=36), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["ci_class_id"], ["ci_classes.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["created_by_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["parent_version_id"],
                ["ci_class_versions.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["published_by_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"], ["tenants.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["updated_by_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "ci_class_id",
                "version",
                name="uq_ci_class_versions_class_version",
            ),
        )
        op.create_index(
            "ix_ci_class_versions_class_status",
            "ci_class_versions",
            ["ci_class_id", "status"],
        )
        op.create_index(
            "ix_ci_class_versions_tenant_status",
            "ci_class_versions",
            ["tenant_id", "status"],
        )

    _add_missing(
        "assets",
        [
            sa.Column("ci_class_id", sa.String(length=36), nullable=True),
            sa.Column("ci_class_version_id", sa.String(length=36), nullable=True),
            sa.Column("ci_class_code", sa.String(length=64), nullable=True),
            sa.Column("ci_class_name", sa.String(length=160), nullable=True),
            sa.Column("ci_schema_version", sa.Integer(), nullable=True),
            sa.Column("ci_schema_hash", sa.String(length=64), nullable=True),
            sa.Column(
                "ci_attributes_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "lifecycle_status",
                sa.String(length=24),
                nullable=False,
                server_default="ACTIVE",
            ),
            sa.Column("owner_user_id", sa.String(length=36), nullable=True),
            sa.Column("support_group", sa.String(length=160), nullable=True),
            sa.Column(
                "criticality",
                sa.String(length=16),
                nullable=False,
                server_default="MEDIUM",
            ),
            sa.Column(
                "environment",
                sa.String(length=24),
                nullable=False,
                server_default="OTHER",
            ),
            sa.Column(
                "ci_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        ],
    )
    inspector = sa.inspect(bind)
    foreign_keys = {
        foreign_key["name"] for foreign_key in inspector.get_foreign_keys("assets")
    }
    missing_foreign_keys = [
        (
            "fk_assets_ci_class_id",
            "ci_classes",
            ["ci_class_id"],
            ["id"],
        ),
        (
            "fk_assets_ci_class_version_id",
            "ci_class_versions",
            ["ci_class_version_id"],
            ["id"],
        ),
        (
            "fk_assets_owner_user_id",
            "users",
            ["owner_user_id"],
            ["id"],
        ),
    ]
    missing_foreign_keys = [
        constraint
        for constraint in missing_foreign_keys
        if constraint[0] not in foreign_keys
    ]
    if bind.dialect.name == "sqlite" and missing_foreign_keys:
        # SQLite cannot ALTER TABLE ADD CONSTRAINT. Batch mode rebuilds the
        # table while preserving its existing data and constraints.
        with op.batch_alter_table("assets") as batch_op:
            for name, referent_table, local_columns, remote_columns in (
                missing_foreign_keys
            ):
                batch_op.create_foreign_key(
                    name,
                    referent_table,
                    local_columns,
                    remote_columns,
                    ondelete="SET NULL",
                )
    else:
        for name, referent_table, local_columns, remote_columns in (
            missing_foreign_keys
        ):
            op.create_foreign_key(
                name,
                "assets",
                referent_table,
                local_columns,
                remote_columns,
                ondelete="SET NULL",
            )
    indexes = {index["name"] for index in inspector.get_indexes("assets")}
    if "ix_assets_tenant_ci_class" not in indexes:
        op.create_index(
            "ix_assets_tenant_ci_class",
            "assets",
            ["tenant_id", "ci_class_id"],
        )
    if "ix_assets_tenant_ci_governance" not in indexes:
        op.create_index(
            "ix_assets_tenant_ci_governance",
            "assets",
            ["tenant_id", "environment", "criticality", "lifecycle_status"],
        )

    own_schema = {"fields": []}
    effective_schema = {"fields": []}
    schema_json = _canonical(own_schema)
    digest = hashlib.sha256(_canonical(effective_schema).encode("utf-8")).hexdigest()
    now = datetime.now(UTC)
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).scalars()
    for tenant_id in tenants:
        existing = bind.execute(
            sa.text(
                """
                SELECT id
                FROM ci_classes
                WHERE tenant_id = :tenant_id AND code = 'GENERIC_ASSET'
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar_one_or_none()
        if existing:
            class_id = existing
            version_id = bind.execute(
                sa.text(
                    """
                    SELECT id
                    FROM ci_class_versions
                    WHERE ci_class_id = :class_id AND status = 'PUBLISHED'
                    ORDER BY version DESC
                    LIMIT 1
                    """
                ),
                {"class_id": class_id},
            ).scalar_one_or_none()
        else:
            actor_id = bind.execute(
                sa.text(
                    """
                    SELECT id
                    FROM users
                    WHERE tenant_id = :tenant_id AND is_active = true
                    ORDER BY created_at
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id},
            ).scalar_one_or_none()
            class_id = str(uuid.uuid4())
            version_id = str(uuid.uuid4())
            bind.execute(
                sa.text(
                    """
                    INSERT INTO ci_classes (
                        id, tenant_id, parent_class_id, code, name, description,
                        status, created_by_id, updated_by_id, created_at, updated_at
                    ) VALUES (
                        :id, :tenant_id, NULL, 'GENERIC_ASSET', 'Базовый актив',
                        'Миграционный базовый класс для существующих активов.',
                        'ACTIVE', :actor_id, :actor_id, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": class_id,
                    "tenant_id": tenant_id,
                    "actor_id": actor_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            bind.execute(
                sa.text(
                    """
                    INSERT INTO ci_class_versions (
                        id, tenant_id, ci_class_id, parent_version_id, version,
                        revision, status, schema_json, schema_hash, created_by_id,
                        updated_by_id, published_by_id, published_at, retired_at,
                        created_at, updated_at
                    ) VALUES (
                        :id, :tenant_id, :class_id, NULL, 1, 1, 'PUBLISHED',
                        :schema_json, :schema_hash, :actor_id, :actor_id,
                        :actor_id, :published_at, NULL, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": version_id,
                    "tenant_id": tenant_id,
                    "class_id": class_id,
                    "schema_json": schema_json,
                    "schema_hash": digest,
                    "actor_id": actor_id,
                    "published_at": now,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        if version_id:
            bind.execute(
                sa.text(
                    """
                    UPDATE assets
                    SET ci_class_id = :class_id,
                        ci_class_version_id = :version_id,
                        ci_class_code = 'GENERIC_ASSET',
                        ci_class_name = 'Базовый актив',
                        ci_schema_version = 1,
                        ci_schema_hash = :schema_hash,
                        lifecycle_status = CASE
                            WHEN status = 'disposed' THEN 'DISPOSED'
                            WHEN status = 'in_stock' THEN 'IN_STOCK'
                            WHEN status IN ('in_repair', 'maintenance')
                                THEN 'MAINTENANCE'
                            ELSE 'ACTIVE'
                        END,
                        support_group = COALESCE(support_group, 'Service Desk')
                    WHERE tenant_id = :tenant_id
                      AND ci_class_id IS NULL
                    """
                ),
                {
                    "class_id": class_id,
                    "version_id": version_id,
                    "schema_hash": digest,
                    "tenant_id": tenant_id,
                },
            )


def downgrade() -> None:
    op.drop_index("ix_assets_tenant_ci_governance", table_name="assets")
    op.drop_index("ix_assets_tenant_ci_class", table_name="assets")
    op.drop_constraint("fk_assets_owner_user_id", "assets", type_="foreignkey")
    op.drop_constraint(
        "fk_assets_ci_class_version_id", "assets", type_="foreignkey"
    )
    op.drop_constraint("fk_assets_ci_class_id", "assets", type_="foreignkey")
    for column in (
        "ci_version",
        "environment",
        "criticality",
        "support_group",
        "owner_user_id",
        "lifecycle_status",
        "ci_attributes_json",
        "ci_schema_hash",
        "ci_schema_version",
        "ci_class_name",
        "ci_class_code",
        "ci_class_version_id",
        "ci_class_id",
    ):
        op.drop_column("assets", column)
    op.drop_table("ci_class_versions")
    op.drop_table("ci_classes")
