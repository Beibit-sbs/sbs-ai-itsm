from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.core.security import hash_password, validate_password_strength
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.external_identity import ExternalIdentity
from app.models.permission import Permission
from app.models.role import Role
from app.models.system_setting import SystemSetting
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit, parse_metadata, verify_audit_chains
from app.services.credential_crypto import encrypt_credential
from app.services.configuration_center import SETTING_CATALOG
from app.services.oidc import OidcClient, OidcError
from app.services.rbac import is_saas_root, require_permissions
from app.services.identity_lifecycle import (
    IdentityLifecycleError,
    ensure_tenant_admin_continuity,
    ownership_summary,
)
from app.services.password_policy import get_password_minimum_length

router = APIRouter(prefix="/admin")
settings = get_settings()


class UserResponse(BaseModel):
    id: str
    tenant_id: str | None
    email: str
    full_name: str
    position: str | None
    department: str | None
    location: str | None
    cost_center: str | None
    phone: str | None
    employee_number: str | None
    manager_id: str | None
    identity_source: str
    provisioning_state: str
    must_change_password: bool
    is_active: bool
    is_superuser: bool
    last_login_at: datetime | None
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserCreateRequest(BaseModel):
    tenant_id: str | None = None
    email: str
    full_name: str
    password: str
    position: str | None = None
    department: str | None = None
    location: str | None = None
    cost_center: str | None = None
    phone: str | None = None
    role_id: str | None = None
    role_ids: list[str] = Field(default_factory=list, max_length=32)


class UserPatchRequest(BaseModel):
    full_name: str | None = None
    position: str | None = None
    department: str | None = None
    location: str | None = None
    cost_center: str | None = None
    phone: str | None = None
    is_active: bool | None = None


class UserPasswordResetRequest(BaseModel):
    new_password: str
    revoke_sessions: bool = True


class UserPasswordResetResponse(BaseModel):
    user_id: str
    sessions_revoked: int
    password_change_required: bool


class RoleResponse(BaseModel):
    id: str
    tenant_id: str | None
    code: str
    name: str
    description: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime


class RoleCreateRequest(BaseModel):
    tenant_id: str | None = None
    code: str
    name: str
    description: str | None = None
    is_system: bool = False


class RolePatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_system: bool | None = None


class PermissionResponse(BaseModel):
    id: str
    code: str
    name: str
    description: str | None
    module: str


class UserRoleAssignRequest(BaseModel):
    role_ids: list[str]


class RolePermissionAssignRequest(BaseModel):
    permission_ids: list[str]


class ExternalIdentityLinkRequest(BaseModel):
    subject: str
    email_at_link: str | None = None


class ExternalIdentityResponse(BaseModel):
    id: str
    user_id: str
    provider_name: str
    issuer: str
    subject: str
    email_at_link: str
    created_at: datetime
    last_login_at: datetime | None


class AuditLogResponse(BaseModel):
    id: str
    tenant_id: str | None
    actor_user_id: str | None
    actor_email: str
    action: str
    entity_type: str
    entity_id: str | None
    ip_address: str | None
    user_agent: str | None
    metadata: dict[str, object]
    chain_scope: str
    sequence: int
    previous_hash: str | None
    event_hash: str
    created_at: datetime


class AuditIntegrityResponse(BaseModel):
    valid: bool
    events_checked: int
    chains_checked: int
    failures: list[dict[str, object]]


class SystemSettingResponse(BaseModel):
    id: str
    tenant_id: str | None
    key: str
    value: str | None
    description: str | None
    is_sensitive: bool
    updated_at: datetime


class SystemSettingPatchRequest(BaseModel):
    value: str


class AiProviderConfigResponse(BaseModel):
    provider: str
    openai_model: str
    openai_base_url: str
    gemini_model: str
    pii_redaction_enabled: bool
    request_timeout_seconds: float
    openai_api_key_configured: bool
    gemini_api_key_configured: bool
    updated_at: datetime | None = None


class AiProviderConfigPatchRequest(BaseModel):
    provider: Literal["mock", "openai", "gemini"] | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None
    gemini_model: str | None = None
    pii_redaction_enabled: bool | None = None
    request_timeout_seconds: float | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    clear_openai_api_key: bool = False
    clear_gemini_api_key: bool = False


class AiProviderConfigTestRequest(BaseModel):
    provider: Literal["mock", "openai", "gemini"] | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None
    gemini_model: str | None = None
    request_timeout_seconds: float | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    sample_text: str = "Пользователь не может войти в корпоративную систему и видит ошибку авторизации"


class AiProviderConfigTestResponse(BaseModel):
    requested_provider: str
    effective_provider: str
    model: str
    success: bool
    simulation: bool = False
    reason: str | None = None
    response_status: int | None = None
    summary: str | None = None
    category: str | None = None
    priority: str | None = None
    confidence: float | None = None
    rationale: str | None = None


class IdentityProviderStatusResponse(BaseModel):
    enabled: bool
    ready: bool
    provider_name: str
    button_label: str
    issuer_url: str | None
    redirect_uri: str | None
    client_id_configured: bool
    client_secret_configured: bool
    client_auth_method: str
    scopes: list[str]
    allowed_algorithms: list[str]
    allowed_email_domains: list[str]
    auto_provision: bool
    allow_email_linking: bool
    default_tenant_id: str | None
    default_role_code: str
    configuration_source: str
    linked_identities: int
    linked_users: int
    successful_logins_24h: int
    failed_logins_24h: int
    readiness_issues: list[str]


class IdentityProviderTestResponse(BaseModel):
    success: bool
    reason: str | None = None
    issuer: str | None = None
    authorization_endpoint_host: str | None = None
    token_endpoint_host: str | None = None
    jwks_host: str | None = None


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.scalar(select(User).where(User.id == current_user.id))


