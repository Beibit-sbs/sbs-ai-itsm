from __future__ import annotations

from datetime import UTC, datetime
import json
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.catalog_form import CatalogFormVersion
from app.models.catalog_user_preference import CatalogUserPreference
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_category import KnowledgeCategory
from app.models.knowledge_usage_log import KnowledgeUsageLog
from app.models.service_catalog import (
    CatalogItem,
    CatalogItemHistory,
    CatalogService,
    ServiceCategory,
    ServiceOffering,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.catalog_forms import (
    canonical_json,
    default_attachment_rules,
    default_schema,
    schema_hash,
)
from app.services.catalog_governance import (
    entitlement_decision,
    normalize_approval_policy,
    normalize_entitlement_rules,
    normalize_sla_policy,
)
from app.services.catalog_personalization import (
    catalog_preferences_by_item,
    get_catalog_preference,
    touch_catalog_preference,
)
from app.services.rbac import has_permission, is_saas_root, require_permissions


router = APIRouter(prefix="/catalog")
Lifecycle = Literal["DRAFT", "IN_REVIEW", "PUBLISHED", "RETIRED"]
EntityStatus = Literal["ACTIVE", "INACTIVE"]
CostType = Literal["NO_CHARGE", "ONE_TIME", "MONTHLY", "ANNUAL"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"IN_REVIEW"},
    "IN_REVIEW": {"DRAFT", "PUBLISHED"},
    "PUBLISHED": {"RETIRED"},
    "RETIRED": set(),
}
_CODE_PATTERN = re.compile(r"[^A-Z0-9_-]+")


class CategoryCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5_000)
    sort_order: int = Field(default=100, ge=0, le=10_000)
    tenant_id: str | None = None


class CategoryPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5_000)
    clear_description: bool = False
    status: EntityStatus | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)


class ServiceCreateRequest(BaseModel):
    category_id: str
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=10_000)
    owner_user_id: str | None = None
    support_group: str | None = Field(default=None, max_length=160)
    tenant_id: str | None = None


class ServicePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=10_000)
    clear_description: bool = False
    owner_user_id: str | None = None
    clear_owner: bool = False
    support_group: str | None = Field(default=None, max_length=160)
    clear_support_group: bool = False
    status: EntityStatus | None = None


class OfferingCreateRequest(BaseModel):
    service_id: str
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=10_000)
    support_group: str | None = Field(default=None, max_length=160)
    expected_fulfillment_minutes: int = Field(default=1440, ge=5, le=525_600)
    tenant_id: str | None = None


class OfferingPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=10_000)
    clear_description: bool = False
    support_group: str | None = Field(default=None, max_length=160)
    clear_support_group: bool = False
    expected_fulfillment_minutes: int | None = Field(
        default=None, ge=5, le=525_600
    )
    status: EntityStatus | None = None


class CatalogItemCreateRequest(BaseModel):
    category_id: str
    service_id: str
    offering_id: str | None = None
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=3, max_length=200)
    short_description: str = Field(min_length=5, max_length=320)
    description: str = Field(min_length=10, max_length=30_000)
    owner_user_id: str | None = None
    support_group: str | None = Field(default=None, max_length=160)
    expected_delivery_minutes: int = Field(default=1440, ge=5, le=525_600)
    approval_required: bool = False
    entitlement_rules: dict[str, object] = Field(default_factory=dict)
    unit_cost_minor: int = Field(default=0, ge=0, le=9_000_000_000_000_000)
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    cost_type: CostType = "NO_CHARGE"
    risk_level: RiskLevel = "LOW"
    approval_policy: dict[str, object] = Field(default_factory=dict)
    sla_policy: dict[str, object] = Field(default_factory=dict)
    tenant_id: str | None = None


class CatalogItemPatchRequest(BaseModel):
    expected_version: int = Field(ge=1)
    category_id: str | None = None
    service_id: str | None = None
    offering_id: str | None = None
    clear_offering: bool = False
    name: str | None = Field(default=None, min_length=3, max_length=200)
    short_description: str | None = Field(default=None, min_length=5, max_length=320)
    description: str | None = Field(default=None, min_length=10, max_length=30_000)
    owner_user_id: str | None = None
    clear_owner: bool = False
    support_group: str | None = Field(default=None, max_length=160)
    expected_delivery_minutes: int | None = Field(default=None, ge=5, le=525_600)
    approval_required: bool | None = None
    entitlement_rules: dict[str, object] | None = None
    unit_cost_minor: int | None = Field(
        default=None, ge=0, le=9_000_000_000_000_000
    )
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    cost_type: CostType | None = None
    risk_level: RiskLevel | None = None
    approval_policy: dict[str, object] | None = None
    sla_policy: dict[str, object] | None = None


class CatalogTransitionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    target_status: Lifecycle
    reason: str = Field(min_length=3, max_length=5_000)


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    code: str
    name: str
    description: str | None
    status: str
    sort_order: int


class ServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    category_id: str
    code: str
    name: str
    description: str | None
    owner_user_id: str | None
    support_group: str | None
    status: str


class OfferingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    service_id: str
    code: str
    name: str
    description: str | None
    support_group: str | None
    expected_fulfillment_minutes: int
    status: str


