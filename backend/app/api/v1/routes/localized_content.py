from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.knowledge_article import KnowledgeArticle
from app.models.localized_content import LocalizedContentVariant
from app.models.notification_template import NotificationTemplate
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.localized_content import (
    LocalizedContentError,
    digest,
    is_source_current,
    normalize_locale,
    normalize_resource_type,
    source_evidence,
    validate_translation_payload,
    variant_integrity,
    variant_payload,
)
from app.services.rbac import is_saas_root, require_permissions
from app.services.tenant_experience import canonical_json


router = APIRouter(prefix="/tenant-content-translations")
MAX_VERSIONS_PER_RESOURCE_LOCALE = 50


class TranslationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str | None = None
    resource_type: str = Field(min_length=2, max_length=32)
    resource_id: str = Field(min_length=1, max_length=80)
    locale: str = Field(min_length=2, max_length=16)
    payload: dict[str, str]


class TranslationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    payload: dict[str, str]


class TranslationSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    submission_note: str = Field(min_length=5, max_length=500)


class TranslationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    decision: str = Field(pattern="^(APPROVE|REJECT)$")
    review_comment: str = Field(min_length=5, max_length=1_000)


class TranslationResponse(BaseModel):
    id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    locale: str
    version: int
    revision: int
    status: str
    source_sha256: str
    source_current: bool
    payload: dict[str, str]
    payload_sha256: str
    integrity_valid: bool
    created_by_id: str | None
    updated_by_id: str | None
    reviewed_by_id: str | None
    review_comment: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TranslationSourceResponse(BaseModel):
    id: str
    resource_type: str
    source_tenant_id: str | None
    inherited: bool
    code: str
    label: str
    payload: dict[str, str]
    source_sha256: str
    updated_at: datetime


def _tenant_id(
    db: Session,
    user: AuthUserResponse,
    requested: str | None,
) -> str:
    if is_saas_root(user):
        if not requested or db.get(Tenant, requested) is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="SaaS Root must select a valid tenant",
            )
        return requested
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session has no tenant scope",
        )
    if requested and requested != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Translation not found",
        )
    return user.tenant_id


def _response(db: Session, item: LocalizedContentVariant) -> TranslationResponse:
    try:
        payload = variant_payload(item)
    except (LocalizedContentError, json.JSONDecodeError):
        payload = {}
    return TranslationResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        locale=item.locale,
        version=item.version,
        revision=item.revision,
        status=item.status,
        source_sha256=item.source_sha256,
        source_current=is_source_current(db, item),
        payload=payload,
        payload_sha256=item.payload_sha256,
        integrity_valid=variant_integrity(item),
        created_by_id=item.created_by_id,
        updated_by_id=item.updated_by_id,
        reviewed_by_id=item.reviewed_by_id,
        review_comment=item.review_comment,
        submitted_at=item.submitted_at,
        reviewed_at=item.reviewed_at,
        published_at=item.published_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _item(
    db: Session,
    translation_id: str,
    tenant_id: str,
    *,
    for_update: bool = False,
) -> LocalizedContentVariant:
    statement = select(LocalizedContentVariant).where(
        LocalizedContentVariant.id == translation_id,
        LocalizedContentVariant.tenant_id == tenant_id,
    )
    if for_update and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Translation not found")
    return item


def _audit(
    db: Session,
    request: Request,
    user: AuthUserResponse,
    item: LocalizedContentVariant,
    action: str,
    metadata: dict[str, object],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type="localized_content",
        entity_id=item.id,
        actor_user=db.get(User, user.id),
        tenant_id=item.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={
            "resource_type": item.resource_type,
            "resource_id": item.resource_id,
            "locale": item.locale,
            "version": item.version,
            "revision": item.revision,
            "status": item.status,
            "source_sha256": item.source_sha256,
            "payload_sha256": item.payload_sha256,
            **metadata,
        },
    )


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Concurrent translation change detected",
        ) from exc


@router.get("", response_model=list[TranslationResponse])
def list_translations(
    tenant_id: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    locale: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TranslationResponse]:
    require_permissions(current_user, "tenant.translations.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statement = select(LocalizedContentVariant).where(
        LocalizedContentVariant.tenant_id == scope
    )
    try:
        if resource_type:
            statement = statement.where(
                LocalizedContentVariant.resource_type
                == normalize_resource_type(resource_type)
            )
        if locale:
            statement = statement.where(
                LocalizedContentVariant.locale == normalize_locale(locale)
            )
    except LocalizedContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if resource_id:
        statement = statement.where(
            LocalizedContentVariant.resource_id == resource_id
        )
    rows = db.scalars(
        statement.order_by(
            LocalizedContentVariant.updated_at.desc(),
            LocalizedContentVariant.version.desc(),
        ).limit(500)
    ).all()
    return [_response(db, item) for item in rows]