def _to_user_response(item: User) -> UserResponse:
    return UserResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        email=item.email,
        full_name=item.full_name,
        position=item.position,
        department=item.department,
        location=item.location,
        cost_center=item.cost_center,
        phone=item.phone,
        employee_number=item.employee_number,
        manager_id=item.manager_id,
        identity_source=item.identity_source,
        provisioning_state=item.provisioning_state,
        must_change_password=item.must_change_password,
        is_active=item.is_active,
        is_superuser=item.is_superuser,
        last_login_at=item.last_login_at,
        deactivated_at=item.deactivated_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _filter_users_by_tenant(statement: Select[tuple[User]], current_user: AuthUserResponse):
    if is_saas_root(current_user):
        return statement
    return statement.where(User.tenant_id == current_user.tenant_id)


def _filter_roles_by_tenant(statement: Select[tuple[Role]], current_user: AuthUserResponse):
    if is_saas_root(current_user):
        return statement
    return statement.where((Role.tenant_id == current_user.tenant_id) | (Role.tenant_id.is_(None)))


def _ensure_user_scope(current_user: AuthUserResponse, user: User) -> None:
    if is_saas_root(current_user):
        return
    if user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


def _ensure_role_scope(current_user: AuthUserResponse, role: Role) -> None:
    if is_saas_root(current_user):
        return
    if role.tenant_id not in {None, current_user.tenant_id}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")


def _ensure_role_assignment_scope(current_user: AuthUserResponse, role: Role) -> None:
    _ensure_role_scope(current_user, role)
    if not is_saas_root(current_user) and role.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global roles cannot be assigned by an organization administrator",
        )


def _ensure_permissions_delegable(
    current_user: AuthUserResponse,
    permissions: list[Permission],
) -> None:
    if is_saas_root(current_user):
        return
    actor_permissions = set(current_user.permissions)
    narrower_scope_substitutes = {
        "tickets.scope.assigned": {"tickets.scope.all", "tickets.assign"},
        "tickets.scope.requester": {"tickets.scope.all"},
        "requests.scope.requester": {"requests.scope.all", "requests.manage"},
    }
    prohibited = sorted(
        permission.code
        for permission in permissions
        if permission.code not in actor_permissions
        and actor_permissions.isdisjoint(
            narrower_scope_substitutes.get(permission.code, set())
        )
    )
    if prohibited:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "A role cannot grant permissions that the current "
                "administrator does not hold"
            ),
        )


def _ensure_record_read_scopes(permissions: list[Permission]) -> None:
    codes = {permission.code for permission in permissions}
    ticket_scopes = {
        "tickets.scope.all",
        "tickets.scope.assigned",
        "tickets.scope.requester",
        "tickets.assign",
        "tickets.self_assign",
    }
    if "tickets.read" in codes and codes.isdisjoint(ticket_scopes):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "tickets.read requires a ticket visibility scope "
                "(all, assigned, requester, assign, or self_assign)"
            ),
        )

    request_scopes = {
        "requests.scope.all",
        "requests.scope.requester",
        "requests.manage",
        "requests.fulfill",
        "requests.approve",
    }
    if "requests.read" in codes and codes.isdisjoint(request_scopes):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "requests.read requires a service-request visibility scope "
                "(all, requester, manage, fulfill, or approve)"
            ),
        )


def _ensure_role_matches_user_tenant(role: Role, tenant_id: str | None) -> None:
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Organization is required before assigning a role",
        )
    if role.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global platform roles cannot be assigned to organization users",
        )
    if role.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Selected role belongs to another organization",
        )


def _ensure_role_mutation_scope(current_user: AuthUserResponse, role: Role) -> None:
    _ensure_role_scope(current_user, role)
    if not is_saas_root(current_user) and (
        role.tenant_id is None or role.is_system
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Global and system roles are read-only for organization "
                "administrators; create a custom tenant role instead"
            ),
        )


def _ensure_tenant_admin_continuity(
    db: Session,
    user: User,
    *,
    replacement_roles: list[Role] | None = None,
    deactivating: bool = False,
) -> None:
    try:
        ensure_tenant_admin_continuity(
            db,
            user,
            replacement_roles=replacement_roles,
            deactivating=deactivating,
        )
    except IdentityLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc


_AI_SETTING_DEFS: dict[str, tuple[str, bool]] = {
    "ai_provider": ("Active AI provider", False),
    "openai_api_key": ("OpenAI API key", True),
    "openai_model": ("OpenAI model", False),
    "openai_base_url": ("OpenAI-compatible base URL", False),
    "gemini_api_key": ("Gemini API key", True),
    "gemini_model": ("Gemini model", False),
    "ai_pii_redaction": ("Enable PII redaction before external AI calls", False),
    "ai_request_timeout_seconds": ("AI provider request timeout in seconds", False),
}


def _get_global_setting(db: Session, key: str) -> SystemSetting | None:
    return db.scalar(select(SystemSetting).where(SystemSetting.tenant_id.is_(None), SystemSetting.key == key))


def _upsert_global_setting(db: Session, key: str, value: str) -> SystemSetting:
    description, is_sensitive = _AI_SETTING_DEFS[key]
    stored_value = value
    if is_sensitive and value:
        stored_value = encrypt_credential(
            value,
            purpose=f"system_setting:{key}",
            tenant_id="global",
        )
    setting = _get_global_setting(db, key)
    if setting is None:
        setting = SystemSetting(
            id=str(uuid.uuid4()),
            tenant_id=None,
            key=key,
            value=stored_value,
            description=description,
            is_sensitive=is_sensitive,
            updated_at=datetime.now(UTC),
        )
        db.add(setting)
        db.flush()
        return setting

    setting.value = stored_value
    setting.description = description
    setting.is_sensitive = is_sensitive
    setting.updated_at = datetime.now(UTC)
    db.flush()
    return setting