class CatalogItemResponse(BaseModel):
    id: str
    tenant_id: str
    category_id: str
    category_name: str
    service_id: str
    service_name: str
    offering_id: str | None
    offering_name: str | None
    code: str
    name: str
    short_description: str
    description: str
    lifecycle_status: str
    version: int
    owner_user_id: str | None
    support_group: str | None
    expected_delivery_minutes: int
    approval_required: bool
    entitlement_rules: dict[str, object]
    unit_cost_minor: int
    currency: str
    cost_type: str
    risk_level: str
    approval_policy: dict[str, object]
    sla_policy: dict[str, object]
    is_entitled: bool = True
    entitlement_reason: str = "Available"
    published_at: datetime | None
    retired_at: datetime | None
    created_at: datetime
    updated_at: datetime
    is_favorite: bool = False
    view_count: int = 0
    request_count: int = 0
    last_viewed_at: datetime | None = None
    last_requested_at: datetime | None = None


class CatalogHistoryResponse(BaseModel):
    id: str
    version: int
    action: str
    lifecycle_status: str
    snapshot: dict[str, object]
    actor_name: str
    actor_email: str
    reason: str | None
    created_at: datetime


class CatalogSummaryResponse(BaseModel):
    categories: int
    services: int
    offerings: int
    draft_items: int
    review_items: int
    published_items: int
    retired_items: int


class CatalogFavoriteRequest(BaseModel):
    is_favorite: bool


class CatalogPreferenceResponse(BaseModel):
    catalog_item_id: str
    is_favorite: bool
    view_count: int
    request_count: int
    last_viewed_at: datetime | None
    last_requested_at: datetime | None


class CatalogKnowledgeSuggestionResponse(BaseModel):
    id: str
    article_number: str
    title: str
    summary: str
    content_preview: str
    category_name: str | None
    tags: list[str] = Field(default_factory=list)
    helpful_count: int
    relevance_score: int


class CatalogDeflectionResponse(BaseModel):
    status: Literal["resolved"]
    catalog_item_id: str
    article_id: str


def _now() -> datetime:
    return datetime.now(UTC)


def _code(value: str) -> str:
    normalized = _CODE_PATTERN.sub("_", value.strip().upper()).strip("_")
    if len(normalized) < 2:
        raise HTTPException(status_code=422, detail="Catalog code is invalid")
    return normalized


def _tenant_id(
    db: Session,
    current_user: AuthUserResponse,
    requested: str | None = None,
) -> str:
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        return current_user.tenant_id
    if requested:
        exists = db.scalar(select(Tenant.id).where(Tenant.id == requested))
        if exists:
            return requested
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    tenant = db.scalar(
        select(Tenant)
        .where(func.lower(Tenant.status) == "active")
        .order_by(Tenant.created_at)
    )
    if tenant is None:
        raise HTTPException(status_code=422, detail="No active tenant is available")
    return tenant.id


def _ensure_unique(
    db: Session,
    model: type[ServiceCategory]
    | type[CatalogService]
    | type[ServiceOffering]
    | type[CatalogItem],
    tenant_id: str,
    code: str,
) -> None:
    if db.scalar(select(model.id).where(model.tenant_id == tenant_id, model.code == code)):
        raise HTTPException(status_code=409, detail=f"Catalog code {code} already exists")


def _ensure_owner(db: Session, tenant_id: str, owner_user_id: str | None) -> None:
    if owner_user_id is None:
        return
    owner = db.get(User, owner_user_id)
    if (
        owner is None
        or (owner.tenant_id != tenant_id and not owner.is_root)
        or not owner.is_active
    ):
        raise HTTPException(status_code=422, detail="Catalog owner is unavailable")


def _tenant_entity(entity, current_user: AuthUserResponse, label: str):
    if entity is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    if not is_saas_root(current_user) and entity.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return entity


def _taxonomy(
    db: Session,
    *,
    tenant_id: str,
    category_id: str,
    service_id: str,
    offering_id: str | None,
) -> tuple[ServiceCategory, CatalogService, ServiceOffering | None]:
    category = db.get(ServiceCategory, category_id)
    service = db.get(CatalogService, service_id)
    offering = db.get(ServiceOffering, offering_id) if offering_id else None
    if category is None or category.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="Catalog category is unavailable")
    if service is None or service.tenant_id != tenant_id or service.category_id != category.id:
        raise HTTPException(status_code=422, detail="Catalog service is unavailable")
    if (
        offering_id
        and (
            offering is None
            or offering.tenant_id != tenant_id
            or offering.service_id != service.id
        )
    ):
        raise HTTPException(status_code=422, detail="Service offering is unavailable")
    return category, service, offering


def _item_query():
    return (
        select(CatalogItem, ServiceCategory, CatalogService, ServiceOffering)
        .join(ServiceCategory, ServiceCategory.id == CatalogItem.category_id)
        .join(CatalogService, CatalogService.id == CatalogItem.service_id)
        .outerjoin(ServiceOffering, ServiceOffering.id == CatalogItem.offering_id)
    )


def _parse_mapping(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _governance_value(
    normalizer,
    value: dict[str, object] | None,
    *,
    field: str,
    **kwargs,
) -> dict[str, object]:
    try:
        return normalizer(value, **kwargs)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field}: {exc}") from exc


