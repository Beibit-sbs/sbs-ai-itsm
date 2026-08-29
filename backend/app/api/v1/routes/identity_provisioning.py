from __future__ import annotations

import ipaddress
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.identity_provisioning import (
    IdentityOwnershipTransfer,
    IdentityProvisioningConnector,
    IdentityProvisioningEvent,
    ProvisionedGroup,
    ProvisionedGroupMember,
    ProvisionedIdentity,
)
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.identity_lifecycle import (
    IdentityLifecycleError,
    apply_identity_roles,
    deactivate_provisioned_user,
    ensure_tenant_admin_continuity,
    generate_connector_token,
    ownership_summary,
    transfer_user_ownership,
    utcnow,
)
from app.services.rbac import is_saas_root, require_permissions
from app.services.scim_provisioning import (
    DEFAULT_ATTRIBUTE_MAPPING,
    SUPPORTED_USER_TARGETS,
    ScimProvisioningError,
    mark_event_applied,
    mark_event_failed,
    replay_provisioning_event,
)


router = APIRouter(prefix="/identity-provisioning")


class ConnectorCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=3, max_length=160)
    provider_type: Literal["SCIM", "ENTRA"] = "ENTRA"
    external_tenant_id: str | None = Field(default=None, max_length=255)
    default_role_id: str
    fallback_owner_id: str
    attribute_mapping: dict[str, str] = Field(default_factory=dict)
    allowed_ip_cidrs: list[str] = Field(default_factory=list, max_length=100)
    retry_max_attempts: int = Field(default=5, ge=1, le=20)

    @field_validator("allowed_ip_cidrs")
    @classmethod
    def validate_cidrs(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            try:
                normalized.append(str(ipaddress.ip_network(value, strict=False)))
            except ValueError as exc:
                raise ValueError(f"Invalid CIDR: {value}") from exc
        return list(dict.fromkeys(normalized))

    @field_validator("attribute_mapping")
    @classmethod
    def validate_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        unsupported = set(value) - SUPPORTED_USER_TARGETS
        if unsupported:
            raise ValueError(
                f"Unsupported mapping targets: {', '.join(sorted(unsupported))}"
            )
        if any(not source.strip() for source in value.values()):
            raise ValueError("Attribute mapping paths cannot be empty")
        return {target: source.strip() for target, source in value.items()}


class ConnectorUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=3, max_length=160)
    external_tenant_id: str | None = Field(default=None, max_length=255)
    default_role_id: str | None = None
    fallback_owner_id: str | None = None
    attribute_mapping: dict[str, str] | None = None
    allowed_ip_cidrs: list[str] | None = Field(default=None, max_length=100)
    retry_max_attempts: int | None = Field(default=None, ge=1, le=20)

    @field_validator("allowed_ip_cidrs")
    @classmethod
    def validate_cidrs(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized: list[str] = []
        for value in values:
            try:
                normalized.append(str(ipaddress.ip_network(value, strict=False)))
            except ValueError as exc:
                raise ValueError(f"Invalid CIDR: {value}") from exc
        return list(dict.fromkeys(normalized))

    @field_validator("attribute_mapping")
    @classmethod
    def validate_mapping(
        cls,
        value: dict[str, str] | None,
    ) -> dict[str, str] | None:
        if value is None:
            return None
        unsupported = set(value) - SUPPORTED_USER_TARGETS
        if unsupported:
            raise ValueError(
                f"Unsupported mapping targets: {', '.join(sorted(unsupported))}"
            )
        if any(not source.strip() for source in value.values()):
            raise ValueError("Attribute mapping paths cannot be empty")
        return {target: source.strip() for target, source in value.items()}


class ConnectorStateChange(BaseModel):
    expected_version: int = Field(ge=1)
    action: Literal["ACTIVATE", "PAUSE", "REVOKE"]
    reason: str = Field(min_length=3, max_length=2_000)


class GroupRoleMapping(BaseModel):
    expected_version: int = Field(ge=1)
    role_id: str | None = None


class ManualLifecycleRequest(BaseModel):
    fallback_owner_id: str
    reason: str = Field(min_length=5, max_length=4_000)


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.get(User, current_user.id)


def _tenant_scope(
    current_user: AuthUserResponse,
    requested_tenant_id: str | None,
    *,
    required_for_root: bool = False,
) -> str | None:
    if is_saas_root(current_user):
        if required_for_root and not requested_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tenant_id is required for SaaS root",
            )
        return requested_tenant_id
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context is required",
        )
    if requested_tenant_id and requested_tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant access denied",
        )
    return current_user.tenant_id


