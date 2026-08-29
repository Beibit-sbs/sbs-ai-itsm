from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.custom_fields import (
    CustomFieldSet,
    CustomFieldSetVersion,
    CustomFieldValue,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.catalog_forms import canonical_json
from app.services.custom_fields import (
    CUSTOM_FIELD_ENTITY_TYPES,
    CUSTOM_FIELD_TYPE_CATALOG,
    compare_schema_compatibility,
    create_field_set,
    create_field_set_draft,
    custom_field_values_response,
    get_entity,
    is_field_set_applicable,
    publish_field_set_version,
    save_custom_field_values,
    schema_hash,
    update_field_set_draft,
    validate_applicability,
    validate_custom_field_schema,
)
from app.services.rbac import has_permission, is_saas_root, require_permissions


router = APIRouter(prefix="/custom-fields")


class FieldSetCreate(BaseModel):
    tenant_id: str | None = None
    code: str = Field(min_length=3, max_length=120)
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    entity_type: Literal["ticket", "asset", "change", "problem", "request"]
    applicability: dict[str, Any] = Field(default_factory=lambda: {"all": []})


class FieldSetUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    status: Literal["ACTIVE", "PAUSED", "ARCHIVED"] | None = None
    applicability: dict[str, Any] | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class DraftCreate(BaseModel):
    expected_field_set_revision: int = Field(ge=1)
    change_summary: str = Field(min_length=3, max_length=2_000)


class DraftUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    schema_definition: dict[str, Any]
    change_summary: str = Field(min_length=3, max_length=2_000)


class PublishRequest(BaseModel):
    expected_field_set_revision: int = Field(ge=1)
    expected_version_revision: int = Field(ge=1)
    allow_breaking_changes: bool = False
    reason: str = Field(min_length=3, max_length=2_000)


class ValuesUpdate(BaseModel):
    values: dict[str, Any]
    expected_version: int | None = Field(default=None, ge=0)


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tenant_id(
    db: Session,
    current_user: AuthUserResponse,
    requested: str | None,
) -> str:
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        if requested and requested != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return current_user.tenant_id
    if not requested:
        raise HTTPException(
            status_code=422,
            detail="tenant_id is required for SaaS Root custom-field administration",
        )
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _scope(current_user: AuthUserResponse, tenant_id: str) -> None:
    if not is_saas_root(current_user) and current_user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Custom-field resource not found")


def _field_set(
    db: Session,
    field_set_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> CustomFieldSet:
    statement = select(CustomFieldSet).where(CustomFieldSet.id == field_set_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Custom-field set not found")
    _scope(current_user, item.tenant_id)
    return item


def _version(
    db: Session,
    field_set: CustomFieldSet,
    version_number: int,
    *,
    lock: bool = False,
) -> CustomFieldSetVersion:
    statement = select(CustomFieldSetVersion).where(
        CustomFieldSetVersion.field_set_id == field_set.id,
        CustomFieldSetVersion.version_number == version_number,
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Custom-field version not found",
        )
    return item


def _audit(
    db: Session,
    request: Request,
    current_user: AuthUserResponse,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    tenant_id: str,
    metadata: dict[str, object],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user=db.get(User, current_user.id),
        actor_email=current_user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _field_set_response(item: CustomFieldSet) -> dict[str, object]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "entity_type": item.entity_type,
        "status": item.status,
        "applicability": _json_object(item.applicability_json),
        "latest_version_number": item.latest_version_number,
        "draft_version_number": item.draft_version_number,
        "published_version_number": item.published_version_number,
        "revision": item.revision,
        "created_by_id": item.created_by_id,
        "updated_by_id": item.updated_by_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _version_response(
    item: CustomFieldSetVersion,
    *,
    include_schema: bool = True,
) -> dict[str, object]:
    schema = _json_object(item.schema_json)
    result: dict[str, object] = {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "field_set_id": item.field_set_id,
        "version_number": item.version_number,
        "status": item.status,
        "schema_sha256": item.schema_sha256,
        "integrity_valid": schema_hash(schema) == item.schema_sha256,
        "validation_status": item.validation_status,
        "validation": _json_object(item.validation_json),
        "revision": item.revision,
        "based_on_version_number": item.based_on_version_number,
        "change_summary": item.change_summary,
        "breaking_change": item.breaking_change,
        "created_by_id": item.created_by_id,
        "updated_by_id": item.updated_by_id,
        "published_by_id": item.published_by_id,
        "published_at": item.published_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    if include_schema:
        result["schema_definition"] = schema
    return result


def _value_schema(
    db: Session,
    value: CustomFieldValue,
) -> tuple[CustomFieldSetVersion, dict[str, Any]]:
    version = db.get(CustomFieldSetVersion, value.field_set_version_id)
    if version is None or version.field_set_id != value.field_set_id:
        raise HTTPException(
            status_code=409,
            detail="Bound custom-field schema version is unavailable",
        )
    schema = _json_object(version.schema_json)
    if schema_hash(schema) != version.schema_sha256:
        raise HTTPException(
            status_code=409,
            detail="Bound custom-field schema failed integrity verification",
        )
    return version, schema


def _conflict(exc: ValueError) -> HTTPException:
    message = str(exc)
    invalid_markers = (
        "invalid",
        "unsupported",
        "must ",
        "required",
        "validation",
        "field_errors",
    )
    code = 422 if any(marker in message.lower() for marker in invalid_markers) else 409
    return HTTPException(status_code=code, detail=message)


@router.get("/catalog")
def get_custom_field_catalog(
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.read")
    return {
        "schema_version": "1.0",
        "entity_types": sorted(CUSTOM_FIELD_ENTITY_TYPES),
        "field_types": CUSTOM_FIELD_TYPE_CATALOG,
        "field_capabilities": [
            "required",
            "visibility_rules",
            "validations",
            "default",
            "searchable",
            "indexed",
            "reportable",
            "sensitive",
            "immutable_after_set",
        ],
        "applicability_operators": ["eq", "neq", "in"],
        "limits": {
            "fields_per_set": 50,
            "searchable_fields_per_set": 20,
            "indexed_fields_per_set": 10,
            "applicability_conditions": 10,
        },
    }


@router.get("/dashboard")
def get_custom_fields_dashboard(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    set_counts = dict(
        db.execute(
            select(CustomFieldSet.status, func.count())
            .where(CustomFieldSet.tenant_id == scoped_tenant)
            .group_by(CustomFieldSet.status)
        ).all()
    )
    entity_counts = dict(
        db.execute(
            select(CustomFieldSet.entity_type, func.count())
            .where(CustomFieldSet.tenant_id == scoped_tenant)
            .group_by(CustomFieldSet.entity_type)
        ).all()
    )
    value_count = int(
        db.scalar(
            select(func.count())
            .select_from(CustomFieldValue)
            .where(CustomFieldValue.tenant_id == scoped_tenant)
        )
        or 0
    )
    invalid_drafts = int(
        db.scalar(
            select(func.count())
            .select_from(CustomFieldSetVersion)
            .where(
                CustomFieldSetVersion.tenant_id == scoped_tenant,
                CustomFieldSetVersion.status == "DRAFT",
                CustomFieldSetVersion.validation_status == "INVALID",
            )
        )
        or 0
    )
    return {
        "tenant_id": scoped_tenant,
        "field_sets": {
            "total": sum(set_counts.values()),
            "by_status": set_counts,
            "by_entity_type": entity_counts,
        },
        "stored_value_records": value_count,
        "invalid_drafts": invalid_drafts,
        "generated_at": datetime.now(UTC),
    }


@router.get("")
def list_field_sets(
    tenant_id: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "custom_fields.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(CustomFieldSet).where(CustomFieldSet.tenant_id == scoped_tenant)
    if entity_type:
        normalized_entity = entity_type.strip().lower()
        if normalized_entity not in CUSTOM_FIELD_ENTITY_TYPES:
            raise HTTPException(status_code=422, detail="Unsupported entity_type")
        statement = statement.where(CustomFieldSet.entity_type == normalized_entity)
    if status_filter:
        statement = statement.where(CustomFieldSet.status == status_filter.strip().upper())
    items = db.scalars(statement.order_by(CustomFieldSet.updated_at.desc())).all()
    return [_field_set_response(item) for item in items]


@router.post("", status_code=status.HTTP_201_CREATED)
def add_field_set(
    payload: FieldSetCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.design")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    try:
        item, draft = create_field_set(
            db,
            tenant_id=tenant_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            entity_type=payload.entity_type,
            applicability=payload.applicability,
            actor_id=current_user.id,
        )
        _audit(
            db,
            request,
            current_user,
            action="custom_field_set_created",
            entity_type="custom_field_set",
            entity_id=item.id,
            tenant_id=tenant_id,
            metadata={
                "code": item.code,
                "target_entity_type": item.entity_type,
                "draft_version": draft.version_number,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Custom-field set code already exists in this tenant",
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    db.refresh(item)
    db.refresh(draft)
    return {
        "field_set": _field_set_response(item),
        "draft": _version_response(draft),
    }


@router.get("/search")
def search_custom_field_values(
    query: str = Query(min_length=2, max_length=200),
    tenant_id: str | None = Query(default=None),
    entity_type: Literal["ticket", "asset", "change", "problem", "request"] | None = Query(
        default=None
    ),
    field_set_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "custom_fields.search")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = (
        select(CustomFieldValue, CustomFieldSet)
        .join(CustomFieldSet, CustomFieldSet.id == CustomFieldValue.field_set_id)
        .where(
            CustomFieldValue.tenant_id == scoped_tenant,
            CustomFieldValue.search_text.contains(
                query.casefold(),
                autoescape=True,
            ),
        )
    )
    if entity_type:
        statement = statement.where(CustomFieldValue.entity_type == entity_type)
    if field_set_id:
        statement = statement.where(CustomFieldValue.field_set_id == field_set_id)
    rows = db.execute(statement.order_by(CustomFieldValue.updated_at.desc()).limit(limit)).all()
    can_read_sensitive = has_permission(
        current_user,
        "custom_fields.sensitive.read",
    )
    settings = get_settings() if can_read_sensitive else None
    results: list[dict[str, object]] = []
    for value, field_set in rows:
        _, schema = _value_schema(db, value)
        result = custom_field_values_response(
            value,
            schema,
            can_read_sensitive=can_read_sensitive,
            settings=settings,
        )
        results.append(
            {
                "field_set": _field_set_response(field_set),
                "value_record": result,
            }
        )
    return results


@router.get("/reports/data")
def get_custom_field_report_data(
    tenant_id: str | None = Query(default=None),
    entity_type: Literal["ticket", "asset", "change", "problem", "request"] | None = Query(
        default=None
    ),
    field_set_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2_000),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.report")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = (
        select(CustomFieldValue, CustomFieldSet)
        .join(CustomFieldSet, CustomFieldSet.id == CustomFieldValue.field_set_id)
        .where(CustomFieldValue.tenant_id == scoped_tenant)
    )
    if entity_type:
        statement = statement.where(CustomFieldValue.entity_type == entity_type)
    if field_set_id:
        statement = statement.where(CustomFieldValue.field_set_id == field_set_id)
    rows = db.execute(statement.order_by(CustomFieldValue.updated_at.desc()).limit(limit)).all()
    can_read_sensitive = has_permission(
        current_user,
        "custom_fields.sensitive.read",
    )
    settings = get_settings() if can_read_sensitive else None
    data: list[dict[str, object]] = []
    for value, field_set in rows:
        _, schema = _value_schema(db, value)
        response = custom_field_values_response(
            value,
            schema,
            can_read_sensitive=can_read_sensitive,
            settings=settings,
        )
        reportable = {
            str(field.get("key"))
            for field in schema.get("fields", [])
            if isinstance(field, dict) and field.get("reportable")
        }
        report_values = {key: raw for key, raw in response["values"].items() if key in reportable}
        data.append(
            {
                "field_set_id": field_set.id,
                "field_set_code": field_set.code,
                "entity_type": value.entity_type,
                "entity_id": value.entity_id,
                "schema_version": value.field_set_version_number,
                "values": report_values,
                "updated_at": value.updated_at,
            }
        )
    return {
        "tenant_id": scoped_tenant,
        "rows": data,
        "count": len(data),
        "generated_at": datetime.now(UTC),
    }


@router.get("/entities/{entity_type}/{entity_id}/field-sets")
def list_entity_field_sets(
    entity_type: Literal["ticket", "asset", "change", "problem", "request"],
    entity_id: str,
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "custom_fields.values.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    try:
        entity = get_entity(
            db,
            tenant_id=scoped_tenant,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    field_sets = db.scalars(
        select(CustomFieldSet)
        .where(
            CustomFieldSet.tenant_id == scoped_tenant,
            CustomFieldSet.entity_type == entity_type,
            CustomFieldSet.status == "ACTIVE",
            CustomFieldSet.published_version_number.is_not(None),
        )
        .order_by(CustomFieldSet.name)
    ).all()
    values = {
        item.field_set_id: item
        for item in db.scalars(
            select(CustomFieldValue).where(
                CustomFieldValue.tenant_id == scoped_tenant,
                CustomFieldValue.entity_type == entity_type,
                CustomFieldValue.entity_id == entity_id,
            )
        ).all()
    }
    can_read_sensitive = has_permission(
        current_user,
        "custom_fields.sensitive.read",
    )
    settings = get_settings() if can_read_sensitive else None
    result: list[dict[str, object]] = []
    for field_set in field_sets:
        if not is_field_set_applicable(field_set, entity):
            continue
        published = _version(
            db,
            field_set,
            int(field_set.published_version_number),
        )
        value = values.get(field_set.id)
        value_response = None
        value_schema_current = True
        if value is not None:
            _, bound_schema = _value_schema(db, value)
            value_response = custom_field_values_response(
                value,
                bound_schema,
                can_read_sensitive=can_read_sensitive,
                settings=settings,
            )
            value_schema_current = value.field_set_version_number == published.version_number
        result.append(
            {
                "field_set": _field_set_response(field_set),
                "published_version": _version_response(published),
                "value_record": value_response,
                "value_schema_current": value_schema_current,
            }
        )
    return result


@router.get("/{field_set_id}")
def get_field_set(
    field_set_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.read")
    item = _field_set(db, field_set_id, current_user)
    versions = db.scalars(
        select(CustomFieldSetVersion)
        .where(CustomFieldSetVersion.field_set_id == item.id)
        .order_by(CustomFieldSetVersion.version_number.desc())
    ).all()
    return {
        "field_set": _field_set_response(item),
        "versions": [_version_response(version, include_schema=False) for version in versions],
    }


@router.patch("/{field_set_id}")
def update_field_set(
    field_set_id: str,
    payload: FieldSetUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.design")
    item = _field_set(db, field_set_id, current_user, lock=True)
    if item.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail=f"Custom-field set changed; current revision is {item.revision}",
        )
    if item.status == "ARCHIVED" and payload.status != "ARCHIVED":
        raise HTTPException(
            status_code=409,
            detail="Archived custom-field set cannot be reactivated",
        )
    if payload.status == "ACTIVE" and item.published_version_number is None:
        raise HTTPException(
            status_code=409,
            detail="Custom-field set requires a published version before activation",
        )
    before = {
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "applicability": _json_object(item.applicability_json),
    }
    if payload.name is not None:
        item.name = payload.name.strip()
    if payload.description is not None:
        item.description = payload.description.strip() or None
    if payload.applicability is not None:
        applicability_errors = validate_applicability(
            item.entity_type,
            payload.applicability,
        )
        if applicability_errors:
            raise HTTPException(
                status_code=422,
                detail="; ".join(applicability_errors),
            )
        item.applicability_json = canonical_json(payload.applicability)
    if payload.status is not None:
        item.status = payload.status
    item.revision += 1
    item.updated_by_id = current_user.id
    item.updated_at = datetime.now(UTC)
    _audit(
        db,
        request,
        current_user,
        action="custom_field_set_updated",
        entity_type="custom_field_set",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "reason": payload.reason,
            "before": before,
            "after_status": item.status,
            "revision": item.revision,
        },
    )
    db.commit()
    db.refresh(item)
    return _field_set_response(item)


@router.get("/{field_set_id}/versions")
def list_field_set_versions(
    field_set_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "custom_fields.read")
    item = _field_set(db, field_set_id, current_user)
    versions = db.scalars(
        select(CustomFieldSetVersion)
        .where(CustomFieldSetVersion.field_set_id == item.id)
        .order_by(CustomFieldSetVersion.version_number.desc())
    ).all()
    return [_version_response(version) for version in versions]


@router.get("/{field_set_id}/versions/compare")
def compare_field_set_versions(
    field_set_id: str,
    from_version: int = Query(ge=1),
    to_version: int = Query(ge=1),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.read")
    item = _field_set(db, field_set_id, current_user)
    source = _version(db, item, from_version)
    target = _version(db, item, to_version)
    return {
        "field_set_id": item.id,
        "from_version": from_version,
        "to_version": to_version,
        **compare_schema_compatibility(
            _json_object(source.schema_json),
            _json_object(target.schema_json),
        ),
    }


@router.get("/{field_set_id}/versions/{version_number}")
def get_field_set_version(
    field_set_id: str,
    version_number: int,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.read")
    item = _field_set(db, field_set_id, current_user)
    return _version_response(_version(db, item, version_number))


@router.post(
    "/{field_set_id}/drafts",
    status_code=status.HTTP_201_CREATED,
)
def add_field_set_draft(
    field_set_id: str,
    payload: DraftCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.design")
    item = _field_set(db, field_set_id, current_user, lock=True)
    if item.revision != payload.expected_field_set_revision:
        raise HTTPException(
            status_code=409,
            detail=f"Custom-field set changed; current revision is {item.revision}",
        )
    try:
        draft = create_field_set_draft(
            db,
            item,
            actor_id=current_user.id,
            change_summary=payload.change_summary,
        )
        _audit(
            db,
            request,
            current_user,
            action="custom_field_draft_created",
            entity_type="custom_field_set_version",
            entity_id=draft.id,
            tenant_id=item.tenant_id,
            metadata={
                "field_set_id": item.id,
                "version_number": draft.version_number,
                "change_summary": payload.change_summary,
            },
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    db.refresh(item)
    db.refresh(draft)
    return {
        "field_set": _field_set_response(item),
        "draft": _version_response(draft),
    }


@router.put("/{field_set_id}/versions/{version_number}")
def edit_field_set_draft(
    field_set_id: str,
    version_number: int,
    payload: DraftUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.design")
    item = _field_set(db, field_set_id, current_user, lock=True)
    version = _version(db, item, version_number, lock=True)
    try:
        outcome = update_field_set_draft(
            db,
            version,
            item,
            schema=payload.schema_definition,
            expected_revision=payload.expected_revision,
            change_summary=payload.change_summary,
            actor_id=current_user.id,
        )
        _audit(
            db,
            request,
            current_user,
            action="custom_field_draft_updated",
            entity_type="custom_field_set_version",
            entity_id=version.id,
            tenant_id=item.tenant_id,
            metadata={
                "field_set_id": item.id,
                "version_number": version.version_number,
                "schema_sha256": version.schema_sha256,
                "validation_status": version.validation_status,
                "compatibility": outcome["compatibility"],
            },
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    db.refresh(version)
    return {
        "version": _version_response(version),
        **outcome,
    }


@router.post("/{field_set_id}/versions/{version_number}/validate")
def validate_field_set_draft(
    field_set_id: str,
    version_number: int,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.design")
    item = _field_set(db, field_set_id, current_user)
    version = _version(db, item, version_number)
    schema = _json_object(version.schema_json)
    if schema_hash(schema) != version.schema_sha256:
        raise HTTPException(
            status_code=409,
            detail="Custom-field schema failed integrity verification",
        )
    return validate_custom_field_schema(schema)


@router.post("/{field_set_id}/versions/{version_number}/publish")
def publish_field_set_draft(
    field_set_id: str,
    version_number: int,
    payload: PublishRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.publish")
    item = _field_set(db, field_set_id, current_user, lock=True)
    version = _version(db, item, version_number, lock=True)
    try:
        compatibility = publish_field_set_version(
            db,
            item,
            version,
            expected_field_set_revision=payload.expected_field_set_revision,
            expected_version_revision=payload.expected_version_revision,
            allow_breaking_changes=payload.allow_breaking_changes,
            actor_id=current_user.id,
        )
        _audit(
            db,
            request,
            current_user,
            action="custom_field_version_published",
            entity_type="custom_field_set_version",
            entity_id=version.id,
            tenant_id=item.tenant_id,
            metadata={
                "field_set_id": item.id,
                "version_number": version.version_number,
                "reason": payload.reason,
                "allow_breaking_changes": payload.allow_breaking_changes,
                "compatibility": compatibility,
                "schema_sha256": version.schema_sha256,
            },
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    db.refresh(item)
    db.refresh(version)
    return {
        "field_set": _field_set_response(item),
        "version": _version_response(version),
        "compatibility": compatibility,
    }


@router.get("/{field_set_id}/entities/{entity_id}/values")
def get_field_set_values(
    field_set_id: str,
    entity_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.values.read")
    item = _field_set(db, field_set_id, current_user)
    try:
        entity = get_entity(
            db,
            tenant_id=item.tenant_id,
            entity_type=item.entity_type,
            entity_id=entity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not is_field_set_applicable(item, entity):
        raise HTTPException(
            status_code=409,
            detail="Custom-field set is not applicable to this entity",
        )
    value = db.scalar(
        select(CustomFieldValue).where(
            CustomFieldValue.field_set_id == item.id,
            CustomFieldValue.entity_type == item.entity_type,
            CustomFieldValue.entity_id == entity_id,
        )
    )
    if value is None:
        return {
            "field_set": _field_set_response(item),
            "value_record": None,
        }
    _, schema = _value_schema(db, value)
    can_read_sensitive = has_permission(
        current_user,
        "custom_fields.sensitive.read",
    )
    return {
        "field_set": _field_set_response(item),
        "value_record": custom_field_values_response(
            value,
            schema,
            can_read_sensitive=can_read_sensitive,
            settings=get_settings() if can_read_sensitive else None,
        ),
    }


@router.put("/{field_set_id}/entities/{entity_id}/values")
def put_field_set_values(
    field_set_id: str,
    entity_id: str,
    payload: ValuesUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "custom_fields.values.write")
    item = _field_set(db, field_set_id, current_user, lock=True)
    try:
        entity = get_entity(
            db,
            tenant_id=item.tenant_id,
            entity_type=item.entity_type,
            entity_id=entity_id,
        )
        value, _ = save_custom_field_values(
            db,
            item,
            entity=entity,
            submitted_values=payload.values,
            expected_version=payload.expected_version,
            actor_id=current_user.id,
            settings=get_settings(),
        )
        _audit(
            db,
            request,
            current_user,
            action="custom_field_values_saved",
            entity_type=f"{item.entity_type}_custom_fields",
            entity_id=entity_id,
            tenant_id=item.tenant_id,
            metadata={
                "field_set_id": item.id,
                "field_set_code": item.code,
                "schema_version": value.field_set_version_number,
                "value_record_version": value.version,
                "submitted_field_keys": sorted(payload.values),
                "contains_sensitive_fields": any(
                    field.get("sensitive") and field.get("key") in payload.values
                    for field in _json_object(
                        _version(
                            db,
                            item,
                            value.field_set_version_number,
                        ).schema_json
                    ).get("fields", [])
                    if isinstance(field, dict)
                ),
            },
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    db.refresh(value)
    _, schema = _value_schema(db, value)
    can_read_sensitive = has_permission(
        current_user,
        "custom_fields.sensitive.read",
    )
    return custom_field_values_response(
        value,
        schema,
        can_read_sensitive=can_read_sensitive,
        settings=get_settings() if can_read_sensitive else None,
    )
