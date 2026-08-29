from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import json
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.tenant import Tenant
from app.models.tenant_experience import (
    TenantBrandAsset,
    TenantExperienceProfile,
    TenantExperienceRevision,
)
from app.models.user import User
from app.services.audit import log_audit
from app.services.rbac import is_saas_root, require_permissions
from app.services.tenant_experience import (
    ALLOWED_CURRENCIES,
    ALLOWED_DATE_STYLES,
    ALLOWED_FIRST_DAYS,
    ALLOWED_FORMAT_LOCALES,
    ALLOWED_HOUR_CYCLES,
    ALLOWED_UI_LOCALES,
    MAX_BRAND_ASSETS_PER_TENANT,
    MAX_LOGO_BYTES,
    apply_experience,
    canonical_json,
    default_experience,
    experience_contrast,
    png_dimensions,
    profile_snapshot,
    sha256_text,
    snapshot_evidence,
    validate_experience,
)


router = APIRouter(prefix="/tenant-experience")
COMMON_TIMEZONES = (
    "Asia/Qyzylorda",
    "Asia/Almaty",
    "UTC",
    "Europe/Moscow",
    "Europe/London",
    "America/New_York",
)


class TerminologyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_singular: str = Field(min_length=2, max_length=40)
    incident_plural: str = Field(min_length=2, max_length=40)
    request_singular: str = Field(min_length=2, max_length=40)
    request_plural: str = Field(min_length=2, max_length=40)
    asset_singular: str = Field(min_length=2, max_length=40)
    asset_plural: str = Field(min_length=2, max_length=40)
    service_singular: str = Field(min_length=2, max_length=40)
    service_plural: str = Field(min_length=2, max_length=40)
    knowledge_base: str = Field(min_length=2, max_length=40)


class ExperienceSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(min_length=2, max_length=80)
    short_name: str = Field(min_length=2, max_length=24)
    primary_color: str = Field(min_length=7, max_length=7)
    accent_color: str = Field(min_length=7, max_length=7)
    surface_color: str = Field(min_length=7, max_length=7)
    text_color: str = Field(min_length=7, max_length=7)
    ui_locale: str = Field(min_length=2, max_length=16)
    format_locale: str = Field(min_length=2, max_length=16)
    timezone: str = Field(min_length=1, max_length=80)
    currency_code: str = Field(min_length=3, max_length=3)
    date_style: str = Field(min_length=4, max_length=12)
    hour_cycle: str = Field(min_length=3, max_length=4)
    first_day_of_week: int
    terminology: TerminologyPayload


class ExperienceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    change_reason: str = Field(min_length=5, max_length=500)
    settings: ExperienceSettingsPayload


class ExperienceRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    target_revision: int = Field(ge=1)
    change_reason: str = Field(min_length=5, max_length=500)


class ExperienceLogoRemoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    change_reason: str = Field(min_length=5, max_length=500)


class BrandLogoResponse(BaseModel):
    asset_id: str
    content_type: str
    data_url: str
    sha256: str
    size_bytes: int
    width: int
    height: int


class ExperienceCapabilitiesResponse(BaseModel):
    ui_locales: list[str]
    format_locales: list[str]
    currencies: list[str]
    date_styles: list[str]
    hour_cycles: list[str]
    first_days_of_week: list[int]
    suggested_timezones: list[str]
    logo_content_types: list[str]
    logo_max_bytes: int


class ExperienceResponse(BaseModel):
    tenant_id: str | None
    revision: int
    is_default: bool
    product_name: str
    short_name: str
    primary_color: str
    accent_color: str
    surface_color: str
    text_color: str
    ui_locale: str
    format_locale: str
    timezone: str
    currency_code: str
    date_style: str
    hour_cycle: str
    first_day_of_week: int
    terminology: TerminologyPayload
    logo: BrandLogoResponse | None
    contrast: dict[str, float | str]
    etag: str
    updated_at: datetime | None
    capabilities: ExperienceCapabilitiesResponse


class ExperienceRevisionResponse(BaseModel):
    revision: int
    snapshot_sha256: str
    integrity_valid: bool
    changed_by_id: str | None
    change_reason: str
    rolled_back_from_revision: int | None
    created_at: datetime


def _capabilities() -> ExperienceCapabilitiesResponse:
    return ExperienceCapabilitiesResponse(
        ui_locales=list(ALLOWED_UI_LOCALES),
        format_locales=list(ALLOWED_FORMAT_LOCALES),
        currencies=list(ALLOWED_CURRENCIES),
        date_styles=list(ALLOWED_DATE_STYLES),
        hour_cycles=list(ALLOWED_HOUR_CYCLES),
        first_days_of_week=list(ALLOWED_FIRST_DAYS),
        suggested_timezones=list(COMMON_TIMEZONES),
        logo_content_types=["image/png"],
        logo_max_bytes=MAX_LOGO_BYTES,
    )


