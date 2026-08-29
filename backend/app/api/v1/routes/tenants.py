from __future__ import annotations

from datetime import UTC, datetime
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.permission import Permission
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.cmdb_bootstrap import ensure_standard_cmdb_model
from app.services.rbac import is_saas_root, require_permissions
from app.services.seed import ROLE_DEFS

router = APIRouter(prefix="/tenants")
TENANT_ROLE_CODES = (
    "organization_admin",
    "it_manager",
    "it_agent",
    "requester",
    "security_officer",
    "knowledge_manager",
)
SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,118}[a-z0-9])?$")


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class TenantProfilePatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class TenantCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=4_000)


def _to_response(tenant: Tenant) -> TenantResponse:
    return TenantResponse.model_validate(tenant, from_attributes=True)


@router.get("", response_model=list[TenantResponse])
def list_tenants(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TenantResponse]:
    require_permissions(current_user, "tenant.read")
    if not is_saas_root(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant fleet access requires SaaS root",
        )
    tenants = db.scalars(select(Tenant).order_by(Tenant.name.asc())).all()
    return [_to_response(tenant) for tenant in tenants]


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenantResponse:
    require_permissions(current_user, "tenant.manage")
    if not is_saas_root(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant provisioning requires SaaS root",
        )

    slug = payload.slug.strip().lower()
    if not SLUG_PATTERN.fullmatch(slug):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Slug must contain lowercase Latin letters, digits, and hyphens",
        )
    duplicate = db.scalar(
        select(Tenant.id).where(func.lower(Tenant.slug) == slug)
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization slug already exists",
        )

    now = datetime.now(UTC)
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=payload.name.strip(),
        slug=slug,
        status="active",
        description=payload.description.strip() if payload.description else None,
        created_at=now,
        updated_at=now,
    )
    db.add(tenant)
    db.flush()

    permissions = {
        permission.code: permission
        for permission in db.scalars(select(Permission)).all()
    }
    for role_code in TENANT_ROLE_CODES:
        definition = ROLE_DEFS[role_code]
        role = Role(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            code=role_code,
            name=definition["name"],
            scope="tenant",
            description=definition["description"],
            is_system=True,
            created_at=now,
            updated_at=now,
        )
        role.permissions = [
            permissions[permission_code]
            for permission_code in definition["permissions"]
            if permission_code in permissions
        ]
        db.add(role)

    cmdb_bootstrap = ensure_standard_cmdb_model(
        db,
        tenant.id,
        current_user.id,
    )
    actor = db.get(User, current_user.id)
    log_audit(
        db,
        action="tenant_created",
        entity_type="tenant",
        entity_id=tenant.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "name": tenant.name,
            "slug": tenant.slug,
            "provisioned_roles": list(TENANT_ROLE_CODES),
            "cmdb_bootstrap": cmdb_bootstrap,
        },
    )
    db.commit()
    db.refresh(tenant)
    return _to_response(tenant)


@router.get("/current", response_model=TenantResponse | None)
def get_current_tenant(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenantResponse | None:
    require_permissions(current_user, "tenant.profile.read")
    if current_user.tenant_id is None:
        return None
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return _to_response(tenant)


@router.patch("/current", response_model=TenantResponse)
def patch_current_tenant(
    payload: TenantProfilePatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenantResponse:
    require_permissions(current_user, "tenant.profile.manage")
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Root session has no current tenant",
        )
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        name = str(updates["name"] or "").strip()
        if not name or len(name) > 200:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant name")
        tenant.name = name
    if "description" in updates:
        description = str(updates["description"] or "").strip()
        tenant.description = description[:4000] or None
    tenant.updated_at = datetime.now(UTC)

    actor = db.get(User, current_user.id)
    log_audit(
        db,
        action="tenant_profile_updated",
        entity_type="tenant",
        entity_id=tenant.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"updated_fields": sorted(updates.keys())},
    )
    db.commit()
    db.refresh(tenant)
    return _to_response(tenant)