def _ai_config_payload(db: Session) -> AiProviderConfigResponse:
    runtime_settings = get_settings()
    latest_update = max(
        (item.updated_at for item in db.scalars(select(SystemSetting).where(SystemSetting.tenant_id.is_(None), SystemSetting.key.in_(tuple(_AI_SETTING_DEFS.keys())))).all()),
        default=None,
    )
    return AiProviderConfigResponse(
        provider=(runtime_settings.ai_provider or "mock").strip().lower(),
        openai_model=runtime_settings.openai_model,
        openai_base_url=runtime_settings.openai_base_url,
        gemini_model=runtime_settings.gemini_model,
        pii_redaction_enabled=bool(runtime_settings.ai_pii_redaction),
        request_timeout_seconds=max(1.0, float(runtime_settings.ai_request_timeout_seconds)),
        openai_api_key_configured=bool(runtime_settings.openai_api_key),
        gemini_api_key_configured=bool(runtime_settings.gemini_api_key),
        updated_at=latest_update,
    )


def _identity_provider_payload(
    db: Session,
    current_user: AuthUserResponse,
) -> IdentityProviderStatusResponse:
    runtime_settings = get_settings()
    issues: list[str] = []
    if not runtime_settings.oidc_enabled:
        issues.append("OIDC is disabled")
    if not runtime_settings.oidc_issuer_url:
        issues.append("OIDC issuer URL is not configured")
    if not runtime_settings.oidc_client_id:
        issues.append("OIDC client ID is not configured")
    if not runtime_settings.oidc_client_secret:
        issues.append("OIDC client secret is not configured")
    if not runtime_settings.oidc_redirect_uri:
        issues.append("OIDC redirect URI is not configured")
    if not runtime_settings.oidc_allowed_email_domains:
        issues.append("Allowed email domains are empty")
    if runtime_settings.oidc_auto_provision and not runtime_settings.oidc_default_tenant_id:
        issues.append("Auto-provisioning requires a default tenant")

    identity_count_stmt = select(func.count(ExternalIdentity.id)).join(
        User, User.id == ExternalIdentity.user_id
    )
    user_count_stmt = select(func.count(func.distinct(ExternalIdentity.user_id))).join(
        User, User.id == ExternalIdentity.user_id
    )
    login_stmt = select(AuditLog.action, func.count(AuditLog.id)).where(
        AuditLog.action.in_(["oidc_login_success", "oidc_login_failed"]),
        AuditLog.created_at >= datetime.now(UTC) - timedelta(hours=24),
    )
    if not is_saas_root(current_user):
        identity_count_stmt = identity_count_stmt.where(User.tenant_id == current_user.tenant_id)
        user_count_stmt = user_count_stmt.where(User.tenant_id == current_user.tenant_id)
        login_stmt = login_stmt.where(AuditLog.tenant_id == current_user.tenant_id)
    login_counts = dict(db.execute(login_stmt.group_by(AuditLog.action)).all())

    return IdentityProviderStatusResponse(
        enabled=runtime_settings.oidc_enabled,
        ready=not issues,
        provider_name=runtime_settings.oidc_provider_name,
        button_label=runtime_settings.oidc_button_label,
        issuer_url=runtime_settings.oidc_issuer_url,
        redirect_uri=runtime_settings.oidc_redirect_uri,
        client_id_configured=bool(runtime_settings.oidc_client_id),
        client_secret_configured=bool(runtime_settings.oidc_client_secret),
        client_auth_method=runtime_settings.oidc_client_auth_method,
        scopes=list(runtime_settings.oidc_scopes),
        allowed_algorithms=list(runtime_settings.oidc_allowed_algorithms),
        allowed_email_domains=list(runtime_settings.oidc_allowed_email_domains),
        auto_provision=runtime_settings.oidc_auto_provision,
        allow_email_linking=runtime_settings.oidc_allow_email_linking,
        default_tenant_id=runtime_settings.oidc_default_tenant_id,
        default_role_code=runtime_settings.oidc_default_role_code,
        configuration_source="environment_and_secret_manager",
        linked_identities=int(db.scalar(identity_count_stmt) or 0),
        linked_users=int(db.scalar(user_count_stmt) or 0),
        successful_logins_24h=int(login_counts.get("oidc_login_success", 0)),
        failed_logins_24h=int(login_counts.get("oidc_login_failed", 0)),
        readiness_issues=issues,
    )


@router.get("/users", response_model=list[UserResponse])
def list_users(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    role_id: str | None = Query(default=None),
    active: bool | None = Query(default=None),
) -> list[UserResponse]:
    require_permissions(current_user, "admin.users.read")
    statement = _filter_users_by_tenant(select(User).order_by(User.created_at.desc()), current_user)
    if role_id:
        statement = statement.where((User.role_id == role_id) | (User.roles.any(Role.id == role_id)))
    if active is not None:
        statement = statement.where(User.is_active == active)
    users = db.scalars(statement).all()
    return [_to_user_response(item) for item in users]


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> UserResponse:
    require_permissions(current_user, "admin.users.read")
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _ensure_user_scope(current_user, user)
    return _to_user_response(user)


@router.get(
    "/users/{user_id}/external-identities",
    response_model=list[ExternalIdentityResponse],
)
def list_user_external_identities(
    user_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ExternalIdentityResponse]:
    require_permissions(current_user, "admin.users.read")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _ensure_user_scope(current_user, user)
    rows = db.scalars(
        select(ExternalIdentity)
        .where(ExternalIdentity.user_id == user.id)
        .order_by(ExternalIdentity.created_at.asc())
    ).all()
    return [ExternalIdentityResponse.model_validate(item, from_attributes=True) for item in rows]


