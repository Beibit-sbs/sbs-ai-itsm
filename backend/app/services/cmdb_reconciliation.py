from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import re
import uuid
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.ai_suggestion import AiSuggestion
from app.models.asset import Asset
from app.models.asset_assignment import AssetAssignment
from app.models.asset_history import AssetHistory
from app.models.asset_import_row import AssetImportRow
from app.models.change_link import ChangeAssetLink
from app.models.ci_class import (
    ConfigurationItemClass,
    ConfigurationItemClassVersion,
)
from app.models.ci_relationship import (
    ConfigurationItemRelationship,
    ConfigurationItemRelationshipType,
)
from app.models.cmdb_reconciliation import (
    CIDuplicateCandidate,
    CMDBFieldOwnership,
    CMDBReconciliationRecord,
    CMDBReconciliationRun,
    CMDBSource,
    CMDBSourceIdentity,
)
from app.models.knowledge_article import KnowledgeArticle
from app.models.problem_link import ProblemAssetLink
from app.models.ticket import Ticket
from app.models.user import User
from app.services.cmdb_schema import (
    canonical_json,
    merge_schemas,
    validate_attributes,
)


CORE_FIELDS = {
    "name",
    "asset_tag",
    "inventory_number",
    "serial_number",
    "manufacturer",
    "model",
    "original_type",
    "lifecycle_status",
    "owner_user_id",
    "support_group",
    "criticality",
    "environment",
    "location",
    "condition",
    "description",
    "assigned_to_name",
    "purchase_date",
    "purchase_cost",
    "current_cost",
    "depreciation_amount",
    "residual_value",
    "purchase_year",
    "verification_status",
}
IDENTIFICATION_CORE_FIELDS = {
    "asset_tag",
    "inventory_number",
    "serial_number",
    "name",
}
ATTRIBUTE_FIELD_PATTERN = re.compile(r"^attributes\.[a-z][a-z0-9_]{1,63}$")
LIFECYCLE_TO_ASSET_STATUS = {
    "PLANNING": "inactive",
    "ORDERED": "inactive",
    "IN_STOCK": "in_stock",
    "ACTIVE": "in_use",
    "MAINTENANCE": "maintenance",
    "RETIRED": "inactive",
    "DISPOSED": "disposed",
}


