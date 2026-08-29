from __future__ import annotations

from datetime import UTC, datetime
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.catalog_form import CatalogFormVersion
from app.models.service_catalog import CatalogItem
from app.services.audit import log_audit
from app.services.catalog_forms import (
    canonical_json,
    default_attachment_rules,
    default_schema,
    schema_hash,
    validate_form_definition,
    validate_submission,
)
from app.services.rbac import has_permission, is_saas_root, require_permissions


router = APIRouter(prefix="/catalog")


class CatalogFormResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    tenant_id: str
    catalog_item_id: str
    version: int
    revision: int
    status: str
    schema_hash: str
    form_schema: dict[str, Any] = Field(alias="schema", serialization_alias="schema")
    attachment_rules: dict[str, Any]
    published_at: datetime | None
    retired_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CatalogFormUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expected_revision: int = Field(ge=1)
    form_schema: dict[str, Any] = Field(alias="schema", serialization_alias="schema")
    attachment_rules: dict[str, Any] = Field(default_factory=default_attachment_rules)


class CatalogFormPublishRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


class AttachmentMetadata(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0, le=104_857_600)
    content_type: str | None = Field(default=None, max_length=160)


class CatalogFormValidationRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    attachments: list[AttachmentMetadata] = Field(default_factory=list, max_length=20)


class CatalogFormValidationResponse(BaseModel):
    valid: bool
    form_version: int
    schema_hash: str
    errors: dict[str, list[str]]
    normalized_values: dict[str, Any]
    visible_fields: list[str]


def _form_response(form: CatalogFormVersion) -> CatalogFormResponse:
    return CatalogFormResponse(
        id=form.id,
        tenant_id=form.tenant_id,
        catalog_item_id=form.catalog_item_id,
        version=form.version,
        revision=form.revision,
        status=form.status,
        schema_hash=form.schema_hash,
        form_schema=json.loads(form.schema_json),
        attachment_rules=json.loads(form.attachment_rules_json),
        published_at=form.published_at,
        retired_at=form.retired_at,
        created_at=form.created_at,
        updated_at=form.updated_at,
    )


def _get_item(
    db: Session,
    item_id: str,
    current_user: AuthUserResponse,
    *,
    require_published: bool = False,
) -> CatalogItem:
    item = db.get(CatalogItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    if not is_saas_root(current_user) and item.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    if require_published and item.lifecycle_status != "PUBLISHED":
        raise HTTPException(status_code=404, detail="Catalog item not found")
    return item


def _draft(db: Session, item_id: str) -> CatalogFormVersion | None:
    return db.scalar(
        select(CatalogFormVersion)
        .where(
            CatalogFormVersion.catalog_item_id == item_id,
            CatalogFormVersion.status == "DRAFT",
        )
        .order_by(CatalogFormVersion.version.desc())
    )


def _published(db: Session, item_id: str) -> CatalogFormVersion | None:
    return db.scalar(
        select(CatalogFormVersion)
        .where(
            CatalogFormVersion.catalog_item_id == item_id,
            CatalogFormVersion.status == "PUBLISHED",
        )
        .order_by(CatalogFormVersion.version.desc())
    )


def _audit(
    db: Session,
    http_request: Request,
    current_user: AuthUserResponse,
    *,
    action: str,
    form: CatalogFormVersion,
    metadata: dict[str, object],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type="catalog_form_version",
        entity_id=form.id,
        actor_email=current_user.email,
        tenant_id=form.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "catalog_item_id": form.catalog_item_id,
            "form_version": form.version,
            "revision": form.revision,
            **metadata,
        },
    )


