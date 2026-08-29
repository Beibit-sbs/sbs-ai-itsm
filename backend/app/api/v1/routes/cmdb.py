from __future__ import annotations

from datetime import UTC, datetime
import json
import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.asset_history import AssetHistory
from app.models.ci_class import (
    ConfigurationItemClass,
    ConfigurationItemClassVersion,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.cmdb_schema import (
    canonical_json,
    merge_schemas,
    normalize_schema,
    schema_hash,
    validate_attributes,
)
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/cmdb")
_CODE_PATTERN = re.compile(r"[^A-Z0-9_-]+")
_LIFECYCLE_TO_ASSET_STATUS = {
    "PLANNING": "inactive",
    "ORDERED": "inactive",
    "IN_STOCK": "in_stock",
    "ACTIVE": "in_use",
    "MAINTENANCE": "maintenance",
    "RETIRED": "inactive",
    "DISPOSED": "disposed",
}


class CIClassCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str | None = None
    parent_class_id: str | None = None
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5_000)
    form_schema: dict[str, Any] = Field(
        default_factory=lambda: {"fields": []},
        alias="schema",
        serialization_alias="schema",
    )


class CIClassDraftUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expected_revision: int = Field(ge=1)
    form_schema: dict[str, Any] = Field(
        alias="schema",
        serialization_alias="schema",
    )


