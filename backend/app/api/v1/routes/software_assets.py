from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.software_asset import (
    SoftwareInstallation,
    SoftwareLicense,
    SoftwareProduct,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.rbac import is_saas_root, require_permissions
from app.services.software_asset_management import (
    build_sam_dashboard,
    reconcile_expired_licenses,
    software_catalog_key,
)


router = APIRouter(prefix="/software-assets")


LicenseType = Literal[
    "NAMED_USER",
    "DEVICE",
    "CONCURRENT",
    "SUBSCRIPTION",
    "PERPETUAL",
    "OEM",
    "ENTERPRISE",
]


class ProductCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    publisher: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    edition: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=120)
    sku: str | None = Field(default=None, max_length=120)
    is_prohibited: bool = False
    prohibited_reason: str | None = Field(default=None, max_length=2_000)


class ProductUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    publisher: str | None = Field(default=None, min_length=1, max_length=200)
    version: str | None = Field(default=None, min_length=1, max_length=100)
    edition: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=120)
    sku: str | None = Field(default=None, max_length=120)
    status: Literal["ACTIVE", "RETIRED"] | None = None
    is_prohibited: bool | None = None
    prohibited_reason: str | None = Field(default=None, max_length=2_000)
    reason: str = Field(min_length=3, max_length=2_000)


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    publisher: str
    version: str
    edition: str | None
    category: str | None
    sku: str | None
    status: str
    is_prohibited: bool
    prohibited_reason: str | None
    version_number: int
    created_at: datetime
    updated_at: datetime


class LicenseCreate(BaseModel):
    tenant_id: str | None = None
    product_id: str
    license_reference: str = Field(min_length=1, max_length=160)
    license_type: LicenseType
    purchased_quantity: int = Field(ge=0, le=10_000_000)
    vendor: str | None = Field(default=None, max_length=200)
    contract_reference: str | None = Field(default=None, max_length=160)
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    renewal_at: datetime | None = None
    auto_renew: bool = False
    unit_cost: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="KZT", pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def validate_dates(self) -> "LicenseCreate":
        if self.starts_at and self.expires_at and self.expires_at <= self.starts_at:
            raise ValueError("expires_at must be later than starts_at")
        return self


class LicenseUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    license_reference: str | None = Field(default=None, min_length=1, max_length=160)
    license_type: LicenseType | None = None
    purchased_quantity: int | None = Field(default=None, ge=0, le=10_000_000)
    vendor: str | None = Field(default=None, max_length=200)
    contract_reference: str | None = Field(default=None, max_length=160)
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    renewal_at: datetime | None = None
    auto_renew: bool | None = None
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    status: Literal["ACTIVE", "SUSPENDED", "EXPIRED", "RETIRED"] | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class LicenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    product_id: str
    product_name: str
    license_reference: str
    license_type: str
    purchased_quantity: int
    vendor: str | None
    contract_reference: str | None
    starts_at: datetime | None
    expires_at: datetime | None
    renewal_at: datetime | None
    auto_renew: bool
    unit_cost: Decimal
    currency: str
    status: str
    version_number: int
    created_at: datetime
    updated_at: datetime


class InstallationCreate(BaseModel):
    tenant_id: str | None = None
    product_id: str
    asset_id: str
    assigned_user_id: str | None = None
    detected_version: str | None = Field(default=None, max_length=100)
    source: str = Field(default="MANUAL", min_length=1, max_length=64)
    authorization_status: Literal["AUTHORIZED", "UNAUTHORIZED", "EXEMPTED"] = "AUTHORIZED"
    authorization_reason: str | None = Field(default=None, max_length=2_000)
    last_seen_at: datetime | None = None


class InstallationUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    assigned_user_id: str | None = None
    detected_version: str | None = Field(default=None, max_length=100)
    authorization_status: Literal["AUTHORIZED", "UNAUTHORIZED", "EXEMPTED"] | None = None
    authorization_reason: str | None = Field(default=None, max_length=2_000)
    status: Literal["ACTIVE", "REMOVED"] | None = None
    last_seen_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class InstallationResponse(BaseModel):
    id: str
    tenant_id: str
    product_id: str
    product_name: str
    asset_id: str
    asset_tag: str
    asset_name: str
    assigned_user_id: str | None
    detected_version: str | None
    source: str
    authorization_status: str
    authorization_reason: str | None
    status: str
    discovered_at: datetime
    last_seen_at: datetime
    removed_at: datetime | None
    version_number: int
    created_at: datetime
    updated_at: datetime


