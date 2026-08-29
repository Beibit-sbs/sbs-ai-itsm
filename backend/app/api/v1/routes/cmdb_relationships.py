from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.asset_history import AssetHistory
from app.models.ci_class import ConfigurationItemClass
from app.models.ci_relationship import (
    ConfigurationItemRelationship,
    ConfigurationItemRelationshipType,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/cmdb")
_CODE_PATTERN = re.compile(r"[^A-Z0-9_-]+")


class RelationshipTypeCreate(BaseModel):
    tenant_id: str | None = None
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=160)
    forward_label: str = Field(min_length=2, max_length=160)
    reverse_label: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5_000)
    source_class_id: str | None = None
    target_class_id: str | None = None
    source_cardinality: Literal["ONE", "MANY"] = "MANY"
    target_cardinality: Literal["ONE", "MANY"] = "MANY"
    allow_self_relationship: bool = False
    allow_cycles: bool = False


class RelationshipTypeUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    forward_label: str | None = Field(default=None, min_length=2, max_length=160)
    reverse_label: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5_000)
    status: Literal["ACTIVE", "INACTIVE"] | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class RelationshipTypeResponse(BaseModel):
    id: str
    tenant_id: str
    code: str
    name: str
    forward_label: str
    reverse_label: str
    description: str | None
    source_class_id: str | None
    source_class_name: str | None
    target_class_id: str | None
    target_class_name: str | None
    source_cardinality: str
    target_cardinality: str
    allow_self_relationship: bool
    allow_cycles: bool
    status: str
    version: int
    active_relationships: int
    created_at: datetime
    updated_at: datetime


class RelationshipCreate(BaseModel):
    relationship_type_id: str
    source_ci_id: str
    target_ci_id: str
    description: str | None = Field(default=None, max_length=5_000)