class ReconciliationConflict(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _source_marker(source: CMDBSource) -> str:
    if source.code == "EXCEL_ASSET_IMPORT":
        return "excel_import"
    return f"cmdb_source:{source.code}"


def _json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def validate_source_definition(
    identification_rules: list[str],
    authoritative_fields: list[str],
) -> tuple[list[str], list[str]]:
    rules = [str(item).strip() for item in identification_rules if str(item).strip()]
    fields = [
        str(item).strip() for item in authoritative_fields if str(item).strip()
    ]
    if not rules or len(rules) > 10 or len(set(rules)) != len(rules):
        raise ValueError("identification_rules must contain 1-10 unique fields")
    if len(fields) > 100 or len(set(fields)) != len(fields):
        raise ValueError("authoritative_fields must contain unique fields")
    for rule in rules:
        if rule not in IDENTIFICATION_CORE_FIELDS and not (
            ATTRIBUTE_FIELD_PATTERN.fullmatch(rule)
        ):
            raise ValueError(f"unsupported identification rule: {rule}")
    for field in fields:
        if field not in CORE_FIELDS and field != "attributes.*" and not (
            ATTRIBUTE_FIELD_PATTERN.fullmatch(field)
        ):
            raise ValueError(f"unsupported authoritative field: {field}")
    return rules, fields


def _effective_schema(
    db: Session,
    version: ConfigurationItemClassVersion,
    seen: set[str] | None = None,
) -> dict[str, Any]:
    visited = seen or set()
    if version.id in visited:
        raise ValueError("CI class inheritance cycle detected")
    visited.add(version.id)
    inherited = None
    if version.parent_version_id:
        parent = db.get(ConfigurationItemClassVersion, version.parent_version_id)
        if parent is None:
            raise ValueError("Referenced parent CI class version is unavailable")
        inherited = _effective_schema(db, parent, visited)
    try:
        own_schema = json.loads(version.schema_json)
    except json.JSONDecodeError as exc:
        raise ValueError("CI class schema is invalid") from exc
    return merge_schemas(inherited, own_schema)


def _published_class(
    db: Session,
    tenant_id: str,
    class_id: str | None,
) -> tuple[ConfigurationItemClass, ConfigurationItemClassVersion] | None:
    if not class_id:
        return None
    ci_class = db.get(ConfigurationItemClass, class_id)
    if ci_class is None or ci_class.tenant_id != tenant_id:
        return None
    version = db.scalar(
        select(ConfigurationItemClassVersion)
        .where(
            ConfigurationItemClassVersion.ci_class_id == ci_class.id,
            ConfigurationItemClassVersion.status == "PUBLISHED",
        )
        .order_by(ConfigurationItemClassVersion.version.desc())
    )
    return (ci_class, version) if version else None


def _attributes(asset: Asset) -> dict[str, Any]:
    return _json_dict(asset.ci_attributes_json)


def _normalize_comparable(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().casefold()
        return normalized or None
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    return str(value).strip().casefold() or None


def _record_value(record: dict[str, Any], field_name: str) -> Any:
    if field_name.startswith("attributes."):
        key = field_name.split(".", 1)[1]
        return (record.get("attributes") or {}).get(key)
    return record.get(field_name)


def _asset_value(asset: Asset, field_name: str) -> Any:
    if field_name.startswith("attributes."):
        key = field_name.split(".", 1)[1]
        return _attributes(asset).get(key)
    return getattr(asset, field_name, None)


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, str):
            value = value.strip()
            normalized[key] = value or None
        elif key == "attributes" and isinstance(value, dict):
            normalized[key] = {
                str(attr_key).strip(): (
                    attr_value.strip()
                    if isinstance(attr_value, str)
                    else attr_value
                )
                for attr_key, attr_value in value.items()
            }
        else:
            normalized[key] = value
    normalized.setdefault("attributes", {})
    return normalized


def _build_indexes(
    assets: list[Asset],
    rules: list[str],
) -> dict[str, dict[str, set[str]]]:
    indexes: dict[str, dict[str, set[str]]] = {rule: {} for rule in rules}
    for asset in assets:
        for rule in rules:
            value = _normalize_comparable(_asset_value(asset, rule))
            if value is not None:
                indexes[rule].setdefault(value, set()).add(asset.id)
    return indexes


def _matches(
    record: dict[str, Any],
    rules: list[str],
    indexes: dict[str, dict[str, set[str]]],
) -> tuple[set[str], list[str]]:
    candidate_ids: set[str] = set()
    reasons: list[str] = []
    for rule in rules:
        value = _normalize_comparable(_record_value(record, rule))
        if value is None:
            continue
        matched = indexes[rule].get(value, set())
        if matched:
            if not candidate_ids:
                candidate_ids = set(matched)
            else:
                narrowed = candidate_ids.intersection(matched)
                candidate_ids = narrowed or candidate_ids.union(matched)
            reasons.append(f"{rule}={value}")
    return candidate_ids, reasons


def _incoming_authoritative_fields(
    source: CMDBSource,
    record: dict[str, Any],
) -> list[str]:
    configured = [str(item) for item in _json_list(source.authoritative_fields_json)]
    selected: list[str] = []
    for field_name in configured:
        if field_name == "attributes.*":
            selected.extend(
                f"attributes.{key}"
                for key in sorted((record.get("attributes") or {}).keys())
            )
        elif _record_value(record, field_name) is not None:
            selected.append(field_name)
    return list(dict.fromkeys(selected))


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _plan_changes(
    asset: Asset,
    source: CMDBSource,
    external_id: str,
    record: dict[str, Any],
    ownership: dict[str, CMDBFieldOwnership],
) -> tuple[list[str], list[str], list[str]]:
    changed: list[str] = []
    blocked: list[str] = []
    unchanged: list[str] = []
    source_marker = _source_marker(source)
    for field_name in _incoming_authoritative_fields(source, record):
        incoming = _record_value(record, field_name)
        current = _asset_value(asset, field_name)
        if _normalize_comparable(incoming) == _normalize_comparable(current):
            unchanged.append(field_name)
            continue
        owner = ownership.get(field_name)
        allowed = False
        if owner is not None:
            allowed = (
                owner.source_id == source.id
                or owner.source_priority >= source.priority
            )
        elif _is_empty(current):
            allowed = True
        elif asset.source == source_marker:
            allowed = True
        elif source.claim_unowned_fields:
            allowed = True
        if allowed:
            changed.append(field_name)
        else:
            blocked.append(field_name)
    return changed, blocked, unchanged


def _record_errors(
    db: Session,
    source: CMDBSource,
    record: dict[str, Any],
    matched_asset: Asset | None,
) -> tuple[list[str], str | None, str | None]:
    errors: list[str] = []
    requested_class_id = record.get("ci_class_id")
    if matched_asset and requested_class_id and (
        requested_class_id != matched_asset.ci_class_id
    ):
        errors.append("class_change_requires_manual_governance")
    class_id = (
        requested_class_id
        or (matched_asset.ci_class_id if matched_asset else None)
        or source.default_class_id
    )
    published = _published_class(db, source.tenant_id, class_id)
    if published is None:
        errors.append("published_ci_class_required")
        return errors, None, None
    ci_class, version = published
    if matched_asset is None and not record.get("name"):
        errors.append("name_required_for_create")
    incoming_attributes = record.get("attributes") or {}
    base_attributes = _attributes(matched_asset) if matched_asset else {}
    candidate_attributes = {**base_attributes, **incoming_attributes}
    _, attribute_errors = validate_attributes(
        _effective_schema(db, version),
        candidate_attributes,
    )
    for key, messages in attribute_errors.items():
        errors.extend(f"attributes.{key}: {message}" for message in messages)
    owner_user_id = record.get("owner_user_id")
    if owner_user_id:
        owner = db.get(User, owner_user_id)
        if (
            owner is None
            or not owner.is_active
            or owner.is_root
            or owner.tenant_id != source.tenant_id
        ):
            errors.append("owner_user_id_is_unavailable")
    return errors, ci_class.id, version.id


def _summary(run: CMDBReconciliationRun) -> dict[str, Any]:
    return {
        "input_count": run.input_count,
        "create_count": run.create_count,
        "update_count": run.update_count,
        "unchanged_count": run.unchanged_count,
        "ambiguous_count": run.ambiguous_count,
        "invalid_count": run.invalid_count,
        "skipped_count": run.skipped_count,
    }


def preview_reconciliation(
    db: Session,
    *,
    source: CMDBSource,
    idempotency_key: str,
    records: list[dict[str, Any]],
    actor_id: str,
) -> CMDBReconciliationRun:
    if source.status != "ACTIVE":
        raise ReconciliationConflict("CMDB source is inactive")
    if not records or len(records) > 500:
        raise ValueError("reconciliation payload must contain 1-500 records")
    idempotency_key = idempotency_key.strip()
    if not idempotency_key or len(idempotency_key) > 160:
        raise ValueError("idempotency_key must contain 1-160 characters")
    external_ids = [str(record.get("external_id", "")).strip() for record in records]
    if any(not value for value in external_ids):
        raise ValueError("every reconciliation record requires external_id")
    if len(set(external_ids)) != len(external_ids):
        raise ValueError("external_id must be unique within a reconciliation run")
    payload_hash = hashlib.sha256(canonical_json(records).encode()).hexdigest()
    existing = db.scalar(
        select(CMDBReconciliationRun).where(
            CMDBReconciliationRun.source_id == source.id,
            CMDBReconciliationRun.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if existing.payload_hash != payload_hash:
            raise ReconciliationConflict(
                "idempotency_key was already used with another payload"
            )
        return existing

    rules, _ = validate_source_definition(
        [str(item) for item in _json_list(source.identification_rules_json)],
        [str(item) for item in _json_list(source.authoritative_fields_json)],
    )
    assets = db.scalars(
        select(Asset).where(Asset.tenant_id == source.tenant_id)
    ).all()
    asset_map = {asset.id: asset for asset in assets}
    indexes = _build_indexes(assets, rules)
    identity_rows = db.scalars(
        select(CMDBSourceIdentity).where(
            CMDBSourceIdentity.source_id == source.id,
            CMDBSourceIdentity.external_id.in_(external_ids),
        )
    ).all()
    identity_map = {item.external_id: item for item in identity_rows}
    payload_identifier_counts: dict[tuple[str, str], int] = {}
    normalized_records = [_normalize_record(payload) for payload in records]
    for normalized in normalized_records:
        for rule in rules:
            comparable = _normalize_comparable(_record_value(normalized, rule))
            if comparable is not None:
                key = (rule, comparable)
                payload_identifier_counts[key] = payload_identifier_counts.get(key, 0) + 1
    ownership_rows = db.scalars(
        select(CMDBFieldOwnership).where(
            CMDBFieldOwnership.tenant_id == source.tenant_id
        )
    ).all()
    ownership_map: dict[str, dict[str, CMDBFieldOwnership]] = {}
    for item in ownership_rows:
        ownership_map.setdefault(item.asset_id, {})[item.field_name] = item

    now = _now()
    run = CMDBReconciliationRun(
        id=str(uuid.uuid4()),
        tenant_id=source.tenant_id,
        source_id=source.id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        mode="PREVIEW",
        status="PENDING",
        input_count=len(records),
        create_count=0,
        update_count=0,
        unchanged_count=0,
        ambiguous_count=0,
        invalid_count=0,
        skipped_count=0,
        summary_json="{}",
        created_by_id=actor_id,
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    db.flush()

    duplicate_pairs: set[tuple[str, str]] = set()
    for row_number, (payload, normalized) in enumerate(
        zip(records, normalized_records, strict=True),
        start=1,
    ):
        external_id = str(normalized["external_id"])
        candidate_ids, reasons = _matches(normalized, rules, indexes)
        bound_identity = identity_map.get(external_id)
        identity_duplicate_ids: set[str] = set()
        identity_errors: list[str] = []
        if bound_identity is not None:
            if (
                candidate_ids
                and bound_identity.asset_id not in candidate_ids
            ):
                identity_errors.append("identification_conflict_with_bound_ci")
            elif bound_identity.asset_id in candidate_ids:
                identity_duplicate_ids = candidate_ids - {
                    bound_identity.asset_id
                }
            candidate_ids = {bound_identity.asset_id}
            reasons.insert(0, f"source_identity={external_id}")
        for rule in rules:
            comparable = _normalize_comparable(_record_value(normalized, rule))
            if (
                comparable is not None
                and payload_identifier_counts[(rule, comparable)] > 1
            ):
                identity_errors.append(
                    f"duplicate_identifier_in_payload:{rule}"
                )
        matched_asset = (
            asset_map.get(next(iter(candidate_ids)))
            if len(candidate_ids) == 1
            else None
        )
        if len(candidate_ids) > 1:
            errors: list[str] = []
            class_id = None
            class_version_id = None
        else:
            errors, class_id, class_version_id = _record_errors(
                db,
                source,
                normalized,
                matched_asset,
            )
        errors = list(dict.fromkeys([*identity_errors, *errors]))
        planned_fields: list[str] = []
        blocked_fields: list[str] = []
        unchanged_fields: list[str] = []
        if len(candidate_ids) > 1 and not identity_errors:
            outcome = "AMBIGUOUS"
            run.ambiguous_count += 1
        elif errors:
            outcome = "INVALID"
            run.invalid_count += 1
        elif matched_asset is None:
            outcome = "CREATE"
            run.create_count += 1
        else:
            planned_fields, blocked_fields, unchanged_fields = _plan_changes(
                matched_asset,
                source,
                external_id,
                normalized,
                ownership_map.get(matched_asset.id, {}),
            )
            if planned_fields:
                outcome = "UPDATE"
                run.update_count += 1
            elif blocked_fields:
                outcome = "SKIPPED"
                run.skipped_count += 1
            else:
                outcome = "UNCHANGED"
                run.unchanged_count += 1
        normalized["_ci_class_id"] = class_id
        normalized["_ci_class_version_id"] = class_version_id
        normalized["_matched_rules"] = reasons
        normalized["_planned_fields"] = planned_fields
        normalized["_blocked_fields"] = blocked_fields
        normalized["_unchanged_fields"] = unchanged_fields
        normalized["_duplicate_candidate_ids"] = sorted(
            identity_duplicate_ids
        )
        record = CMDBReconciliationRecord(
            id=str(uuid.uuid4()),
            tenant_id=source.tenant_id,
            run_id=run.id,
            row_number=row_number,
            external_id=external_id,
            record_hash=hashlib.sha256(
                canonical_json(payload).encode()
            ).hexdigest(),
            payload_json=canonical_json(payload),
            normalized_json=canonical_json(normalized),
            outcome=outcome,
            matched_ci_id=matched_asset.id if matched_asset else None,
            candidate_ids_json=canonical_json(sorted(candidate_ids)),
            errors_json=canonical_json(errors),
            created_at=now,
        )
        db.add(record)
        db.flush()
        if outcome == "AMBIGUOUS" or identity_duplicate_ids:
            if identity_duplicate_ids and bound_identity is not None:
                primary_id = bound_identity.asset_id
                duplicate_ids = sorted(identity_duplicate_ids)
            else:
                ordered_ids = sorted(candidate_ids)
                primary_id = ordered_ids[0]
                duplicate_ids = ordered_ids[1:]
            for duplicate_id in duplicate_ids:
                pair = (primary_id, duplicate_id)
                if pair in duplicate_pairs:
                    continue
                duplicate_pairs.add(pair)
                confidence = max(
                    (
                        0.99
                        if reason.startswith("asset_tag=")
                        else 0.95
                        if reason.startswith("serial_number=")
                        else 0.9
                        if reason.startswith("inventory_number=")
                        else 0.6
                    )
                    for reason in reasons
                )
                db.add(
                    CIDuplicateCandidate(
                        id=str(uuid.uuid4()),
                        tenant_id=source.tenant_id,
                        run_id=run.id,
                        record_id=record.id,
                        primary_ci_id=primary_id,
                        duplicate_ci_id=duplicate_id,
                        confidence=confidence,
                        reasons_json=canonical_json(reasons),
                        status="OPEN",
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
    run.status = "PREVIEWED"
    run.completed_at = _now()
    run.summary_json = canonical_json(_summary(run))
    run.updated_at = run.completed_at
    source.last_run_at = run.completed_at
    source.updated_at = run.completed_at
    db.flush()
    return run


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _value_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _set_ownership(
    db: Session,
    *,
    source: CMDBSource,
    asset: Asset,
    external_id: str,
    field_name: str,
    value: Any,
    now: datetime,
) -> None:
    ownership = db.scalar(
        select(CMDBFieldOwnership).where(
            CMDBFieldOwnership.asset_id == asset.id,
            CMDBFieldOwnership.field_name == field_name,
        )
    )
    if ownership is None:
        ownership = CMDBFieldOwnership(
            id=str(uuid.uuid4()),
            tenant_id=source.tenant_id,
            asset_id=asset.id,
            field_name=field_name,
            source_id=source.id,
            external_id=external_id,
            source_priority=source.priority,
            value_hash=_value_hash(value),
            observed_at=now,
            updated_at=now,
        )
        db.add(ownership)
    else:
        ownership.source_id = source.id
        ownership.external_id = external_id
        ownership.source_priority = source.priority
        ownership.value_hash = _value_hash(value)
        ownership.observed_at = now
        ownership.updated_at = now


def _set_source_identity(
    db: Session,
    *,
    source: CMDBSource,
    asset: Asset,
    external_id: str,
    now: datetime,
) -> None:
    identity = db.scalar(
        select(CMDBSourceIdentity).where(
            CMDBSourceIdentity.source_id == source.id,
            CMDBSourceIdentity.external_id == external_id,
        )
    )
    if identity is None:
        db.add(
            CMDBSourceIdentity(
                id=str(uuid.uuid4()),
                tenant_id=source.tenant_id,
                source_id=source.id,
                external_id=external_id,
                asset_id=asset.id,
                first_seen_at=now,
                last_seen_at=now,
                discovery_state="ACTIVE",
                missing_run_count=0,
                first_missing_at=None,
                last_missing_at=None,
                updated_at=now,
            )
        )
        return
    if identity.asset_id != asset.id:
        raise ReconciliationConflict(
            "source identity is already bound to another configuration item"
        )
    identity.last_seen_at = now
    identity.discovery_state = "ACTIVE"
    identity.missing_run_count = 0
    identity.first_missing_at = None
    identity.last_missing_at = None
    identity.updated_at = now


def _default_owner(db: Session, tenant_id: str) -> User | None:
    return db.scalar(
        select(User)
        .where(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            User.is_root.is_(False),
        )
        .order_by(User.created_at, User.id)
    )


def _apply_field(asset: Asset, field_name: str, value: Any) -> None:
    if field_name.startswith("attributes."):
        attributes = _attributes(asset)
        attributes[field_name.split(".", 1)[1]] = value
        asset.ci_attributes_json = canonical_json(attributes)
        return
    if field_name == "purchase_date":
        value = _parse_datetime(value)
    elif field_name in {
        "purchase_cost",
        "current_cost",
        "depreciation_amount",
        "residual_value",
    }:
        value = float(value) if value is not None else None
    elif field_name == "purchase_year":
        value = int(value) if value is not None else None
    setattr(asset, field_name, value)
    if field_name == "lifecycle_status" and value:
        asset.status = LIFECYCLE_TO_ASSET_STATUS[str(value)]


def _create_asset(
    db: Session,
    *,
    source: CMDBSource,
    run: CMDBReconciliationRun,
    record: CMDBReconciliationRecord,
    normalized: dict[str, Any],
    actor_id: str,
) -> tuple[Asset | None, list[str]]:
    class_id = normalized.get("_ci_class_id")
    published = _published_class(db, source.tenant_id, class_id)
    if published is None:
        return None, ["published_ci_class_required"]
    ci_class, version = published
    attributes, attribute_errors = validate_attributes(
        _effective_schema(db, version),
        normalized.get("attributes") or {},
    )
    if attribute_errors:
        return None, [
            f"attributes.{key}: {message}"
            for key, messages in attribute_errors.items()
            for message in messages
        ]
    asset_tag = normalized.get("asset_tag")
    if not asset_tag:
        digest = hashlib.sha256(
            f"{source.tenant_id}:{source.id}:{record.external_id}".encode()
        ).hexdigest()[:10].upper()
        asset_tag = f"SRC-{source.code[:14]}-{digest}"[:32]
    if db.scalar(select(Asset.id).where(Asset.asset_tag == asset_tag)):
        return None, ["asset_tag_already_exists"]
    owner = (
        db.get(User, normalized.get("owner_user_id"))
        if normalized.get("owner_user_id")
        else _default_owner(db, source.tenant_id)
    )
    lifecycle = normalized.get("lifecycle_status") or "ACTIVE"
    now = _now()
    asset = Asset(
        id=str(uuid.uuid4()),
        tenant_id=source.tenant_id,
        ci_class_id=ci_class.id,
        ci_class_version_id=version.id,
        ci_class_code=ci_class.code,
        ci_class_name=ci_class.name,
        ci_schema_version=version.version,
        ci_schema_hash=version.schema_hash,
        ci_attributes_json=canonical_json(attributes),
        lifecycle_status=lifecycle,
        owner_user_id=owner.id if owner else None,
        support_group=normalized.get("support_group") or "Service Desk",
        criticality=normalized.get("criticality") or "MEDIUM",
        environment=normalized.get("environment") or "OTHER",
        ci_version=1,
        asset_tag=asset_tag,
        name=normalized["name"],
        asset_type=ci_class.code,
        type=ci_class.code,
        serial_number=normalized.get("serial_number"),
        inventory_number=normalized.get("inventory_number"),
        source=_source_marker(source),
        source_batch_id=run.id,
        original_type=normalized.get("original_type"),
        manufacturer=normalized.get("manufacturer"),
        model=normalized.get("model"),
        status=LIFECYCLE_TO_ASSET_STATUS[lifecycle],
        owner_name=owner.full_name if owner else "Unassigned",
        assigned_to_name=normalized.get("assigned_to_name"),
        location=normalized.get("location") or "Location unknown",
        purchase_date=_parse_datetime(normalized.get("purchase_date")),
        purchase_cost=normalized.get("purchase_cost"),
        current_cost=normalized.get("current_cost"),
        depreciation_amount=normalized.get("depreciation_amount"),
        residual_value=normalized.get("residual_value"),
        purchase_year=normalized.get("purchase_year"),
        verification_status=normalized.get("verification_status"),
        condition=normalized.get("condition") or "good",
        description=normalized.get("description"),
        imported_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(asset)
    db.flush()
    _set_source_identity(
        db,
        source=source,
        asset=asset,
        external_id=record.external_id,
        now=now,
    )
    for field_name in _incoming_authoritative_fields(source, normalized):
        _set_ownership(
            db,
            source=source,
            asset=asset,
            external_id=record.external_id,
            field_name=field_name,
            value=_record_value(normalized, field_name),
            now=now,
        )
    db.add(
        AssetHistory(
            id=str(uuid.uuid4()),
            asset_id=asset.id,
            actor_id=actor_id,
            action="ci_reconciliation_created",
            old_value=None,
            new_value={
                "source_id": source.id,
                "source_code": source.code,
                "run_id": run.id,
                "external_id": record.external_id,
                "class": ci_class.code,
                "schema_hash": version.schema_hash,
            },
            comment="CI created by governed reconciliation",
            created_at=now,
        )
    )
    return asset, []


def _apply_update(
    db: Session,
    *,
    source: CMDBSource,
    run: CMDBReconciliationRun,
    record: CMDBReconciliationRecord,
    normalized: dict[str, Any],
    actor_id: str,
) -> tuple[Asset | None, list[str], list[str], list[str]]:
    statement = select(Asset).where(Asset.id == record.matched_ci_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    asset = db.scalar(statement)
    if asset is None or asset.tenant_id != source.tenant_id:
        return None, ["matched_ci_unavailable"], [], []
    ownership_rows = db.scalars(
        select(CMDBFieldOwnership).where(
            CMDBFieldOwnership.asset_id == asset.id
        )
    ).all()
    ownership = {item.field_name: item for item in ownership_rows}
    changed, blocked, _ = _plan_changes(
        asset,
        source,
        record.external_id,
        normalized,
        ownership,
    )
    if not changed:
        return asset, [], blocked, []
    version = db.get(ConfigurationItemClassVersion, asset.ci_class_version_id)
    if version is None:
        return None, ["ci_schema_snapshot_unavailable"], blocked, []
    candidate_attributes = _attributes(asset)
    for field_name in changed:
        if field_name.startswith("attributes."):
            candidate_attributes[field_name.split(".", 1)[1]] = _record_value(
                normalized,
                field_name,
            )
    _, attribute_errors = validate_attributes(
        _effective_schema(db, version),
        candidate_attributes,
    )
    if attribute_errors:
        return None, [
            f"attributes.{key}: {message}"
            for key, messages in attribute_errors.items()
            for message in messages
        ], blocked, []
    before = {
        field_name: _asset_value(asset, field_name)
        for field_name in changed
    }
    now = _now()
    _set_source_identity(
        db,
        source=source,
        asset=asset,
        external_id=record.external_id,
        now=now,
    )
    for field_name in changed:
        incoming = _record_value(normalized, field_name)
        _apply_field(asset, field_name, incoming)
        if field_name == "owner_user_id" and incoming:
            owner = db.get(User, incoming)
            if owner is not None:
                asset.owner_name = owner.full_name
        _set_ownership(
            db,
            source=source,
            asset=asset,
            external_id=record.external_id,
            field_name=field_name,
            value=incoming,
            now=now,
        )
    asset.source_batch_id = run.id
    asset.imported_at = now
    asset.ci_version += 1
    asset.updated_at = now
    db.add(
        AssetHistory(
            id=str(uuid.uuid4()),
            asset_id=asset.id,
            actor_id=actor_id,
            action="ci_reconciliation_updated",
            old_value=jsonable_encoder(before),
            new_value=jsonable_encoder(
                {
                    field_name: _asset_value(asset, field_name)
                    for field_name in changed
                }
            ),
            comment=(
                f"Source {source.code}; run {run.id}; "
                f"blocked fields: {', '.join(blocked) or 'none'}"
            ),
            created_at=now,
        )
    )
    return asset, [], blocked, changed


def apply_reconciliation(
    db: Session,
    *,
    run_id: str,
    actor_id: str,
) -> CMDBReconciliationRun:
    statement = select(CMDBReconciliationRun).where(
        CMDBReconciliationRun.id == run_id
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    run = db.scalar(statement)
    if run is None:
        raise ValueError("CMDB reconciliation run not found")
    if run.status in {"COMPLETED", "COMPLETED_WITH_ERRORS"}:
        return run
    if run.status != "PREVIEWED":
        raise ReconciliationConflict("Only a previewed reconciliation run can apply")
    if run.invalid_count or run.ambiguous_count:
        raise ReconciliationConflict(
            "Reconciliation run contains invalid or ambiguous records; "
            "correct the source data and create a new preview"
        )
    source = db.get(CMDBSource, run.source_id)
    if source is None or source.status != "ACTIVE":
        raise ReconciliationConflict("CMDB source is unavailable or inactive")
    run.mode = "APPLY"
    run.status = "RUNNING"
    run.started_at = _now()
    run.completed_at = None
    errors_count = 0
    applied_created = 0
    applied_updated = 0
    records = db.scalars(
        select(CMDBReconciliationRecord)
        .where(CMDBReconciliationRecord.run_id == run.id)
        .order_by(CMDBReconciliationRecord.row_number)
    ).all()
    for record in records:
        normalized = _json_dict(record.normalized_json)
        if record.outcome == "CREATE":
            asset, errors = _create_asset(
                db,
                source=source,
                run=run,
                record=record,
                normalized=normalized,
                actor_id=actor_id,
            )
            if errors or asset is None:
                record.outcome = "INVALID"
                record.errors_json = canonical_json(errors)
                errors_count += 1
            else:
                record.outcome = "APPLIED_CREATED"
                record.matched_ci_id = asset.id
                record.applied_at = _now()
                applied_created += 1
        elif record.outcome == "UPDATE":
            asset, errors, blocked, changed = _apply_update(
                db,
                source=source,
                run=run,
                record=record,
                normalized=normalized,
                actor_id=actor_id,
            )
            if errors or asset is None:
                record.outcome = "INVALID"
                record.errors_json = canonical_json(errors)
                errors_count += 1
            elif not changed:
                _set_source_identity(
                    db,
                    source=source,
                    asset=asset,
                    external_id=record.external_id,
                    now=_now(),
                )
                record.outcome = "UNCHANGED"
                record.applied_at = _now()
            else:
                record.outcome = "APPLIED_UPDATED"
                normalized["_blocked_fields_at_apply"] = blocked
                record.normalized_json = canonical_json(normalized)
                record.applied_at = _now()
                applied_updated += 1
        elif record.outcome in {"UNCHANGED", "SKIPPED"} and record.matched_ci_id:
            asset = db.get(Asset, record.matched_ci_id)
            if asset is not None and asset.tenant_id == source.tenant_id:
                _set_source_identity(
                    db,
                    source=source,
                    asset=asset,
                    external_id=record.external_id,
                    now=_now(),
                )
            record.applied_at = _now()
        else:
            record.applied_at = _now()
    run.create_count = applied_created
    run.update_count = applied_updated
    run.invalid_count += errors_count
    run.status = "COMPLETED_WITH_ERRORS" if errors_count else "COMPLETED"
    run.completed_at = _now()
    run.updated_at = run.completed_at
    summary = _summary(run)
    summary["applied_created"] = applied_created
    summary["applied_updated"] = applied_updated
    summary["apply_errors"] = errors_count
    run.summary_json = canonical_json(summary)
    source.last_run_at = run.completed_at
    if not errors_count:
        source.last_success_at = run.completed_at
    source.updated_at = run.completed_at
    db.flush()
    return run


def dismiss_duplicate_candidate(
    db: Session,
    *,
    candidate_id: str,
    expected_version: int,
    actor_id: str,
    reason: str,
) -> CIDuplicateCandidate:
    statement = select(CIDuplicateCandidate).where(
        CIDuplicateCandidate.id == candidate_id
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    candidate = db.scalar(statement)
    if candidate is None:
        raise ValueError("CI duplicate candidate not found")
    if candidate.status != "OPEN":
        raise ReconciliationConflict("CI duplicate candidate is already resolved")
    if candidate.version != expected_version:
        raise ReconciliationConflict(
            f"CI duplicate candidate changed; current version is {candidate.version}"
        )
    now = _now()
    candidate.status = "DISMISSED"
    candidate.version += 1
    candidate.resolution_reason = reason.strip()
    candidate.resolved_by_id = actor_id
    candidate.resolved_at = now
    candidate.updated_at = now
    db.flush()
    return candidate


def _rewire_unique_links(
    db: Session,
    *,
    model: type[ChangeAssetLink] | type[ProblemAssetLink],
    grouping_field: str,
    primary_id: str,
    duplicate_id: str,
) -> tuple[int, int]:
    asset_column = getattr(model, "asset_id")
    group_column = getattr(model, grouping_field)
    primary_groups = set(
        db.scalars(
            select(group_column).where(asset_column == primary_id)
        ).all()
    )
    rewired = 0
    collapsed = 0
    for link in db.scalars(
        select(model).where(asset_column == duplicate_id)
    ).all():
        group_value = getattr(link, grouping_field)
        if group_value in primary_groups:
            db.delete(link)
            collapsed += 1
        else:
            link.asset_id = primary_id
            primary_groups.add(group_value)
            rewired += 1
    return rewired, collapsed


def _rewire_relationships(
    db: Session,
    *,
    primary_id: str,
    duplicate_id: str,
    actor_id: str,
    now: datetime,
) -> tuple[int, int]:
    rewired = 0
    retired = 0
    relationships = db.scalars(
        select(ConfigurationItemRelationship).where(
            ConfigurationItemRelationship.status == "ACTIVE",
            or_(
                ConfigurationItemRelationship.source_ci_id == duplicate_id,
                ConfigurationItemRelationship.target_ci_id == duplicate_id,
            ),
        )
    ).all()
    for relationship in relationships:
        source_id = (
            primary_id
            if relationship.source_ci_id == duplicate_id
            else relationship.source_ci_id
        )
        target_id = (
            primary_id
            if relationship.target_ci_id == duplicate_id
            else relationship.target_ci_id
        )
        existing = None
        cardinality_conflict = False
        cycle_conflict = False
        if source_id != target_id:
            existing = db.scalar(
                select(ConfigurationItemRelationship.id).where(
                    ConfigurationItemRelationship.id != relationship.id,
                    ConfigurationItemRelationship.relationship_type_id
                    == relationship.relationship_type_id,
                    ConfigurationItemRelationship.source_ci_id == source_id,
                    ConfigurationItemRelationship.target_ci_id == target_id,
                    ConfigurationItemRelationship.status == "ACTIVE",
                )
            )
            relationship_type = db.get(
                ConfigurationItemRelationshipType,
                relationship.relationship_type_id,
            )
            if relationship_type is None:
                cardinality_conflict = True
            elif relationship_type.source_cardinality == "ONE":
                cardinality_conflict = bool(
                    db.scalar(
                        select(ConfigurationItemRelationship.id).where(
                            ConfigurationItemRelationship.id
                            != relationship.id,
                            ConfigurationItemRelationship.relationship_type_id
                            == relationship.relationship_type_id,
                            ConfigurationItemRelationship.source_ci_id
                            == source_id,
                            ConfigurationItemRelationship.status == "ACTIVE",
                        )
                    )
                )
            if (
                relationship_type is not None
                and relationship_type.target_cardinality == "ONE"
            ):
                cardinality_conflict = cardinality_conflict or bool(
                    db.scalar(
                        select(ConfigurationItemRelationship.id).where(
                            ConfigurationItemRelationship.id
                            != relationship.id,
                            ConfigurationItemRelationship.relationship_type_id
                            == relationship.relationship_type_id,
                            ConfigurationItemRelationship.target_ci_id
                            == target_id,
                            ConfigurationItemRelationship.status == "ACTIVE",
                        )
                    )
                )
            if (
                relationship_type is not None
                and not relationship_type.allow_cycles
                and not cardinality_conflict
                and not existing
            ):
                visited = {target_id}
                frontier = {target_id}
                while frontier and source_id not in visited:
                    next_frontier = set(
                        db.scalars(
                            select(
                                ConfigurationItemRelationship.target_ci_id
                            ).where(
                                ConfigurationItemRelationship.id
                                != relationship.id,
                                ConfigurationItemRelationship.relationship_type_id
                                == relationship.relationship_type_id,
                                ConfigurationItemRelationship.source_ci_id.in_(
                                    frontier
                                ),
                                ConfigurationItemRelationship.status
                                == "ACTIVE",
                            )
                        ).all()
                    ) - visited
                    visited.update(next_frontier)
                    frontier = next_frontier
                cycle_conflict = source_id in visited
        if (
            source_id == target_id
            or existing
            or cardinality_conflict
            or cycle_conflict
        ):
            relationship.status = "RETIRED"
            relationship.version += 1
            relationship.retired_by_id = actor_id
            relationship.retired_at = now
            relationship.updated_at = now
            suffix = (
                "Retired during governed CI duplicate merge "
                "to preserve relationship constraints."
            )
            relationship.description = (
                f"{relationship.description}\n{suffix}"
                if relationship.description
                else suffix
            )
            retired += 1
            continue
        relationship.source_ci_id = source_id
        relationship.target_ci_id = target_id
        relationship.version += 1
        relationship.updated_at = now
        rewired += 1
    return rewired, retired


def merge_duplicate_candidate(
    db: Session,
    *,
    candidate_id: str,
    expected_version: int,
    expected_primary_version: int,
    expected_duplicate_version: int,
    actor_id: str,
    reason: str,
) -> tuple[CIDuplicateCandidate, dict[str, int]]:
    candidate_statement = select(CIDuplicateCandidate).where(
        CIDuplicateCandidate.id == candidate_id
    )
    if db.get_bind().dialect.name == "postgresql":
        candidate_statement = candidate_statement.with_for_update()
    candidate = db.scalar(candidate_statement)
    if candidate is None:
        raise ValueError("CI duplicate candidate not found")
    if candidate.status != "OPEN":
        raise ReconciliationConflict("CI duplicate candidate is already resolved")
    if candidate.version != expected_version:
        raise ReconciliationConflict(
            f"CI duplicate candidate changed; current version is {candidate.version}"
        )

    asset_statement = (
        select(Asset)
        .where(
            Asset.id.in_(
                [candidate.primary_ci_id, candidate.duplicate_ci_id]
            )
        )
        .order_by(Asset.id)
    )
    if db.get_bind().dialect.name == "postgresql":
        asset_statement = asset_statement.with_for_update()
    assets = {item.id: item for item in db.scalars(asset_statement).all()}
    primary = assets.get(candidate.primary_ci_id)
    duplicate = assets.get(candidate.duplicate_ci_id)
    if primary is None or duplicate is None:
        raise ReconciliationConflict("One of the duplicate CIs is unavailable")
    if (
        primary.tenant_id != candidate.tenant_id
        or duplicate.tenant_id != candidate.tenant_id
    ):
        raise ReconciliationConflict("CI duplicate candidate tenant mismatch")
    if primary.ci_version != expected_primary_version:
        raise ReconciliationConflict(
            f"Primary CI changed; current version is {primary.ci_version}"
        )
    if duplicate.ci_version != expected_duplicate_version:
        raise ReconciliationConflict(
            f"Duplicate CI changed; current version is {duplicate.ci_version}"
        )
    if duplicate.lifecycle_status in {"RETIRED", "DISPOSED"}:
        raise ReconciliationConflict("Duplicate CI is already retired")

    now = _now()
    copied_fields = 0
    mergeable_fields = (
        "serial_number",
        "inventory_number",
        "manufacturer",
        "model",
        "owner_user_id",
        "support_group",
        "location",
        "assigned_to_name",
        "purchase_date",
        "purchase_cost",
        "current_cost",
        "depreciation_amount",
        "residual_value",
        "purchase_year",
        "verification_status",
        "description",
    )
    for field_name in mergeable_fields:
        primary_value = getattr(primary, field_name)
        duplicate_value = getattr(duplicate, field_name)
        if _is_empty(primary_value) and not _is_empty(duplicate_value):
            setattr(primary, field_name, duplicate_value)
            copied_fields += 1
    primary_attributes = _attributes(primary)
    for key, value in _attributes(duplicate).items():
        if _is_empty(primary_attributes.get(key)) and not _is_empty(value):
            primary_attributes[key] = value
            copied_fields += 1
    primary.ci_attributes_json = canonical_json(primary_attributes)
    if primary.owner_user_id:
        owner = db.get(User, primary.owner_user_id)
        if owner is not None:
            primary.owner_name = owner.full_name

    ticket_count = 0
    for ticket in db.scalars(
        select(Ticket).where(Ticket.asset_id == duplicate.id)
    ).all():
        ticket.asset_id = primary.id
        ticket.updated_at = now
        ticket_count += 1
    assignment_count = 0
    for assignment in db.scalars(
        select(AssetAssignment).where(
            AssetAssignment.asset_id == duplicate.id
        )
    ).all():
        assignment.asset_id = primary.id
        assignment_count += 1
    suggestion_count = 0
    for suggestion in db.scalars(
        select(AiSuggestion).where(AiSuggestion.asset_id == duplicate.id)
    ).all():
        suggestion.asset_id = primary.id
        suggestion_count += 1
    import_row_count = 0
    for import_row in db.scalars(
        select(AssetImportRow).where(AssetImportRow.asset_id == duplicate.id)
    ).all():
        import_row.asset_id = primary.id
        import_row_count += 1
    article_count = 0
    for article in db.scalars(
        select(KnowledgeArticle).where(
            KnowledgeArticle.source_asset_id == duplicate.id
        )
    ).all():
        article.source_asset_id = primary.id
        article.updated_at = now
        article_count += 1

    change_rewired, change_collapsed = _rewire_unique_links(
        db,
        model=ChangeAssetLink,
        grouping_field="change_id",
        primary_id=primary.id,
        duplicate_id=duplicate.id,
    )
    problem_rewired, problem_collapsed = _rewire_unique_links(
        db,
        model=ProblemAssetLink,
        grouping_field="problem_id",
        primary_id=primary.id,
        duplicate_id=duplicate.id,
    )
    relationship_rewired, relationship_retired = _rewire_relationships(
        db,
        primary_id=primary.id,
        duplicate_id=duplicate.id,
        actor_id=actor_id,
        now=now,
    )

    primary_ownership = {
        item.field_name: item
        for item in db.scalars(
            select(CMDBFieldOwnership).where(
                CMDBFieldOwnership.asset_id == primary.id
            )
        ).all()
    }
    ownership_rewired = 0
    ownership_collapsed = 0
    for ownership in db.scalars(
        select(CMDBFieldOwnership).where(
            CMDBFieldOwnership.asset_id == duplicate.id
        )
    ).all():
        existing = primary_ownership.get(ownership.field_name)
        if existing is None:
            ownership.asset_id = primary.id
            primary_ownership[ownership.field_name] = ownership
            ownership_rewired += 1
        else:
            if ownership.source_priority < existing.source_priority:
                existing.source_id = ownership.source_id
                existing.external_id = ownership.external_id
                existing.source_priority = ownership.source_priority
                existing.value_hash = ownership.value_hash
                existing.observed_at = ownership.observed_at
                existing.updated_at = now
            db.delete(ownership)
            ownership_collapsed += 1
    identity_count = 0
    for identity in db.scalars(
        select(CMDBSourceIdentity).where(
            CMDBSourceIdentity.asset_id == duplicate.id
        )
    ).all():
        identity.asset_id = primary.id
        identity.updated_at = now
        identity_count += 1
    record_count = 0
    for record in db.scalars(
        select(CMDBReconciliationRecord).where(
            CMDBReconciliationRecord.matched_ci_id == duplicate.id
        )
    ).all():
        record.matched_ci_id = primary.id
        record_count += 1

    for other in db.scalars(
        select(CIDuplicateCandidate).where(
            CIDuplicateCandidate.id != candidate.id,
            CIDuplicateCandidate.status == "OPEN",
            or_(
                CIDuplicateCandidate.primary_ci_id == duplicate.id,
                CIDuplicateCandidate.duplicate_ci_id == duplicate.id,
            ),
        )
    ).all():
        other.status = "DISMISSED"
        other.version += 1
        other.resolution_reason = (
            f"Automatically resolved by merge candidate {candidate.id}"
        )
        other.resolved_by_id = actor_id
        other.resolved_at = now
        other.updated_at = now

    before_duplicate = {
        "lifecycle_status": duplicate.lifecycle_status,
        "status": duplicate.status,
        "ci_version": duplicate.ci_version,
    }
    primary.ci_version += 1
    primary.updated_at = now
    duplicate.lifecycle_status = "RETIRED"
    duplicate.status = "inactive"
    duplicate.ci_version += 1
    duplicate.updated_at = now
    duplicate.description = (
        f"{duplicate.description}\n" if duplicate.description else ""
    ) + f"Merged into CI {primary.id}: {reason.strip()}"
    db.add_all(
        [
            AssetHistory(
                id=str(uuid.uuid4()),
                asset_id=primary.id,
                actor_id=actor_id,
                action="ci_duplicate_absorbed",
                old_value={"ci_version": expected_primary_version},
                new_value={
                    "duplicate_ci_id": duplicate.id,
                    "copied_fields": copied_fields,
                    "ci_version": primary.ci_version,
                },
                comment=reason.strip(),
                created_at=now,
            ),
            AssetHistory(
                id=str(uuid.uuid4()),
                asset_id=duplicate.id,
                actor_id=actor_id,
                action="ci_duplicate_merged",
                old_value=before_duplicate,
                new_value={
                    "primary_ci_id": primary.id,
                    "lifecycle_status": duplicate.lifecycle_status,
                    "status": duplicate.status,
                    "ci_version": duplicate.ci_version,
                },
                comment=reason.strip(),
                created_at=now,
            ),
        ]
    )
    candidate.status = "MERGED"
    candidate.version += 1
    candidate.resolution_reason = reason.strip()
    candidate.resolved_by_id = actor_id
    candidate.resolved_at = now
    candidate.updated_at = now
    summary = {
        "copied_fields": copied_fields,
        "tickets_rewired": ticket_count,
        "assignments_rewired": assignment_count,
        "suggestions_rewired": suggestion_count,
        "import_rows_rewired": import_row_count,
        "articles_rewired": article_count,
        "change_links_rewired": change_rewired,
        "change_links_collapsed": change_collapsed,
        "problem_links_rewired": problem_rewired,
        "problem_links_collapsed": problem_collapsed,
        "relationships_rewired": relationship_rewired,
        "relationships_retired": relationship_retired,
        "ownership_rewired": ownership_rewired,
        "ownership_collapsed": ownership_collapsed,
        "source_identities_rewired": identity_count,
        "reconciliation_records_rewired": record_count,
    }
    db.flush()
    return candidate, summary