def _tenant_id(db: Session, user: AuthUserResponse, requested: str | None) -> str:
    if not is_saas_root(user):
        if not user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        if requested and requested != user.tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return user.tenant_id
    if not requested:
        raise HTTPException(status_code=422, detail="tenant_id is required for SaaS Root SAM administration")
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _scope(user: AuthUserResponse, tenant_id: str, detail: str) -> None:
    if not is_saas_root(user) and user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=detail)


def _actor(db: Session, user: AuthUserResponse) -> User:
    actor = db.get(User, user.id)
    if actor is None:
        raise HTTPException(status_code=401, detail="Authenticated user is unavailable")
    return actor


def _audit_context(request: Request) -> dict[str, str | None]:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


def _product(db: Session, product_id: str, user: AuthUserResponse) -> SoftwareProduct:
    item = db.get(SoftwareProduct, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Software product not found")
    _scope(user, item.tenant_id, "Software product not found")
    return item


def _license(db: Session, license_id: str, user: AuthUserResponse) -> SoftwareLicense:
    item = db.get(SoftwareLicense, license_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Software license not found")
    _scope(user, item.tenant_id, "Software license not found")
    return item


def _installation(db: Session, installation_id: str, user: AuthUserResponse) -> SoftwareInstallation:
    item = db.get(SoftwareInstallation, installation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Software installation not found")
    _scope(user, item.tenant_id, "Software installation not found")
    return item


def _license_response(db: Session, item: SoftwareLicense) -> LicenseResponse:
    product = db.get(SoftwareProduct, item.product_id)
    return LicenseResponse(
        **{column.name: getattr(item, column.name) for column in item.__table__.columns if column.name != "created_by_id"},
        product_name=product.name if product else "Unknown product",
    )


def _installation_response(db: Session, item: SoftwareInstallation) -> InstallationResponse:
    product = db.get(SoftwareProduct, item.product_id)
    asset = db.get(Asset, item.asset_id)
    return InstallationResponse(
        **{column.name: getattr(item, column.name) for column in item.__table__.columns if column.name != "created_by_id"},
        product_name=product.name if product else "Unknown product",
        asset_tag=asset.asset_tag if asset else "—",
        asset_name=asset.name if asset else "Unknown asset",
    )


def _commit_or_conflict(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc


@router.get("/dashboard")
def get_dashboard(
    tenant_id: str | None = Query(default=None),
    renewal_days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "sam.read")
    scope = _tenant_id(db, current_user, tenant_id)
    return build_sam_dashboard(db, tenant_id=scope, renewal_days=renewal_days)


@router.get("/products", response_model=list[ProductResponse])
def list_products(
    tenant_id: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    status_filter: Literal["ALL", "ACTIVE", "RETIRED"] = Query(default="ALL", alias="status"),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[SoftwareProduct]:
    require_permissions(current_user, "sam.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statement = select(SoftwareProduct).where(SoftwareProduct.tenant_id == scope)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                SoftwareProduct.name.ilike(pattern),
                SoftwareProduct.publisher.ilike(pattern),
                SoftwareProduct.sku.ilike(pattern),
            )
        )
    if status_filter != "ALL":
        statement = statement.where(SoftwareProduct.status == status_filter)
    return list(db.scalars(statement.order_by(SoftwareProduct.name.asc())).all())


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> SoftwareProduct:
    require_permissions(current_user, "sam.catalog.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    if payload.is_prohibited and not payload.prohibited_reason:
        raise HTTPException(status_code=422, detail="prohibited_reason is required")
    actor = _actor(db, current_user)
    item = SoftwareProduct(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        catalog_key=software_catalog_key(
            name=payload.name,
            publisher=payload.publisher,
            version=payload.version,
            edition=payload.edition,
        ),
        name=payload.name.strip(),
        publisher=payload.publisher.strip(),
        version=payload.version.strip(),
        edition=payload.edition.strip() if payload.edition else None,
        category=payload.category.strip() if payload.category else None,
        sku=payload.sku.strip() if payload.sku else None,
        is_prohibited=payload.is_prohibited,
        prohibited_reason=payload.prohibited_reason,
        created_by_id=actor.id,
    )
    db.add(item)
    log_audit(
        db,
        action="sam.product.created",
        entity_type="software_product",
        entity_id=item.id,
        actor_user=actor,
        tenant_id=tenant_id,
        metadata={"name": item.name, "publisher": item.publisher, "version": item.version},
        **_audit_context(request),
    )
    _commit_or_conflict(db, "This software product already exists")
    db.refresh(item)
    return item


@router.patch("/products/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: str,
    payload: ProductUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> SoftwareProduct:
    require_permissions(current_user, "sam.catalog.manage")
    item = _product(db, product_id, current_user)
    if item.version_number != payload.expected_version:
        raise HTTPException(status_code=409, detail="Software product was changed; reload and retry")
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version", "reason"})
    for key, value in changes.items():
        setattr(item, key, value.strip() if isinstance(value, str) else value)
    if item.is_prohibited and not item.prohibited_reason:
        raise HTTPException(status_code=422, detail="prohibited_reason is required")
    item.catalog_key = software_catalog_key(
        name=item.name, publisher=item.publisher, version=item.version, edition=item.edition
    )
    item.version_number += 1
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="sam.product.updated",
        entity_type="software_product",
        entity_id=item.id,
        actor_user=actor,
        tenant_id=item.tenant_id,
        metadata={"changed_fields": sorted(changes), "reason": payload.reason},
        **_audit_context(request),
    )
    _commit_or_conflict(db, "This software product already exists")
    db.refresh(item)
    return item


@router.get("/licenses", response_model=list[LicenseResponse])
def list_licenses(
    tenant_id: str | None = Query(default=None),
    product_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[LicenseResponse]:
    require_permissions(current_user, "sam.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statement = select(SoftwareLicense).where(SoftwareLicense.tenant_id == scope)
    if product_id:
        statement = statement.where(SoftwareLicense.product_id == product_id)
    rows = db.scalars(statement.order_by(SoftwareLicense.created_at.desc())).all()
    return [_license_response(db, item) for item in rows]


@router.post("/licenses", response_model=LicenseResponse, status_code=status.HTTP_201_CREATED)
def create_license(
    payload: LicenseCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> LicenseResponse:
    require_permissions(current_user, "sam.licenses.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    product = _product(db, payload.product_id, current_user)
    if product.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="Product does not belong to the selected tenant")
    actor = _actor(db, current_user)
    item = SoftwareLicense(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        product_id=product.id,
        license_reference=payload.license_reference.strip(),
        license_type=payload.license_type,
        purchased_quantity=payload.purchased_quantity,
        vendor=payload.vendor,
        contract_reference=payload.contract_reference,
        starts_at=payload.starts_at,
        expires_at=payload.expires_at,
        renewal_at=payload.renewal_at,
        auto_renew=payload.auto_renew,
        unit_cost=payload.unit_cost,
        currency=payload.currency,
        created_by_id=actor.id,
    )
    db.add(item)
    log_audit(
        db,
        action="sam.license.created",
        entity_type="software_license",
        entity_id=item.id,
        actor_user=actor,
        tenant_id=tenant_id,
        metadata={
            "product_id": product.id,
            "license_reference": item.license_reference,
            "purchased_quantity": item.purchased_quantity,
        },
        **_audit_context(request),
    )
    _commit_or_conflict(db, "Software license could not be created")
    db.refresh(item)
    return _license_response(db, item)


@router.patch("/licenses/{license_id}", response_model=LicenseResponse)
def update_license(
    license_id: str,
    payload: LicenseUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> LicenseResponse:
    require_permissions(current_user, "sam.licenses.manage")
    item = _license(db, license_id, current_user)
    if item.version_number != payload.expected_version:
        raise HTTPException(status_code=409, detail="Software license was changed; reload and retry")
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version", "reason"})
    for key, value in changes.items():
        setattr(item, key, value.strip() if isinstance(value, str) else value)
    if item.starts_at and item.expires_at and item.expires_at <= item.starts_at:
        raise HTTPException(status_code=422, detail="expires_at must be later than starts_at")
    item.version_number += 1
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="sam.license.updated",
        entity_type="software_license",
        entity_id=item.id,
        actor_user=actor,
        tenant_id=item.tenant_id,
        metadata={"changed_fields": sorted(changes), "reason": payload.reason},
        **_audit_context(request),
    )
    _commit_or_conflict(db, "Software license could not be updated")
    db.refresh(item)
    return _license_response(db, item)


@router.get("/installations", response_model=list[InstallationResponse])
def list_installations(
    tenant_id: str | None = Query(default=None),
    product_id: str | None = Query(default=None),
    authorization_status: Literal["ALL", "AUTHORIZED", "UNAUTHORIZED", "EXEMPTED"] = "ALL",
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[InstallationResponse]:
    require_permissions(current_user, "sam.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statement = select(SoftwareInstallation).where(SoftwareInstallation.tenant_id == scope)
    if product_id:
        statement = statement.where(SoftwareInstallation.product_id == product_id)
    if authorization_status != "ALL":
        statement = statement.where(SoftwareInstallation.authorization_status == authorization_status)
    rows = db.scalars(statement.order_by(SoftwareInstallation.last_seen_at.desc())).all()
    return [_installation_response(db, item) for item in rows]


@router.post("/installations", response_model=InstallationResponse, status_code=status.HTTP_201_CREATED)
def create_installation(
    payload: InstallationCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> InstallationResponse:
    require_permissions(current_user, "sam.installations.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    product = _product(db, payload.product_id, current_user)
    asset = db.get(Asset, payload.asset_id)
    if product.tenant_id != tenant_id or asset is None or asset.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="Product and asset must belong to the selected tenant")
    if payload.assigned_user_id:
        assigned = db.get(User, payload.assigned_user_id)
        if assigned is None or assigned.tenant_id != tenant_id:
            raise HTTPException(status_code=422, detail="Assigned user must belong to the selected tenant")
    authorization_status = payload.authorization_status
    authorization_reason = payload.authorization_reason
    if product.is_prohibited and authorization_status == "AUTHORIZED":
        authorization_status = "UNAUTHORIZED"
        authorization_reason = authorization_reason or "Software is prohibited by catalog policy"
    actor = _actor(db, current_user)
    item = SoftwareInstallation(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        product_id=product.id,
        asset_id=asset.id,
        assigned_user_id=payload.assigned_user_id,
        detected_version=payload.detected_version,
        source=payload.source.strip().upper(),
        authorization_status=authorization_status,
        authorization_reason=authorization_reason,
        last_seen_at=payload.last_seen_at or datetime.now(UTC),
        created_by_id=actor.id,
    )
    db.add(item)
    log_audit(
        db,
        action="sam.installation.created",
        entity_type="software_installation",
        entity_id=item.id,
        actor_user=actor,
        tenant_id=tenant_id,
        metadata={
            "product_id": product.id,
            "asset_id": asset.id,
            "authorization_status": authorization_status,
        },
        **_audit_context(request),
    )
    _commit_or_conflict(db, "This software installation is already registered on the asset")
    db.refresh(item)
    return _installation_response(db, item)


@router.patch("/installations/{installation_id}", response_model=InstallationResponse)
def update_installation(
    installation_id: str,
    payload: InstallationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> InstallationResponse:
    require_permissions(current_user, "sam.installations.manage")
    item = _installation(db, installation_id, current_user)
    if item.version_number != payload.expected_version:
        raise HTTPException(status_code=409, detail="Software installation was changed; reload and retry")
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version", "reason"})
    if "assigned_user_id" in changes and changes["assigned_user_id"]:
        assigned = db.get(User, changes["assigned_user_id"])
        if assigned is None or assigned.tenant_id != item.tenant_id:
            raise HTTPException(status_code=422, detail="Assigned user must belong to the selected tenant")
    for key, value in changes.items():
        setattr(item, key, value)
    product = db.get(SoftwareProduct, item.product_id)
    if (
        item.authorization_status == "AUTHORIZED"
        and product is not None
        and product.is_prohibited
    ):
        raise HTTPException(
            status_code=422,
            detail="Prohibited software cannot be authorized",
        )
    if item.status == "REMOVED":
        item.removed_at = item.removed_at or datetime.now(UTC)
    else:
        item.removed_at = None
    item.version_number += 1
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="sam.installation.updated",
        entity_type="software_installation",
        entity_id=item.id,
        actor_user=actor,
        tenant_id=item.tenant_id,
        metadata={"changed_fields": sorted(changes), "reason": payload.reason},
        **_audit_context(request),
    )
    db.commit()
    db.refresh(item)
    return _installation_response(db, item)


@router.post("/reconcile")
def reconcile_sam(
    request: Request,
    tenant_id: str | None = Query(default=None),
    renewal_days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    require_permissions(current_user, "sam.reconcile")
    scope = _tenant_id(db, current_user, tenant_id)
    actor = _actor(db, current_user)
    expired_ids = reconcile_expired_licenses(db, tenant_id=scope)
    db.flush()
    dashboard = build_sam_dashboard(db, tenant_id=scope, renewal_days=renewal_days)
    log_audit(
        db,
        action="sam.reconciled",
        entity_type="software_asset_management",
        entity_id=scope,
        actor_user=actor,
        tenant_id=scope,
        metadata={
            "expired_license_ids": expired_ids,
            "noncompliant_products": dashboard["summary"]["noncompliant_products"],
            "unauthorized_installations": dashboard["summary"]["unauthorized_installations"],
        },
        **_audit_context(request),
    )
    db.commit()
    return {"expired_licenses_updated": len(expired_ids), "dashboard": dashboard}