def _ensure_tenant_access(
    current_user: AuthUserResponse,
    tenant_id: str,
) -> None:
    _tenant_scope(current_user, tenant_id)


def _connector(
    db: Session,
    current_user: AuthUserResponse,
    connector_id: str,
) -> IdentityProvisioningConnector:
    item = db.get(IdentityProvisioningConnector, connector_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity connector not found",
        )
    _ensure_tenant_access(current_user, item.tenant_id)
    return item


def _role_for_connector(
    db: Session,
    *,
    tenant_id: str,
    role_id: str,
) -> Role:
    role = db.get(Role, role_id)
    if role is None or role.tenant_id != tenant_id or role.code == "saas_root":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A tenant-scoped role is required",
        )
    return role


def _fallback_owner(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
) -> User:
    user = db.get(User, user_id)
    if (
        user is None
        or user.tenant_id != tenant_id
        or not user.is_active
        or user.is_root
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fallback owner must be an active user in the connector tenant",
        )
    return user


def _count(
    db: Session,
    model: type,
    *conditions: object,
) -> int:
    return int(
        db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    )


def _connector_dict(
    db: Session,
    item: IdentityProvisioningConnector,
) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "name": item.name,
        "provider_type": item.provider_type,
        "external_tenant_id": item.external_tenant_id,
        "status": item.status,
        "token_hint": item.token_hint,
        "token_rotated_at": item.token_rotated_at,
        "default_role_id": item.default_role_id,
        "fallback_owner_id": item.fallback_owner_id,
        "attribute_mapping": {
            **DEFAULT_ATTRIBUTE_MAPPING,
            **(item.attribute_mapping_json or {}),
        },
        "allowed_ip_cidrs": item.allowed_ip_cidrs_json or [],
        "retry_max_attempts": item.retry_max_attempts,
        "last_success_at": item.last_success_at,
        "last_failure_at": item.last_failure_at,
        "success_count": item.success_count,
        "failure_count": item.failure_count,
        "last_error": item.last_error,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "scim_base_path": "/api/v1/scim/v2",
        "counts": {
            "identities": _count(
                db,
                ProvisionedIdentity,
                ProvisionedIdentity.connector_id == item.id,
            ),
            "active_identities": _count(
                db,
                ProvisionedIdentity,
                ProvisionedIdentity.connector_id == item.id,
                ProvisionedIdentity.lifecycle_state == "ACTIVE",
            ),
            "groups": _count(
                db,
                ProvisionedGroup,
                ProvisionedGroup.connector_id == item.id,
                ProvisionedGroup.is_active.is_(True),
            ),
            "retry_queue": _count(
                db,
                IdentityProvisioningEvent,
                IdentityProvisioningEvent.connector_id == item.id,
                IdentityProvisioningEvent.status == "RETRY_SCHEDULED",
            ),
            "dead_letter": _count(
                db,
                IdentityProvisioningEvent,
                IdentityProvisioningEvent.connector_id == item.id,
                IdentityProvisioningEvent.status == "DEAD_LETTER",
            ),
        },
    }


def _identity_dict(
    db: Session,
    identity: ProvisionedIdentity,
) -> dict[str, Any]:
    user = db.get(User, identity.user_id)
    groups = db.execute(
        select(ProvisionedGroup.id, ProvisionedGroup.display_name)
        .join(
            ProvisionedGroupMember,
            ProvisionedGroupMember.group_id == ProvisionedGroup.id,
        )
        .where(ProvisionedGroupMember.identity_id == identity.id)
        .order_by(ProvisionedGroup.display_name.asc())
    ).all()
    return {
        "id": identity.id,
        "tenant_id": identity.tenant_id,
        "connector_id": identity.connector_id,
        "user_id": identity.user_id,
        "external_id": identity.external_id,
        "user_name": identity.user_name,
        "lifecycle_state": identity.lifecycle_state,
        "manager_external_id": identity.manager_external_id,
        "scim_version": identity.scim_version,
        "last_synced_at": identity.last_synced_at,
        "deprovisioned_at": identity.deprovisioned_at,
        "created_at": identity.created_at,
        "user": (
            {
                "email": user.email,
                "full_name": user.full_name,
                "position": user.position,
                "department": user.department,
                "location": user.location,
                "employee_number": user.employee_number,
                "is_active": user.is_active,
                "manager_id": user.manager_id,
                "role_id": user.role_id,
            }
            if user
            else None
        ),
        "groups": [
            {"id": group_id, "display_name": display_name}
            for group_id, display_name in groups
        ],
    }


