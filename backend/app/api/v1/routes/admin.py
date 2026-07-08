from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.core.security import hash_password, validate_password_strength
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.permission import Permission
from app.models.role import Role
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services.audit import log_audit, parse_metadata
from app.services.rbac import is_saas_root, require_permissions

router = APIRouter(prefix="/admin")
settings = get_settings()


class UserResponse(BaseModel):
    id: str
    tenant_id: str | None
    email: str
    full_name: str
    position: str | None
    department: str | None
    phone: str | None
    is_active: bool
    is_superuser: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserCreateRequest(BaseModel):
    tenant_id: str | None = None
    email: str
    full_name: str
    password: str
    position: str | None = None
    department: str | None = None
    phone: str | None = None
    role_id: str | None = None


class UserPatchRequest(BaseModel):
    full_name: str | None = None
    position: str | None = None
    department: str | None = None
    phone: str | None = None
    is_active: bool | None = None


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
    created_at: datetime


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
        phone=item.phone,
        is_active=item.is_active,
        is_superuser=item.is_superuser,
        last_login_at=item.last_login_at,
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


def _password_min_length(db: Session, tenant_id: str | None) -> int:
    statement = select(SystemSetting).where(SystemSetting.key == "password_min_length")
    candidate = db.scalar(statement.where(SystemSetting.tenant_id == tenant_id)) if tenant_id else None
    if candidate is None:
        candidate = db.scalar(statement.where(SystemSetting.tenant_id.is_(None)))
    try:
        return int(candidate.value) if candidate is not None else 10
    except (TypeError, ValueError):
        return 10


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
    password_error = validate_password_strength(
        request.password,
        minimum_length=_password_min_length(db, tenant_id),
        demo_mode=settings.demo_mode,
    )
    if password_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=password_error)

    role: Role | None = None
    if request.role_id:
        role = db.scalar(select(Role).where(Role.id == request.role_id))
        if role is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role not found")
        _ensure_role_scope(current_user, role)

    now = datetime.now(UTC)
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        role_id=role.id if role else None,
        email=request.email,
        full_name=request.full_name,
        position=request.position,
        department=request.department,
        phone=request.phone,
        password_hash=hash_password(request.password),
        is_active=True,
        is_superuser=False,
        is_root=False,
        created_at=now,
        updated_at=now,
    )
    if role is not None:
        user.roles = [role]
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
    user.is_active = True
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
    user.is_active = False
    user.updated_at = datetime.now(UTC)
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="user_deactivated",
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

    roles = db.scalars(select(Role).where(Role.id.in_(request.role_ids))).all() if request.role_ids else []
    if len(roles) != len(set(request.role_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more roles not found")
    for role in roles:
        _ensure_role_scope(current_user, role)

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
    if db.scalar(select(Role).where(Role.code == request.code, Role.tenant_id == tenant_id)) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role code already exists")

    now = datetime.now(UTC)
    role = Role(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=request.code,
        name=request.name,
        scope="tenant" if tenant_id is not None else "global",
        description=request.description,
        is_system=request.is_system,
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
    _ensure_role_scope(current_user, role)

    updates = request.model_dump(exclude_unset=True)
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


@router.get("/permissions", response_model=list[PermissionResponse])
def list_permissions(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[PermissionResponse]:
    require_permissions(current_user, "admin.permissions.read")
    permissions = db.scalars(select(Permission).order_by(Permission.module.asc(), Permission.code.asc())).all()
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
            created_at=item.created_at,
        )
        for item in logs
    ]


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
        created_at=audit.created_at,
    )


@router.get("/settings", response_model=list[SystemSettingResponse])
def list_settings(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SystemSettingResponse]:
    require_permissions(current_user, "admin.settings.read")
    statement = select(SystemSetting).order_by(SystemSetting.key.asc())
    if not is_saas_root(current_user):
        statement = statement.where((SystemSetting.tenant_id == current_user.tenant_id) | (SystemSetting.tenant_id.is_(None)))
    settings = db.scalars(statement).all()
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
    statement = select(SystemSetting).where(SystemSetting.key == setting_key)
    if not is_saas_root(current_user):
        statement = statement.where((SystemSetting.tenant_id == current_user.tenant_id) | (SystemSetting.tenant_id.is_(None)))
    setting = db.scalar(statement)
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