def _resolve_tenant_id(
    db: Session,
    current_user: AuthUserResponse,
    requested_tenant_id: str | None,
) -> str | None:
    if is_saas_root(current_user):
        tenant_id = requested_tenant_id
        if tenant_id is None:
            return None
    else:
        tenant_id = current_user.tenant_id
        if tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Session has no tenant scope",
            )
        if requested_tenant_id is not None and requested_tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant access denied",
            )
    if db.get(Tenant, tenant_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    return tenant_id


def _logo_response(
    db: Session,
    tenant_id: str | None,
    logo_asset_id: str | None,
) -> BrandLogoResponse | None:
    if tenant_id is None or logo_asset_id is None:
        return None
    asset = db.get(TenantBrandAsset, logo_asset_id)
    if asset is None or asset.tenant_id != tenant_id or asset.kind != "LOGO":
        return None
    encoded = base64.b64encode(asset.payload).decode("ascii")
    return BrandLogoResponse(
        asset_id=asset.id,
        content_type=asset.content_type,
        data_url=f"data:{asset.content_type};base64,{encoded}",
        sha256=asset.sha256,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
    )


def _to_response(
    db: Session,
    tenant_id: str | None,
    profile: TenantExperienceProfile | None,
) -> ExperienceResponse:
    settings = profile_snapshot(profile) if profile is not None else default_experience()
    serialized, etag = snapshot_evidence(settings)
    del serialized
    return ExperienceResponse(
        tenant_id=tenant_id,
        revision=profile.revision if profile is not None else 0,
        is_default=profile is None,
        **{key: value for key, value in settings.items() if key != "logo_asset_id"},
        logo=_logo_response(db, tenant_id, settings["logo_asset_id"]),
        contrast=experience_contrast(settings),
        etag=etag,
        updated_at=profile.updated_at if profile is not None else None,
        capabilities=_capabilities(),
    )


def _profile_for_update(
    db: Session,
    tenant_id: str,
    expected_revision: int,
    actor_id: str,
) -> TenantExperienceProfile:
    profile = db.scalar(
        select(TenantExperienceProfile)
        .where(TenantExperienceProfile.tenant_id == tenant_id)
        .with_for_update()
    )
    actual_revision = profile.revision if profile is not None else 0
    if actual_revision != expected_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Tenant experience revision conflict",
                "expected_revision": expected_revision,
                "actual_revision": actual_revision,
            },
        )
    if profile is not None:
        return profile
    defaults = default_experience()
    profile = TenantExperienceProfile(
        tenant_id=tenant_id,
        revision=0,
        product_name=defaults["product_name"],
        short_name=defaults["short_name"],
        logo_asset_id=None,
        primary_color=defaults["primary_color"],
        accent_color=defaults["accent_color"],
        surface_color=defaults["surface_color"],
        text_color=defaults["text_color"],
        ui_locale=defaults["ui_locale"],
        format_locale=defaults["format_locale"],
        timezone=defaults["timezone"],
        currency_code=defaults["currency_code"],
        date_style=defaults["date_style"],
        hour_cycle=defaults["hour_cycle"],
        first_day_of_week=defaults["first_day_of_week"],
        terminology_json=canonical_json(defaults["terminology"]),
        updated_by_id=actor_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(profile)
    return profile


def _record_revision(
    db: Session,
    *,
    profile: TenantExperienceProfile,
    settings: dict[str, object],
    actor_id: str,
    change_reason: str,
    rolled_back_from_revision: int | None = None,
) -> TenantExperienceRevision:
    snapshot_json, snapshot_sha256 = snapshot_evidence(settings)
    revision = TenantExperienceRevision(
        id=str(uuid.uuid4()),
        tenant_id=profile.tenant_id,
        revision=profile.revision,
        snapshot_json=snapshot_json,
        snapshot_sha256=snapshot_sha256,
        changed_by_id=actor_id,
        change_reason=" ".join(change_reason.split()),
        rolled_back_from_revision=rolled_back_from_revision,
        created_at=datetime.now(UTC),
    )
    db.add(revision)
    return revision


def _finalize_change(
    db: Session,
    *,
    http_request: Request,
    current_user: AuthUserResponse,
    profile: TenantExperienceProfile,
    settings: dict[str, object],
    change_reason: str,
    action: str,
    metadata: dict[str, object] | None = None,
    rolled_back_from_revision: int | None = None,
) -> None:
    now = datetime.now(UTC)
    profile.revision += 1
    profile.updated_by_id = current_user.id
    profile.updated_at = now
    _, snapshot_sha256 = snapshot_evidence(settings)
    _record_revision(
        db,
        profile=profile,
        settings=settings,
        actor_id=current_user.id,
        change_reason=change_reason,
        rolled_back_from_revision=rolled_back_from_revision,
    )
    actor = db.get(User, current_user.id)
    log_audit(
        db,
        action=action,
        entity_type="tenant_experience",
        entity_id=profile.tenant_id,
        actor_user=actor,
        tenant_id=profile.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "revision": profile.revision,
            "snapshot_sha256": snapshot_sha256,
            "change_reason_sha256": sha256_text(" ".join(change_reason.split())),
            **(metadata or {}),
        },
    )