@router.get("/sources", response_model=list[TranslationSourceResponse])
def list_translation_sources(
    resource_type: str = Query(),
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TranslationSourceResponse]:
    require_permissions(current_user, "tenant.translations.read")
    scope = _tenant_id(db, current_user, tenant_id)
    try:
        normalized_type = normalize_resource_type(resource_type)
    except LocalizedContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if normalized_type == "KNOWLEDGE_ARTICLE":
        sources = db.scalars(
            select(KnowledgeArticle)
            .where(
                (KnowledgeArticle.tenant_id == scope)
                | (KnowledgeArticle.tenant_id.is_(None))
            )
            .order_by(
                KnowledgeArticle.updated_at.desc(),
                KnowledgeArticle.article_number.asc(),
            )
            .limit(500)
        ).all()
        return [
            TranslationSourceResponse(
                id=item.id,
                resource_type=normalized_type,
                source_tenant_id=item.tenant_id,
                inherited=item.tenant_id is None,
                code=item.article_number,
                label=item.title,
                payload={
                    "title": item.title,
                    "summary": item.summary,
                    "content": item.content,
                },
                source_sha256=digest(
                    {
                        "title": item.title,
                        "summary": item.summary,
                        "content": item.content,
                    }
                ),
                updated_at=item.updated_at,
            )
            for item in sources
        ]

    templates = db.scalars(
        select(NotificationTemplate)
        .where(
            (NotificationTemplate.tenant_id == scope)
            | (NotificationTemplate.tenant_id.is_(None))
        )
        .order_by(
            NotificationTemplate.code.asc(),
            NotificationTemplate.tenant_id.desc(),
        )
        .limit(500)
    ).all()
    return [
        TranslationSourceResponse(
            id=item.id,
            resource_type=normalized_type,
            source_tenant_id=item.tenant_id,
            inherited=item.tenant_id is None,
            code=item.code,
            label=item.name,
            payload={
                "name": item.name,
                "subject_template": item.subject_template,
                "body_template": item.body_template,
            },
            source_sha256=digest(
                {
                    "name": item.name,
                    "subject_template": item.subject_template,
                    "body_template": item.body_template,
                }
            ),
            updated_at=item.updated_at,
        )
        for item in templates
    ]