@router.post(
    "/users/{user_id}/external-identities",
    response_model=ExternalIdentityResponse,
    status_code=status.HTTP_201_CREATED,
)
def link_user_external_identity(
    user_id: str,
    payload: ExternalIdentityLinkRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExternalIdentityResponse:
    require_permissions(current_user, "admin.users.update")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _ensure_user_scope(current_user, user)
    issuer = (settings.oidc_issuer_url or "").rstrip("/")
    subject = payload.subject.strip()
    if not settings.oidc_enabled or not issuer:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OIDC must be configured before identities can be linked",
        )
    if not subject or len(subject) > 255:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OIDC subject")
    if db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == issuer,
            ExternalIdentity.subject == subject,
        )
    ) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OIDC subject is already linked",
        )
    if db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.user_id == user.id,
            ExternalIdentity.provider_name == settings.oidc_provider_name,
        )
    ) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already has an identity for this provider",
        )
    email_at_link = (payload.email_at_link or user.email).strip().lower()
    if "@" not in email_at_link or len(email_at_link) > 255:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid identity email")
    identity = ExternalIdentity(
        id=str(uuid.uuid4()),
        user_id=user.id,
        provider_name=settings.oidc_provider_name,
        issuer=issuer,
        subject=subject,
        email_at_link=email_at_link,
    )
    db.add(identity)
    log_audit(
        db,
        action="external_identity_linked",
        entity_type="user",
        entity_id=user.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"provider": identity.provider_name, "identity_id": identity.id},
    )
    db.commit()
    db.refresh(identity)
    return ExternalIdentityResponse.model_validate(identity, from_attributes=True)


@router.delete("/users/{user_id}/external-identities/{identity_id}", status_code=204)
def unlink_user_external_identity(
    user_id: str,
    identity_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    require_permissions(current_user, "admin.users.update")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _ensure_user_scope(current_user, user)
    identity = db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.id == identity_id,
            ExternalIdentity.user_id == user.id,
        )
    )
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="External identity not found"
        )
    provider_name = identity.provider_name
    db.delete(identity)
    log_audit(
        db,
        action="external_identity_unlinked",
        entity_type="user",
        entity_id=user.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"provider": provider_name, "identity_id": identity_id},
    )
    db.commit()


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    request: UserCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    require_permissions(current_user, "admin.users.create")
    if db.scalar(select(User).where(User.email == request.email)) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User email already exists")

    tenant_id = request.tenant_id if is_saas_root(current_user) else current_user.tenant_id
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Organization is required for a new user",
        )
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status.lower() != "active":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Selected organization is unavailable",
        )
    password_error = validate_password_strength(
        request.password,
        minimum_length=get_password_minimum_length(db, tenant_id),
        demo_mode=settings.demo_mode,
    )
    if password_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=password_error)

    role_ids = list(
        dict.fromkeys(
            [
                *(request.role_ids or []),
                *([request.role_id] if request.role_id else []),
            ]
        )
    )
    roles = (
        db.scalars(select(Role).where(Role.id.in_(role_ids))).all()
        if role_ids
        else []
    )
    if len(roles) != len(role_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more roles were not found",
        )
    roles_by_id = {role.id: role for role in roles}
    ordered_roles = [roles_by_id[role_id] for role_id in role_ids]
    for role in ordered_roles:
        _ensure_role_assignment_scope(current_user, role)
        _ensure_role_matches_user_tenant(role, tenant_id)
        _ensure_permissions_delegable(current_user, list(role.permissions))

    now = datetime.now(UTC)
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        role_id=ordered_roles[0].id if ordered_roles else None,
        email=request.email,
        full_name=request.full_name,
        position=request.position,
        department=request.department,
        location=request.location,
        cost_center=request.cost_center,
        phone=request.phone,
        password_hash=hash_password(request.password),
        must_change_password=True,
        is_active=True,
        is_superuser=False,
        is_root=False,
        created_at=now,
        updated_at=now,
    )
    if ordered_roles:
        user.roles = ordered_roles
    db.add(user)
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="user_created",
        entity_type="user",
        entity_id=user.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"email": user.email},
    )
    db.commit()
    db.refresh(user)
    return _to_user_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def patch_user(
    user_id: str,
    request: UserPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    require_permissions(current_user, "admin.users.update")
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _ensure_user_scope(current_user, user)

    updates = request.model_dump(exclude_unset=True)
    if "is_active" in updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use the dedicated activate/deactivate lifecycle action",
        )
    if user.identity_source in {"SCIM", "ENTRA"} and updates:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This profile is authoritative in the identity provider",
        )
    for field_name, value in updates.items():
        setattr(user, field_name, value)
    user.updated_at = datetime.now(UTC)

    actor = _actor(db, current_user)
    log_audit(
        db,
        action="user_updated",
        entity_type="user",
        entity_id=user.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"updated_fields": list(updates.keys())},
    )
    db.commit()
    db.refresh(user)
    return _to_user_response(user)


@router.post("/users/{user_id}/reset-password", response_model=UserPasswordResetResponse)
def reset_user_password(
    user_id: str,
    request: UserPasswordResetRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPasswordResetResponse:
    require_permissions(current_user, "admin.users.update")
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _ensure_user_scope(current_user, user)
    if user.identity_source in {"OIDC", "SCIM", "ENTRA"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Password reset is disabled for provisioned identities",
        )
    if not request.revoke_sessions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Session revocation is mandatory for an administrative password reset",
        )

    password_error = validate_password_strength(
        request.new_password,
        minimum_length=get_password_minimum_length(db, user.tenant_id),
        demo_mode=settings.demo_mode,
    )
    if password_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=password_error)

    user.password_hash = hash_password(request.new_password)
    user.must_change_password = True
    user.updated_at = datetime.now(UTC)
    sessions_revoked = 0
    if request.revoke_sessions:
        active_sessions = db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
        ).all()
        revoked_at = datetime.now(UTC)
        for auth_session in active_sessions:
            auth_session.revoked_at = revoked_at
        sessions_revoked = len(active_sessions)

    log_audit(
        db,
        action="user_password_reset",
        entity_type="user",
        entity_id=user.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "sessions_revoked": sessions_revoked,
            "password_change_required": True,
        },
    )
    db.commit()
    return UserPasswordResetResponse(
        user_id=user.id,
        sessions_revoked=sessions_revoked,
        password_change_required=True,
    )