def _commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Concurrent tenant experience update detected",
        ) from exc


@router.get("/current", response_model=ExperienceResponse)
def get_tenant_experience(
    response: Response,
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExperienceResponse:
    require_permissions(current_user, "tenant.experience.read")
    resolved_tenant_id = _resolve_tenant_id(db, current_user, tenant_id)
    profile = (
        db.get(TenantExperienceProfile, resolved_tenant_id)
        if resolved_tenant_id is not None
        else None
    )
    payload = _to_response(db, resolved_tenant_id, profile)
    response.headers["Cache-Control"] = "private, max-age=60"
    response.headers["ETag"] = f'"{payload.etag}"'
    return payload


@router.put("/current", response_model=ExperienceResponse)
def update_tenant_experience(
    payload: ExperienceUpdateRequest,
    http_request: Request,
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExperienceResponse:
    require_permissions(current_user, "tenant.experience.manage")
    resolved_tenant_id = _resolve_tenant_id(db, current_user, tenant_id)
    if resolved_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select a tenant before managing experience",
        )
    profile = _profile_for_update(
        db,
        resolved_tenant_id,
        payload.expected_revision,
        current_user.id,
    )
    current = profile_snapshot(profile)
    candidate = {
        **payload.settings.model_dump(),
        "logo_asset_id": current["logo_asset_id"],
    }
    try:
        normalized = validate_experience(candidate)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if canonical_json(normalized) == canonical_json(current):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tenant experience contains no changes",
        )
    changed_fields = sorted(
        key for key in normalized if normalized[key] != current[key]
    )
    apply_experience(profile, normalized)
    _finalize_change(
        db,
        http_request=http_request,
        current_user=current_user,
        profile=profile,
        settings=normalized,
        change_reason=payload.change_reason,
        action="tenant_experience.updated",
        metadata={
            "changed_fields": changed_fields,
            "contrast": experience_contrast(normalized),
        },
    )
    _commit_or_conflict(db)
    db.refresh(profile)
    return _to_response(db, resolved_tenant_id, profile)

@router.get("/revisions", response_model=list[ExperienceRevisionResponse])
def list_tenant_experience_revisions(
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ExperienceRevisionResponse]:
    require_permissions(current_user, "tenant.experience.rollback")
    resolved_tenant_id = _resolve_tenant_id(db, current_user, tenant_id)
    if resolved_tenant_id is None:
        return []
    rows = db.scalars(
        select(TenantExperienceRevision)
        .where(TenantExperienceRevision.tenant_id == resolved_tenant_id)
        .order_by(TenantExperienceRevision.revision.desc())
        .limit(limit)
    ).all()
    return [
        ExperienceRevisionResponse(
            revision=row.revision,
            snapshot_sha256=row.snapshot_sha256,
            integrity_valid=hashlib.sha256(
                row.snapshot_json.encode("utf-8")
            ).hexdigest()
            == row.snapshot_sha256,
            changed_by_id=row.changed_by_id,
            change_reason=row.change_reason,
            rolled_back_from_revision=row.rolled_back_from_revision,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/rollback", response_model=ExperienceResponse)
def rollback_tenant_experience(
    payload: ExperienceRollbackRequest,
    http_request: Request,
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExperienceResponse:
    require_permissions(current_user, "tenant.experience.rollback")
    resolved_tenant_id = _resolve_tenant_id(db, current_user, tenant_id)
    if resolved_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select a tenant before rolling back experience",
        )
    profile = _profile_for_update(
        db,
        resolved_tenant_id,
        payload.expected_revision,
        current_user.id,
    )
    target = db.scalar(
        select(TenantExperienceRevision).where(
            TenantExperienceRevision.tenant_id == resolved_tenant_id,
            TenantExperienceRevision.revision == payload.target_revision,
        )
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant experience revision not found",
        )
    if hashlib.sha256(target.snapshot_json.encode("utf-8")).hexdigest() != (
        target.snapshot_sha256
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Revision integrity check failed",
        )
    try:
        settings = validate_experience(json.loads(target.snapshot_json))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Revision snapshot is invalid",
        ) from exc
    logo_asset_id = settings["logo_asset_id"]
    if logo_asset_id is not None:
        asset = db.get(TenantBrandAsset, logo_asset_id)
        if asset is None or asset.tenant_id != resolved_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Revision logo evidence is unavailable",
            )
    apply_experience(profile, settings)
    _finalize_change(
        db,
        http_request=http_request,
        current_user=current_user,
        profile=profile,
        settings=settings,
        change_reason=payload.change_reason,
        action="tenant_experience.rolled_back",
        metadata={"target_revision": target.revision},
        rolled_back_from_revision=target.revision,
    )
    _commit_or_conflict(db)
    db.refresh(profile)
    return _to_response(db, resolved_tenant_id, profile)


