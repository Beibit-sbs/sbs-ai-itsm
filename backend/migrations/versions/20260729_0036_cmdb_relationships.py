"""Add governed CI relationships and standard service-model classes.

Revision ID: 20260729_0036
Revises: 20260729_0035
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260729_0036"
down_revision = "20260729_0035"
branch_labels = None
depends_on = None


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _schema_hash(schema: dict) -> str:
    return hashlib.sha256(_canonical(schema).encode("utf-8")).hexdigest()


def _ensure_class(
    bind,
    *,
    tenant_id: str,
    actor_id: str | None,
    parent_class_id: str,
    parent_version_id: str,
    code: str,
    name: str,
    description: str,
    fields: list[dict],
    now: datetime,
) -> str:
    existing = bind.execute(
        sa.text(
            """
            SELECT id
            FROM ci_classes
            WHERE tenant_id = :tenant_id AND code = :code
            """
        ),
        {"tenant_id": tenant_id, "code": code},
    ).scalar_one_or_none()
    if existing:
        return existing

    class_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    own_schema = {"fields": fields}
    effective_schema = {
        "fields": [{**field, "inherited": False} for field in fields]
    }
    bind.execute(
        sa.text(
            """
            INSERT INTO ci_classes (
                id, tenant_id, parent_class_id, code, name, description,
                status, created_by_id, updated_by_id, created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :parent_class_id, :code, :name, :description,
                'ACTIVE', :actor_id, :actor_id, :created_at, :updated_at
            )
            """
        ),
        {
            "id": class_id,
            "tenant_id": tenant_id,
            "parent_class_id": parent_class_id,
            "code": code,
            "name": name,
            "description": description,
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
                :id, :tenant_id, :class_id, :parent_version_id, 1, 1,
                'PUBLISHED', :schema_json, :schema_hash, :actor_id,
                :actor_id, :actor_id, :published_at, NULL, :created_at,
                :updated_at
            )
            """
        ),
        {
            "id": version_id,
            "tenant_id": tenant_id,
            "class_id": class_id,
            "parent_version_id": parent_version_id,
            "schema_json": _canonical(own_schema),
            "schema_hash": _schema_hash(effective_schema),
            "actor_id": actor_id,
            "published_at": now,
            "created_at": now,
            "updated_at": now,
        },
    )
    return class_id