class CIClassPublish(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


class CIClassVersionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    ci_class_id: str
    parent_version_id: str | None
    version: int
    revision: int
    status: str
    form_schema: dict[str, Any] = Field(
        alias="schema",
        serialization_alias="schema",
    )
    effective_schema: dict[str, Any]
    schema_hash: str
    published_at: datetime | None
    retired_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CIClassResponse(BaseModel):
    id: str
    tenant_id: str
    parent_class_id: str | None
    parent_class_name: str | None
    code: str
    name: str
    description: str | None
    status: str
    published_version: CIClassVersionResponse | None
    draft_version: CIClassVersionResponse | None
    created_at: datetime
    updated_at: datetime


class ConfigurationItemCreate(BaseModel):
    ci_class_id: str
    asset_tag: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=200)
    inventory_number: str | None = Field(default=None, max_length=80)
    serial_number: str | None = Field(default=None, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    lifecycle_status: Literal[
        "PLANNING",
        "ORDERED",
        "IN_STOCK",
        "ACTIVE",
        "MAINTENANCE",
        "RETIRED",
        "DISPOSED",
    ] = "ACTIVE"
    owner_user_id: str | None = None
    support_group: str | None = Field(default=None, max_length=160)
    criticality: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    environment: Literal[
        "PRODUCTION",
        "STAGING",
        "TEST",
        "DEVELOPMENT",
        "OTHER",
    ] = "PRODUCTION"
    location: str = Field(default="Location unknown", min_length=2, max_length=200)
    condition: str = Field(default="good", min_length=2, max_length=32)
    description: str | None = Field(default=None, max_length=10_000)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ConfigurationItemUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    ci_class_id: str | None = None
    upgrade_schema: bool = False
    lifecycle_status: Literal[
        "PLANNING",
        "ORDERED",
        "IN_STOCK",
        "ACTIVE",
        "MAINTENANCE",
        "RETIRED",
        "DISPOSED",
    ] | None = None
    owner_user_id: str | None = None
    support_group: str | None = Field(default=None, max_length=160)
    criticality: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
    environment: Literal[
        "PRODUCTION",
        "STAGING",
        "TEST",
        "DEVELOPMENT",
        "OTHER",
    ] | None = None
    attributes: dict[str, Any] | None = None
    comment: str = Field(min_length=3, max_length=2_000)


class ConfigurationItemResponse(BaseModel):
    id: str
    tenant_id: str | None
    asset_tag: str
    name: str
    ci_class_id: str | None
    ci_class_version_id: str | None
    ci_class_code: str | None
    ci_class_name: str | None
    ci_schema_version: int | None
    ci_schema_hash: str | None
    attributes: dict[str, Any]
    lifecycle_status: str
    owner_user_id: str | None
    owner_name: str
    support_group: str | None
    criticality: str
    environment: str
    version: int
    status: str
    created_at: datetime
    updated_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _code(value: str) -> str:
    normalized = _CODE_PATTERN.sub("_", value.strip().upper()).strip("_")
    if len(normalized) < 2:
        raise HTTPException(status_code=422, detail="CI class code is invalid")
    return normalized


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
            detail="tenant_id is required for SaaS Root CMDB administration",
        )
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _class_or_404(
    db: Session,
    class_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> ConfigurationItemClass:
    statement = select(ConfigurationItemClass).where(
        ConfigurationItemClass.id == class_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    ci_class = db.scalar(statement)
    if ci_class is None or (
        not is_saas_root(current_user)
        and ci_class.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="CI class not found")
    return ci_class


def _version(
    db: Session,
    class_id: str,
    version_status: str,
) -> ConfigurationItemClassVersion | None:
    return db.scalar(
        select(ConfigurationItemClassVersion)
        .where(
            ConfigurationItemClassVersion.ci_class_id == class_id,
            ConfigurationItemClassVersion.status == version_status,
        )
        .order_by(ConfigurationItemClassVersion.version.desc())
    )


def _effective_schema(
    db: Session,
    version: ConfigurationItemClassVersion,
    seen: set[str] | None = None,
) -> dict[str, Any]:
    visited = seen or set()
    if version.id in visited:
        raise HTTPException(status_code=409, detail="CI class inheritance cycle detected")
    visited.add(version.id)
    parent_schema: dict[str, Any] = {"fields": []}
    if version.parent_version_id:
        parent = db.get(ConfigurationItemClassVersion, version.parent_version_id)
        if parent is None:
            raise HTTPException(
                status_code=409,
                detail="Referenced parent class version is unavailable",
            )
        parent_schema = _effective_schema(db, parent, visited)
    try:
        return merge_schemas(parent_schema, json.loads(version.schema_json))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"Invalid CI schema: {exc}") from exc


def _version_response(
    db: Session,
    version: ConfigurationItemClassVersion,
) -> CIClassVersionResponse:
    return CIClassVersionResponse(
        id=version.id,
        ci_class_id=version.ci_class_id,
        parent_version_id=version.parent_version_id,
        version=version.version,
        revision=version.revision,
        status=version.status,
        form_schema=json.loads(version.schema_json),
        effective_schema=_effective_schema(db, version),
        schema_hash=version.schema_hash,
        published_at=version.published_at,
        retired_at=version.retired_at,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _class_response(
    db: Session,
    ci_class: ConfigurationItemClass,
) -> CIClassResponse:
    parent = (
        db.get(ConfigurationItemClass, ci_class.parent_class_id)
        if ci_class.parent_class_id
        else None
    )
    published = _version(db, ci_class.id, "PUBLISHED")
    draft = _version(db, ci_class.id, "DRAFT")
    return CIClassResponse(
        id=ci_class.id,
        tenant_id=ci_class.tenant_id,
        parent_class_id=ci_class.parent_class_id,
        parent_class_name=parent.name if parent else None,
        code=ci_class.code,
        name=ci_class.name,
        description=ci_class.description,
        status=ci_class.status,
        published_version=_version_response(db, published) if published else None,
        draft_version=_version_response(db, draft) if draft else None,
        created_at=ci_class.created_at,
        updated_at=ci_class.updated_at,
    )


def _owner(
    db: Session,
    tenant_id: str,
    owner_user_id: str | None,
    current_user: AuthUserResponse,
) -> User | None:
    user = db.get(User, owner_user_id) if owner_user_id else None
    if user is None and not is_saas_root(current_user):
        user = db.get(User, current_user.id)
    if user is None and is_saas_root(current_user):
        user = db.scalar(
            select(User)
            .where(
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
                User.is_root.is_(False),
            )
            .order_by(User.created_at, User.id)
        )
    if user is None or not user.is_active:
        raise HTTPException(status_code=422, detail="CI owner is unavailable")
    if user.is_root or user.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="CI owner belongs to another tenant")
    return user


def _attributes(asset: Asset) -> dict[str, Any]:
    try:
        parsed = json.loads(asset.ci_attributes_json or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _item_response(asset: Asset) -> ConfigurationItemResponse:
    return ConfigurationItemResponse(
        id=asset.id,
        tenant_id=asset.tenant_id,
        asset_tag=asset.asset_tag,
        name=asset.name,
        ci_class_id=asset.ci_class_id,
        ci_class_version_id=asset.ci_class_version_id,
        ci_class_code=asset.ci_class_code,
        ci_class_name=asset.ci_class_name,
        ci_schema_version=asset.ci_schema_version,
        ci_schema_hash=asset.ci_schema_hash,
        attributes=_attributes(asset),
        lifecycle_status=asset.lifecycle_status,
        owner_user_id=asset.owner_user_id,
        owner_name=asset.owner_name,
        support_group=asset.support_group,
        criticality=asset.criticality,
        environment=asset.environment,
        version=asset.ci_version,
        status=asset.status,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def _audit(
    db: Session,
    http_request: Request,
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
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata=metadata,
    )


@router.get("/classes", response_model=list[CIClassResponse])
def list_ci_classes(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CIClassResponse]:
    require_permissions(current_user, "assets.read")
    statement = select(ConfigurationItemClass)
    if not is_saas_root(current_user):
        statement = statement.where(
            ConfigurationItemClass.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(ConfigurationItemClass.tenant_id == tenant_id)
    classes = db.scalars(
        statement.order_by(ConfigurationItemClass.name)
    ).all()
    return [_class_response(db, ci_class) for ci_class in classes]


@router.post(
    "/classes",
    response_model=CIClassResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_ci_class(
    payload: CIClassCreate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CIClassResponse:
    require_permissions(current_user, "assets.update")
    parent = (
        _class_or_404(db, payload.parent_class_id, current_user)
        if payload.parent_class_id
        else None
    )
    tenant_id = _tenant_id(
        db,
        current_user,
        parent.tenant_id if parent else payload.tenant_id,
    )
    if parent and parent.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="Parent class tenant mismatch")
    parent_version = _version(db, parent.id, "PUBLISHED") if parent else None
    if parent and parent_version is None:
        raise HTTPException(status_code=409, detail="Parent class is not published")
    code = _code(payload.code)
    if db.scalar(
        select(ConfigurationItemClass.id).where(
            ConfigurationItemClass.tenant_id == tenant_id,
            ConfigurationItemClass.code == code,
        )
    ):
        raise HTTPException(status_code=409, detail="CI class code already exists")
    try:
        own_schema = normalize_schema(payload.form_schema)
        effective = merge_schemas(
            _effective_schema(db, parent_version) if parent_version else None,
            own_schema,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid CI schema: {exc}") from exc
    now = _now()
    ci_class = ConfigurationItemClass(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        parent_class_id=parent.id if parent else None,
        code=code,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        status="DRAFT",
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    version = ConfigurationItemClassVersion(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ci_class_id=ci_class.id,
        parent_version_id=parent_version.id if parent_version else None,
        version=1,
        revision=1,
        status="DRAFT",
        schema_json=canonical_json(own_schema),
        schema_hash=schema_hash(effective),
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(ci_class)
    db.flush()
    db.add(version)
    db.flush()
    _audit(
        db,
        http_request,
        current_user,
        action="ci_class_created",
        entity_type="ci_class",
        entity_id=ci_class.id,
        tenant_id=tenant_id,
        metadata={
            "code": code,
            "parent_class_id": ci_class.parent_class_id,
            "schema_hash": version.schema_hash,
        },
    )
    db.commit()
    db.refresh(ci_class)
    return _class_response(db, ci_class)


@router.post(
    "/classes/{class_id}/draft",
    response_model=CIClassResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_ci_class_draft(
    class_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CIClassResponse:
    require_permissions(current_user, "assets.update")
    ci_class = _class_or_404(db, class_id, current_user, lock=True)
    existing = _version(db, ci_class.id, "DRAFT")
    if existing:
        return _class_response(db, ci_class)
    published = _version(db, ci_class.id, "PUBLISHED")
    if published is None:
        raise HTTPException(status_code=409, detail="Published class version not found")
    parent_version = None
    if ci_class.parent_class_id:
        parent_version = _version(db, ci_class.parent_class_id, "PUBLISHED")
        if parent_version is None:
            raise HTTPException(status_code=409, detail="Parent class is not published")
    latest = db.scalar(
        select(func.max(ConfigurationItemClassVersion.version)).where(
            ConfigurationItemClassVersion.ci_class_id == ci_class.id
        )
    )
    effective = merge_schemas(
        _effective_schema(db, parent_version) if parent_version else None,
        json.loads(published.schema_json),
    )
    now = _now()
    draft = ConfigurationItemClassVersion(
        id=str(uuid.uuid4()),
        tenant_id=ci_class.tenant_id,
        ci_class_id=ci_class.id,
        parent_version_id=parent_version.id if parent_version else None,
        version=(latest or 0) + 1,
        revision=1,
        status="DRAFT",
        schema_json=published.schema_json,
        schema_hash=schema_hash(effective),
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(draft)
    ci_class.updated_by_id = current_user.id
    _audit(
        db,
        http_request,
        current_user,
        action="ci_class_draft_created",
        entity_type="ci_class_version",
        entity_id=draft.id,
        tenant_id=ci_class.tenant_id,
        metadata={"ci_class_id": ci_class.id, "version": draft.version},
    )
    db.commit()
    return _class_response(db, ci_class)


@router.put("/classes/{class_id}/draft", response_model=CIClassResponse)
def update_ci_class_draft(
    class_id: str,
    payload: CIClassDraftUpdate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CIClassResponse:
    require_permissions(current_user, "assets.update")
    ci_class = _class_or_404(db, class_id, current_user, lock=True)
    draft = _version(db, ci_class.id, "DRAFT")
    if draft is None:
        raise HTTPException(status_code=404, detail="CI class draft not found")
    if draft.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail=f"CI class draft changed; current revision is {draft.revision}",
        )
    try:
        own_schema = normalize_schema(payload.form_schema)
        parent_schema = None
        if draft.parent_version_id:
            parent_version = db.get(
                ConfigurationItemClassVersion,
                draft.parent_version_id,
            )
            if parent_version is None:
                raise HTTPException(
                    status_code=409,
                    detail="Referenced parent class version is unavailable",
                )
            parent_schema = _effective_schema(db, parent_version)
        effective = merge_schemas(parent_schema, own_schema)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid CI schema: {exc}") from exc
    draft.schema_json = canonical_json(own_schema)
    draft.schema_hash = schema_hash(effective)
    draft.revision += 1
    draft.updated_by_id = current_user.id
    draft.updated_at = _now()
    ci_class.updated_by_id = current_user.id
    _audit(
        db,
        http_request,
        current_user,
        action="ci_class_draft_updated",
        entity_type="ci_class_version",
        entity_id=draft.id,
        tenant_id=ci_class.tenant_id,
        metadata={
            "ci_class_id": ci_class.id,
            "version": draft.version,
            "revision": draft.revision,
            "schema_hash": draft.schema_hash,
        },
    )
    db.commit()
    return _class_response(db, ci_class)


@router.post("/classes/{class_id}/publish", response_model=CIClassResponse)
def publish_ci_class(
    class_id: str,
    payload: CIClassPublish,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CIClassResponse:
    require_permissions(current_user, "assets.update")
    ci_class = _class_or_404(db, class_id, current_user, lock=True)
    draft = _version(db, ci_class.id, "DRAFT")
    if draft is None:
        raise HTTPException(status_code=404, detail="CI class draft not found")
    if draft.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail=f"CI class draft changed; current revision is {draft.revision}",
        )
    parent_version = None
    if ci_class.parent_class_id:
        parent_version = _version(db, ci_class.parent_class_id, "PUBLISHED")
        if parent_version is None:
            raise HTTPException(status_code=409, detail="Parent class is not published")
    try:
        effective = merge_schemas(
            _effective_schema(db, parent_version) if parent_version else None,
            json.loads(draft.schema_json),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid CI schema: {exc}") from exc
    now = _now()
    previous = _version(db, ci_class.id, "PUBLISHED")
    if previous:
        previous.status = "RETIRED"
        previous.retired_at = now
        previous.updated_by_id = current_user.id
    draft.parent_version_id = parent_version.id if parent_version else None
    draft.schema_hash = schema_hash(effective)
    draft.status = "PUBLISHED"
    draft.published_at = now
    draft.published_by_id = current_user.id
    draft.updated_by_id = current_user.id
    ci_class.status = "ACTIVE"
    ci_class.updated_by_id = current_user.id
    _audit(
        db,
        http_request,
        current_user,
        action="ci_class_published",
        entity_type="ci_class_version",
        entity_id=draft.id,
        tenant_id=ci_class.tenant_id,
        metadata={
            "ci_class_id": ci_class.id,
            "version": draft.version,
            "schema_hash": draft.schema_hash,
            "parent_version_id": draft.parent_version_id,
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    return _class_response(db, ci_class)


@router.post(
    "/items",
    response_model=ConfigurationItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_configuration_item(
    payload: ConfigurationItemCreate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfigurationItemResponse:
    require_permissions(current_user, "assets.create")
    ci_class = _class_or_404(db, payload.ci_class_id, current_user)
    version = _version(db, ci_class.id, "PUBLISHED")
    if version is None:
        raise HTTPException(status_code=409, detail="CI class is not published")
    if db.scalar(select(Asset.id).where(Asset.asset_tag == payload.asset_tag.strip())):
        raise HTTPException(status_code=409, detail="Asset tag already exists")
    effective_schema = _effective_schema(db, version)
    normalized, errors = validate_attributes(effective_schema, payload.attributes)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "CI attribute validation failed", "errors": errors},
        )
    owner = _owner(db, ci_class.tenant_id, payload.owner_user_id, current_user)
    now = _now()
    asset = Asset(
        id=str(uuid.uuid4()),
        tenant_id=ci_class.tenant_id,
        ci_class_id=ci_class.id,
        ci_class_version_id=version.id,
        ci_class_code=ci_class.code,
        ci_class_name=ci_class.name,
        ci_schema_version=version.version,
        ci_schema_hash=version.schema_hash,
        ci_attributes_json=canonical_json(normalized),
        lifecycle_status=payload.lifecycle_status,
        owner_user_id=owner.id,
        support_group=payload.support_group.strip() if payload.support_group else None,
        criticality=payload.criticality,
        environment=payload.environment,
        ci_version=1,
        asset_tag=payload.asset_tag.strip(),
        name=payload.name.strip(),
        asset_type=ci_class.code,
        type=ci_class.code,
        serial_number=payload.serial_number.strip() if payload.serial_number else None,
        inventory_number=(
            payload.inventory_number.strip() if payload.inventory_number else None
        ),
        source="cmdb_manual",
        manufacturer=payload.manufacturer.strip() if payload.manufacturer else None,
        model=payload.model.strip() if payload.model else None,
        status=_LIFECYCLE_TO_ASSET_STATUS[payload.lifecycle_status],
        owner_name=owner.full_name,
        location=payload.location.strip(),
        condition=payload.condition.strip(),
        description=payload.description.strip() if payload.description else None,
        created_at=now,
        updated_at=now,
    )
    db.add(asset)
    db.flush()
    db.add(
        AssetHistory(
            id=str(uuid.uuid4()),
            asset_id=asset.id,
            actor_id=current_user.id,
            action="ci_created",
            old_value=None,
            new_value={
                "class": ci_class.code,
                "class_version": version.version,
                "schema_hash": version.schema_hash,
                "attributes": normalized,
                "lifecycle_status": asset.lifecycle_status,
                "criticality": asset.criticality,
                "environment": asset.environment,
            },
            comment="Configuration item created",
            created_at=now,
        )
    )
    _audit(
        db,
        http_request,
        current_user,
        action="configuration_item_created",
        entity_type="asset",
        entity_id=asset.id,
        tenant_id=ci_class.tenant_id,
        metadata={
            "asset_tag": asset.asset_tag,
            "ci_class_id": ci_class.id,
            "ci_class_version_id": version.id,
            "schema_hash": version.schema_hash,
        },
    )
    db.commit()
    db.refresh(asset)
    return _item_response(asset)


@router.get("/items", response_model=list[ConfigurationItemResponse])
def list_configuration_items(
    tenant_id: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConfigurationItemResponse]:
    require_permissions(current_user, "assets.read")
    scoped_tenant_id = _tenant_id(db, current_user, tenant_id)
    statement = select(Asset).where(
        Asset.tenant_id == scoped_tenant_id,
        Asset.ci_class_id.is_not(None),
    )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            (Asset.name.ilike(pattern))
            | (Asset.asset_tag.ilike(pattern))
            | (Asset.inventory_number.ilike(pattern))
        )
    assets = db.scalars(
        statement.order_by(Asset.name, Asset.asset_tag).limit(limit)
    ).all()
    return [_item_response(asset) for asset in assets]


@router.patch("/items/{asset_id}", response_model=ConfigurationItemResponse)
def update_configuration_item(
    asset_id: str,
    payload: ConfigurationItemUpdate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfigurationItemResponse:
    require_permissions(current_user, "assets.update")
    statement = select(Asset).where(Asset.id == asset_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    asset = db.scalar(statement)
    if asset is None or (
        not is_saas_root(current_user) and asset.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Configuration item not found")
    if asset.ci_version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Configuration item changed; current version is {asset.ci_version}",
        )
    target_class_id = payload.ci_class_id or asset.ci_class_id
    if not target_class_id:
        raise HTTPException(status_code=409, detail="CI class is not assigned")
    ci_class = _class_or_404(db, target_class_id, current_user)
    if ci_class.tenant_id != asset.tenant_id:
        raise HTTPException(status_code=422, detail="CI class tenant mismatch")
    if payload.ci_class_id or payload.upgrade_schema or not asset.ci_class_version_id:
        version = _version(db, ci_class.id, "PUBLISHED")
    else:
        version = db.get(ConfigurationItemClassVersion, asset.ci_class_version_id)
    if version is None:
        raise HTTPException(status_code=409, detail="Published CI class is unavailable")
    values = payload.attributes if payload.attributes is not None else _attributes(asset)
    normalized, errors = validate_attributes(_effective_schema(db, version), values)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "CI attribute validation failed", "errors": errors},
        )
    before = {
        "ci_class_id": asset.ci_class_id,
        "ci_class_version_id": asset.ci_class_version_id,
        "schema_hash": asset.ci_schema_hash,
        "attributes": _attributes(asset),
        "lifecycle_status": asset.lifecycle_status,
        "owner_user_id": asset.owner_user_id,
        "support_group": asset.support_group,
        "criticality": asset.criticality,
        "environment": asset.environment,
        "version": asset.ci_version,
    }
    owner = (
        _owner(db, ci_class.tenant_id, payload.owner_user_id, current_user)
        if "owner_user_id" in payload.model_fields_set
        else db.get(User, asset.owner_user_id)
    )
    asset.ci_class_id = ci_class.id
    asset.ci_class_version_id = version.id
    asset.ci_class_code = ci_class.code
    asset.ci_class_name = ci_class.name
    asset.ci_schema_version = version.version
    asset.ci_schema_hash = version.schema_hash
    asset.ci_attributes_json = canonical_json(normalized)
    asset.asset_type = ci_class.code
    asset.type = ci_class.code
    if payload.lifecycle_status is not None:
        asset.lifecycle_status = payload.lifecycle_status
        asset.status = _LIFECYCLE_TO_ASSET_STATUS[payload.lifecycle_status]
    if owner is not None:
        asset.owner_user_id = owner.id
        asset.owner_name = owner.full_name
    if "support_group" in payload.model_fields_set:
        asset.support_group = (
            payload.support_group.strip() if payload.support_group else None
        )
    if payload.criticality is not None:
        asset.criticality = payload.criticality
    if payload.environment is not None:
        asset.environment = payload.environment
    asset.ci_version += 1
    asset.updated_at = _now()
    after = {
        "ci_class_id": asset.ci_class_id,
        "ci_class_version_id": asset.ci_class_version_id,
        "schema_hash": asset.ci_schema_hash,
        "attributes": normalized,
        "lifecycle_status": asset.lifecycle_status,
        "owner_user_id": asset.owner_user_id,
        "support_group": asset.support_group,
        "criticality": asset.criticality,
        "environment": asset.environment,
        "version": asset.ci_version,
    }
    db.add(
        AssetHistory(
            id=str(uuid.uuid4()),
            asset_id=asset.id,
            actor_id=current_user.id,
            action="ci_updated",
            old_value=before,
            new_value=after,
            comment=payload.comment.strip(),
            created_at=_now(),
        )
    )
    _audit(
        db,
        http_request,
        current_user,
        action="configuration_item_updated",
        entity_type="asset",
        entity_id=asset.id,
        tenant_id=ci_class.tenant_id,
        metadata=after,
    )
    db.commit()
    db.refresh(asset)
    return _item_response(asset)