def _entitlement(
    db: Session,
    item: CatalogItem,
    current_user: AuthUserResponse,
    *,
    bypass: bool,
) -> tuple[bool, str]:
    return entitlement_decision(
        item,
        user=db.get(User, current_user.id),
        fallback_user_id=current_user.id,
        fallback_tenant_id=current_user.tenant_id,
        fallback_role=current_user.role,
        bypass=bypass,
    )


def _item_response(
    row,
    preference: CatalogUserPreference | None = None,
    entitlement: tuple[bool, str] = (True, "Available"),
) -> CatalogItemResponse:
    item, category, service, offering = row
    return CatalogItemResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        category_id=item.category_id,
        category_name=category.name,
        service_id=item.service_id,
        service_name=service.name,
        offering_id=item.offering_id,
        offering_name=offering.name if offering else None,
        code=item.code,
        name=item.name,
        short_description=item.short_description,
        description=item.description,
        lifecycle_status=item.lifecycle_status,
        version=item.version,
        owner_user_id=item.owner_user_id,
        support_group=item.support_group,
        expected_delivery_minutes=item.expected_delivery_minutes,
        approval_required=item.approval_required,
        entitlement_rules=_parse_mapping(item.entitlement_rules_json),
        unit_cost_minor=item.unit_cost_minor,
        currency=item.currency,
        cost_type=item.cost_type,
        risk_level=item.risk_level,
        approval_policy=_parse_mapping(item.approval_policy_json),
        sla_policy=_parse_mapping(item.sla_policy_json),
        is_entitled=entitlement[0],
        entitlement_reason=entitlement[1],
        published_at=item.published_at,
        retired_at=item.retired_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
        is_favorite=preference.is_favorite if preference else False,
        view_count=preference.view_count if preference else 0,
        request_count=preference.request_count if preference else 0,
        last_viewed_at=preference.last_viewed_at if preference else None,
        last_requested_at=preference.last_requested_at if preference else None,
    )


def _preference_response(
    preference: CatalogUserPreference,
) -> CatalogPreferenceResponse:
    return CatalogPreferenceResponse(
        catalog_item_id=preference.catalog_item_id,
        is_favorite=preference.is_favorite,
        view_count=preference.view_count,
        request_count=preference.request_count,
        last_viewed_at=preference.last_viewed_at,
        last_requested_at=preference.last_requested_at,
    )


_KNOWLEDGE_STOPWORDS = {
    "req",
    "request",
    "service",
    "для",
    "или",
    "как",
    "при",
    "что",
    "это",
    "услуга",
    "услуги",
    "запрос",
}


def _knowledge_terms(item: CatalogItem, category: ServiceCategory) -> list[str]:
    text = f"{item.code} {item.name} {item.short_description} {category.name}".lower()
    terms = {
        token.strip("_-")
        for token in re.findall(r"[\w-]{3,}", text, flags=re.UNICODE)
        if token.strip("_-") not in _KNOWLEDGE_STOPWORDS
    }
    return sorted(terms, key=lambda value: (-len(value), value))[:16]


def _knowledge_tags(article: KnowledgeArticle) -> list[str]:
    if isinstance(article.tags_json, list):
        return [str(tag) for tag in article.tags_json]
    return [tag.strip() for tag in (article.tags or "").split(",") if tag.strip()]


def _snapshot(item: CatalogItem) -> dict[str, object]:
    return {
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "short_description": item.short_description,
        "description": item.description,
        "category_id": item.category_id,
        "service_id": item.service_id,
        "offering_id": item.offering_id,
        "lifecycle_status": item.lifecycle_status,
        "version": item.version,
        "owner_user_id": item.owner_user_id,
        "support_group": item.support_group,
        "expected_delivery_minutes": item.expected_delivery_minutes,
        "approval_required": item.approval_required,
        "entitlement_rules": _parse_mapping(item.entitlement_rules_json),
        "unit_cost_minor": item.unit_cost_minor,
        "currency": item.currency,
        "cost_type": item.cost_type,
        "risk_level": item.risk_level,
        "approval_policy": _parse_mapping(item.approval_policy_json),
        "sla_policy": _parse_mapping(item.sla_policy_json),
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "retired_at": item.retired_at.isoformat() if item.retired_at else None,
    }


def _history(
    db: Session,
    item: CatalogItem,
    current_user: AuthUserResponse,
    *,
    action: str,
    reason: str | None = None,
) -> None:
    db.add(
        CatalogItemHistory(
            id=str(uuid.uuid4()),
            tenant_id=item.tenant_id,
            catalog_item_id=item.id,
            version=item.version,
            action=action,
            lifecycle_status=item.lifecycle_status,
            snapshot_json=json.dumps(_snapshot(item), ensure_ascii=False, sort_keys=True),
            actor_user_id=current_user.id,
            actor_name=current_user.full_name,
            actor_email=current_user.email,
            reason=reason,
        )
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
        actor_email=current_user.email,
        tenant_id=tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata=metadata,
    )