@router.post("", response_model=TranslationResponse, status_code=201)
def create_translation(
    payload: TranslationCreateRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranslationResponse:
    require_permissions(current_user, "tenant.translations.manage")
    scope = _tenant_id(db, current_user, payload.tenant_id)
    try:
        resource_type = normalize_resource_type(payload.resource_type)
        locale = normalize_locale(payload.locale)
        source, source_sha256 = source_evidence(
            db,
            tenant_id=scope,
            resource_type=resource_type,
            resource_id=payload.resource_id,
        )
        translated = validate_translation_payload(
            resource_type,
            payload.payload,
            source=source,
        )
    except LocalizedContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    version = int(
        db.scalar(
            select(func.max(LocalizedContentVariant.version)).where(
                LocalizedContentVariant.tenant_id == scope,
                LocalizedContentVariant.resource_type == resource_type,
                LocalizedContentVariant.resource_id == payload.resource_id,
                LocalizedContentVariant.locale == locale,
            )
        )
        or 0
    ) + 1
    if version > MAX_VERSIONS_PER_RESOURCE_LOCALE:
        raise HTTPException(
            status_code=409,
            detail="Translation version retention limit reached",
        )
    now = datetime.now(UTC)
    payload_json = canonical_json(translated)
    item = LocalizedContentVariant(
        id=str(uuid.uuid4()),
        tenant_id=scope,
        resource_type=resource_type,
        resource_id=payload.resource_id,
        locale=locale,
        version=version,
        revision=1,
        status="DRAFT",
        source_sha256=source_sha256,
        payload_json=payload_json,
        payload_sha256=hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    _audit(db, request, current_user, item, "localized_content.created", {})
    _commit(db)
    db.refresh(item)
    return _response(db, item)


@router.put("/{translation_id}", response_model=TranslationResponse)
def update_translation(
    translation_id: str,
    payload: TranslationUpdateRequest,
    request: Request,
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranslationResponse:
    require_permissions(current_user, "tenant.translations.manage")
    scope = _tenant_id(db, current_user, tenant_id)
    item = _item(db, translation_id, scope, for_update=True)
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Translation revision conflict")
    if item.status not in {"DRAFT", "REJECTED"}:
        raise HTTPException(status_code=409, detail="Only draft/rejected content can be edited")
    try:
        source, source_sha256 = source_evidence(
            db,
            tenant_id=scope,
            resource_type=item.resource_type,
            resource_id=item.resource_id,
        )
        translated = validate_translation_payload(
            item.resource_type,
            payload.payload,
            source=source,
        )
    except LocalizedContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload_json = canonical_json(translated)
    item.payload_json = payload_json
    item.payload_sha256 = digest(translated)
    item.source_sha256 = source_sha256
    item.status = "DRAFT"
    item.revision += 1
    item.updated_by_id = current_user.id
    item.review_comment = None
    item.reviewed_by_id = None
    item.reviewed_at = None
    item.updated_at = datetime.now(UTC)
    _audit(db, request, current_user, item, "localized_content.updated", {})
    _commit(db)
    db.refresh(item)
    return _response(db, item)


@router.post("/{translation_id}/submit", response_model=TranslationResponse)
def submit_translation(
    translation_id: str,
    payload: TranslationSubmitRequest,
    request: Request,
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranslationResponse:
    require_permissions(current_user, "tenant.translations.manage")
    scope = _tenant_id(db, current_user, tenant_id)
    item = _item(db, translation_id, scope, for_update=True)
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Translation revision conflict")
    if item.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Only draft content can be submitted")
    if not variant_integrity(item) or not is_source_current(db, item):
        raise HTTPException(status_code=409, detail="Translation or source evidence is stale")
    item.status = "IN_REVIEW"
    item.revision += 1
    item.submitted_at = datetime.now(UTC)
    item.updated_at = item.submitted_at
    item.updated_by_id = current_user.id
    _audit(
        db,
        request,
        current_user,
        item,
        "localized_content.submitted",
        {"submission_note_sha256": digest(payload.submission_note)},
    )
    _commit(db)
    db.refresh(item)
    return _response(db, item)


@router.post("/{translation_id}/decision", response_model=TranslationResponse)
def decide_translation(
    translation_id: str,
    payload: TranslationDecisionRequest,
    request: Request,
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranslationResponse:
    require_permissions(current_user, "tenant.translations.publish")
    scope = _tenant_id(db, current_user, tenant_id)
    item = _item(db, translation_id, scope, for_update=True)
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Translation revision conflict")
    if item.status != "IN_REVIEW":
        raise HTTPException(status_code=409, detail="Translation is not in review")
    if current_user.id in {item.created_by_id, item.updated_by_id}:
        raise HTTPException(
            status_code=409,
            detail="Four-eyes review requires a different publisher",
        )
    if not variant_integrity(item) or not is_source_current(db, item):
        raise HTTPException(
            status_code=409,
            detail="Translation or source changed after submission",
        )
    now = datetime.now(UTC)
    item.revision += 1
    item.reviewed_by_id = current_user.id
    item.review_comment = payload.review_comment.strip()
    item.reviewed_at = now
    item.updated_at = now
    if payload.decision == "REJECT":
        item.status = "REJECTED"
        action = "localized_content.rejected"
    else:
        previous = db.scalars(
            select(LocalizedContentVariant).where(
                LocalizedContentVariant.tenant_id == scope,
                LocalizedContentVariant.resource_type == item.resource_type,
                LocalizedContentVariant.resource_id == item.resource_id,
                LocalizedContentVariant.locale == item.locale,
                LocalizedContentVariant.status == "PUBLISHED",
                LocalizedContentVariant.id != item.id,
            )
        ).all()
        for prior in previous:
            prior.status = "RETIRED"
            prior.revision += 1
            prior.updated_at = now
            prior.updated_by_id = current_user.id
        if previous:
            db.flush()
        item.status = "PUBLISHED"
        item.published_at = now
        action = "localized_content.published"
    _audit(
        db,
        request,
        current_user,
        item,
        action,
        {"review_comment_sha256": digest(payload.review_comment)},
    )
    _commit(db)
    db.refresh(item)
    return _response(db, item)