def _group_dict(db: Session, group: ProvisionedGroup) -> dict[str, Any]:
    return {
        "id": group.id,
        "tenant_id": group.tenant_id,
        "connector_id": group.connector_id,
        "external_id": group.external_id,
        "display_name": group.display_name,
        "mapped_role_id": group.mapped_role_id,
        "is_active": group.is_active,
        "scim_version": group.scim_version,
        "last_synced_at": group.last_synced_at,
        "member_count": _count(
            db,
            ProvisionedGroupMember,
            ProvisionedGroupMember.group_id == group.id,
        ),
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def _event_dict(event: IdentityProvisioningEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "tenant_id": event.tenant_id,
        "connector_id": event.connector_id,
        "external_event_id": event.external_event_id,
        "resource_type": event.resource_type,
        "operation": event.operation,
        "external_id": event.external_id,
        "status": event.status,
        "attempts": event.attempts,
        "error_code": event.error_code,
        "error_message": event.error_message,
        "next_retry_at": event.next_retry_at,
        "applied_user_id": event.applied_user_id,
        "completed_at": event.completed_at,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


@router.get("/dashboard")
def dashboard(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.read")
    scoped_tenant = _tenant_scope(current_user, tenant_id)
    connector_filter: list[object] = []
    identity_filter: list[object] = []
    event_filter: list[object] = []
    transfer_filter: list[object] = []
    if scoped_tenant:
        connector_filter.append(
            IdentityProvisioningConnector.tenant_id == scoped_tenant
        )
        identity_filter.append(ProvisionedIdentity.tenant_id == scoped_tenant)
        event_filter.append(IdentityProvisioningEvent.tenant_id == scoped_tenant)
        transfer_filter.append(
            IdentityOwnershipTransfer.tenant_id == scoped_tenant
        )
    return {
        "connectors": _count(
            db,
            IdentityProvisioningConnector,
            *connector_filter,
        ),
        "active_connectors": _count(
            db,
            IdentityProvisioningConnector,
            *connector_filter,
            IdentityProvisioningConnector.status == "ACTIVE",
        ),
        "active_identities": _count(
            db,
            ProvisionedIdentity,
            *identity_filter,
            ProvisionedIdentity.lifecycle_state == "ACTIVE",
        ),
        "deprovisioned_identities": _count(
            db,
            ProvisionedIdentity,
            *identity_filter,
            ProvisionedIdentity.lifecycle_state == "DEPROVISIONED",
        ),
        "retry_queue": _count(
            db,
            IdentityProvisioningEvent,
            *event_filter,
            IdentityProvisioningEvent.status == "RETRY_SCHEDULED",
        ),
        "dead_letter": _count(
            db,
            IdentityProvisioningEvent,
            *event_filter,
            IdentityProvisioningEvent.status == "DEAD_LETTER",
        ),
        "ownership_transfers": _count(
            db,
            IdentityOwnershipTransfer,
            *transfer_filter,
        ),
    }


@router.get("/connectors")
def list_connectors(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "identity.provisioning.read")
    scoped_tenant = _tenant_scope(current_user, tenant_id)
    statement = select(IdentityProvisioningConnector)
    if scoped_tenant:
        statement = statement.where(
            IdentityProvisioningConnector.tenant_id == scoped_tenant
        )
    items = db.scalars(
        statement.order_by(IdentityProvisioningConnector.created_at.desc())
    ).all()
    return [_connector_dict(db, item) for item in items]


@router.post("/connectors", status_code=status.HTTP_201_CREATED)
def create_connector(
    payload: ConnectorCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.manage")
    tenant_id = _tenant_scope(
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    assert tenant_id is not None
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status.lower() != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An active tenant is required",
        )
    _role_for_connector(db, tenant_id=tenant_id, role_id=payload.default_role_id)
    _fallback_owner(
        db,
        tenant_id=tenant_id,
        user_id=payload.fallback_owner_id,
    )
    token, token_hash, token_hint = generate_connector_token()
    now = utcnow()
    connector = IdentityProvisioningConnector(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=payload.name.strip(),
        provider_type=payload.provider_type,
        external_tenant_id=(
            payload.external_tenant_id.strip()
            if payload.external_tenant_id
            else None
        ),
        status="DRAFT",
        token_hash=token_hash,
        token_hint=token_hint,
        token_rotated_at=now,
        default_role_id=payload.default_role_id,
        fallback_owner_id=payload.fallback_owner_id,
        attribute_mapping_json=payload.attribute_mapping,
        allowed_ip_cidrs_json=payload.allowed_ip_cidrs,
        retry_max_attempts=payload.retry_max_attempts,
        last_success_at=None,
        last_failure_at=None,
        success_count=0,
        failure_count=0,
        last_error=None,
        version=1,
        created_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(connector)
    actor = _actor(db, current_user)
    log_audit(
        db,
        action="identity_connector_created",
        entity_type="identity_provisioning_connector",
        entity_id=connector.id,
        actor_user=actor,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={
            "name": connector.name,
            "provider_type": connector.provider_type,
            "token_hint": connector.token_hint,
        },
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connector name, token, or external tenant is already in use",
        ) from exc
    db.refresh(connector)
    return {
        "connector": _connector_dict(db, connector),
        "bearer_token": token,
        "token_notice": "This token is shown once. Store it in the identity provider now.",
    }


@router.get("/connectors/{connector_id}")
def get_connector(
    connector_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.read")
    return _connector_dict(db, _connector(db, current_user, connector_id))


@router.patch("/connectors/{connector_id}")
def update_connector(
    connector_id: str,
    payload: ConnectorUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.manage")
    connector = _connector(db, current_user, connector_id)
    if connector.status == "REVOKED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A revoked connector cannot be modified",
        )
    if connector.version != payload.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connector was updated by another administrator",
        )
    if payload.default_role_id:
        _role_for_connector(
            db,
            tenant_id=connector.tenant_id,
            role_id=payload.default_role_id,
        )
        connector.default_role_id = payload.default_role_id
    if payload.fallback_owner_id:
        _fallback_owner(
            db,
            tenant_id=connector.tenant_id,
            user_id=payload.fallback_owner_id,
        )
        connector.fallback_owner_id = payload.fallback_owner_id
    if payload.name is not None:
        connector.name = payload.name.strip()
    if payload.external_tenant_id is not None:
        connector.external_tenant_id = payload.external_tenant_id.strip() or None
    if payload.attribute_mapping is not None:
        connector.attribute_mapping_json = payload.attribute_mapping
    if payload.allowed_ip_cidrs is not None:
        connector.allowed_ip_cidrs_json = payload.allowed_ip_cidrs
    if payload.retry_max_attempts is not None:
        connector.retry_max_attempts = payload.retry_max_attempts
    connector.version += 1
    connector.updated_at = utcnow()
    log_audit(
        db,
        action="identity_connector_updated",
        entity_type="identity_provisioning_connector",
        entity_id=connector.id,
        actor_user=_actor(db, current_user),
        tenant_id=connector.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={
            "status": connector.status,
            "version": connector.version,
        },
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connector name or external tenant is already in use",
        ) from exc
    db.refresh(connector)
    return _connector_dict(db, connector)


@router.post("/connectors/{connector_id}/state")
def change_connector_state(
    connector_id: str,
    payload: ConnectorStateChange,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.manage")
    connector = _connector(db, current_user, connector_id)
    if connector.version != payload.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connector was updated by another administrator",
        )
    transitions = {
        "ACTIVATE": {"DRAFT", "PAUSED"},
        "PAUSE": {"ACTIVE"},
        "REVOKE": {"DRAFT", "ACTIVE", "PAUSED"},
    }
    if connector.status not in transitions[payload.action]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot {payload.action.lower()} connector from {connector.status}",
        )
    if payload.action == "ACTIVATE":
        _role_for_connector(
            db,
            tenant_id=connector.tenant_id,
            role_id=connector.default_role_id,
        )
        _fallback_owner(
            db,
            tenant_id=connector.tenant_id,
            user_id=connector.fallback_owner_id,
        )
        connector.status = "ACTIVE"
    elif payload.action == "PAUSE":
        connector.status = "PAUSED"
    else:
        connector.status = "REVOKED"
    connector.version += 1
    connector.updated_at = utcnow()
    log_audit(
        db,
        action=f"identity_connector_{payload.action.lower()}d",
        entity_type="identity_provisioning_connector",
        entity_id=connector.id,
        actor_user=_actor(db, current_user),
        tenant_id=connector.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"reason": payload.reason, "version": connector.version},
    )
    db.commit()
    db.refresh(connector)
    return _connector_dict(db, connector)


@router.post("/connectors/{connector_id}/rotate-token")
def rotate_connector_token(
    connector_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.manage")
    connector = _connector(db, current_user, connector_id)
    if connector.status == "REVOKED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A revoked connector cannot rotate credentials",
        )
    token, token_hash, token_hint = generate_connector_token()
    connector.token_hash = token_hash
    connector.token_hint = token_hint
    connector.token_rotated_at = utcnow()
    connector.version += 1
    connector.updated_at = utcnow()
    log_audit(
        db,
        action="identity_connector_token_rotated",
        entity_type="identity_provisioning_connector",
        entity_id=connector.id,
        actor_user=_actor(db, current_user),
        tenant_id=connector.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"token_hint": token_hint, "version": connector.version},
    )
    db.commit()
    return {
        "connector": _connector_dict(db, connector),
        "bearer_token": token,
        "token_notice": "The previous token is invalid. This token is shown once.",
    }


@router.get("/identities")
def list_identities(
    tenant_id: str | None = Query(default=None),
    connector_id: str | None = Query(default=None),
    lifecycle_state: Literal["ACTIVE", "SUSPENDED", "DEPROVISIONED"] | None = Query(
        default=None
    ),
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=250),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.read")
    scoped_tenant = _tenant_scope(current_user, tenant_id)
    statement = select(ProvisionedIdentity).join(
        User,
        User.id == ProvisionedIdentity.user_id,
    )
    if scoped_tenant:
        statement = statement.where(
            ProvisionedIdentity.tenant_id == scoped_tenant
        )
    if connector_id:
        connector = _connector(db, current_user, connector_id)
        statement = statement.where(
            ProvisionedIdentity.connector_id == connector.id
        )
    if lifecycle_state:
        statement = statement.where(
            ProvisionedIdentity.lifecycle_state == lifecycle_state
        )
    if search:
        pattern = f"%{search.strip().lower()}%"
        statement = statement.where(
            func.lower(User.email).like(pattern)
            | func.lower(User.full_name).like(pattern)
            | func.lower(ProvisionedIdentity.external_id).like(pattern)
        )
    total = int(
        db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    items = db.scalars(
        statement
        .order_by(ProvisionedIdentity.last_synced_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_identity_dict(db, item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/identities/{identity_id}/ownership")
def preview_identity_ownership(
    identity_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.read")
    identity = db.get(ProvisionedIdentity, identity_id)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provisioned identity not found",
        )
    _ensure_tenant_access(current_user, identity.tenant_id)
    user = db.get(User, identity.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Linked user not found",
        )
    return {
        "identity_id": identity.id,
        "user_id": user.id,
        **ownership_summary(
            db,
            tenant_id=identity.tenant_id,
            user=user,
        ).as_dict(),
    }


@router.post("/identities/{identity_id}/deprovision")
def manual_deprovision_identity(
    identity_id: str,
    payload: ManualLifecycleRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.manage")
    identity = db.get(ProvisionedIdentity, identity_id)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provisioned identity not found",
        )
    _ensure_tenant_access(current_user, identity.tenant_id)
    connector = db.get(IdentityProvisioningConnector, identity.connector_id)
    fallback = _fallback_owner(
        db,
        tenant_id=identity.tenant_id,
        user_id=payload.fallback_owner_id,
    )
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provisioning connector no longer exists",
        )
    try:
        transfer = deactivate_provisioned_user(
            db,
            connector=connector,
            identity=identity,
            fallback_owner=fallback,
            reason=payload.reason,
            initiated_by=_actor(db, current_user),
        )
    except IdentityLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc
    log_audit(
        db,
        action="identity_manual_deprovision",
        entity_type="provisioned_identity",
        entity_id=identity.id,
        actor_user=_actor(db, current_user),
        tenant_id=identity.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"ownership_transfer_id": transfer.id},
    )
    db.commit()
    return {
        "identity": _identity_dict(db, identity),
        "ownership_transfer": {
            "id": transfer.id,
            "from_user_id": transfer.from_user_id,
            "to_user_id": transfer.to_user_id,
            "counts": transfer.transferred_counts_json,
            "sessions_revoked": transfer.sessions_revoked,
        },
    }


@router.get("/groups")
def list_groups(
    tenant_id: str | None = Query(default=None),
    connector_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "identity.provisioning.read")
    scoped_tenant = _tenant_scope(current_user, tenant_id)
    statement = select(ProvisionedGroup)
    if scoped_tenant:
        statement = statement.where(ProvisionedGroup.tenant_id == scoped_tenant)
    if connector_id:
        connector = _connector(db, current_user, connector_id)
        statement = statement.where(
            ProvisionedGroup.connector_id == connector.id
        )
    groups = db.scalars(
        statement.order_by(ProvisionedGroup.display_name.asc())
    ).all()
    return [_group_dict(db, group) for group in groups]


@router.patch("/groups/{group_id}/role-mapping")
def map_group_role(
    group_id: str,
    payload: GroupRoleMapping,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.manage")
    group = db.get(ProvisionedGroup, group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provisioned group not found",
        )
    _ensure_tenant_access(current_user, group.tenant_id)
    if group.scim_version != payload.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Group was updated by the identity provider",
        )
    if payload.role_id:
        _role_for_connector(
            db,
            tenant_id=group.tenant_id,
            role_id=payload.role_id,
        )
    group.mapped_role_id = payload.role_id
    group.scim_version += 1
    group.updated_at = utcnow()
    # Role resolution queries the persisted group mapping. SessionLocal has
    # autoflush disabled, so make the new mapping visible before recalculating
    # every active member.
    db.flush()
    connector = db.get(IdentityProvisioningConnector, group.connector_id)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provisioning connector no longer exists",
        )
    identities = db.scalars(
        select(ProvisionedIdentity)
        .join(
            ProvisionedGroupMember,
            ProvisionedGroupMember.identity_id == ProvisionedIdentity.id,
        )
        .where(ProvisionedGroupMember.group_id == group.id)
    ).all()
    for identity in identities:
        if identity.lifecycle_state == "ACTIVE":
            apply_identity_roles(db, connector=connector, identity=identity)
    log_audit(
        db,
        action="identity_group_role_mapped",
        entity_type="provisioned_group",
        entity_id=group.id,
        actor_user=_actor(db, current_user),
        tenant_id=group.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={
            "role_id": payload.role_id,
            "affected_identities": len(identities),
        },
    )
    db.commit()
    db.refresh(group)
    return _group_dict(db, group)


@router.get("/events")
def list_events(
    tenant_id: str | None = Query(default=None),
    connector_id: str | None = Query(default=None),
    event_status: Literal[
        "RECEIVED",
        "APPLIED",
        "FAILED",
        "RETRY_SCHEDULED",
        "DEAD_LETTER",
    ]
    | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=250),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.read")
    scoped_tenant = _tenant_scope(current_user, tenant_id)
    statement = select(IdentityProvisioningEvent)
    if scoped_tenant:
        statement = statement.where(
            IdentityProvisioningEvent.tenant_id == scoped_tenant
        )
    if connector_id:
        connector = _connector(db, current_user, connector_id)
        statement = statement.where(
            IdentityProvisioningEvent.connector_id == connector.id
        )
    if event_status:
        statement = statement.where(
            IdentityProvisioningEvent.status == event_status
        )
    total = int(
        db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    items = db.scalars(
        statement
        .order_by(IdentityProvisioningEvent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_event_dict(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/events/{event_id}/retry")
def retry_event(
    event_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.manage")
    event = db.get(IdentityProvisioningEvent, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provisioning event not found",
        )
    _ensure_tenant_access(current_user, event.tenant_id)
    if event.status not in {"FAILED", "RETRY_SCHEDULED", "DEAD_LETTER"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Event in {event.status} status cannot be retried",
        )
    connector = db.get(IdentityProvisioningConnector, event.connector_id)
    if connector is None or connector.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Activate the connector before retrying the event",
        )
    event.status = "RECEIVED"
    event.operation = "RETRY"
    event.attempts += 1
    event.next_retry_at = None
    try:
        with db.begin_nested():
            result = replay_provisioning_event(
                db,
                event=event,
                connector=connector,
                base_url="/api/v1/scim/v2",
            )
        mark_event_applied(
            event,
            connector,
            response=result,
            applied_user_id=event.applied_user_id,
        )
        log_audit(
            db,
            action="identity_event_retried",
            entity_type="identity_provisioning_event",
            entity_id=event.id,
            actor_user=_actor(db, current_user),
            tenant_id=event.tenant_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            metadata={"attempts": event.attempts, "status": event.status},
        )
        db.commit()
    except (ScimProvisioningError, IntegrityError) as exc:
        is_scim_error = isinstance(exc, ScimProvisioningError)
        detail = (
            exc.detail
            if is_scim_error
            else "Database constraint rejected the provisioning retry"
        )
        mark_event_failed(
            event,
            connector,
            error_code=(
                (exc.scim_type or type(exc).__name__)
                if is_scim_error
                else "INTEGRITY_ERROR"
            ),
            error_message=detail,
            retryable=exc.retryable if is_scim_error else False,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Retry failed: {detail}",
        ) from exc
    return {"event": _event_dict(event), "result": result}


@router.get("/ownership-transfers")
def list_ownership_transfers(
    tenant_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=250),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.read")
    scoped_tenant = _tenant_scope(current_user, tenant_id)
    statement = select(IdentityOwnershipTransfer)
    if scoped_tenant:
        statement = statement.where(
            IdentityOwnershipTransfer.tenant_id == scoped_tenant
        )
    total = int(
        db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    items = db.scalars(
        statement
        .order_by(IdentityOwnershipTransfer.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": item.id,
                "tenant_id": item.tenant_id,
                "from_user_id": item.from_user_id,
                "to_user_id": item.to_user_id,
                "provisioning_event_id": item.provisioning_event_id,
                "reason": item.reason,
                "counts": item.transferred_counts_json,
                "sessions_revoked": item.sessions_revoked,
                "status": item.status,
                "initiated_by_id": item.initiated_by_id,
                "created_at": item.created_at,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/users/{user_id}/ownership")
def preview_user_ownership(
    user_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.read")
    user = db.get(User, user_id)
    if user is None or user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant user not found",
        )
    _ensure_tenant_access(current_user, user.tenant_id)
    return {
        "user_id": user.id,
        "email": user.email,
        **ownership_summary(
            db,
            tenant_id=user.tenant_id,
            user=user,
        ).as_dict(),
    }


@router.post("/users/{user_id}/safe-deactivate")
def safe_deactivate_user(
    user_id: str,
    payload: ManualLifecycleRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "identity.provisioning.manage")
    user = db.get(User, user_id)
    if user is None or user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant user not found",
        )
    _ensure_tenant_access(current_user, user.tenant_id)
    if user.id == current_user.id or user.is_root or user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Self, root, and superuser accounts cannot be deactivated here",
        )
    fallback = _fallback_owner(
        db,
        tenant_id=user.tenant_id,
        user_id=payload.fallback_owner_id,
    )
    try:
        ensure_tenant_admin_continuity(db, user, deactivating=True)
        transfer = transfer_user_ownership(
            db,
            tenant_id=user.tenant_id,
            from_user=user,
            to_user=fallback,
            reason=payload.reason,
            initiated_by=_actor(db, current_user),
            revoke_sessions=True,
        )
    except IdentityLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc
    user.is_active = False
    user.provisioning_state = "DEPROVISIONED"
    user.deactivated_at = datetime.now(UTC)
    user.updated_at = datetime.now(UTC)
    user.roles = []
    user.role_id = None
    log_audit(
        db,
        action="user_safe_deactivated",
        entity_type="user",
        entity_id=user.id,
        actor_user=_actor(db, current_user),
        tenant_id=user.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={
            "fallback_owner_id": fallback.id,
            "ownership_transfer_id": transfer.id,
            "counts": transfer.transferred_counts_json,
            "sessions_revoked": transfer.sessions_revoked,
        },
    )
    db.commit()
    return {
        "user_id": user.id,
        "is_active": user.is_active,
        "provisioning_state": user.provisioning_state,
        "ownership_transfer": {
            "id": transfer.id,
            "to_user_id": transfer.to_user_id,
            "counts": transfer.transferred_counts_json,
            "sessions_revoked": transfer.sessions_revoked,
        },
    }