@router.patch("/users/{user_id}/activate", response_model=UserResponse)
def activate_user(
    user_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    require_permissions(current_user, "admin.users.update")
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _ensure_user_scope(current_user, user)
    if user.identity_source in {"SCIM", "ENTRA"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reactivate this identity in the authoritative identity provider",
        )
    user.is_active = True
    user.deactivated_at = None
    user.provisioning_state = (
        "LOCAL" if user.identity_source == "LOCAL" else "ACTIVE"
    )
    user.updated_at = datetime.now(UTC)
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="user_activated",
        entity_type="user",
        entity_id=user.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"email": user.email},
    )
    db.commit()
    db.refresh(user)
    return _to_user_response(user)


@router.patch("/users/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(
    user_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    require_permissions(current_user, "admin.users.update")
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _ensure_user_scope(current_user, user)
    if user.id == current_user.id or user.is_root or user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Self, root, and superuser accounts cannot be deactivated",
        )
    if user.identity_source in {"SCIM", "ENTRA"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deprovision this identity in the authoritative identity provider",
        )
    _ensure_tenant_admin_continuity(db, user, deactivating=True)
    if user.tenant_id is not None:
        owned = ownership_summary(db, tenant_id=user.tenant_id, user=user)
        if owned.total:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        "User owns active work. Use Identity Provisioning safe "
                        "deactivation and select a fallback owner."
                    ),
                    "ownership": owned.as_dict(),
                },
            )
    user.is_active = False
    user.provisioning_state = "DEPROVISIONED"
    user.deactivated_at = datetime.now(UTC)
    user.updated_at = datetime.now(UTC)
    active_sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    revoked_at = datetime.now(UTC)
    for auth_session in active_sessions:
        auth_session.revoked_at = revoked_at
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="user_deactivated",
        entity_type="user",
        entity_id=user.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"email": user.email, "sessions_revoked": len(active_sessions)},
    )
    db.commit()
    db.refresh(user)
    return _to_user_response(user)


@router.get("/users/{user_id}/roles", response_model=list[RoleResponse])
def list_user_roles(user_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[RoleResponse]:
    require_permissions(current_user, "admin.roles.read")
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _ensure_user_scope(current_user, user)
    roles = user.roles[:]
    if user.role and user.role not in roles:
        roles.append(user.role)
    return [
        RoleResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            code=item.code,
            name=item.name,
            description=item.description,
            is_system=item.is_system,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in roles
    ]


@router.post("/users/{user_id}/roles", response_model=list[RoleResponse])
def assign_roles_to_user(
    user_id: str,
    request: UserRoleAssignRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RoleResponse]:
    require_permissions(current_user, "admin.roles.manage")
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _ensure_user_scope(current_user, user)
    if user.identity_source in {"SCIM", "ENTRA"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Roles for this identity are authoritative in provisioned "
                "group mappings"
            ),
        )

    role_ids = list(dict.fromkeys(request.role_ids))
    loaded_roles = (
        db.scalars(select(Role).where(Role.id.in_(role_ids))).all()
        if role_ids
        else []
    )
    if len(loaded_roles) != len(role_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more roles not found")
    roles_by_id = {role.id: role for role in loaded_roles}
    roles = [roles_by_id[role_id] for role_id in role_ids]
    for role in roles:
        _ensure_role_assignment_scope(current_user, role)
        _ensure_role_matches_user_tenant(role, user.tenant_id)
        _ensure_permissions_delegable(current_user, list(role.permissions))

    _ensure_tenant_admin_continuity(db, user, replacement_roles=list(roles))
    user.roles = roles
    user.role_id = roles[0].id if roles else None
    user.updated_at = datetime.now(UTC)

    actor = _actor(db, current_user)
    log_audit(
        db,
        action="role_assigned",
        entity_type="user",
        entity_id=user.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"role_codes": [item.code for item in roles]},
    )
    db.commit()
    return [
        RoleResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            code=item.code,
            name=item.name,
            description=item.description,
            is_system=item.is_system,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in roles
    ]


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[RoleResponse]:
    require_permissions(current_user, "admin.roles.read")
    roles = db.scalars(_filter_roles_by_tenant(select(Role).order_by(Role.code.asc()), current_user)).all()
    return [
        RoleResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            code=item.code,
            name=item.name,
            description=item.description,
            is_system=item.is_system,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in roles
    ]


