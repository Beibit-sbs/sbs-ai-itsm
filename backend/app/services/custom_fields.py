from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.asset import Asset
from app.models.change_request import ChangeRequest
from app.models.custom_fields import (
    CustomFieldSet,
    CustomFieldSetVersion,
    CustomFieldValue,
)
from app.models.problem import Problem
from app.models.service_request import ServiceRequest
from app.models.ticket import Ticket
from app.services.catalog_forms import (
    canonical_json,
    default_attachment_rules,
    validate_form_definition,
    validate_submission,
)
from app.services.credential_crypto import decrypt_credential, encrypt_credential


CUSTOM_FIELD_ENTITY_TYPES = {
    "ticket": Ticket,
    "asset": Asset,
    "change": ChangeRequest,
    "problem": Problem,
    "request": ServiceRequest,
}
CUSTOM_FIELD_TYPE_CATALOG = [
    "text",
    "textarea",
    "number",
    "boolean",
    "select",
    "multiselect",
    "date",
    "email",
]
_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,119}$")
_APPLICABILITY_FIELDS = {
    "ticket": {"status", "priority", "category", "source", "service_name"},
    "asset": {"status", "asset_type", "category", "location", "department"},
    "change": {"status", "change_type", "environment", "risk_level", "service_name"},
    "problem": {"status", "problem_type", "priority", "category", "service_name"},
    "request": {"status", "source", "service_name", "cost_center"},
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def default_custom_field_schema(entity_type: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "title": f"Custom fields · {entity_type}",
        "introduction": "",
        "sections": [
            {
                "id": "additional_details",
                "title": "Additional details",
                "description": "",
                "order": 10,
            }
        ],
        "fields": [],
    }


def schema_hash(schema: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest()


def values_hash(values: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(values).encode("utf-8")).hexdigest()


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def validate_applicability(
    entity_type: str,
    applicability: dict[str, Any],
) -> list[str]:
    if not isinstance(applicability, dict):
        return ["applicability must be an object"]
    unknown = set(applicability) - {"all"}
    if unknown:
        return ["applicability supports only the all condition list"]
    conditions = applicability.get("all", [])
    if not isinstance(conditions, list) or len(conditions) > 10:
        return ["applicability.all must be an array of at most 10 conditions"]
    errors: list[str] = []
    allowed_fields = _APPLICABILITY_FIELDS.get(entity_type, set())
    for index, condition in enumerate(conditions):
        if not isinstance(condition, dict):
            errors.append(f"applicability.all[{index}] must be an object")
            continue
        field = str(condition.get("field", ""))
        operator = str(condition.get("operator", ""))
        if field not in allowed_fields:
            errors.append(f"applicability.all[{index}].field is unavailable for {entity_type}")
        if operator not in {"eq", "neq", "in"}:
            errors.append(f"applicability.all[{index}].operator must be eq, neq, or in")
        if "value" not in condition:
            errors.append(f"applicability.all[{index}].value is required")
        if operator == "in" and not isinstance(condition.get("value"), list):
            errors.append(f"applicability.all[{index}].value must be an array for in")
    return errors


def validate_custom_field_schema(schema: dict[str, Any]) -> dict[str, Any]:
    errors = validate_form_definition(schema, default_attachment_rules())
    warnings: list[str] = []
    if schema.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    fields = schema.get("fields", [])
    searchable_count = indexed_count = reportable_count = sensitive_count = 0
    for index, field in enumerate(fields if isinstance(fields, list) else []):
        if not isinstance(field, dict):
            continue
        path = f"fields[{index}]"
        for flag in (
            "searchable",
            "indexed",
            "reportable",
            "sensitive",
            "immutable_after_set",
        ):
            if not isinstance(field.get(flag, False), bool):
                errors.append(f"{path}.{flag} must be boolean")
        searchable = bool(field.get("searchable", False))
        indexed = bool(field.get("indexed", False))
        reportable = bool(field.get("reportable", False))
        sensitive = bool(field.get("sensitive", False))
        searchable_count += int(searchable)
        indexed_count += int(indexed)
        reportable_count += int(reportable)
        sensitive_count += int(sensitive)
        if sensitive and (searchable or indexed):
            errors.append(f"{path} sensitive fields cannot be searchable or indexed")
        if field.get("type") in {"textarea", "multiselect"} and indexed:
            errors.append(f"{path} type cannot be indexed")
        if searchable and field.get("type") not in {
            "text",
            "email",
            "select",
            "multiselect",
        }:
            errors.append(f"{path} type cannot be searchable")
        if field.get("default") is not None:
            default_errors, normalized, _ = validate_submission(
                {
                    **schema,
                    "fields": [{**field, "required": True}],
                },
                default_attachment_rules(),
                {str(field.get("key")): field["default"]},
                [],
            )
            if default_errors or str(field.get("key")) not in normalized:
                errors.append(f"{path}.default does not satisfy field validation")
    if searchable_count > 20:
        errors.append("A field set can contain at most 20 searchable fields")
    if indexed_count > 10:
        errors.append("A field set can contain at most 10 indexed fields")
    if not reportable_count and fields:
        warnings.append("No fields are enabled for reporting")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "fields": len(fields) if isinstance(fields, list) else 0,
            "searchable": searchable_count,
            "indexed": indexed_count,
            "reportable": reportable_count,
            "sensitive": sensitive_count,
        },
    }


