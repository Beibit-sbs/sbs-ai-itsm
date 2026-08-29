from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.global_search import SavedSearchView
from app.models.role import Role
from app.models.user import User
from app.services.audit import log_audit
from app.services.global_search import (
    SEARCH_ENTITY_TYPES,
    SearchRecord,
    normalize_entity_types,
    run_global_search,
)
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/search")
MAX_QUERY_LENGTH = 100
MAX_SAVED_VIEWS = 50


class GlobalSearchResult(BaseModel):
    entity_type: str
    id: str
    tenant_id: str | None
    identifier: str
    title: str
    subtitle: str | None
    status: str | None
    href: str
    updated_at: datetime
    score: int
    matched_fields: list[str]


class GlobalSearchResponse(BaseModel):
    items: list[GlobalSearchResult]
    counts: dict[str, int]
    selected_types: list[str]
    total: int
    query_sha256: str
    duration_ms: int


class SavedSearchQuery(BaseModel):
    q: str = Field(min_length=2, max_length=MAX_QUERY_LENGTH)
    types: list[str] = Field(default_factory=lambda: list(SEARCH_ENTITY_TYPES))

    @field_validator("q")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 2:
            raise ValueError("Search query must contain at least 2 characters")
        return normalized

    @field_validator("types")
    @classmethod
    def validate_types(cls, value: list[str]) -> list[str]:
        try:
            normalized = normalize_entity_types(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if not normalized:
            raise ValueError("At least one entity type is required")
        return normalized


class SavedSearchViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    query: SavedSearchQuery
    is_shared: bool = False
    shared_role_codes: list[str] = Field(default_factory=list, max_length=20)
    tenant_id: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Saved view name is required")
        return normalized


class SavedSearchViewUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    query: SavedSearchQuery | None = None
    is_shared: bool | None = None
    shared_role_codes: list[str] | None = Field(default=None, max_length=20)

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Saved view name is required")
        return normalized


class SavedSearchViewResponse(BaseModel):
    id: str
    tenant_id: str | None
    owner_user_id: str
    name: str
    query: SavedSearchQuery
    query_sha256: str
    is_shared: bool
    shared_role_codes: list[str]
    is_owner: bool
    revision: int
    created_at: datetime
    updated_at: datetime


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_types(raw: str | None) -> list[str]:
    values = raw.split(",") if raw else None
    try:
        return normalize_entity_types(values)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.get(User, current_user.id)


def _serialize_view(
    view: SavedSearchView,
    current_user: AuthUserResponse,
) -> SavedSearchViewResponse:
    return SavedSearchViewResponse(
        id=view.id,
        tenant_id=view.tenant_id,
        owner_user_id=view.owner_user_id,
        name=view.name,
        query=SavedSearchQuery.model_validate(json.loads(view.query_json)),
        query_sha256=view.query_sha256,
        is_shared=view.is_shared,
        shared_role_codes=list(json.loads(view.shared_role_codes_json)),
        is_owner=view.owner_user_id == current_user.id,
        revision=view.revision,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _view_scope(
    current_user: AuthUserResponse,
    *,
    tenant_id: str | None = None,
):
    shared_for_role = and_(
        SavedSearchView.is_shared.is_(True),
        SavedSearchView.shared_role_codes_json.contains(
            f'"{current_user.role}"'
        ),
    )
    statement = select(SavedSearchView).where(
        or_(
            SavedSearchView.owner_user_id == current_user.id,
            shared_for_role,
        )
    )
    if is_saas_root(current_user):
        if tenant_id is not None:
            statement = statement.where(SavedSearchView.tenant_id == tenant_id)
        return statement
    return statement.where(SavedSearchView.tenant_id == current_user.tenant_id)


def _get_owned_view(
    db: Session,
    view_id: str,
    current_user: AuthUserResponse,
) -> SavedSearchView:
    view = db.get(SavedSearchView, view_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Saved search view not found")
    if view.owner_user_id != current_user.id and not is_saas_root(current_user):
        raise HTTPException(status_code=404, detail="Saved search view not found")
    if (
        not is_saas_root(current_user)
        and view.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Saved search view not found")
    return view


def _validated_roles(
    db: Session,
    current_user: AuthUserResponse,
    *,
    tenant_id: str | None,
    is_shared: bool,
    role_codes: list[str],
) -> list[str]:
    normalized = sorted(
        {
            item.strip().lower()
            for item in role_codes
            if item and item.strip()
        }
    )
    if not is_shared:
        return []
    require_permissions(current_user, "search.views.share")
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail="Shared views require at least one target role",
        )
    statement = select(Role.code).where(Role.code.in_(normalized))
    if tenant_id is not None:
        statement = statement.where(Role.tenant_id == tenant_id)
    available = set(db.scalars(statement).all())
    missing = sorted(set(normalized) - available)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown target roles: {', '.join(missing)}",
        )
    return normalized


@router.get("", response_model=GlobalSearchResponse)
def global_search(
    http_request: Request,
    q: str = Query(min_length=2, max_length=MAX_QUERY_LENGTH),
    types: str | None = Query(default=None, max_length=200),
    per_type_limit: int = Query(default=8, ge=1, le=20),
    total_limit: int = Query(default=40, ge=1, le=100),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GlobalSearchResponse:
    require_permissions(current_user, "search.use")
    normalized_query = " ".join(q.strip().split())
    if len(normalized_query) < 2:
        raise HTTPException(status_code=422, detail="Search query is too short")
    selected_types = _parse_types(types)
    started_at = time.perf_counter()
    records, counts = run_global_search(
        db,
        current_user,
        query=normalized_query,
        entity_types=selected_types,
        per_type_limit=per_type_limit,
        total_limit=total_limit,
    )
    duration_ms = round((time.perf_counter() - started_at) * 1000)
    query_sha256 = _sha256(normalized_query.casefold())
    log_audit(
        db,
        action="global_search.executed",
        entity_type="global_search",
        entity_id=None,
        actor_user=_actor(db, current_user),
        tenant_id=current_user.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "query_sha256": query_sha256,
            "selected_types": selected_types,
            "result_counts": counts,
            "result_total": len(records),
            "duration_ms": duration_ms,
        },
    )
    db.commit()
    return GlobalSearchResponse(
        items=[
            GlobalSearchResult.model_validate(record.__dict__)
            for record in records
            if isinstance(record, SearchRecord)
        ],
        counts=counts,
        selected_types=selected_types,
        total=len(records),
        query_sha256=query_sha256,
        duration_ms=duration_ms,
    )


@router.get("/views", response_model=list[SavedSearchViewResponse])
def list_saved_search_views(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SavedSearchViewResponse]:
    require_permissions(current_user, "search.views.manage")
    if not is_saas_root(current_user) and tenant_id not in (
        None,
        current_user.tenant_id,
    ):
        raise HTTPException(status_code=403, detail="Tenant access denied")
    rows = db.scalars(
        _view_scope(current_user, tenant_id=tenant_id).order_by(
            SavedSearchView.is_shared.desc(),
            SavedSearchView.updated_at.desc(),
        )
    ).all()
    return [_serialize_view(row, current_user) for row in rows]


@router.post(
    "/views",
    response_model=SavedSearchViewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_saved_search_view(
    payload: SavedSearchViewCreate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedSearchViewResponse:
    require_permissions(current_user, "search.views.manage")
    tenant_id = payload.tenant_id if is_saas_root(current_user) else current_user.tenant_id
    if not is_saas_root(current_user) and payload.tenant_id not in (None, tenant_id):
        raise HTTPException(status_code=403, detail="Tenant access denied")
    owned_count = int(
        db.scalar(
            select(func.count(SavedSearchView.id)).where(
                SavedSearchView.owner_user_id == current_user.id
            )
        )
        or 0
    )
    if owned_count >= MAX_SAVED_VIEWS:
        raise HTTPException(
            status_code=409,
            detail=f"Saved view limit reached ({MAX_SAVED_VIEWS})",
        )
    existing = db.scalar(
        select(SavedSearchView.id).where(
            SavedSearchView.owner_user_id == current_user.id,
            SavedSearchView.tenant_id == tenant_id,
            func.lower(SavedSearchView.name) == payload.name.lower(),
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Saved view name already exists")
    role_codes = _validated_roles(
        db,
        current_user,
        tenant_id=tenant_id,
        is_shared=payload.is_shared,
        role_codes=payload.shared_role_codes,
    )
    query_json = _canonical_json(payload.query.model_dump())
    view = SavedSearchView(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        owner_user_id=current_user.id,
        name=payload.name,
        query_json=query_json,
        query_sha256=_sha256(query_json),
        is_shared=payload.is_shared,
        shared_role_codes_json=_canonical_json(role_codes),
        revision=1,
    )
    db.add(view)
    log_audit(
        db,
        action="global_search.view_created",
        entity_type="saved_search_view",
        entity_id=view.id,
        actor_user=_actor(db, current_user),
        tenant_id=tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "query_sha256": view.query_sha256,
            "is_shared": view.is_shared,
            "shared_role_codes": role_codes,
            "revision": view.revision,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Saved view name already exists",
        ) from exc
    db.refresh(view)
    return _serialize_view(view, current_user)


@router.patch("/views/{view_id}", response_model=SavedSearchViewResponse)
def update_saved_search_view(
    view_id: str,
    payload: SavedSearchViewUpdate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedSearchViewResponse:
    require_permissions(current_user, "search.views.manage")
    view = _get_owned_view(db, view_id, current_user)
    if view.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail=f"Revision conflict: current revision is {view.revision}",
        )
    next_shared = payload.is_shared if payload.is_shared is not None else view.is_shared
    current_roles = list(json.loads(view.shared_role_codes_json))
    next_roles = (
        payload.shared_role_codes
        if payload.shared_role_codes is not None
        else current_roles
    )
    validated_roles = _validated_roles(
        db,
        current_user,
        tenant_id=view.tenant_id,
        is_shared=next_shared,
        role_codes=next_roles,
    )
    if payload.name is not None:
        view.name = payload.name
    if payload.query is not None:
        view.query_json = _canonical_json(payload.query.model_dump())
        view.query_sha256 = _sha256(view.query_json)
    view.is_shared = next_shared
    view.shared_role_codes_json = _canonical_json(validated_roles)
    view.revision += 1
    log_audit(
        db,
        action="global_search.view_updated",
        entity_type="saved_search_view",
        entity_id=view.id,
        actor_user=_actor(db, current_user),
        tenant_id=view.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "query_sha256": view.query_sha256,
            "is_shared": view.is_shared,
            "shared_role_codes": validated_roles,
            "revision": view.revision,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Saved view name already exists",
        ) from exc
    db.refresh(view)
    return _serialize_view(view, current_user)


@router.delete("/views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_search_view(
    view_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    require_permissions(current_user, "search.views.manage")
    view = _get_owned_view(db, view_id, current_user)
    evidence = {
        "query_sha256": view.query_sha256,
        "is_shared": view.is_shared,
        "revision": view.revision,
    }
    tenant_id = view.tenant_id
    db.delete(view)
    log_audit(
        db,
        action="global_search.view_deleted",
        entity_type="saved_search_view",
        entity_id=view_id,
        actor_user=_actor(db, current_user),
        tenant_id=tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata=evidence,
    )
    db.commit()
