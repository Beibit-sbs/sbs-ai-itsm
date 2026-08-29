from __future__ import annotations

from datetime import UTC, datetime
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.ci_class import (
    ConfigurationItemClass,
    ConfigurationItemClassVersion,
)
from app.models.ci_relationship import ConfigurationItemRelationshipType
from app.models.cmdb_reconciliation import CMDBSource
from app.models.tenant import Tenant
from app.models.user import User
from app.services.cmdb_schema import (
    canonical_json,
    merge_schemas,
    normalize_schema,
    schema_hash,
)


def _field(
    key: str,
    label: str,
    field_type: str,
    *,
    required: bool = False,
    options: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "key": key,
        "label": label,
        "type": field_type,
        "required": required,
        "description": "",
        "options": options or [],
    }


STANDARD_CLASSES = (
    {
        "code": "BUSINESS_SERVICE",
        "name": "Бизнес-сервис",
        "description": "Пользовательский или клиентский сервис с бизнес-владельцем.",
        "fields": [
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
    },
    {
        "code": "TECHNICAL_SERVICE",
        "name": "Технический сервис",
        "description": "Техническая capability, поддерживающая бизнес-сервисы.",
        "fields": [
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
    },
    {
        "code": "APPLICATION",
        "name": "Приложение",
        "description": "Управляемое программное приложение или информационная система.",
        "fields": [
            _field("application_id", "Application ID", "text", required=True),
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
    },
    {
        "code": "INFRASTRUCTURE",
        "name": "Инфраструктура",
        "description": "Сервер, виртуальная машина, устройство или облачный ресурс.",
        "fields": [
            _field("hostname", "Hostname", "text", required=True),
            _field("management_ip", "Management IP", "text"),
        ],
    },
    {
        "code": "LOCATION",
        "name": "Локация",
        "description": "Площадка, дата-центр, здание, кабинет или логическая зона.",
        "fields": [
            _field("location_code", "Location code", "text", required=True),
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
    },
)


STANDARD_RELATIONSHIP_TYPES = (
    {
        "code": "SERVICE_DEPENDS_ON",
        "name": "Зависимость бизнес-сервиса",
        "forward_label": "зависит от",
        "reverse_label": "поддерживает",
        "description": "Бизнес-сервис зависит от технического сервиса.",
        "source_class_code": "BUSINESS_SERVICE",
        "target_class_code": "TECHNICAL_SERVICE",
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
        "source_class_code": "TECHNICAL_SERVICE",
        "target_class_code": "APPLICATION",
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
        "source_class_code": "APPLICATION",
        "target_class_code": "INFRASTRUCTURE",
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
        "source_class_code": None,
        "target_class_code": "LOCATION",
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
        "source_class_code": "INFRASTRUCTURE",
        "target_class_code": "INFRASTRUCTURE",
        "source_cardinality": "MANY",
        "target_cardinality": "MANY",
        "allow_cycles": True,
    },
)

LIFECYCLE_BY_ASSET_STATUS = {
    "disposed": "DISPOSED",
    "in_stock": "IN_STOCK",
    "in_repair": "MAINTENANCE",
    "maintenance": "MAINTENANCE",
    "inactive": "RETIRED",
    "active": "ACTIVE",
    "in_use": "ACTIVE",
}

EXCEL_SOURCE_IDENTIFICATION_RULES = [
    "inventory_number",
    "serial_number",
    "asset_tag",
]
EXCEL_SOURCE_AUTHORITATIVE_FIELDS = [
    "name",
    "inventory_number",
    "original_type",
    "lifecycle_status",
    "location",
    "assigned_to_name",
    "purchase_date",
    "purchase_cost",
    "current_cost",
    "depreciation_amount",
    "residual_value",
    "purchase_year",
    "verification_status",
]


def _effective_schema(
    db: Session,
    version: ConfigurationItemClassVersion,
    seen: set[str] | None = None,
) -> dict:
    visited = seen or set()
    if version.id in visited:
        raise ValueError("CI class inheritance cycle detected during bootstrap")
    visited.add(version.id)
    inherited = None
    if version.parent_version_id:
        parent = db.get(ConfigurationItemClassVersion, version.parent_version_id)
        if parent is None:
            raise ValueError("CMDB parent version is missing during bootstrap")
        inherited = _effective_schema(db, parent, visited)
    return merge_schemas(inherited, json.loads(version.schema_json))


def _ensure_class(
    db: Session,
    *,
    tenant_id: str,
    actor_id: str | None,
    code: str,
    name: str,
    description: str,
    fields: list[dict],
    parent: tuple[ConfigurationItemClass, ConfigurationItemClassVersion] | None,
    now: datetime,
) -> tuple[ConfigurationItemClass, ConfigurationItemClassVersion, bool]:
    ci_class = db.scalar(
        select(ConfigurationItemClass).where(
            ConfigurationItemClass.tenant_id == tenant_id,
            ConfigurationItemClass.code == code,
        )
    )
    created = ci_class is None
    if ci_class is None:
        ci_class = ConfigurationItemClass(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            parent_class_id=parent[0].id if parent else None,
            code=code,
            name=name,
            description=description,
            status="ACTIVE",
            created_by_id=actor_id,
            updated_by_id=actor_id,
            created_at=now,
            updated_at=now,
        )
        db.add(ci_class)
        db.flush()
    published = db.scalar(
        select(ConfigurationItemClassVersion)
        .where(
            ConfigurationItemClassVersion.ci_class_id == ci_class.id,
            ConfigurationItemClassVersion.status == "PUBLISHED",
        )
        .order_by(ConfigurationItemClassVersion.version.desc())
    )
    if published is not None:
        return ci_class, published, created

    latest_version = db.scalar(
        select(func.max(ConfigurationItemClassVersion.version)).where(
            ConfigurationItemClassVersion.ci_class_id == ci_class.id
        )
    )
    own_schema = normalize_schema({"fields": fields})
    inherited = _effective_schema(db, parent[1]) if parent else None
    effective = merge_schemas(inherited, own_schema)
    published = ConfigurationItemClassVersion(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ci_class_id=ci_class.id,
        parent_version_id=parent[1].id if parent else None,
        version=(latest_version or 0) + 1,
        revision=1,
        status="PUBLISHED",
        schema_json=canonical_json(own_schema),
        schema_hash=schema_hash(effective),
        created_by_id=actor_id,
        updated_by_id=actor_id,
        published_by_id=actor_id,
        published_at=now,
        created_at=now,
        updated_at=now,
    )
    ci_class.status = "ACTIVE"
    ci_class.updated_by_id = actor_id
    ci_class.updated_at = now
    db.add(published)
    db.flush()
    return ci_class, published, created


def ensure_standard_cmdb_model(
    db: Session,
    tenant_id: str,
    actor_id: str | None = None,
) -> dict[str, int]:
    if db.get(Tenant, tenant_id) is None:
        raise ValueError("Tenant is unavailable for CMDB bootstrap")
    if actor_id:
        actor = db.get(User, actor_id)
        if actor is None:
            raise ValueError("CMDB bootstrap actor is unavailable")
        if not actor.is_root and actor.tenant_id != tenant_id:
            raise ValueError("CMDB bootstrap actor belongs to another tenant")

    now = datetime.now(UTC)
    generic = _ensure_class(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        code="GENERIC_ASSET",
        name="Базовый актив",
        description="Системный базовый класс конфигурационных единиц.",
        fields=[],
        parent=None,
        now=now,
    )
    class_map = {generic[0].code: generic[0]}
    classes_created = int(generic[2])
    assets_classified = 0
    unclassified_assets = db.scalars(
        select(Asset).where(
            Asset.tenant_id == tenant_id,
            Asset.ci_class_id.is_(None),
        )
    ).all()
    for asset in unclassified_assets:
        asset.ci_class_id = generic[0].id
        asset.ci_class_version_id = generic[1].id
        asset.ci_class_code = generic[0].code
        asset.ci_class_name = generic[0].name
        asset.ci_schema_version = generic[1].version
        asset.ci_schema_hash = generic[1].schema_hash
        asset.ci_attributes_json = asset.ci_attributes_json or "{}"
        asset.lifecycle_status = LIFECYCLE_BY_ASSET_STATUS.get(
            asset.status,
            "ACTIVE",
        )
        asset.support_group = asset.support_group or "Service Desk"
        asset.criticality = asset.criticality or "MEDIUM"
        asset.environment = asset.environment or "OTHER"
        asset.ci_version = asset.ci_version or 1
        assets_classified += 1
    for definition in STANDARD_CLASSES:
        ci_class, _, created = _ensure_class(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            code=definition["code"],
            name=definition["name"],
            description=definition["description"],
            fields=definition["fields"],
            parent=(generic[0], generic[1]),
            now=now,
        )
        class_map[ci_class.code] = ci_class
        classes_created += int(created)

    relationship_types_created = 0
    for definition in STANDARD_RELATIONSHIP_TYPES:
        existing = db.scalar(
            select(ConfigurationItemRelationshipType).where(
                ConfigurationItemRelationshipType.tenant_id == tenant_id,
                ConfigurationItemRelationshipType.code == definition["code"],
            )
        )
        if existing is not None:
            continue
        source_code = definition["source_class_code"]
        target_code = definition["target_class_code"]
        relationship_type = ConfigurationItemRelationshipType(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            code=definition["code"],
            name=definition["name"],
            forward_label=definition["forward_label"],
            reverse_label=definition["reverse_label"],
            description=definition["description"],
            source_class_id=class_map[source_code].id if source_code else None,
            target_class_id=class_map[target_code].id if target_code else None,
            source_cardinality=definition["source_cardinality"],
            target_cardinality=definition["target_cardinality"],
            allow_self_relationship=False,
            allow_cycles=definition["allow_cycles"],
            status="ACTIVE",
            version=1,
            created_by_id=actor_id,
            updated_by_id=actor_id,
            created_at=now,
            updated_at=now,
        )
        db.add(relationship_type)
        relationship_types_created += 1
    sources_created = 0
    excel_source = db.scalar(
        select(CMDBSource).where(
            CMDBSource.tenant_id == tenant_id,
            CMDBSource.code == "EXCEL_ASSET_IMPORT",
        )
    )
    if excel_source is None:
        db.add(
            CMDBSource(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                external_system_id=None,
                default_class_id=generic[0].id,
                code="EXCEL_ASSET_IMPORT",
                name="Excel Asset Import",
                description="Governed source for the built-in Excel asset import.",
                source_type="FILE",
                priority=300,
                identification_rules_json=canonical_json(
                    EXCEL_SOURCE_IDENTIFICATION_RULES
                ),
                authoritative_fields_json=canonical_json(
                    EXCEL_SOURCE_AUTHORITATIVE_FIELDS
                ),
                claim_unowned_fields=False,
                stale_after_hours=720,
                status="ACTIVE",
                version=1,
                created_by_id=actor_id,
                updated_by_id=actor_id,
                created_at=now,
                updated_at=now,
            )
        )
        sources_created = 1
    db.flush()
    return {
        "classes_created": classes_created,
        "relationship_types_created": relationship_types_created,
        "assets_classified": assets_classified,
        "sources_created": sources_created,
    }