def compare_schema_compatibility(
    previous: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    old_fields = {
        str(field.get("key")): field
        for field in previous.get("fields", [])
        if isinstance(field, dict)
    }
    new_fields = {
        str(field.get("key")): field
        for field in candidate.get("fields", [])
        if isinstance(field, dict)
    }
    breaking: list[dict[str, Any]] = []
    additive: list[dict[str, Any]] = []
    for key in sorted(old_fields.keys() - new_fields.keys()):
        breaking.append({"field": key, "reason": "field_removed"})
    for key in sorted(new_fields.keys() - old_fields.keys()):
        additive.append({"field": key, "reason": "field_added"})
        if new_fields[key].get("required") and new_fields[key].get("default") is None:
            breaking.append({"field": key, "reason": "required_field_without_default"})
    for key in sorted(old_fields.keys() & new_fields.keys()):
        old = old_fields[key]
        new = new_fields[key]
        if old.get("type") != new.get("type"):
            breaking.append(
                {
                    "field": key,
                    "reason": "type_changed",
                    "before": old.get("type"),
                    "after": new.get("type"),
                }
            )
        if not old.get("required") and new.get("required") and new.get("default") is None:
            breaking.append({"field": key, "reason": "became_required_without_default"})
        if old.get("sensitive") and not new.get("sensitive"):
            breaking.append({"field": key, "reason": "sensitive_classification_removed"})
        if old.get("immutable_after_set") and not new.get("immutable_after_set"):
            breaking.append({"field": key, "reason": "immutability_removed"})
    return {
        "compatible": not breaking,
        "breaking": breaking,
        "additive": additive,
    }


def create_field_set(
    db: Session,
    *,
    tenant_id: str,
    code: str,
    name: str,
    description: str | None,
    entity_type: str,
    applicability: dict[str, Any],
    actor_id: str | None,
) -> tuple[CustomFieldSet, CustomFieldSetVersion]:
    normalized_code = code.strip().lower()
    normalized_entity = entity_type.strip().lower()
    if not _CODE_PATTERN.fullmatch(normalized_code):
        raise ValueError("Field-set code is invalid")
    if normalized_entity not in CUSTOM_FIELD_ENTITY_TYPES:
        raise ValueError("Custom-field entity type is unsupported")
    applicability_errors = validate_applicability(
        normalized_entity,
        applicability,
    )
    if applicability_errors:
        raise ValueError("; ".join(applicability_errors))
    if len(name.strip()) < 2:
        raise ValueError("Field-set name must contain at least 2 characters")
    now = utcnow()
    schema = default_custom_field_schema(normalized_entity)
    validation = validate_custom_field_schema(schema)
    field_set = CustomFieldSet(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=normalized_code,
        name=name.strip(),
        description=description.strip() if description else None,
        entity_type=normalized_entity,
        status="PAUSED",
        applicability_json=canonical_json(applicability),
        latest_version_number=1,
        draft_version_number=1,
        published_version_number=None,
        revision=1,
        created_by_id=actor_id,
        updated_by_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    version = CustomFieldSetVersion(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        field_set_id=field_set.id,
        version_number=1,
        status="DRAFT",
        schema_json=canonical_json(schema),
        schema_sha256=schema_hash(schema),
        validation_status="VALID",
        validation_json=canonical_json(validation),
        revision=1,
        based_on_version_number=None,
        change_summary="Initial draft",
        breaking_change=False,
        created_by_id=actor_id,
        updated_by_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add_all([field_set, version])
    db.flush()
    return field_set, version


def create_field_set_draft(
    db: Session,
    field_set: CustomFieldSet,
    *,
    actor_id: str | None,
    change_summary: str,
) -> CustomFieldSetVersion:
    if field_set.status == "ARCHIVED":
        raise ValueError("Archived field set cannot create drafts")
    if field_set.draft_version_number is not None:
        raise ValueError("Field set already has an editable draft")
    source = None
    if field_set.published_version_number is not None:
        source = db.scalar(
            select(CustomFieldSetVersion).where(
                CustomFieldSetVersion.field_set_id == field_set.id,
                CustomFieldSetVersion.version_number == field_set.published_version_number,
            )
        )
    schema = (
        _json_object(source.schema_json)
        if source is not None
        else default_custom_field_schema(field_set.entity_type)
    )
    number = field_set.latest_version_number + 1
    validation = validate_custom_field_schema(schema)
    now = utcnow()
    version = CustomFieldSetVersion(
        id=str(uuid.uuid4()),
        tenant_id=field_set.tenant_id,
        field_set_id=field_set.id,
        version_number=number,
        status="DRAFT",
        schema_json=canonical_json(schema),
        schema_sha256=schema_hash(schema),
        validation_status="VALID" if validation["valid"] else "INVALID",
        validation_json=canonical_json(validation),
        revision=1,
        based_on_version_number=(source.version_number if source is not None else None),
        change_summary=change_summary.strip(),
        breaking_change=False,
        created_by_id=actor_id,
        updated_by_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    field_set.latest_version_number = number
    field_set.draft_version_number = number
    field_set.revision += 1
    field_set.updated_by_id = actor_id
    field_set.updated_at = now
    db.add(version)
    db.flush()
    return version


def update_field_set_draft(
    db: Session,
    version: CustomFieldSetVersion,
    field_set: CustomFieldSet,
    *,
    schema: dict[str, Any],
    expected_revision: int,
    change_summary: str,
    actor_id: str | None,
) -> dict[str, Any]:
    if version.status != "DRAFT":
        raise ValueError("Published custom-field versions are immutable")
    if version.revision != expected_revision:
        raise ValueError(f"Field-set draft changed; current revision is {version.revision}")
    validation = validate_custom_field_schema(schema)
    compatibility = {"compatible": True, "breaking": [], "additive": []}
    if field_set.published_version_number is not None:
        published = db.scalar(
            select(CustomFieldSetVersion).where(
                CustomFieldSetVersion.field_set_id == field_set.id,
                CustomFieldSetVersion.version_number == field_set.published_version_number,
            )
        )
        if published is not None:
            compatibility = compare_schema_compatibility(
                _json_object(published.schema_json),
                schema,
            )
    version.schema_json = canonical_json(schema)
    version.schema_sha256 = schema_hash(schema)
    version.validation_status = "VALID" if validation["valid"] else "INVALID"
    version.validation_json = canonical_json(validation)
    version.change_summary = change_summary.strip()
    version.revision += 1
    version.updated_by_id = actor_id
    version.updated_at = utcnow()
    field_set.updated_by_id = actor_id
    field_set.updated_at = utcnow()
    return {"validation": validation, "compatibility": compatibility}


def publish_field_set_version(
    db: Session,
    field_set: CustomFieldSet,
    version: CustomFieldSetVersion,
    *,
    expected_field_set_revision: int,
    expected_version_revision: int,
    allow_breaking_changes: bool,
    actor_id: str | None,
) -> dict[str, Any]:
    if field_set.status == "ARCHIVED":
        raise ValueError("Archived field set cannot publish")
    if field_set.revision != expected_field_set_revision:
        raise ValueError(f"Field set changed; current revision is {field_set.revision}")
    if version.status != "DRAFT":
        raise ValueError("Only a custom-field draft can publish")
    if version.revision != expected_version_revision:
        raise ValueError(f"Field-set draft changed; current revision is {version.revision}")
    schema = _json_object(version.schema_json)
    if schema_hash(schema) != version.schema_sha256:
        raise ValueError("Custom-field draft integrity check failed")
    validation = validate_custom_field_schema(schema)
    if not validation["valid"]:
        raise ValueError("Custom-field draft is invalid: " + "; ".join(validation["errors"]))
    previous = None
    compatibility = {"compatible": True, "breaking": [], "additive": []}
    if field_set.published_version_number is not None:
        previous = db.scalar(
            select(CustomFieldSetVersion).where(
                CustomFieldSetVersion.field_set_id == field_set.id,
                CustomFieldSetVersion.version_number == field_set.published_version_number,
            )
        )
    if previous is not None:
        previous_schema = _json_object(previous.schema_json)
        if schema_hash(previous_schema) != previous.schema_sha256:
            raise ValueError("Published custom-field version integrity check failed")
        compatibility = compare_schema_compatibility(previous_schema, schema)
        existing_value_count = int(
            db.scalar(
                select(func.count())
                .select_from(CustomFieldValue)
                .where(CustomFieldValue.field_set_id == field_set.id)
            )
            or 0
        )
        if existing_value_count and not compatibility["compatible"] and not allow_breaking_changes:
            raise ValueError("Breaking schema change requires explicit approval")
    now = utcnow()
    if previous is not None and previous.status == "PUBLISHED":
        previous.status = "RETIRED"
        previous.updated_at = now
    version.status = "PUBLISHED"
    version.breaking_change = not bool(compatibility["compatible"])
    version.published_by_id = actor_id
    version.published_at = now
    version.updated_at = now
    field_set.published_version_number = version.version_number
    field_set.draft_version_number = None
    field_set.status = "ACTIVE"
    field_set.revision += 1
    field_set.updated_by_id = actor_id
    field_set.updated_at = now
    db.flush()
    return compatibility


def get_entity(
    db: Session,
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
) -> Any:
    model = CUSTOM_FIELD_ENTITY_TYPES.get(entity_type)
    if model is None:
        raise ValueError("Custom-field entity type is unsupported")
    entity = db.scalar(
        select(model).where(
            model.id == entity_id,
            model.tenant_id == tenant_id,
        )
    )
    if entity is None:
        raise ValueError("Custom-field entity was not found")
    return entity


def is_field_set_applicable(
    field_set: CustomFieldSet,
    entity: Any,
) -> bool:
    applicability = _json_object(field_set.applicability_json)
    conditions = applicability.get("all", [])
    if not isinstance(conditions, list):
        return False
    for condition in conditions:
        if not isinstance(condition, dict):
            return False
        actual = getattr(entity, str(condition.get("field", "")), None)
        operator = condition.get("operator")
        expected = condition.get("value")
        if operator == "eq" and actual != expected:
            return False
        if operator == "neq" and actual == expected:
            return False
        if operator == "in" and (not isinstance(expected, list) or actual not in expected):
            return False
    return True


def _published_version(
    db: Session,
    field_set: CustomFieldSet,
) -> CustomFieldSetVersion:
    if field_set.published_version_number is None:
        raise ValueError("Field set has no published version")
    version = db.scalar(
        select(CustomFieldSetVersion).where(
            CustomFieldSetVersion.field_set_id == field_set.id,
            CustomFieldSetVersion.version_number == field_set.published_version_number,
            CustomFieldSetVersion.status == "PUBLISHED",
        )
    )
    if version is None:
        raise ValueError("Published custom-field version is unavailable")
    schema = _json_object(version.schema_json)
    if schema_hash(schema) != version.schema_sha256:
        raise ValueError("Published custom-field version integrity check failed")
    return version


def _field_map(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(field.get("key")): field
        for field in schema.get("fields", [])
        if isinstance(field, dict)
    }


def _decrypt_stored_values(
    stored: dict[str, Any],
    schema: dict[str, Any],
    *,
    tenant_id: str,
    field_set_id: str,
    settings: Settings | None,
) -> dict[str, Any]:
    fields = _field_map(schema)
    output: dict[str, Any] = {}
    for key, value in stored.items():
        if (
            fields.get(key, {}).get("sensitive")
            and isinstance(value, dict)
            and isinstance(value.get("__encrypted__"), str)
        ):
            plaintext = decrypt_credential(
                value["__encrypted__"],
                purpose=f"custom-field:{field_set_id}:{key}",
                tenant_id=tenant_id,
                settings=settings,
            )
            output[key] = json.loads(plaintext)
        else:
            output[key] = value
    return output


def _stored_values(
    normalized: dict[str, Any],
    submitted: dict[str, Any],
    previous_stored: dict[str, Any],
    schema: dict[str, Any],
    *,
    tenant_id: str,
    field_set_id: str,
    settings: Settings | None,
) -> dict[str, Any]:
    fields = _field_map(schema)
    stored: dict[str, Any] = {}
    for key, value in normalized.items():
        field = fields.get(key, {})
        if not field.get("sensitive"):
            stored[key] = value
            continue
        if key not in submitted and key in previous_stored:
            stored[key] = previous_stored[key]
            continue
        stored[key] = {
            "__encrypted__": encrypt_credential(
                canonical_json(value),
                purpose=f"custom-field:{field_set_id}:{key}",
                tenant_id=tenant_id,
                settings=settings,
            )
        }
    return stored


def _search_text(values: dict[str, Any], schema: dict[str, Any]) -> str:
    fields = _field_map(schema)
    parts: list[str] = []
    for key, value in values.items():
        if not fields.get(key, {}).get("searchable"):
            continue
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return " ".join(parts)[:20_000].casefold()


def save_custom_field_values(
    db: Session,
    field_set: CustomFieldSet,
    *,
    entity: Any,
    submitted_values: dict[str, Any],
    expected_version: int | None,
    actor_id: str | None,
    settings: Settings | None = None,
) -> tuple[CustomFieldValue, dict[str, Any]]:
    if field_set.status != "ACTIVE":
        raise ValueError("Only active field sets accept values")
    if not is_field_set_applicable(field_set, entity):
        raise ValueError("Field set is not applicable to this entity")
    version = _published_version(db, field_set)
    schema = _json_object(version.schema_json)
    existing_statement = select(CustomFieldValue).where(
        CustomFieldValue.field_set_id == field_set.id,
        CustomFieldValue.entity_type == field_set.entity_type,
        CustomFieldValue.entity_id == entity.id,
    )
    if db.get_bind().dialect.name == "postgresql":
        existing_statement = existing_statement.with_for_update()
    existing = db.scalar(existing_statement)
    if existing is not None and expected_version != existing.version:
        raise ValueError(f"Custom-field values changed; current version is {existing.version}")
    if existing is None and expected_version not in {None, 0}:
        raise ValueError("Custom-field values do not exist yet")
    previous_stored = _json_object(existing.values_json) if existing else {}
    previous_schema = schema
    if existing is not None and existing.field_set_version_id != version.id:
        previous_version = db.get(
            CustomFieldSetVersion,
            existing.field_set_version_id,
        )
        if previous_version is None or previous_version.field_set_id != field_set.id:
            raise ValueError("Bound custom-field schema version is unavailable")
        previous_schema = _json_object(previous_version.schema_json)
        if schema_hash(previous_schema) != previous_version.schema_sha256:
            raise ValueError("Bound custom-field schema failed integrity verification")
    previous_plain = _decrypt_stored_values(
        previous_stored,
        previous_schema,
        tenant_id=field_set.tenant_id,
        field_set_id=field_set.id,
        settings=settings,
    )
    merged = {**previous_plain, **submitted_values}
    errors, normalized, _ = validate_submission(
        schema,
        default_attachment_rules(),
        merged,
        [],
    )
    if errors:
        raise ValueError(canonical_json({"field_errors": errors}))
    fields = _field_map(schema)
    for key, field in fields.items():
        if (
            existing is not None
            and field.get("immutable_after_set")
            and key in previous_plain
            and key in submitted_values
            and normalized.get(key) != previous_plain.get(key)
        ):
            raise ValueError(f"Custom field {key} is immutable after first set")
    stored = _stored_values(
        normalized,
        submitted_values,
        previous_stored,
        schema,
        tenant_id=field_set.tenant_id,
        field_set_id=field_set.id,
        settings=settings,
    )
    now = utcnow()
    if existing is None:
        existing = CustomFieldValue(
            id=str(uuid.uuid4()),
            tenant_id=field_set.tenant_id,
            field_set_id=field_set.id,
            field_set_version_id=version.id,
            field_set_version_number=version.version_number,
            entity_type=field_set.entity_type,
            entity_id=entity.id,
            values_json=canonical_json(stored),
            values_sha256=values_hash(stored),
            search_text=_search_text(normalized, schema),
            version=1,
            created_by_id=actor_id,
            updated_by_id=actor_id,
            created_at=now,
            updated_at=now,
        )
        db.add(existing)
    else:
        existing.field_set_version_id = version.id
        existing.field_set_version_number = version.version_number
        existing.values_json = canonical_json(stored)
        existing.values_sha256 = values_hash(stored)
        existing.search_text = _search_text(normalized, schema)
        existing.version += 1
        existing.updated_by_id = actor_id
        existing.updated_at = now
    db.flush()
    return existing, normalized


def custom_field_values_response(
    item: CustomFieldValue,
    schema: dict[str, Any],
    *,
    can_read_sensitive: bool,
    settings: Settings | None = None,
) -> dict[str, Any]:
    stored = _json_object(item.values_json)
    if values_hash(stored) != item.values_sha256:
        raise ValueError("Custom-field value integrity check failed")
    fields = _field_map(schema)
    if can_read_sensitive:
        plain = _decrypt_stored_values(
            stored,
            schema,
            tenant_id=item.tenant_id,
            field_set_id=item.field_set_id,
            settings=settings,
        )
    else:
        plain = {
            key: ("••••••" if fields.get(key, {}).get("sensitive") else value)
            for key, value in stored.items()
        }
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "field_set_id": item.field_set_id,
        "field_set_version_id": item.field_set_version_id,
        "field_set_version_number": item.field_set_version_number,
        "entity_type": item.entity_type,
        "entity_id": item.entity_id,
        "values": plain,
        "values_sha256": item.values_sha256,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