@router.get(
    "/items/{item_id}/form",
    response_model=CatalogFormResponse,
)
def get_catalog_form(
    item_id: str,
    mode: Literal["published", "draft"] = Query(default="published"),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogFormResponse:
    require_permissions(current_user, "catalog.read")
    if mode == "draft":
        require_permissions(current_user, "catalog.manage")
        _get_item(db, item_id, current_user)
        form = _draft(db, item_id)
    else:
        _get_item(
            db,
            item_id,
            current_user,
            require_published=not has_permission(current_user, "catalog.manage"),
        )
        form = _published(db, item_id)
    if form is None:
        raise HTTPException(status_code=404, detail="Catalog form not found")
    return _form_response(form)


@router.get(
    "/items/{item_id}/form/versions",
    response_model=list[CatalogFormResponse],
)
def list_catalog_form_versions(
    item_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CatalogFormResponse]:
    require_permissions(current_user, "catalog.manage")
    _get_item(db, item_id, current_user)
    forms = db.scalars(
        select(CatalogFormVersion)
        .where(CatalogFormVersion.catalog_item_id == item_id)
        .order_by(CatalogFormVersion.version.desc())
    ).all()
    return [_form_response(form) for form in forms]


@router.post(
    "/items/{item_id}/form/draft",
    response_model=CatalogFormResponse,
    status_code=201,
)
def initialize_catalog_form_draft(
    item_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogFormResponse:
    require_permissions(current_user, "catalog.manage")
    item = _get_item(db, item_id, current_user)
    if item.lifecycle_status == "RETIRED":
        raise HTTPException(status_code=409, detail="Retired catalog items are immutable")
    existing = _draft(db, item_id)
    if existing is not None:
        return _form_response(existing)

    published = _published(db, item_id)
    latest_version = db.scalar(
        select(func.max(CatalogFormVersion.version)).where(
            CatalogFormVersion.catalog_item_id == item_id
        )
    )
    schema = json.loads(published.schema_json) if published else default_schema()
    attachment_rules = (
        json.loads(published.attachment_rules_json)
        if published
        else default_attachment_rules()
    )
    form = CatalogFormVersion(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        catalog_item_id=item.id,
        version=(latest_version or 0) + 1,
        revision=1,
        status="DRAFT",
        schema_json=canonical_json(schema),
        attachment_rules_json=canonical_json(attachment_rules),
        schema_hash=schema_hash(schema, attachment_rules),
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(form)
    db.flush()
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_form_draft_created",
        form=form,
        metadata={"copied_from_version": published.version if published else None},
    )
    db.commit()
    db.refresh(form)
    return _form_response(form)


@router.put(
    "/items/{item_id}/form/draft",
    response_model=CatalogFormResponse,
)
def update_catalog_form_draft(
    item_id: str,
    payload: CatalogFormUpdateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogFormResponse:
    require_permissions(current_user, "catalog.manage")
    item = _get_item(db, item_id, current_user)
    if item.lifecycle_status == "RETIRED":
        raise HTTPException(status_code=409, detail="Retired catalog items are immutable")
    form = _draft(db, item_id)
    if form is None:
        raise HTTPException(status_code=404, detail="Catalog form draft not found")
    if form.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail="Catalog form draft was changed by another user",
        )
    definition_errors = validate_form_definition(
        payload.form_schema,
        payload.attachment_rules,
    )
    if definition_errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Catalog form definition is invalid", "errors": definition_errors},
        )

    form.schema_json = canonical_json(payload.form_schema)
    form.attachment_rules_json = canonical_json(payload.attachment_rules)
    form.schema_hash = schema_hash(payload.form_schema, payload.attachment_rules)
    form.revision += 1
    form.updated_by_id = current_user.id
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_form_draft_updated",
        form=form,
        metadata={
            "field_count": len(payload.form_schema.get("fields", [])),
            "section_count": len(payload.form_schema.get("sections", [])),
        },
    )
    db.commit()
    db.refresh(form)
    return _form_response(form)


@router.post(
    "/items/{item_id}/form/publish",
    response_model=CatalogFormResponse,
)
def publish_catalog_form(
    item_id: str,
    payload: CatalogFormPublishRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogFormResponse:
    require_permissions(current_user, "catalog.publish")
    item = _get_item(db, item_id, current_user)
    if item.lifecycle_status == "RETIRED":
        raise HTTPException(status_code=409, detail="Retired catalog items are immutable")
    form = _draft(db, item_id)
    if form is None:
        raise HTTPException(status_code=404, detail="Catalog form draft not found")
    if form.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail="Catalog form draft was changed by another user",
        )
    schema = json.loads(form.schema_json)
    attachment_rules = json.loads(form.attachment_rules_json)
    definition_errors = validate_form_definition(schema, attachment_rules)
    if definition_errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Catalog form definition is invalid", "errors": definition_errors},
        )
    now = datetime.now(UTC)
    previous = _published(db, item_id)
    if previous is not None:
        previous.status = "RETIRED"
        previous.retired_at = now
        previous.updated_by_id = current_user.id
    form.status = "PUBLISHED"
    form.published_at = now
    form.published_by_id = current_user.id
    form.updated_by_id = current_user.id
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_form_published",
        form=form,
        metadata={
            "reason": payload.reason.strip(),
            "superseded_version": previous.version if previous else None,
            "schema_hash": form.schema_hash,
        },
    )
    db.commit()
    db.refresh(form)
    return _form_response(form)


@router.post(
    "/items/{item_id}/form/validate",
    response_model=CatalogFormValidationResponse,
)
def validate_catalog_form_submission(
    item_id: str,
    payload: CatalogFormValidationRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogFormValidationResponse:
    require_permissions(current_user, "catalog.read")
    _get_item(
        db,
        item_id,
        current_user,
        require_published=not has_permission(current_user, "catalog.manage"),
    )
    form = _published(db, item_id)
    if form is None:
        raise HTTPException(status_code=404, detail="Published catalog form not found")
    errors, normalized, visible_fields = validate_submission(
        json.loads(form.schema_json),
        json.loads(form.attachment_rules_json),
        payload.values,
        [attachment.model_dump() for attachment in payload.attachments],
    )
    return CatalogFormValidationResponse(
        valid=not errors,
        form_version=form.version,
        schema_hash=form.schema_hash,
        errors=errors,
        normalized_values=normalized,
        visible_fields=visible_fields,
    )