@router.get("/roles/{role_id}", response_model=RoleResponse)
def get_role(role_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> RoleResponse:
    require_permissions(current_user, "admin.roles.read")
    role = db.scalar(select(Role).where(Role.id == role_id))
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    _ensure_role_scope(current_user, role)
    return RoleResponse(
        id=role.id,
        tenant_id=role.tenant_id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def create_role(
    request: RoleCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoleResponse:
    require_permissions(current_user, "admin.roles.manage")
    tenant_id = request.tenant_id if is_saas_root(current_user) else current_user.tenant_id
    normalized_code = request.code.strip().lower()
    normalized_name = request.name.strip()
    if re.fullmatch(r"[a-z0-9_]{2,120}", normalized_code) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role code must contain 2-120 lowercase letters, digits, or underscores",
        )
    if not normalized_name or len(normalized_name) > 120:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role name")
    if normalized_code == "saas_root" and tenant_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The saas_root role code is reserved for the global root role",
        )
    if db.scalar(select(Role).where(Role.code == normalized_code, Role.tenant_id == tenant_id)) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role code already exists")

    now = datetime.now(UTC)
    role = Role(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=normalized_code,
        name=normalized_name,
        scope="tenant" if tenant_id is not None else "global",
        description=request.description,
        is_system=request.is_system if is_saas_root(current_user) else False,
        created_at=now,
        updated_at=now,
    )
    db.add(role)
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="role_created",
        entity_type="role",
        entity_id=role.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"role_code": role.code},
    )
    db.commit()
    db.refresh(role)
    return RoleResponse(
        id=role.id,
        tenant_id=role.tenant_id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


@router.patch("/roles/{role_id}", response_model=RoleResponse)
def patch_role(
    role_id: str,
    request: RolePatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoleResponse:
    require_permissions(current_user, "admin.roles.manage")
    role = db.scalar(select(Role).where(Role.id == role_id))
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    _ensure_role_mutation_scope(current_user, role)

    updates = request.model_dump(exclude_unset=True)
    if not is_saas_root(current_user):
        updates.pop("is_system", None)
    for field_name, value in updates.items():
        setattr(role, field_name, value)
    role.updated_at = datetime.now(UTC)

    actor = _actor(db, current_user)
    log_audit(
        db,
        action="role_updated",
        entity_type="role",
        entity_id=role.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"updated_fields": list(updates.keys())},
    )
    db.commit()
    db.refresh(role)
    return RoleResponse(
        id=role.id,
        tenant_id=role.tenant_id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


@router.get("/roles/{role_id}/permissions", response_model=list[PermissionResponse])
def list_role_permissions(
    role_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PermissionResponse]:
    require_permissions(current_user, "admin.roles.read")
    role = db.scalar(select(Role).where(Role.id == role_id))
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    _ensure_role_scope(current_user, role)
    return [
        PermissionResponse(
            id=item.id,
            code=item.code,
            name=item.name,
            description=item.description,
            module=item.module,
        )
        for item in sorted(role.permissions, key=lambda permission: (permission.module, permission.code))
    ]


@router.put("/roles/{role_id}/permissions", response_model=list[PermissionResponse])
def replace_role_permissions(
    role_id: str,
    request: RolePermissionAssignRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PermissionResponse]:
    require_permissions(current_user, "admin.roles.manage")
    role = db.scalar(select(Role).where(Role.id == role_id))
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    _ensure_role_mutation_scope(current_user, role)

    permission_ids = list(dict.fromkeys(request.permission_ids))
    permissions = (
        db.scalars(select(Permission).where(Permission.id.in_(permission_ids))).all()
        if permission_ids
        else []
    )
    if len(permissions) != len(permission_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more permissions were not found",
        )
    _ensure_permissions_delegable(current_user, list(permissions))
    _ensure_record_read_scopes(list(permissions))

    previous_codes = sorted(item.code for item in role.permissions)
    role.permissions = sorted(permissions, key=lambda permission: (permission.module, permission.code))
    role.updated_at = datetime.now(UTC)
    current_codes = [item.code for item in role.permissions]
    log_audit(
        db,
        action="role_permissions_changed",
        entity_type="role",
        entity_id=role.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "role_code": role.code,
            "added": sorted(set(current_codes) - set(previous_codes)),
            "removed": sorted(set(previous_codes) - set(current_codes)),
        },
    )
    db.commit()
    return [
        PermissionResponse(
            id=item.id,
            code=item.code,
            name=item.name,
            description=item.description,
            module=item.module,
        )
        for item in role.permissions
    ]


@router.get("/permissions", response_model=list[PermissionResponse])
def list_permissions(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[PermissionResponse]:
    require_permissions(current_user, "admin.permissions.read")
    statement = select(Permission).order_by(
        Permission.module.asc(),
        Permission.code.asc(),
    )
    if not is_saas_root(current_user):
        statement = statement.where(
            Permission.code.in_(tuple(current_user.permissions))
        )
    permissions = db.scalars(statement).all()
    return [
        PermissionResponse(
            id=item.id,
            code=item.code,
            name=item.name,
            description=item.description,
            module=item.module,
        )
        for item in permissions
    ]


@router.get("/audit-logs", response_model=list[AuditLogResponse])
def list_audit_logs(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    action: str | None = Query(default=None),
    actor_email: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
) -> list[AuditLogResponse]:
    require_permissions(current_user, "security.audit.read")
    statement = select(AuditLog).order_by(AuditLog.created_at.desc())
    if not is_saas_root(current_user):
        statement = statement.where(AuditLog.tenant_id == current_user.tenant_id)
    if action:
        statement = statement.where(AuditLog.action == action)
    if actor_email:
        statement = statement.where(AuditLog.actor_email == actor_email)
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type)
    logs = db.scalars(statement.limit(500)).all()
    return [
        AuditLogResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            actor_user_id=item.actor_user_id,
            actor_email=item.actor_email,
            action=item.action,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            ip_address=item.ip_address,
            user_agent=item.user_agent,
            metadata=parse_metadata(item.metadata_json),
            chain_scope=item.chain_scope,
            sequence=item.sequence,
            previous_hash=item.previous_hash,
            event_hash=item.event_hash,
            created_at=item.created_at,
        )
        for item in logs
    ]


@router.get("/audit-logs/integrity", response_model=AuditIntegrityResponse)
def verify_audit_log_integrity(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditIntegrityResponse:
    require_permissions(current_user, "security.audit.read")
    scopes: set[str] | None = None
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant scope is required to verify audit integrity",
            )
        scopes = {current_user.tenant_id}
    return AuditIntegrityResponse.model_validate(
        verify_audit_chains(db, scopes=scopes)
    )