def _ensure_standard_published_form(
    db: Session,
    item: CatalogItem,
    current_user: AuthUserResponse,
    http_request: Request,
) -> CatalogFormVersion:
    published = db.scalar(
        select(CatalogFormVersion)
        .where(
            CatalogFormVersion.catalog_item_id == item.id,
            CatalogFormVersion.status == "PUBLISHED",
        )
        .order_by(CatalogFormVersion.version.desc())
    )
    if published is not None:
        return published

    latest_version = db.scalar(
        select(func.max(CatalogFormVersion.version)).where(
            CatalogFormVersion.catalog_item_id == item.id
        )
    )
    form_schema = default_schema()
    attachment_rules = default_attachment_rules()
    now = _now()
    form = CatalogFormVersion(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        catalog_item_id=item.id,
        version=(latest_version or 0) + 1,
        revision=1,
        status="PUBLISHED",
        schema_json=canonical_json(form_schema),
        attachment_rules_json=canonical_json(attachment_rules),
        schema_hash=schema_hash(form_schema, attachment_rules),
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        published_by_id=current_user.id,
        published_at=now,
    )
    db.add(form)
    db.flush()
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_form_standard_published",
        entity_type="catalog_form_version",
        entity_id=form.id,
        tenant_id=item.tenant_id,
        metadata={
            "catalog_item_id": item.id,
            "catalog_item_code": item.code,
            "form_version": form.version,
            "schema_hash": form.schema_hash,
            "reason": "Catalog item published without an existing order form",
        },
    )
    return form