def _ensure_relationship_type(
    bind,
    *,
    tenant_id: str,
    actor_id: str | None,
    code: str,
    name: str,
    forward_label: str,
    reverse_label: str,
    description: str,
    source_class_id: str | None,
    target_class_id: str | None,
    source_cardinality: str,
    target_cardinality: str,
    allow_cycles: bool,
    now: datetime,
) -> None:
    exists = bind.execute(
        sa.text(
            """
            SELECT id
            FROM ci_relationship_types
            WHERE tenant_id = :tenant_id AND code = :code
            """
        ),
        {"tenant_id": tenant_id, "code": code},
    ).scalar_one_or_none()
    if exists:
        return
    bind.execute(
        sa.text(
            """
            INSERT INTO ci_relationship_types (
                id, tenant_id, code, name, forward_label, reverse_label,
                description, source_class_id, target_class_id,
                source_cardinality, target_cardinality,
                allow_self_relationship, allow_cycles, status, version,
                created_by_id, updated_by_id, created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :code, :name, :forward_label, :reverse_label,
                :description, :source_class_id, :target_class_id,
                :source_cardinality, :target_cardinality,
                :allow_self_relationship, :allow_cycles, 'ACTIVE', 1,
                :actor_id, :actor_id, :created_at, :updated_at
            )
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "code": code,
            "name": name,
            "forward_label": forward_label,
            "reverse_label": reverse_label,
            "description": description,
            "source_class_id": source_class_id,
            "target_class_id": target_class_id,
            "source_cardinality": source_cardinality,
            "target_cardinality": target_cardinality,
            "allow_self_relationship": False,
            "allow_cycles": allow_cycles,
            "actor_id": actor_id,
            "created_at": now,
            "updated_at": now,
        },
    )


def _field(
    key: str,
    label: str,
    field_type: str,
    *,
    required: bool = False,
    description: str = "",
    options: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "key": key,
        "label": label,
        "type": field_type,
        "required": required,
        "description": description,
        "options": options or [],
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "ci_relationship_types" not in tables:
        op.create_table(
            "ci_relationship_types",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("forward_label", sa.String(length=160), nullable=False),
            sa.Column("reverse_label", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("source_class_id", sa.String(length=36), nullable=True),
            sa.Column("target_class_id", sa.String(length=36), nullable=True),
            sa.Column(
                "source_cardinality",
                sa.String(length=8),
                nullable=False,
            ),
            sa.Column(
                "target_cardinality",
                sa.String(length=8),
                nullable=False,
            ),
            sa.Column(
                "allow_self_relationship",
                sa.Boolean(),
                nullable=False,
            ),
            sa.Column("allow_cycles", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
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
            sa.CheckConstraint(
                "source_cardinality IN ('ONE', 'MANY')",
                name="ck_ci_relationship_types_source_cardinality",
            ),
            sa.CheckConstraint(
                "target_cardinality IN ('ONE', 'MANY')",
                name="ck_ci_relationship_types_target_cardinality",
            ),
            sa.CheckConstraint(
                "status IN ('ACTIVE', 'INACTIVE')",
                name="ck_ci_relationship_types_status",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["source_class_id"],
                ["ci_classes.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["target_class_id"],
                ["ci_classes.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["updated_by_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "code",
                name="uq_ci_relationship_types_tenant_code",
            ),
        )
        op.create_index(
            "ix_ci_relationship_types_tenant_status",
            "ci_relationship_types",
            ["tenant_id", "status"],
        )

    inspector = sa.inspect(bind)
    if "ci_relationships" not in set(inspector.get_table_names()):
        op.create_table(
            "ci_relationships",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column(
                "relationship_type_id",
                sa.String(length=36),
                nullable=False,
            ),
            sa.Column("source_ci_id", sa.String(length=36), nullable=False),
            sa.Column("target_ci_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_by_id", sa.String(length=36), nullable=True),
            sa.Column("retired_by_id", sa.String(length=36), nullable=True),
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
            sa.Column(
                "retired_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.CheckConstraint(
                "status IN ('ACTIVE', 'RETIRED')",
                name="ck_ci_relationships_status",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["relationship_type_id"],
                ["ci_relationship_types.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["retired_by_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["source_ci_id"],
                ["assets.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["target_ci_id"],
                ["assets.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "relationship_type_id",
                "source_ci_id",
                "target_ci_id",
                "status",
                name="uq_ci_relationships_type_pair_status",
            ),
        )
        op.create_index(
            "ix_ci_relationships_tenant_source_status",
            "ci_relationships",
            ["tenant_id", "source_ci_id", "status"],
        )
        op.create_index(
            "ix_ci_relationships_tenant_target_status",
            "ci_relationships",
            ["tenant_id", "target_ci_id", "status"],
        )
        op.create_index(
            "ix_ci_relationships_type_status",
            "ci_relationships",
            ["relationship_type_id", "status"],
        )

    now = datetime.now(UTC)
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).scalars()
    for tenant_id in tenants:
        actor_id = bind.execute(
            sa.text(
                """
                SELECT id
                FROM users
                WHERE tenant_id = :tenant_id AND is_active = :is_active
                ORDER BY created_at, id
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "is_active": True},
        ).scalar_one_or_none()
        generic = bind.execute(
            sa.text(
                """
                SELECT c.id, v.id
                FROM ci_classes c
                JOIN ci_class_versions v ON v.ci_class_id = c.id
                WHERE c.tenant_id = :tenant_id
                  AND c.code = 'GENERIC_ASSET'
                  AND v.status = 'PUBLISHED'
                ORDER BY v.version DESC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id},
        ).one_or_none()
        if generic is None:
            continue
        generic_class_id, generic_version_id = generic

        business_service_id = _ensure_class(
            bind,
            tenant_id=tenant_id,
            actor_id=actor_id,
            parent_class_id=generic_class_id,
            parent_version_id=generic_version_id,
            code="BUSINESS_SERVICE",
            name="Бизнес-сервис",
            description="Пользовательский или клиентский сервис с бизнес-владельцем.",
            fields=[
                _field(
                    "service_tier",
                    "Класс сервиса",
                    "select",
                    required=True,
                    options=[
                        {"value": "tier_1", "label": "Tier 1"},
                        {"value": "tier_2", "label": "Tier 2"},
                        {"value": "tier_3", "label": "Tier 3"},
                    ],
                ),
                _field("business_owner", "Business owner email", "email"),
            ],
            now=now,
        )
        technical_service_id = _ensure_class(
            bind,
            tenant_id=tenant_id,
            actor_id=actor_id,
            parent_class_id=generic_class_id,
            parent_version_id=generic_version_id,
            code="TECHNICAL_SERVICE",
            name="Технический сервис",
            description="Техническая capability, поддерживающая бизнес-сервисы.",
            fields=[
                _field("service_owner", "Service owner email", "email"),
                _field(
                    "recovery_tier",
                    "Recovery tier",
                    "select",
                    options=[
                        {"value": "gold", "label": "Gold"},
                        {"value": "silver", "label": "Silver"},
                        {"value": "bronze", "label": "Bronze"},
                    ],
                ),
            ],
            now=now,
        )
        application_id = _ensure_class(
            bind,
            tenant_id=tenant_id,
            actor_id=actor_id,
            parent_class_id=generic_class_id,
            parent_version_id=generic_version_id,
            code="APPLICATION",
            name="Приложение",
            description="Управляемое программное приложение или информационная система.",
            fields=[
                _field(
                    "application_id",
                    "Application ID",
                    "text",
                    required=True,
                ),
                _field("vendor", "Vendor", "text"),
                _field(
                    "data_classification",
                    "Классификация данных",
                    "select",
                    required=True,
                    options=[
                        {"value": "public", "label": "Public"},
                        {"value": "internal", "label": "Internal"},
                        {"value": "confidential", "label": "Confidential"},
                        {"value": "restricted", "label": "Restricted"},
                    ],
                ),
            ],
            now=now,
        )
        infrastructure_id = _ensure_class(
            bind,
            tenant_id=tenant_id,
            actor_id=actor_id,
            parent_class_id=generic_class_id,
            parent_version_id=generic_version_id,
            code="INFRASTRUCTURE",
            name="Инфраструктура",
            description="Сервер, виртуальная машина, устройство или облачный ресурс.",
            fields=[
                _field("hostname", "Hostname", "text", required=True),
                _field("management_ip", "Management IP", "text"),
            ],
            now=now,
        )
        location_id = _ensure_class(
            bind,
            tenant_id=tenant_id,
            actor_id=actor_id,
            parent_class_id=generic_class_id,
            parent_version_id=generic_version_id,
            code="LOCATION",
            name="Локация",
            description="Площадка, дата-центр, здание, кабинет или логическая зона.",
            fields=[
                _field(
                    "location_code",
                    "Location code",
                    "text",
                    required=True,
                ),
                _field(
                    "site_type",
                    "Тип площадки",
                    "select",
                    options=[
                        {"value": "datacenter", "label": "Data center"},
                        {"value": "office", "label": "Office"},
                        {"value": "cloud_region", "label": "Cloud region"},
                        {"value": "logical", "label": "Logical"},
                    ],
                ),
            ],
            now=now,
        )

        for relationship_type in (
            {
                "code": "SERVICE_DEPENDS_ON",
                "name": "Зависимость бизнес-сервиса",
                "forward_label": "зависит от",
                "reverse_label": "поддерживает",
                "description": "Бизнес-сервис зависит от технического сервиса.",
                "source_class_id": business_service_id,
                "target_class_id": technical_service_id,
                "source_cardinality": "MANY",
                "target_cardinality": "MANY",
                "allow_cycles": False,
            },
            {
                "code": "TECH_SERVICE_USES_APPLICATION",
                "name": "Использование приложения",
                "forward_label": "использует",
                "reverse_label": "поддерживает технический сервис",
                "description": "Технический сервис использует приложение.",
                "source_class_id": technical_service_id,
                "target_class_id": application_id,
                "source_cardinality": "MANY",
                "target_cardinality": "MANY",
                "allow_cycles": False,
            },
            {
                "code": "APPLICATION_RUNS_ON",
                "name": "Размещение приложения",
                "forward_label": "работает на",
                "reverse_label": "размещает приложение",
                "description": "Приложение работает на инфраструктурном CI.",
                "source_class_id": application_id,
                "target_class_id": infrastructure_id,
                "source_cardinality": "MANY",
                "target_cardinality": "MANY",
                "allow_cycles": False,
            },
            {
                "code": "LOCATED_IN",
                "name": "Размещение CI",
                "forward_label": "расположен в",
                "reverse_label": "содержит",
                "description": "CI расположен в физической или логической локации.",
                "source_class_id": None,
                "target_class_id": location_id,
                "source_cardinality": "ONE",
                "target_cardinality": "MANY",
                "allow_cycles": False,
            },
            {
                "code": "INFRASTRUCTURE_CONNECTED_TO",
                "name": "Связь инфраструктуры",
                "forward_label": "подключён к",
                "reverse_label": "подключён от",
                "description": "Направленная инфраструктурная связь.",
                "source_class_id": infrastructure_id,
                "target_class_id": infrastructure_id,
                "source_cardinality": "MANY",
                "target_cardinality": "MANY",
                "allow_cycles": True,
            },
        ):
            _ensure_relationship_type(
                bind,
                tenant_id=tenant_id,
                actor_id=actor_id,
                now=now,
                **relationship_type,
            )


def downgrade() -> None:
    op.drop_index(
        "ix_ci_relationships_type_status",
        table_name="ci_relationships",
    )
    op.drop_index(
        "ix_ci_relationships_tenant_target_status",
        table_name="ci_relationships",
    )
    op.drop_index(
        "ix_ci_relationships_tenant_source_status",
        table_name="ci_relationships",
    )
    op.drop_table("ci_relationships")
    op.drop_index(
        "ix_ci_relationship_types_tenant_status",
        table_name="ci_relationship_types",
    )
    op.drop_table("ci_relationship_types")