@router.get("/audit-logs/{audit_id}", response_model=AuditLogResponse)
def get_audit_log(audit_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> AuditLogResponse:
    require_permissions(current_user, "security.audit.read")
    audit = db.scalar(select(AuditLog).where(AuditLog.id == audit_id))
    if audit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    if not is_saas_root(current_user) and audit.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    return AuditLogResponse(
        id=audit.id,
        tenant_id=audit.tenant_id,
        actor_user_id=audit.actor_user_id,
        actor_email=audit.actor_email,
        action=audit.action,
        entity_type=audit.entity_type,
        entity_id=audit.entity_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        metadata=parse_metadata(audit.metadata_json),
        chain_scope=audit.chain_scope,
        sequence=audit.sequence,
        previous_hash=audit.previous_hash,
        event_hash=audit.event_hash,
        created_at=audit.created_at,
    )


@router.get("/settings", response_model=list[SystemSettingResponse])
def list_settings(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SystemSettingResponse]:
    require_permissions(current_user, "admin.settings.read")
    if is_saas_root(current_user):
        settings = db.scalars(
            select(SystemSetting)
            .where(SystemSetting.tenant_id.is_(None))
            .order_by(SystemSetting.key.asc())
        ).all()
    else:
        candidates = db.scalars(
            select(SystemSetting)
            .where(
                (SystemSetting.tenant_id == current_user.tenant_id)
                | (SystemSetting.tenant_id.is_(None))
            )
            .order_by(SystemSetting.key.asc())
        ).all()
        effective: dict[str, SystemSetting] = {}
        for item in candidates:
            existing = effective.get(item.key)
            if existing is None or item.tenant_id == current_user.tenant_id:
                effective[item.key] = item
        settings = [effective[key] for key in sorted(effective)]
    return [
        SystemSettingResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            key=item.key,
            value=None if item.is_sensitive else item.value,
            description=item.description,
            is_sensitive=item.is_sensitive,
            updated_at=item.updated_at,
        )
        for item in settings
    ]


@router.patch("/settings/{setting_key}", response_model=SystemSettingResponse)
def patch_setting(
    setting_key: str,
    request: SystemSettingPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SystemSettingResponse:
    require_permissions(current_user, "admin.settings.update")
    if setting_key in SETTING_CATALOG:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Use the typed Configuration Center endpoint for this setting",
        )
    target_tenant_id = None if is_saas_root(current_user) else current_user.tenant_id
    setting = db.scalar(
        select(SystemSetting).where(
            SystemSetting.key == setting_key,
            SystemSetting.tenant_id == target_tenant_id
            if target_tenant_id is not None
            else SystemSetting.tenant_id.is_(None),
        )
    )
    if setting is None and target_tenant_id is not None:
        inherited = db.scalar(
            select(SystemSetting).where(
                SystemSetting.key == setting_key,
                SystemSetting.tenant_id.is_(None),
            )
        )
        if inherited is not None:
            setting = SystemSetting(
                id=str(uuid.uuid4()),
                tenant_id=target_tenant_id,
                key=inherited.key,
                value=inherited.value,
                description=inherited.description,
                is_sensitive=inherited.is_sensitive,
                updated_at=datetime.now(UTC),
            )
            db.add(setting)
            db.flush()
    if setting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")
    if setting.is_sensitive:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sensitive setting cannot be updated from this endpoint")

    setting.value = request.value
    setting.updated_at = datetime.now(UTC)

    actor = _actor(db, current_user)
    log_audit(
        db,
        action="setting_changed",
        entity_type="system_setting",
        entity_id=setting.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"key": setting.key},
    )
    db.commit()
    db.refresh(setting)
    return SystemSettingResponse(
        id=setting.id,
        tenant_id=setting.tenant_id,
        key=setting.key,
        value=None if setting.is_sensitive else setting.value,
        description=setting.description,
        is_sensitive=setting.is_sensitive,
        updated_at=setting.updated_at,
    )