def _get_item(
    db: Session,
    item_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> CatalogItem:
    statement = select(CatalogItem).where(CatalogItem.id == item_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    if not is_saas_root(current_user) and item.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    if (
        not has_permission(current_user, "catalog.manage")
        and item.lifecycle_status != "PUBLISHED"
    ):
        raise HTTPException(status_code=404, detail="Catalog item not found")
    if not has_permission(current_user, "catalog.manage"):
        entitled, _ = _entitlement(db, item, current_user, bypass=False)
        if not entitled:
            raise HTTPException(status_code=404, detail="Catalog item not found")
    return item


@router.get("/summary", response_model=CatalogSummaryResponse)
def catalog_summary(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogSummaryResponse:
    require_permissions(current_user, "catalog.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statuses = dict(
        db.execute(
            select(CatalogItem.lifecycle_status, func.count(CatalogItem.id))
            .where(CatalogItem.tenant_id == scope)
            .group_by(CatalogItem.lifecycle_status)
        ).all()
    )
    return CatalogSummaryResponse(
        categories=db.scalar(
            select(func.count(ServiceCategory.id)).where(ServiceCategory.tenant_id == scope)
        )
        or 0,
        services=db.scalar(
            select(func.count(CatalogService.id)).where(CatalogService.tenant_id == scope)
        )
        or 0,
        offerings=db.scalar(
            select(func.count(ServiceOffering.id)).where(ServiceOffering.tenant_id == scope)
        )
        or 0,
        draft_items=statuses.get("DRAFT", 0),
        review_items=statuses.get("IN_REVIEW", 0),
        published_items=statuses.get("PUBLISHED", 0),
        retired_items=statuses.get("RETIRED", 0),
    )


@router.get("/categories", response_model=list[CategoryResponse])
def list_categories(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ServiceCategory]:
    require_permissions(current_user, "catalog.read")
    scope = _tenant_id(db, current_user, tenant_id)
    return list(
        db.scalars(
            select(ServiceCategory)
            .where(ServiceCategory.tenant_id == scope)
            .order_by(ServiceCategory.sort_order, ServiceCategory.name)
        ).all()
    )


@router.post("/categories", response_model=CategoryResponse, status_code=201)
def create_category(
    payload: CategoryCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ServiceCategory:
    require_permissions(current_user, "catalog.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    code = _code(payload.code)
    _ensure_unique(db, ServiceCategory, tenant_id, code)
    category = ServiceCategory(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=code,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        status="ACTIVE",
        sort_order=payload.sort_order,
    )
    db.add(category)
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_category_created",
        entity_type="service_category",
        entity_id=category.id,
        tenant_id=tenant_id,
        metadata={"code": code, "name": category.name},
    )
    db.commit()
    db.refresh(category)
    return category


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
def patch_category(
    category_id: str,
    payload: CategoryPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ServiceCategory:
    require_permissions(current_user, "catalog.manage")
    category = _tenant_entity(
        db.get(ServiceCategory, category_id), current_user, "Catalog category"
    )
    if payload.name is not None:
        category.name = payload.name.strip()
    if payload.clear_description:
        category.description = None
    elif payload.description is not None:
        category.description = payload.description.strip() or None
    if payload.status is not None:
        category.status = payload.status
    if payload.sort_order is not None:
        category.sort_order = payload.sort_order
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_category_updated",
        entity_type="service_category",
        entity_id=category.id,
        tenant_id=category.tenant_id,
        metadata={"code": category.code, "updated_fields": sorted(payload.model_fields_set)},
    )
    db.commit()
    db.refresh(category)
    return category


@router.get("/services", response_model=list[ServiceResponse])
def list_services(
    category_id: str | None = None,
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CatalogService]:
    require_permissions(current_user, "catalog.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statement = select(CatalogService).where(CatalogService.tenant_id == scope)
    if category_id:
        statement = statement.where(CatalogService.category_id == category_id)
    return list(db.scalars(statement.order_by(CatalogService.name)).all())


@router.post("/services", response_model=ServiceResponse, status_code=201)
def create_service(
    payload: ServiceCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogService:
    require_permissions(current_user, "catalog.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    category = db.get(ServiceCategory, payload.category_id)
    if category is None or category.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="Catalog category is unavailable")
    _ensure_owner(db, tenant_id, payload.owner_user_id)
    code = _code(payload.code)
    _ensure_unique(db, CatalogService, tenant_id, code)
    service = CatalogService(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        category_id=category.id,
        code=code,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        owner_user_id=payload.owner_user_id,
        support_group=payload.support_group.strip() if payload.support_group else None,
        status="ACTIVE",
    )
    db.add(service)
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_service_created",
        entity_type="catalog_service",
        entity_id=service.id,
        tenant_id=tenant_id,
        metadata={"code": code, "category_id": category.id},
    )
    db.commit()
    db.refresh(service)
    return service


@router.patch("/services/{service_id}", response_model=ServiceResponse)
def patch_service(
    service_id: str,
    payload: ServicePatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogService:
    require_permissions(current_user, "catalog.manage")
    service = _tenant_entity(
        db.get(CatalogService, service_id), current_user, "Catalog service"
    )
    if payload.name is not None:
        service.name = payload.name.strip()
    if payload.clear_description:
        service.description = None
    elif payload.description is not None:
        service.description = payload.description.strip() or None
    owner_user_id = (
        None
        if payload.clear_owner
        else payload.owner_user_id
        if payload.owner_user_id is not None
        else service.owner_user_id
    )
    _ensure_owner(db, service.tenant_id, owner_user_id)
    service.owner_user_id = owner_user_id
    if payload.clear_support_group:
        service.support_group = None
    elif payload.support_group is not None:
        service.support_group = payload.support_group.strip() or None
    if payload.status is not None:
        service.status = payload.status
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_service_updated",
        entity_type="catalog_service",
        entity_id=service.id,
        tenant_id=service.tenant_id,
        metadata={"code": service.code, "updated_fields": sorted(payload.model_fields_set)},
    )
    db.commit()
    db.refresh(service)
    return service


@router.get("/offerings", response_model=list[OfferingResponse])
def list_offerings(
    service_id: str | None = None,
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ServiceOffering]:
    require_permissions(current_user, "catalog.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statement = select(ServiceOffering).where(ServiceOffering.tenant_id == scope)
    if service_id:
        statement = statement.where(ServiceOffering.service_id == service_id)
    return list(db.scalars(statement.order_by(ServiceOffering.name)).all())


@router.post("/offerings", response_model=OfferingResponse, status_code=201)
def create_offering(
    payload: OfferingCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ServiceOffering:
    require_permissions(current_user, "catalog.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    service = db.get(CatalogService, payload.service_id)
    if service is None or service.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="Catalog service is unavailable")
    code = _code(payload.code)
    _ensure_unique(db, ServiceOffering, tenant_id, code)
    offering = ServiceOffering(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        service_id=service.id,
        code=code,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        support_group=payload.support_group.strip() if payload.support_group else None,
        expected_fulfillment_minutes=payload.expected_fulfillment_minutes,
        status="ACTIVE",
    )
    db.add(offering)
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_offering_created",
        entity_type="service_offering",
        entity_id=offering.id,
        tenant_id=tenant_id,
        metadata={"code": code, "service_id": service.id},
    )
    db.commit()
    db.refresh(offering)
    return offering


@router.patch("/offerings/{offering_id}", response_model=OfferingResponse)
def patch_offering(
    offering_id: str,
    payload: OfferingPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ServiceOffering:
    require_permissions(current_user, "catalog.manage")
    offering = _tenant_entity(
        db.get(ServiceOffering, offering_id), current_user, "Service offering"
    )
    if payload.name is not None:
        offering.name = payload.name.strip()
    if payload.clear_description:
        offering.description = None
    elif payload.description is not None:
        offering.description = payload.description.strip() or None
    if payload.clear_support_group:
        offering.support_group = None
    elif payload.support_group is not None:
        offering.support_group = payload.support_group.strip() or None
    if payload.expected_fulfillment_minutes is not None:
        offering.expected_fulfillment_minutes = payload.expected_fulfillment_minutes
    if payload.status is not None:
        offering.status = payload.status
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_offering_updated",
        entity_type="service_offering",
        entity_id=offering.id,
        tenant_id=offering.tenant_id,
        metadata={"code": offering.code, "updated_fields": sorted(payload.model_fields_set)},
    )
    db.commit()
    db.refresh(offering)
    return offering


@router.get("/items", response_model=list[CatalogItemResponse])
def list_items(
    search: str | None = Query(default=None, max_length=200),
    category_id: str | None = None,
    lifecycle_status: Lifecycle | None = None,
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CatalogItemResponse]:
    require_permissions(current_user, "catalog.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statement = _item_query().where(CatalogItem.tenant_id == scope)
    can_manage = has_permission(current_user, "catalog.manage")
    if not can_manage:
        statement = statement.where(CatalogItem.lifecycle_status == "PUBLISHED")
    elif lifecycle_status:
        statement = statement.where(CatalogItem.lifecycle_status == lifecycle_status)
    if category_id:
        statement = statement.where(CatalogItem.category_id == category_id)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                CatalogItem.name.ilike(pattern),
                CatalogItem.short_description.ilike(pattern),
                CatalogItem.code.ilike(pattern),
            )
        )
    rows = db.execute(statement.order_by(CatalogItem.name)).all()
    entitlement_by_item = {
        row[0].id: _entitlement(
            db,
            row[0],
            current_user,
            bypass=can_manage,
        )
        for row in rows
    }
    if not can_manage:
        rows = [row for row in rows if entitlement_by_item[row[0].id][0]]
    preferences = catalog_preferences_by_item(
        db,
        tenant_id=scope,
        user_id=current_user.id,
        catalog_item_ids=[row[0].id for row in rows],
    )
    return [
        _item_response(
            row,
            preferences.get(row[0].id),
            entitlement_by_item[row[0].id],
        )
        for row in rows
    ]


@router.get("/items/{item_id}", response_model=CatalogItemResponse)
def get_item(
    item_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogItemResponse:
    require_permissions(current_user, "catalog.read")
    item = _get_item(db, item_id, current_user)
    row = db.execute(_item_query().where(CatalogItem.id == item.id)).one()
    preference = get_catalog_preference(
        db,
        tenant_id=item.tenant_id,
        user_id=current_user.id,
        catalog_item_id=item.id,
    )
    return _item_response(
        row,
        preference,
        _entitlement(
            db,
            item,
            current_user,
            bypass=has_permission(current_user, "catalog.manage"),
        ),
    )


@router.post(
    "/items/{item_id}/view",
    response_model=CatalogPreferenceResponse,
)
def record_item_view(
    item_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogPreferenceResponse:
    require_permissions(current_user, "catalog.read")
    item = _get_item(db, item_id, current_user)
    preference = touch_catalog_preference(
        db,
        tenant_id=item.tenant_id,
        user_id=current_user.id,
        catalog_item_id=item.id,
        viewed=True,
    )
    db.commit()
    db.refresh(preference)
    return _preference_response(preference)


@router.put(
    "/items/{item_id}/favorite",
    response_model=CatalogPreferenceResponse,
)
def set_item_favorite(
    item_id: str,
    payload: CatalogFavoriteRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogPreferenceResponse:
    require_permissions(current_user, "catalog.read")
    item = _get_item(db, item_id, current_user)
    preference = touch_catalog_preference(
        db,
        tenant_id=item.tenant_id,
        user_id=current_user.id,
        catalog_item_id=item.id,
        favorite=payload.is_favorite,
    )
    _audit(
        db,
        http_request,
        current_user,
        action=(
            "catalog_item_favorited"
            if payload.is_favorite
            else "catalog_item_unfavorited"
        ),
        entity_type="catalog_item",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"code": item.code, "is_favorite": payload.is_favorite},
    )
    db.commit()
    db.refresh(preference)
    return _preference_response(preference)


@router.get(
    "/items/{item_id}/knowledge-suggestions",
    response_model=list[CatalogKnowledgeSuggestionResponse],
)
def catalog_knowledge_suggestions(
    item_id: str,
    limit: int = Query(default=3, ge=1, le=8),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CatalogKnowledgeSuggestionResponse]:
    require_permissions(current_user, "catalog.read", "knowledge.read")
    item = _get_item(db, item_id, current_user)
    category = db.get(ServiceCategory, item.category_id)
    if category is None:
        return []
    terms = _knowledge_terms(item, category)
    if not terms:
        return []

    match_clauses = []
    for term in terms:
        pattern = f"%{term}%"
        match_clauses.append(
            or_(
                func.lower(KnowledgeArticle.title).like(pattern),
                func.lower(KnowledgeArticle.summary).like(pattern),
                func.lower(KnowledgeArticle.content).like(pattern),
                func.lower(func.coalesce(KnowledgeArticle.tags, "")).like(pattern),
                func.lower(
                    func.coalesce(KnowledgeArticle.ticket_category, "")
                ).like(pattern),
            )
        )
    rows = db.execute(
        select(KnowledgeArticle, KnowledgeCategory)
        .join(
            KnowledgeCategory,
            KnowledgeCategory.id == KnowledgeArticle.category_id,
        )
        .where(
            KnowledgeArticle.status == "published",
            KnowledgeArticle.visibility.in_(("public", "internal")),
            or_(*match_clauses),
        )
        .order_by(
            KnowledgeArticle.helpful_count.desc(),
            KnowledgeArticle.updated_at.desc(),
        )
        .limit(60)
    ).all()

    scored: list[tuple[int, KnowledgeArticle, KnowledgeCategory]] = []
    for article, article_category in rows:
        title = article.title.lower()
        summary = article.summary.lower()
        content = article.content.lower()
        tags = (article.tags or "").lower()
        ticket_category = (article.ticket_category or "").lower()
        score = sum(
            (8 if term in title else 0)
            + (5 if term in tags or term in ticket_category else 0)
            + (3 if term in summary else 0)
            + (1 if term in content else 0)
            for term in terms
        )
        if score:
            score += min(article.helpful_count or 0, 10)
            scored.append((score, article, article_category))
    scored.sort(
        key=lambda entry: (
            -entry[0],
            -(entry[1].helpful_count or 0),
            entry[1].title.lower(),
        )
    )
    return [
        CatalogKnowledgeSuggestionResponse(
            id=article.id,
            article_number=article.article_number,
            title=article.title,
            summary=article.summary,
            content_preview=(
                article.content
                if len(article.content) <= 600
                else f"{article.content[:597].rstrip()}..."
            ),
            category_name=article_category.name,
            tags=_knowledge_tags(article),
            helpful_count=article.helpful_count or 0,
            relevance_score=score,
        )
        for score, article, article_category in scored[:limit]
    ]


@router.post(
    "/items/{item_id}/knowledge/{article_id}/resolved",
    response_model=CatalogDeflectionResponse,
)
def confirm_catalog_deflection(
    item_id: str,
    article_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogDeflectionResponse:
    require_permissions(current_user, "catalog.read", "knowledge.read")
    item = _get_item(db, item_id, current_user)
    article = db.scalar(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == article_id,
            KnowledgeArticle.status == "published",
            KnowledgeArticle.visibility.in_(("public", "internal")),
        )
    )
    if article is None:
        raise HTTPException(status_code=404, detail="Knowledge article not found")
    now = _now()
    article.last_used_at = now
    db.add(
        KnowledgeUsageLog(
            id=str(uuid.uuid4()),
            article_id=article.id,
            user_id=current_user.id,
            action="catalog_deflection_resolved",
            context={
                "catalog_item_id": item.id,
                "catalog_item_code": item.code,
                "tenant_id": item.tenant_id,
            },
        )
    )
    db.commit()
    return CatalogDeflectionResponse(
        status="resolved",
        catalog_item_id=item.id,
        article_id=article.id,
    )


@router.post("/items", response_model=CatalogItemResponse, status_code=201)
def create_item(
    payload: CatalogItemCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogItemResponse:
    require_permissions(current_user, "catalog.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    _taxonomy(
        db,
        tenant_id=tenant_id,
        category_id=payload.category_id,
        service_id=payload.service_id,
        offering_id=payload.offering_id,
    )
    _ensure_owner(db, tenant_id, payload.owner_user_id)
    code = _code(payload.code)
    _ensure_unique(db, CatalogItem, tenant_id, code)
    entitlement_rules = _governance_value(
        normalize_entitlement_rules,
        payload.entitlement_rules,
        field="entitlement rules",
    )
    approval_policy = _governance_value(
        normalize_approval_policy,
        payload.approval_policy,
        field="approval policy",
    )
    sla_policy = _governance_value(
        normalize_sla_policy,
        payload.sla_policy,
        field="SLA policy",
        default_target_minutes=payload.expected_delivery_minutes,
    )
    currency = payload.currency.strip().upper()
    if not currency.isalpha():
        raise HTTPException(status_code=422, detail="Currency must be a 3-letter code")
    item = CatalogItem(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        category_id=payload.category_id,
        service_id=payload.service_id,
        offering_id=payload.offering_id,
        code=code,
        name=payload.name.strip(),
        short_description=payload.short_description.strip(),
        description=payload.description.strip(),
        lifecycle_status="DRAFT",
        version=1,
        owner_user_id=payload.owner_user_id,
        support_group=payload.support_group.strip() if payload.support_group else None,
        expected_delivery_minutes=payload.expected_delivery_minutes,
        approval_required=payload.approval_required,
        entitlement_rules_json=json.dumps(
            entitlement_rules, ensure_ascii=False, sort_keys=True
        ),
        unit_cost_minor=payload.unit_cost_minor,
        currency=currency,
        cost_type=payload.cost_type,
        risk_level=payload.risk_level,
        approval_policy_json=json.dumps(
            approval_policy, ensure_ascii=False, sort_keys=True
        ),
        sla_policy_json=json.dumps(sla_policy, ensure_ascii=False, sort_keys=True),
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(item)
    db.flush()
    _history(db, item, current_user, action="CREATED")
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_item_created",
        entity_type="catalog_item",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"code": code, "version": 1},
    )
    db.commit()
    row = db.execute(_item_query().where(CatalogItem.id == item.id)).one()
    return _item_response(row)


@router.patch("/items/{item_id}", response_model=CatalogItemResponse)
def patch_item(
    item_id: str,
    payload: CatalogItemPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogItemResponse:
    require_permissions(current_user, "catalog.manage")
    item = _get_item(db, item_id, current_user, lock=True)
    if item.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Catalog item changed; current version is {item.version}",
        )
    if item.lifecycle_status == "RETIRED":
        raise HTTPException(status_code=409, detail="Retired catalog items are immutable")
    if item.lifecycle_status == "PUBLISHED":
        _history(
            db,
            item,
            current_user,
            action="PUBLISHED_VERSION_SUPERSEDED",
            reason="Published item edited into a new draft",
        )
        item.lifecycle_status = "DRAFT"
        item.published_at = None
    category_id = payload.category_id or item.category_id
    service_id = payload.service_id or item.service_id
    offering_id = None if payload.clear_offering else (
        payload.offering_id if payload.offering_id is not None else item.offering_id
    )
    _taxonomy(
        db,
        tenant_id=item.tenant_id,
        category_id=category_id,
        service_id=service_id,
        offering_id=offering_id,
    )
    owner_user_id = (
        None
        if payload.clear_owner
        else payload.owner_user_id
        if payload.owner_user_id is not None
        else item.owner_user_id
    )
    _ensure_owner(db, item.tenant_id, owner_user_id)
    item.category_id = category_id
    item.service_id = service_id
    item.offering_id = offering_id
    item.owner_user_id = owner_user_id
    for field in (
        "name",
        "short_description",
        "description",
        "support_group",
        "expected_delivery_minutes",
        "approval_required",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(item, field, value.strip() if isinstance(value, str) else value)
    if payload.entitlement_rules is not None:
        item.entitlement_rules_json = json.dumps(
            _governance_value(
                normalize_entitlement_rules,
                payload.entitlement_rules,
                field="entitlement rules",
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    if payload.unit_cost_minor is not None:
        item.unit_cost_minor = payload.unit_cost_minor
    if payload.currency is not None:
        currency = payload.currency.strip().upper()
        if not currency.isalpha():
            raise HTTPException(status_code=422, detail="Currency must be a 3-letter code")
        item.currency = currency
    if payload.cost_type is not None:
        item.cost_type = payload.cost_type
    if payload.risk_level is not None:
        item.risk_level = payload.risk_level
    if payload.approval_policy is not None:
        item.approval_policy_json = json.dumps(
            _governance_value(
                normalize_approval_policy,
                payload.approval_policy,
                field="approval policy",
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    if payload.sla_policy is not None or payload.expected_delivery_minutes is not None:
        sla_source = (
            payload.sla_policy
            if payload.sla_policy is not None
            else _parse_mapping(item.sla_policy_json)
        )
        item.sla_policy_json = json.dumps(
            _governance_value(
                normalize_sla_policy,
                sla_source,
                field="SLA policy",
                default_target_minutes=item.expected_delivery_minutes,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    item.version += 1
    item.updated_by_id = current_user.id
    _history(db, item, current_user, action="UPDATED")
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_item_updated",
        entity_type="catalog_item",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"code": item.code, "version": item.version},
    )
    db.commit()
    row = db.execute(_item_query().where(CatalogItem.id == item.id)).one()
    return _item_response(row)


@router.post("/items/{item_id}/transition", response_model=CatalogItemResponse)
def transition_item(
    item_id: str,
    payload: CatalogTransitionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogItemResponse:
    require_permissions(current_user, "catalog.manage")
    item = _get_item(db, item_id, current_user, lock=True)
    if item.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Catalog item changed; current version is {item.version}",
        )
    if payload.target_status not in TRANSITIONS[item.lifecycle_status]:
        raise HTTPException(
            status_code=409,
            detail=f"Transition {item.lifecycle_status} -> {payload.target_status} is not allowed",
        )
    if payload.target_status in {"PUBLISHED", "RETIRED"}:
        require_permissions(current_user, "catalog.publish")
    if payload.target_status == "PUBLISHED":
        missing = []
        if not item.owner_user_id:
            missing.append("owner")
        if not item.support_group:
            missing.append("support group")
        if not item.description.strip():
            missing.append("description")
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot publish without: {', '.join(missing)}",
            )
        _taxonomy(
            db,
            tenant_id=item.tenant_id,
            category_id=item.category_id,
            service_id=item.service_id,
            offering_id=item.offering_id,
        )
        _ensure_standard_published_form(db, item, current_user, http_request)
        item.published_at = _now()
        item.retired_at = None
    if payload.target_status == "RETIRED":
        item.retired_at = _now()
    previous = item.lifecycle_status
    item.lifecycle_status = payload.target_status
    item.version += 1
    item.updated_by_id = current_user.id
    _history(
        db,
        item,
        current_user,
        action=f"TRANSITIONED_TO_{payload.target_status}",
        reason=payload.reason.strip(),
    )
    _audit(
        db,
        http_request,
        current_user,
        action="catalog_item_status_changed",
        entity_type="catalog_item",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "code": item.code,
            "from_status": previous,
            "to_status": payload.target_status,
            "version": item.version,
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    row = db.execute(_item_query().where(CatalogItem.id == item.id)).one()
    return _item_response(row)


@router.get("/items/{item_id}/history", response_model=list[CatalogHistoryResponse])
def item_history(
    item_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CatalogHistoryResponse]:
    require_permissions(current_user, "catalog.manage")
    item = _get_item(db, item_id, current_user)
    rows = db.scalars(
        select(CatalogItemHistory)
        .where(CatalogItemHistory.catalog_item_id == item.id)
        .order_by(CatalogItemHistory.created_at, CatalogItemHistory.id)
    ).all()
    return [
        CatalogHistoryResponse(
            id=row.id,
            version=row.version,
            action=row.action,
            lifecycle_status=row.lifecycle_status,
            snapshot=_parse_mapping(row.snapshot_json),
            actor_name=row.actor_name,
            actor_email=row.actor_email,
            reason=row.reason,
            created_at=row.created_at,
        )
        for row in rows
    ]