class RelationshipRetire(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


class CINodeResponse(BaseModel):
    id: str
    asset_tag: str
    name: str
    ci_class_id: str | None
    ci_class_code: str | None
    ci_class_name: str | None
    lifecycle_status: str
    criticality: str
    environment: str
    support_group: str | None
    depth: int | None = None


class RelationshipResponse(BaseModel):
    id: str
    tenant_id: str
    relationship_type_id: str
    relationship_type_code: str
    relationship_type_name: str
    forward_label: str
    reverse_label: str
    source: CINodeResponse
    target: CINodeResponse
    status: str
    version: int
    description: str | None
    created_at: datetime
    updated_at: datetime
    retired_at: datetime | None


class TopologyResponse(BaseModel):
    root_ci_id: str
    direction: str
    requested_depth: int
    nodes: list[CINodeResponse]
    edges: list[RelationshipResponse]
    truncated: bool


def _now() -> datetime:
    return datetime.now(UTC)


def _code(value: str) -> str:
    normalized = _CODE_PATTERN.sub("_", value.strip().upper()).strip("_")
    if len(normalized) < 2:
        raise HTTPException(status_code=422, detail="Relationship type code is invalid")
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
            detail="tenant_id is required for SaaS Root relationship administration",
        )
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _relationship_type_or_404(
    db: Session,
    relationship_type_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> ConfigurationItemRelationshipType:
    statement = select(ConfigurationItemRelationshipType).where(
        ConfigurationItemRelationshipType.id == relationship_type_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    relationship_type = db.scalar(statement)
    if relationship_type is None or (
        not is_saas_root(current_user)
        and relationship_type.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="CI relationship type not found")
    return relationship_type


def _relationship_or_404(
    db: Session,
    relationship_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> ConfigurationItemRelationship:
    statement = select(ConfigurationItemRelationship).where(
        ConfigurationItemRelationship.id == relationship_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    relationship = db.scalar(statement)
    if relationship is None or (
        not is_saas_root(current_user)
        and relationship.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="CI relationship not found")
    return relationship


def _asset_or_404(
    db: Session,
    asset_id: str,
    current_user: AuthUserResponse,
) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or (
        not is_saas_root(current_user) and asset.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Configuration item not found")
    if not asset.tenant_id:
        raise HTTPException(status_code=409, detail="Configuration item has no tenant")
    return asset


def _class_in_tenant(
    db: Session,
    class_id: str | None,
    tenant_id: str,
) -> ConfigurationItemClass | None:
    if not class_id:
        return None
    ci_class = db.get(ConfigurationItemClass, class_id)
    if ci_class is None or ci_class.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="CI class is unavailable")
    return ci_class


def _class_is_a(
    db: Session,
    actual_class_id: str | None,
    required_class_id: str | None,
) -> bool:
    if required_class_id is None:
        return True
    visited: set[str] = set()
    current_id = actual_class_id
    while current_id:
        if current_id == required_class_id:
            return True
        if current_id in visited:
            return False
        visited.add(current_id)
        ci_class = db.get(ConfigurationItemClass, current_id)
        current_id = ci_class.parent_class_id if ci_class else None
    return False


def _node(asset: Asset, depth: int | None = None) -> CINodeResponse:
    return CINodeResponse(
        id=asset.id,
        asset_tag=asset.asset_tag,
        name=asset.name,
        ci_class_id=asset.ci_class_id,
        ci_class_code=asset.ci_class_code,
        ci_class_name=asset.ci_class_name,
        lifecycle_status=asset.lifecycle_status,
        criticality=asset.criticality,
        environment=asset.environment,
        support_group=asset.support_group,
        depth=depth,
    )


def _type_response(
    db: Session,
    relationship_type: ConfigurationItemRelationshipType,
) -> RelationshipTypeResponse:
    source_class = (
        db.get(ConfigurationItemClass, relationship_type.source_class_id)
        if relationship_type.source_class_id
        else None
    )
    target_class = (
        db.get(ConfigurationItemClass, relationship_type.target_class_id)
        if relationship_type.target_class_id
        else None
    )
    active_relationships = db.scalar(
        select(func.count(ConfigurationItemRelationship.id)).where(
            ConfigurationItemRelationship.relationship_type_id
            == relationship_type.id,
            ConfigurationItemRelationship.status == "ACTIVE",
        )
    )
    return RelationshipTypeResponse(
        id=relationship_type.id,
        tenant_id=relationship_type.tenant_id,
        code=relationship_type.code,
        name=relationship_type.name,
        forward_label=relationship_type.forward_label,
        reverse_label=relationship_type.reverse_label,
        description=relationship_type.description,
        source_class_id=relationship_type.source_class_id,
        source_class_name=source_class.name if source_class else None,
        target_class_id=relationship_type.target_class_id,
        target_class_name=target_class.name if target_class else None,
        source_cardinality=relationship_type.source_cardinality,
        target_cardinality=relationship_type.target_cardinality,
        allow_self_relationship=relationship_type.allow_self_relationship,
        allow_cycles=relationship_type.allow_cycles,
        status=relationship_type.status,
        version=relationship_type.version,
        active_relationships=active_relationships or 0,
        created_at=relationship_type.created_at,
        updated_at=relationship_type.updated_at,
    )


def _relationship_response(
    db: Session,
    relationship: ConfigurationItemRelationship,
    *,
    depths: dict[str, int] | None = None,
    assets: dict[str, Asset] | None = None,
    relationship_types: dict[str, ConfigurationItemRelationshipType] | None = None,
) -> RelationshipResponse:
    asset_map = assets or {}
    source = asset_map.get(relationship.source_ci_id) or db.get(
        Asset,
        relationship.source_ci_id,
    )
    target = asset_map.get(relationship.target_ci_id) or db.get(
        Asset,
        relationship.target_ci_id,
    )
    relationship_type = (relationship_types or {}).get(
        relationship.relationship_type_id
    ) or db.get(
        ConfigurationItemRelationshipType,
        relationship.relationship_type_id,
    )
    if source is None or target is None or relationship_type is None:
        raise HTTPException(status_code=409, detail="CI relationship is inconsistent")
    depth_map = depths or {}
    return RelationshipResponse(
        id=relationship.id,
        tenant_id=relationship.tenant_id,
        relationship_type_id=relationship_type.id,
        relationship_type_code=relationship_type.code,
        relationship_type_name=relationship_type.name,
        forward_label=relationship_type.forward_label,
        reverse_label=relationship_type.reverse_label,
        source=_node(source, depth_map.get(source.id)),
        target=_node(target, depth_map.get(target.id)),
        status=relationship.status,
        version=relationship.version,
        description=relationship.description,
        created_at=relationship.created_at,
        updated_at=relationship.updated_at,
        retired_at=relationship.retired_at,
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


def _history(
    db: Session,
    relationship: ConfigurationItemRelationship,
    relationship_type: ConfigurationItemRelationshipType,
    current_user: AuthUserResponse,
    *,
    action: str,
    reason: str,
) -> None:
    now = _now()
    shared = {
        "relationship_id": relationship.id,
        "relationship_type_id": relationship_type.id,
        "relationship_type_code": relationship_type.code,
        "source_ci_id": relationship.source_ci_id,
        "target_ci_id": relationship.target_ci_id,
        "status": relationship.status,
        "version": relationship.version,
    }
    for asset_id, direction, label in (
        (
            relationship.source_ci_id,
            "outgoing",
            relationship_type.forward_label,
        ),
        (
            relationship.target_ci_id,
            "incoming",
            relationship_type.reverse_label,
        ),
    ):
        db.add(
            AssetHistory(
                id=str(uuid.uuid4()),
                asset_id=asset_id,
                actor_id=current_user.id,
                action=action,
                old_value=None,
                new_value={**shared, "direction": direction, "label": label},
                comment=reason,
                created_at=now,
            )
        )


def _would_create_cycle(
    db: Session,
    relationship_type: ConfigurationItemRelationshipType,
    source_ci_id: str,
    target_ci_id: str,
) -> bool:
    rows = db.execute(
        select(
            ConfigurationItemRelationship.source_ci_id,
            ConfigurationItemRelationship.target_ci_id,
        ).where(
            ConfigurationItemRelationship.tenant_id
            == relationship_type.tenant_id,
            ConfigurationItemRelationship.relationship_type_id
            == relationship_type.id,
            ConfigurationItemRelationship.status == "ACTIVE",
        )
    ).all()
    adjacency: dict[str, set[str]] = {}
    for source_id, target_id in rows:
        adjacency.setdefault(source_id, set()).add(target_id)
    queue = deque([target_ci_id])
    visited: set[str] = set()
    while queue:
        current = queue.popleft()
        if current == source_ci_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        queue.extend(adjacency.get(current, ()))
    return False


def _validate_relationship(
    db: Session,
    relationship_type: ConfigurationItemRelationshipType,
    source: Asset,
    target: Asset,
) -> None:
    if relationship_type.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="CI relationship type is inactive")
    if source.tenant_id != relationship_type.tenant_id:
        raise HTTPException(status_code=422, detail="Source CI tenant mismatch")
    if target.tenant_id != relationship_type.tenant_id:
        raise HTTPException(status_code=422, detail="Target CI tenant mismatch")
    if source.id == target.id and not relationship_type.allow_self_relationship:
        raise HTTPException(status_code=422, detail="Self relationship is not allowed")
    if not _class_is_a(
        db,
        source.ci_class_id,
        relationship_type.source_class_id,
    ):
        raise HTTPException(
            status_code=422,
            detail="Source CI class is not allowed for this relationship type",
        )
    if not _class_is_a(
        db,
        target.ci_class_id,
        relationship_type.target_class_id,
    ):
        raise HTTPException(
            status_code=422,
            detail="Target CI class is not allowed for this relationship type",
        )
    if relationship_type.source_cardinality == "ONE":
        existing_target = db.scalar(
            select(ConfigurationItemRelationship.id).where(
                ConfigurationItemRelationship.relationship_type_id
                == relationship_type.id,
                ConfigurationItemRelationship.source_ci_id == source.id,
                ConfigurationItemRelationship.status == "ACTIVE",
            )
        )
        if existing_target:
            raise HTTPException(
                status_code=409,
                detail="Source cardinality ONE would be violated",
            )
    if relationship_type.target_cardinality == "ONE":
        existing_source = db.scalar(
            select(ConfigurationItemRelationship.id).where(
                ConfigurationItemRelationship.relationship_type_id
                == relationship_type.id,
                ConfigurationItemRelationship.target_ci_id == target.id,
                ConfigurationItemRelationship.status == "ACTIVE",
            )
        )
        if existing_source:
            raise HTTPException(
                status_code=409,
                detail="Target cardinality ONE would be violated",
            )
    if (
        not relationship_type.allow_cycles
        and _would_create_cycle(db, relationship_type, source.id, target.id)
    ):
        raise HTTPException(
            status_code=409,
            detail="Relationship would create a prohibited cycle",
        )


@router.get(
    "/relationship-types",
    response_model=list[RelationshipTypeResponse],
)
def list_relationship_types(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RelationshipTypeResponse]:
    require_permissions(current_user, "assets.read")
    statement = select(ConfigurationItemRelationshipType)
    if not is_saas_root(current_user):
        statement = statement.where(
            ConfigurationItemRelationshipType.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(
            ConfigurationItemRelationshipType.tenant_id == tenant_id
        )
    relationship_types = db.scalars(
        statement.order_by(ConfigurationItemRelationshipType.name)
    ).all()
    return [_type_response(db, item) for item in relationship_types]


@router.post(
    "/relationship-types",
    response_model=RelationshipTypeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_relationship_type(
    payload: RelationshipTypeCreate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RelationshipTypeResponse:
    require_permissions(current_user, "assets.update")
    requested_tenants = {
        ci_class.tenant_id
        for ci_class in (
            db.get(ConfigurationItemClass, payload.source_class_id)
            if payload.source_class_id
            else None,
            db.get(ConfigurationItemClass, payload.target_class_id)
            if payload.target_class_id
            else None,
        )
        if ci_class is not None
    }
    if len(requested_tenants) > 1:
        raise HTTPException(status_code=422, detail="CI class tenant mismatch")
    if payload.tenant_id and requested_tenants and (
        payload.tenant_id not in requested_tenants
    ):
        raise HTTPException(status_code=422, detail="CI class tenant mismatch")
    inferred_tenant = payload.tenant_id or next(iter(requested_tenants), None)
    tenant_id = _tenant_id(db, current_user, inferred_tenant)
    source_class = _class_in_tenant(db, payload.source_class_id, tenant_id)
    target_class = _class_in_tenant(db, payload.target_class_id, tenant_id)
    code = _code(payload.code)
    if db.scalar(
        select(ConfigurationItemRelationshipType.id).where(
            ConfigurationItemRelationshipType.tenant_id == tenant_id,
            ConfigurationItemRelationshipType.code == code,
        )
    ):
        raise HTTPException(
            status_code=409,
            detail="CI relationship type code already exists",
        )
    now = _now()
    relationship_type = ConfigurationItemRelationshipType(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=code,
        name=payload.name.strip(),
        forward_label=payload.forward_label.strip(),
        reverse_label=payload.reverse_label.strip(),
        description=payload.description.strip() if payload.description else None,
        source_class_id=source_class.id if source_class else None,
        target_class_id=target_class.id if target_class else None,
        source_cardinality=payload.source_cardinality,
        target_cardinality=payload.target_cardinality,
        allow_self_relationship=payload.allow_self_relationship,
        allow_cycles=payload.allow_cycles,
        status="ACTIVE",
        version=1,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(relationship_type)
    db.flush()
    _audit(
        db,
        http_request,
        current_user,
        action="ci_relationship_type_created",
        entity_type="ci_relationship_type",
        entity_id=relationship_type.id,
        tenant_id=tenant_id,
        metadata={
            "code": code,
            "source_class_id": relationship_type.source_class_id,
            "target_class_id": relationship_type.target_class_id,
            "source_cardinality": relationship_type.source_cardinality,
            "target_cardinality": relationship_type.target_cardinality,
            "allow_cycles": relationship_type.allow_cycles,
        },
    )
    db.commit()
    db.refresh(relationship_type)
    return _type_response(db, relationship_type)


@router.patch(
    "/relationship-types/{relationship_type_id}",
    response_model=RelationshipTypeResponse,
)
def update_relationship_type(
    relationship_type_id: str,
    payload: RelationshipTypeUpdate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RelationshipTypeResponse:
    require_permissions(current_user, "assets.update")
    relationship_type = _relationship_type_or_404(
        db,
        relationship_type_id,
        current_user,
        lock=True,
    )
    if relationship_type.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=(
                "CI relationship type changed; "
                f"current version is {relationship_type.version}"
            ),
        )
    updates = payload.model_dump(
        exclude={"expected_version", "reason"},
        exclude_unset=True,
    )
    before = {
        key: getattr(relationship_type, key)
        for key in updates
    }
    for field_name, value in updates.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(relationship_type, field_name, value)
    relationship_type.version += 1
    relationship_type.updated_by_id = current_user.id
    relationship_type.updated_at = _now()
    _audit(
        db,
        http_request,
        current_user,
        action="ci_relationship_type_updated",
        entity_type="ci_relationship_type",
        entity_id=relationship_type.id,
        tenant_id=relationship_type.tenant_id,
        metadata={
            "before": before,
            "after": updates,
            "version": relationship_type.version,
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    db.refresh(relationship_type)
    return _type_response(db, relationship_type)


@router.get("/relationships", response_model=list[RelationshipResponse])
def list_relationships(
    ci_id: str,
    include_retired: bool = False,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RelationshipResponse]:
    require_permissions(current_user, "assets.read")
    asset = _asset_or_404(db, ci_id, current_user)
    statement = select(ConfigurationItemRelationship).where(
        ConfigurationItemRelationship.tenant_id == asset.tenant_id,
        or_(
            ConfigurationItemRelationship.source_ci_id == asset.id,
            ConfigurationItemRelationship.target_ci_id == asset.id,
        ),
    )
    if not include_retired:
        statement = statement.where(
            ConfigurationItemRelationship.status == "ACTIVE"
        )
    relationships = db.scalars(
        statement.order_by(ConfigurationItemRelationship.created_at.desc())
    ).all()
    return [_relationship_response(db, item) for item in relationships]


@router.post(
    "/relationships",
    response_model=RelationshipResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_relationship(
    payload: RelationshipCreate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RelationshipResponse:
    require_permissions(current_user, "assets.update")
    relationship_type = _relationship_type_or_404(
        db,
        payload.relationship_type_id,
        current_user,
        lock=True,
    )
    source = _asset_or_404(db, payload.source_ci_id, current_user)
    target = _asset_or_404(db, payload.target_ci_id, current_user)
    duplicate = db.scalar(
        select(ConfigurationItemRelationship.id).where(
            ConfigurationItemRelationship.relationship_type_id
            == relationship_type.id,
            ConfigurationItemRelationship.source_ci_id == source.id,
            ConfigurationItemRelationship.target_ci_id == target.id,
            ConfigurationItemRelationship.status == "ACTIVE",
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="CI relationship already exists")
    _validate_relationship(db, relationship_type, source, target)
    relationship = db.scalar(
        select(ConfigurationItemRelationship).where(
            ConfigurationItemRelationship.relationship_type_id
            == relationship_type.id,
            ConfigurationItemRelationship.source_ci_id == source.id,
            ConfigurationItemRelationship.target_ci_id == target.id,
            ConfigurationItemRelationship.status == "RETIRED",
        )
    )
    now = _now()
    if relationship:
        relationship.status = "ACTIVE"
        relationship.version += 1
        relationship.description = (
            payload.description.strip() if payload.description else None
        )
        relationship.created_by_id = current_user.id
        relationship.retired_by_id = None
        relationship.created_at = now
        relationship.updated_at = now
        relationship.retired_at = None
    else:
        relationship = ConfigurationItemRelationship(
            id=str(uuid.uuid4()),
            tenant_id=relationship_type.tenant_id,
            relationship_type_id=relationship_type.id,
            source_ci_id=source.id,
            target_ci_id=target.id,
            status="ACTIVE",
            version=1,
            description=(
                payload.description.strip() if payload.description else None
            ),
            created_by_id=current_user.id,
            created_at=now,
            updated_at=now,
        )
        db.add(relationship)
    db.flush()
    _history(
        db,
        relationship,
        relationship_type,
        current_user,
        action="ci_relationship_created",
        reason=relationship.description or "CI relationship created",
    )
    _audit(
        db,
        http_request,
        current_user,
        action="ci_relationship_created",
        entity_type="ci_relationship",
        entity_id=relationship.id,
        tenant_id=relationship.tenant_id,
        metadata={
            "relationship_type_id": relationship_type.id,
            "relationship_type_code": relationship_type.code,
            "source_ci_id": source.id,
            "target_ci_id": target.id,
            "version": relationship.version,
        },
    )
    db.commit()
    db.refresh(relationship)
    return _relationship_response(
        db,
        relationship,
        assets={source.id: source, target.id: target},
        relationship_types={relationship_type.id: relationship_type},
    )


@router.post(
    "/relationships/{relationship_id}/retire",
    response_model=RelationshipResponse,
)
def retire_relationship(
    relationship_id: str,
    payload: RelationshipRetire,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RelationshipResponse:
    require_permissions(current_user, "assets.update")
    relationship = _relationship_or_404(
        db,
        relationship_id,
        current_user,
        lock=True,
    )
    if relationship.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="CI relationship is not active")
    if relationship.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=(
                "CI relationship changed; "
                f"current version is {relationship.version}"
            ),
        )
    relationship_type = db.get(
        ConfigurationItemRelationshipType,
        relationship.relationship_type_id,
    )
    if relationship_type is None:
        raise HTTPException(status_code=409, detail="CI relationship type is missing")
    relationship.status = "RETIRED"
    relationship.version += 1
    relationship.retired_by_id = current_user.id
    relationship.retired_at = _now()
    relationship.updated_at = relationship.retired_at
    _history(
        db,
        relationship,
        relationship_type,
        current_user,
        action="ci_relationship_retired",
        reason=payload.reason.strip(),
    )
    _audit(
        db,
        http_request,
        current_user,
        action="ci_relationship_retired",
        entity_type="ci_relationship",
        entity_id=relationship.id,
        tenant_id=relationship.tenant_id,
        metadata={
            "relationship_type_id": relationship.relationship_type_id,
            "source_ci_id": relationship.source_ci_id,
            "target_ci_id": relationship.target_ci_id,
            "version": relationship.version,
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    db.refresh(relationship)
    return _relationship_response(
        db,
        relationship,
        relationship_types={relationship_type.id: relationship_type},
    )


@router.get("/topology/{ci_id}", response_model=TopologyResponse)
def get_topology(
    ci_id: str,
    direction: Literal["upstream", "downstream", "both"] = "both",
    depth: int = Query(default=3, ge=1, le=8),
    max_nodes: int = Query(default=200, ge=2, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TopologyResponse:
    require_permissions(current_user, "assets.read")
    root = _asset_or_404(db, ci_id, current_user)
    visited = {root.id}
    depths = {root.id: 0}
    frontier = {root.id}
    edge_map: dict[str, ConfigurationItemRelationship] = {}
    truncated = False

    for current_depth in range(1, depth + 1):
        if not frontier:
            break
        direction_filters = []
        if direction in {"downstream", "both"}:
            direction_filters.append(
                ConfigurationItemRelationship.source_ci_id.in_(frontier)
            )
        if direction in {"upstream", "both"}:
            direction_filters.append(
                ConfigurationItemRelationship.target_ci_id.in_(frontier)
            )
        relationships = db.scalars(
            select(ConfigurationItemRelationship).where(
                ConfigurationItemRelationship.tenant_id == root.tenant_id,
                ConfigurationItemRelationship.status == "ACTIVE",
                or_(*direction_filters),
            )
        ).all()
        next_frontier: set[str] = set()
        for relationship in relationships:
            candidates: list[str] = []
            if (
                direction in {"downstream", "both"}
                and relationship.source_ci_id in frontier
            ):
                candidates.append(relationship.target_ci_id)
            if (
                direction in {"upstream", "both"}
                and relationship.target_ci_id in frontier
            ):
                candidates.append(relationship.source_ci_id)
            for candidate in candidates:
                if candidate in visited:
                    edge_map[relationship.id] = relationship
                    continue
                if len(visited) >= max_nodes:
                    truncated = True
                    continue
                visited.add(candidate)
                depths[candidate] = current_depth
                next_frontier.add(candidate)
                edge_map[relationship.id] = relationship
        frontier = next_frontier

    assets = {
        asset.id: asset
        for asset in db.scalars(
            select(Asset).where(
                Asset.tenant_id == root.tenant_id,
                Asset.id.in_(visited),
            )
        ).all()
    }
    relationships = [
        relationship
        for relationship in edge_map.values()
        if relationship.source_ci_id in assets and relationship.target_ci_id in assets
    ]
    type_ids = {item.relationship_type_id for item in relationships}
    relationship_types = {
        item.id: item
        for item in db.scalars(
            select(ConfigurationItemRelationshipType).where(
                ConfigurationItemRelationshipType.id.in_(type_ids)
            )
        ).all()
    } if type_ids else {}
    ordered_assets = sorted(
        assets.values(),
        key=lambda item: (depths.get(item.id, depth + 1), item.name.lower()),
    )
    return TopologyResponse(
        root_ci_id=root.id,
        direction=direction,
        requested_depth=depth,
        nodes=[_node(asset, depths.get(asset.id)) for asset in ordered_assets],
        edges=[
            _relationship_response(
                db,
                relationship,
                depths=depths,
                assets=assets,
                relationship_types=relationship_types,
            )
            for relationship in sorted(
                relationships,
                key=lambda item: (item.created_at, item.id),
            )
        ],
        truncated=truncated,
    )