@router.get("/identity-provider", response_model=IdentityProviderStatusResponse)
def get_identity_provider_status(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IdentityProviderStatusResponse:
    require_permissions(current_user, "admin.settings.read")
    return _identity_provider_payload(db, current_user)


@router.post("/identity-provider/test", response_model=IdentityProviderTestResponse)
async def test_identity_provider(
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IdentityProviderTestResponse:
    require_permissions(current_user, "admin.settings.update")
    runtime_settings = get_settings()
    success = False
    reason: str | None = None
    metadata: dict[str, object] = {}
    if not runtime_settings.oidc_enabled:
        reason = "OIDC is disabled"
    else:
        try:
            metadata = await OidcClient(runtime_settings).metadata(force=True)
            success = True
        except OidcError as exc:
            reason = str(exc)

    log_audit(
        db,
        action="identity_provider_tested",
        entity_type="identity_provider",
        entity_id=runtime_settings.oidc_provider_name,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"success": success, "reason": reason},
    )
    db.commit()

    def host(field: str) -> str | None:
        value = str(metadata.get(field) or "")
        return urlsplit(value).hostname if value else None

    return IdentityProviderTestResponse(
        success=success,
        reason=reason,
        issuer=str(metadata.get("issuer") or "") or runtime_settings.oidc_issuer_url,
        authorization_endpoint_host=host("authorization_endpoint"),
        token_endpoint_host=host("token_endpoint"),
        jwks_host=host("jwks_uri"),
    )


@router.get("/ai-provider-config", response_model=AiProviderConfigResponse)
def get_ai_provider_config(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiProviderConfigResponse:
    require_permissions(current_user, "admin.settings.read")
    from app.services.ai.provider import _overlay_settings_from_db

    runtime_settings = get_settings()
    _overlay_settings_from_db(runtime_settings)
    return _ai_config_payload(db)


@router.patch("/ai-provider-config", response_model=AiProviderConfigResponse)
def patch_ai_provider_config(
    request: AiProviderConfigPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiProviderConfigResponse:
    require_permissions(current_user, "admin.settings.update")
    if not is_saas_root(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global AI provider configuration requires SaaS Root",
        )

    if request.request_timeout_seconds is not None and request.request_timeout_seconds <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="AI request timeout must be positive")

    runtime_settings = get_settings()
    from app.services.ai.provider import _overlay_settings_from_db

    _overlay_settings_from_db(runtime_settings)
    updated_keys: list[str] = []

    effective_openai_key = (
        request.openai_api_key.strip()
        if request.openai_api_key is not None
        else runtime_settings.openai_api_key
    )
    if request.clear_openai_api_key:
        effective_openai_key = None

    effective_gemini_key = (
        request.gemini_api_key.strip()
        if request.gemini_api_key is not None
        else runtime_settings.gemini_api_key
    )
    if request.clear_gemini_api_key:
        effective_gemini_key = None

    effective_provider = request.provider or runtime_settings.ai_provider or "mock"
    if effective_provider == "openai" and not effective_openai_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot activate OpenAI without API key")
    if effective_provider == "gemini" and not effective_gemini_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot activate Gemini without API key")

    if request.provider is not None:
        _upsert_global_setting(db, "ai_provider", request.provider)
        runtime_settings.ai_provider = request.provider
        updated_keys.append("ai_provider")
    if request.openai_model is not None:
        _upsert_global_setting(db, "openai_model", request.openai_model.strip())
        runtime_settings.openai_model = request.openai_model.strip()
        updated_keys.append("openai_model")
    if request.openai_base_url is not None:
        _upsert_global_setting(db, "openai_base_url", request.openai_base_url.strip())
        runtime_settings.openai_base_url = request.openai_base_url.strip()
        updated_keys.append("openai_base_url")
    if request.gemini_model is not None:
        _upsert_global_setting(db, "gemini_model", request.gemini_model.strip())
        runtime_settings.gemini_model = request.gemini_model.strip()
        updated_keys.append("gemini_model")
    if request.pii_redaction_enabled is not None:
        _upsert_global_setting(db, "ai_pii_redaction", "true" if request.pii_redaction_enabled else "false")
        runtime_settings.ai_pii_redaction = request.pii_redaction_enabled
        updated_keys.append("ai_pii_redaction")
    if request.request_timeout_seconds is not None:
        value = str(request.request_timeout_seconds)
        _upsert_global_setting(db, "ai_request_timeout_seconds", value)
        runtime_settings.ai_request_timeout_seconds = request.request_timeout_seconds
        updated_keys.append("ai_request_timeout_seconds")
    if request.openai_api_key is not None:
        value = request.openai_api_key.strip()
        _upsert_global_setting(db, "openai_api_key", value)
        runtime_settings.openai_api_key = value or None
        updated_keys.append("openai_api_key")
    if request.gemini_api_key is not None:
        value = request.gemini_api_key.strip()
        _upsert_global_setting(db, "gemini_api_key", value)
        runtime_settings.gemini_api_key = value or None
        updated_keys.append("gemini_api_key")
    if request.clear_openai_api_key:
        _upsert_global_setting(db, "openai_api_key", "")
        runtime_settings.openai_api_key = None
        updated_keys.append("openai_api_key")
    if request.clear_gemini_api_key:
        _upsert_global_setting(db, "gemini_api_key", "")
        runtime_settings.gemini_api_key = None
        updated_keys.append("gemini_api_key")

    actor = _actor(db, current_user)
    log_audit(
        db,
        action="ai_provider_config_changed",
        entity_type="ai_provider_config",
        entity_id="global",
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"updated_keys": updated_keys},
    )
    db.commit()
    return _ai_config_payload(db)


@router.post("/ai-provider-config/test", response_model=AiProviderConfigTestResponse)
def test_ai_provider_config(
    request: AiProviderConfigTestRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiProviderConfigTestResponse:
    require_permissions(current_user, "admin.settings.update")
    if not is_saas_root(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global AI provider connection tests require SaaS Root",
        )

    runtime_settings = get_settings()
    from app.services.ai.provider import _overlay_settings_from_db

    _overlay_settings_from_db(runtime_settings)
    provider = request.provider or (runtime_settings.ai_provider or "mock")
    openai_model = request.openai_model or runtime_settings.openai_model
    openai_base_url = request.openai_base_url or runtime_settings.openai_base_url
    gemini_model = request.gemini_model or runtime_settings.gemini_model
    timeout = request.request_timeout_seconds or runtime_settings.ai_request_timeout_seconds
    openai_api_key = request.openai_api_key if request.openai_api_key is not None else runtime_settings.openai_api_key
    gemini_api_key = request.gemini_api_key if request.gemini_api_key is not None else runtime_settings.gemini_api_key

    from app.services.ai.provider import check_provider_configuration

    result = asyncio.run(
        check_provider_configuration(
            provider=provider,
            sample_text=request.sample_text,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            openai_base_url=openai_base_url,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            timeout=timeout,
        )
    )
    log_audit(
        db,
        action="ai_provider_connection_tested",
        entity_type="ai_provider_config",
        entity_id=provider,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "requested_provider": result.requested_provider,
            "effective_provider": result.effective_provider,
            "model": result.model,
            "success": result.success,
            "simulation": result.simulation,
            "reason": result.reason,
            "response_status": result.response_status,
        },
    )
    db.commit()

    return AiProviderConfigTestResponse(
        requested_provider=result.requested_provider,
        effective_provider=result.effective_provider,
        model=result.model,
        success=result.success,
        simulation=result.simulation,
        reason=result.reason,
        response_status=result.response_status,
        summary=result.summary,
        category=result.category,
        priority=result.priority,
        confidence=result.confidence,
        rationale=result.rationale,
    )