@router.post("/logo", response_model=ExperienceResponse)
async def upload_tenant_logo(
    http_request: Request,
    expected_revision: int = Form(ge=0),
    change_reason: str = Form(min_length=5, max_length=500),
    file: UploadFile = File(...),
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExperienceResponse:
    require_permissions(current_user, "tenant.experience.manage")
    resolved_tenant_id = _resolve_tenant_id(db, current_user, tenant_id)
    if resolved_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select a tenant before uploading a logo",
        )
    payload = await file.read(MAX_LOGO_BYTES + 1)
    try:
        width, height = png_dimensions(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    logo_sha256 = hashlib.sha256(payload).hexdigest()
    asset = db.scalar(
        select(TenantBrandAsset).where(
            TenantBrandAsset.tenant_id == resolved_tenant_id,
            TenantBrandAsset.kind == "LOGO",
            TenantBrandAsset.sha256 == logo_sha256,
        )
    )
    if asset is None:
        asset_count = db.scalar(
            select(func.count(TenantBrandAsset.id)).where(
                TenantBrandAsset.tenant_id == resolved_tenant_id
            )
        ) or 0
        if asset_count >= MAX_BRAND_ASSETS_PER_TENANT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tenant brand asset retention limit reached",
            )
        asset = TenantBrandAsset(
            id=str(uuid.uuid4()),
            tenant_id=resolved_tenant_id,
            kind="LOGO",
            content_type="image/png",
            payload=payload,
            sha256=logo_sha256,
            size_bytes=len(payload),
            width=width,
            height=height,
            created_by_id=current_user.id,
            created_at=datetime.now(UTC),
        )
        db.add(asset)
    profile = _profile_for_update(
        db,
        resolved_tenant_id,
        expected_revision,
        current_user.id,
    )
    settings = profile_snapshot(profile)
    if settings["logo_asset_id"] == asset.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This logo is already active",
        )
    settings["logo_asset_id"] = asset.id
    apply_experience(profile, settings)
    _finalize_change(
        db,
        http_request=http_request,
        current_user=current_user,
        profile=profile,
        settings=settings,
        change_reason=change_reason,
        action="tenant_experience.logo_updated",
        metadata={
            "logo_sha256": logo_sha256,
            "size_bytes": len(payload),
            "width": width,
            "height": height,
        },
    )
    _commit_or_conflict(db)
    db.refresh(profile)
    return _to_response(db, resolved_tenant_id, profile)


@router.delete("/logo", response_model=ExperienceResponse)
def remove_tenant_logo(
    payload: ExperienceLogoRemoveRequest,
    http_request: Request,
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExperienceResponse:
    require_permissions(current_user, "tenant.experience.manage")
    resolved_tenant_id = _resolve_tenant_id(db, current_user, tenant_id)
    if resolved_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select a tenant before removing a logo",
        )
    profile = _profile_for_update(
        db,
        resolved_tenant_id,
        payload.expected_revision,
        current_user.id,
    )
    settings = profile_snapshot(profile)
    if settings["logo_asset_id"] is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tenant logo is not configured",
        )
    previous_logo_id = str(settings["logo_asset_id"])
    settings["logo_asset_id"] = None
    apply_experience(profile, settings)
    _finalize_change(
        db,
        http_request=http_request,
        current_user=current_user,
        profile=profile,
        settings=settings,
        change_reason=payload.change_reason,
        action="tenant_experience.logo_removed",
        metadata={"previous_logo_asset_id": previous_logo_id},
    )
    _commit_or_conflict(db)
    db.refresh(profile)
    return _to_response(db, resolved_tenant_id, profile)
