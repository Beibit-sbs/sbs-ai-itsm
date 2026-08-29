from __future__ import annotations

from datetime import UTC, datetime
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.core.context import get_correlation_id
from app.db.session import get_db
from app.models.asset import Asset
from app.models.integration_platform import (
    IntegrationApiRequestLog,
    IntegrationApiToken,
    IntegrationServiceAccount,
    OutboundWebhookDelivery,
    OutboundWebhookSubscription,
)
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.user import User
from app.services.audit import log_audit
from app.services.cmdb_schema import canonical_json
from app.services.integration_platform import (
    SERVICE_ACCOUNT_SCOPES,
    ServiceAccountPrincipal,
    ServiceTokenError,
    authenticate_service_token,
    create_sdk_event,
    encrypt_subscription_secret,
    encrypt_subscription_target,
    issue_service_token,
    new_signing_secret,
    queue_outbound_webhook_event,
    replay_outbound_webhook_delivery,
    validate_event_types,
    validate_ip_cidrs,
    validate_outbound_target_url,
    validate_service_account_scopes,
)
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/integration-platform")
service_bearer = HTTPBearer(
    scheme_name="ServiceAccountBearer",
    auto_error=False,
)


class ServiceAccountCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)
    allowed_scopes: list[str] = Field(min_length=1, max_length=20)
    allowed_ip_cidrs: list[str] = Field(default_factory=list, max_length=100)
    rate_limit_per_minute: int = Field(default=120, ge=1, le=10_000)
    max_token_ttl_days: int = Field(default=90, ge=1, le=365)


class ServiceAccountUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)
    allowed_scopes: list[str] | None = Field(default=None, min_length=1, max_length=20)
    allowed_ip_cidrs: list[str] | None = Field(default=None, max_length=100)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10_000)
    max_token_ttl_days: int | None = Field(default=None, ge=1, le=365)
    status: Literal["ACTIVE", "SUSPENDED", "REVOKED"] | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class TokenIssue(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    scopes: list[str] = Field(min_length=1, max_length=20)
    ttl_days: int = Field(default=30, ge=1, le=365)


class TokenRotate(BaseModel):
    expected_version: int = Field(ge=1)
    ttl_days: int | None = Field(default=None, ge=1, le=365)
    reason: str = Field(min_length=3, max_length=2_000)


class TokenRevoke(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


class OutboundWebhookCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)
    target_url: str = Field(min_length=8, max_length=4_000)
    event_types: list[str] = Field(min_length=1, max_length=100)
    timeout_seconds: int = Field(default=15, ge=1, le=60)
    max_attempts: int = Field(default=6, ge=1, le=20)


class OutboundWebhookUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)
    target_url: str | None = Field(default=None, min_length=8, max_length=4_000)
    event_types: list[str] | None = Field(default=None, min_length=1, max_length=100)
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    status: Literal["DRAFT", "ACTIVE", "PAUSED", "REVOKED"] | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2_000)


class SdkEventCreate(BaseModel):
    event_type: str = Field(min_length=2, max_length=120)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: str | None = Field(default=None, max_length=120)
    data: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=120)


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _name(value: str, *, label: str) -> str:
    normalized = value.strip()
    if len(normalized) < 2:
        raise HTTPException(
            status_code=422,
            detail=f"{label} must contain at least 2 characters",
        )
    return normalized


def _flush_unique(db: Session, *, detail: str) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc


def _tenant_id(
    db: Session,
    current_user: AuthUserResponse,
    requested: str | None,
) -> str:
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        if requested and requested != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return current_user.tenant_id
    if not requested:
        raise HTTPException(
            status_code=422,
            detail="tenant_id is required for SaaS Root integration administration",
        )
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _scope(current_user: AuthUserResponse, tenant_id: str, message: str) -> None:
    if not is_saas_root(current_user) and current_user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=message)


def _account(
    db: Session,
    account_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> IntegrationServiceAccount:
    statement = select(IntegrationServiceAccount).where(
        IntegrationServiceAccount.id == account_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Service account not found")
    _scope(current_user, item.tenant_id, "Service account not found")
    return item


def _token(
    db: Session,
    token_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> IntegrationApiToken:
    statement = select(IntegrationApiToken).where(
        IntegrationApiToken.id == token_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="API token not found")
    _scope(current_user, item.tenant_id, "API token not found")
    return item


def _subscription(
    db: Session,
    subscription_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> OutboundWebhookSubscription:
    statement = select(OutboundWebhookSubscription).where(
        OutboundWebhookSubscription.id == subscription_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
    _scope(current_user, item.tenant_id, "Webhook subscription not found")
    return item


def _delivery(
    db: Session,
    delivery_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> OutboundWebhookDelivery:
    statement = select(OutboundWebhookDelivery).where(
        OutboundWebhookDelivery.id == delivery_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Webhook delivery not found")
    _scope(current_user, item.tenant_id, "Webhook delivery not found")
    return item


def _audit(
    db: Session,
    request: Request,
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
        actor_user=db.get(User, current_user.id),
        actor_email=current_user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _account_response(
    db: Session,
    item: IntegrationServiceAccount,
) -> dict[str, object]:
    active_tokens = int(
        db.scalar(
            select(func.count())
            .select_from(IntegrationApiToken)
            .where(
                IntegrationApiToken.service_account_id == item.id,
                IntegrationApiToken.status == "ACTIVE",
                IntegrationApiToken.expires_at > datetime.now(UTC),
            )
        )
        or 0
    )
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "client_id": item.client_id,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "allowed_scopes": _json_list(item.allowed_scopes_json),
        "allowed_ip_cidrs": _json_list(item.allowed_ip_cidrs_json),
        "rate_limit_per_minute": item.rate_limit_per_minute,
        "max_token_ttl_days": item.max_token_ttl_days,
        "version": item.version,
        "active_tokens": active_tokens,
        "total_requests": item.total_requests,
        "failed_auth_count": item.failed_auth_count,
        "last_used_at": item.last_used_at,
        "last_used_ip": item.last_used_ip,
        "revoked_at": item.revoked_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _token_response(
    item: IntegrationApiToken,
    *,
    revealed_token: str | None = None,
) -> dict[str, object]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "service_account_id": item.service_account_id,
        "name": item.name,
        "token_hint": item.token_hint,
        "scopes": _json_list(item.scopes_json),
        "status": (
            "EXPIRED"
            if item.status == "ACTIVE"
            and (
                item.expires_at.replace(tzinfo=UTC)
                if item.expires_at.tzinfo is None
                else item.expires_at
            )
            <= datetime.now(UTC)
            else item.status
        ),
        "version": item.version,
        "expires_at": item.expires_at,
        "last_used_at": item.last_used_at,
        "last_used_ip": item.last_used_ip,
        "revoked_at": item.revoked_at,
        "replaced_by_token_id": item.replaced_by_token_id,
        "created_at": item.created_at,
        "access_token": revealed_token,
        "token_type": "Bearer" if revealed_token else None,
    }


def _subscription_response(
    item: OutboundWebhookSubscription,
    *,
    signing_secret: str | None = None,
) -> dict[str, object]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "event_types": _json_list(item.event_types_json),
        "target_hint": item.target_hint,
        "target_host": item.target_host,
        "target_version": item.target_version,
        "signing_secret_hint": item.signing_secret_hint,
        "signing_secret_version": item.signing_secret_version,
        "last_tested_target_version": item.last_tested_target_version,
        "last_tested_secret_version": item.last_tested_secret_version,
        "timeout_seconds": item.timeout_seconds,
        "max_attempts": item.max_attempts,
        "version": item.version,
        "success_count": item.success_count,
        "failure_count": item.failure_count,
        "dead_letter_count": item.dead_letter_count,
        "last_success_at": item.last_success_at,
        "last_failure_at": item.last_failure_at,
        "last_error": item.last_error,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "signing_secret": signing_secret,
    }


def _delivery_response(item: OutboundWebhookDelivery) -> dict[str, object]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "subscription_id": item.subscription_id,
        "replay_of_id": item.replay_of_id,
        "event_id": item.event_id,
        "event_type": item.event_type,
        "entity_type": item.entity_type,
        "entity_id": item.entity_id,
        "payload_sha256": item.payload_sha256,
        "payload_bytes": item.payload_bytes,
        "status": item.status,
        "is_test": item.is_test,
        "attempts": item.attempts,
        "max_attempts": item.max_attempts,
        "next_attempt_at": item.next_attempt_at,
        "response_status": item.response_status,
        "response_time_ms": item.response_time_ms,
        "target_version_used": item.target_version_used,
        "signing_secret_version_used": item.signing_secret_version_used,
        "provider_request_id": item.provider_request_id,
        "last_error": item.last_error,
        "completed_at": item.completed_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/scopes")
def list_service_account_scopes(
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[dict[str, str]]:
    require_permissions(current_user, "integration.platform.accounts.read")
    return [
        {"scope": scope, "description": description}
        for scope, description in SERVICE_ACCOUNT_SCOPES.items()
    ]


@router.get("/service-accounts")
def list_service_accounts(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "integration.platform.accounts.read")
    statement = select(IntegrationServiceAccount)
    if not is_saas_root(current_user):
        statement = statement.where(
            IntegrationServiceAccount.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(IntegrationServiceAccount.tenant_id == tenant_id)
    items = db.scalars(statement.order_by(IntegrationServiceAccount.name)).all()
    return [_account_response(db, item) for item in items]


@router.post("/service-accounts", status_code=status.HTTP_201_CREATED)
def create_service_account(
    payload: ServiceAccountCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.accounts.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    try:
        scopes = validate_service_account_scopes(payload.allowed_scopes)
        cidrs = validate_ip_cidrs(payload.allowed_ip_cidrs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = datetime.now(UTC)
    item = IntegrationServiceAccount(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        client_id=f"svc_{uuid.uuid4().hex}",
        name=_name(payload.name, label="Service-account name"),
        description=payload.description.strip() if payload.description else None,
        status="ACTIVE",
        allowed_scopes_json=canonical_json(scopes),
        allowed_ip_cidrs_json=canonical_json(cidrs),
        rate_limit_per_minute=payload.rate_limit_per_minute,
        max_token_ttl_days=payload.max_token_ttl_days,
        version=1,
        total_requests=0,
        failed_auth_count=0,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    _flush_unique(
        db,
        detail="A service account with this name already exists in the tenant",
    )
    _audit(
        db,
        request,
        current_user,
        action="integration_service_account_created",
        entity_type="integration_service_account",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={
            "client_id": item.client_id,
            "scopes": scopes,
            "rate_limit_per_minute": item.rate_limit_per_minute,
        },
    )
    db.commit()
    db.refresh(item)
    return _account_response(db, item)


@router.patch("/service-accounts/{account_id}")
def update_service_account(
    account_id: str,
    payload: ServiceAccountUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.accounts.manage")
    item = _account(db, account_id, current_user, lock=True)
    if item.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Service account changed; current version is {item.version}",
        )
    if item.status == "REVOKED" and payload.status != "REVOKED":
        raise HTTPException(status_code=409, detail="Revoked account cannot reactivate")
    before = {
        "name": item.name,
        "status": item.status,
        "scopes": _json_list(item.allowed_scopes_json),
        "ip_cidrs": _json_list(item.allowed_ip_cidrs_json),
        "rate_limit_per_minute": item.rate_limit_per_minute,
    }
    try:
        if payload.allowed_scopes is not None:
            item.allowed_scopes_json = canonical_json(
                validate_service_account_scopes(payload.allowed_scopes)
            )
        if payload.allowed_ip_cidrs is not None:
            item.allowed_ip_cidrs_json = canonical_json(
                validate_ip_cidrs(payload.allowed_ip_cidrs)
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    updates = payload.model_dump(
        exclude={
            "expected_version",
            "reason",
            "allowed_scopes",
            "allowed_ip_cidrs",
        },
        exclude_unset=True,
    )
    for key, value in updates.items():
        if isinstance(value, str):
            value = value.strip()
        if key == "name" and value is not None:
            value = _name(value, label="Service-account name")
        setattr(item, key, value)
    now = datetime.now(UTC)
    if item.status == "REVOKED":
        item.revoked_at = now
        item.revoked_by_id = current_user.id
        tokens = db.scalars(
            select(IntegrationApiToken).where(
                IntegrationApiToken.service_account_id == item.id,
                IntegrationApiToken.status == "ACTIVE",
            )
        ).all()
        for token in tokens:
            token.status = "REVOKED"
            token.revoked_at = now
            token.revoked_by_id = current_user.id
            token.version += 1
            token.updated_at = now
    item.version += 1
    item.updated_by_id = current_user.id
    item.updated_at = now
    _audit(
        db,
        request,
        current_user,
        action="integration_service_account_updated",
        entity_type="integration_service_account",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "before": before,
            "after": {
                "name": item.name,
                "status": item.status,
                "scopes": _json_list(item.allowed_scopes_json),
                "ip_cidrs": _json_list(item.allowed_ip_cidrs_json),
                "rate_limit_per_minute": item.rate_limit_per_minute,
            },
            "reason": payload.reason.strip(),
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A service account with this name already exists in the tenant",
        ) from exc
    db.refresh(item)
    return _account_response(db, item)


@router.get("/service-accounts/{account_id}/tokens")
def list_service_tokens(
    account_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "integration.platform.tokens.read")
    account = _account(db, account_id, current_user)
    items = db.scalars(
        select(IntegrationApiToken)
        .where(IntegrationApiToken.service_account_id == account.id)
        .order_by(IntegrationApiToken.created_at.desc())
    ).all()
    return [_token_response(item) for item in items]


@router.post(
    "/service-accounts/{account_id}/tokens",
    status_code=status.HTTP_201_CREATED,
)
def issue_api_token(
    account_id: str,
    payload: TokenIssue,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.tokens.issue")
    account = _account(db, account_id, current_user, lock=True)
    try:
        item, raw_token = issue_service_token(
            db,
            account,
            name=payload.name,
            scopes=payload.scopes,
            ttl_days=payload.ttl_days,
            actor_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="API token could not be issued; retry the request",
        ) from exc
    _audit(
        db,
        request,
        current_user,
        action="integration_api_token_issued",
        entity_type="integration_api_token",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "service_account_id": account.id,
            "token_hint": item.token_hint,
            "scopes": _json_list(item.scopes_json),
            "expires_at": item.expires_at.isoformat(),
        },
    )
    db.commit()
    db.refresh(item)
    return _token_response(item, revealed_token=raw_token)


@router.post("/tokens/{token_id}/rotate")
def rotate_api_token(
    token_id: str,
    payload: TokenRotate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.tokens.issue")
    item = _token(db, token_id, current_user)
    account = _account(
        db,
        item.service_account_id,
        current_user,
        lock=True,
    )
    item = _token(db, token_id, current_user, lock=True)
    if item.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"API token changed; current version is {item.version}",
        )
    expires_at = (
        item.expires_at.replace(tzinfo=UTC)
        if item.expires_at.tzinfo is None
        else item.expires_at
    )
    if item.status != "ACTIVE" or expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="Only active tokens can rotate")
    if account.tenant_id != item.tenant_id:
        raise HTTPException(status_code=409, detail="Service account is unavailable")
    remaining = max(
        1,
        int((expires_at - datetime.now(UTC)).days) + 1,
    )
    ttl_days = payload.ttl_days or min(remaining, account.max_token_ttl_days)
    try:
        replacement, raw_token = issue_service_token(
            db,
            account,
            name=item.name,
            scopes=_json_list(item.scopes_json),
            ttl_days=ttl_days,
            actor_id=current_user.id,
            exclude_token_id=item.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Replacement token could not be issued; retry the request",
        ) from exc
    now = datetime.now(UTC)
    item.status = "REVOKED"
    item.revoked_at = now
    item.revoked_by_id = current_user.id
    item.replaced_by_token_id = replacement.id
    item.version += 1
    item.updated_at = now
    _audit(
        db,
        request,
        current_user,
        action="integration_api_token_rotated",
        entity_type="integration_api_token",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "replacement_token_id": replacement.id,
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    db.refresh(replacement)
    return _token_response(replacement, revealed_token=raw_token)


@router.post("/tokens/{token_id}/revoke")
def revoke_api_token(
    token_id: str,
    payload: TokenRevoke,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.tokens.revoke")
    item = _token(db, token_id, current_user, lock=True)
    if item.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"API token changed; current version is {item.version}",
        )
    if item.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Token is already inactive")
    now = datetime.now(UTC)
    item.status = "REVOKED"
    item.revoked_at = now
    item.revoked_by_id = current_user.id
    item.version += 1
    item.updated_at = now
    _audit(
        db,
        request,
        current_user,
        action="integration_api_token_revoked",
        entity_type="integration_api_token",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason": payload.reason.strip()},
    )
    db.commit()
    db.refresh(item)
    return _token_response(item)


@router.get("/request-logs")
def list_service_request_logs(
    tenant_id: str | None = None,
    account_id: str | None = None,
    outcome: Literal["ALLOWED", "DENIED"] | None = None,
    limit: int = Query(default=200, ge=1, le=1_000),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "integration.platform.observability.read")
    statement = select(IntegrationApiRequestLog)
    if not is_saas_root(current_user):
        statement = statement.where(
            IntegrationApiRequestLog.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(IntegrationApiRequestLog.tenant_id == tenant_id)
    if account_id:
        statement = statement.where(
            IntegrationApiRequestLog.service_account_id == account_id
        )
    if outcome:
        statement = statement.where(IntegrationApiRequestLog.outcome == outcome)
    items = db.scalars(
        statement.order_by(IntegrationApiRequestLog.created_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id": item.id,
            "tenant_id": item.tenant_id,
            "service_account_id": item.service_account_id,
            "token_id": item.token_id,
            "request_id": item.request_id,
            "method": item.method,
            "path": item.path,
            "source_ip": item.source_ip,
            "required_scope": item.required_scope,
            "outcome": item.outcome,
            "reason": item.reason,
            "created_at": item.created_at,
        }
        for item in items
    ]


@router.get("/webhooks")
def list_outbound_webhooks(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "integration.platform.webhooks.read")
    statement = select(OutboundWebhookSubscription)
    if not is_saas_root(current_user):
        statement = statement.where(
            OutboundWebhookSubscription.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(
            OutboundWebhookSubscription.tenant_id == tenant_id
        )
    items = db.scalars(
        statement.order_by(OutboundWebhookSubscription.name)
    ).all()
    return [_subscription_response(item) for item in items]


@router.post("/webhooks", status_code=status.HTTP_201_CREATED)
def create_outbound_webhook(
    payload: OutboundWebhookCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.webhooks.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    try:
        target_url, target_host, target_hint = validate_outbound_target_url(
            payload.target_url
        )
        event_types = validate_event_types(payload.event_types)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = datetime.now(UTC)
    item = OutboundWebhookSubscription(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=_name(payload.name, label="Webhook name"),
        description=payload.description.strip() if payload.description else None,
        status="DRAFT",
        event_types_json=canonical_json(event_types),
        target_hint=target_hint,
        target_host=target_host,
        target_version=1,
        signing_secret_version=1,
        timeout_seconds=payload.timeout_seconds,
        max_attempts=payload.max_attempts,
        version=1,
        success_count=0,
        failure_count=0,
        dead_letter_count=0,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    secret = new_signing_secret()
    item.target_url_encrypted = encrypt_subscription_target(item, target_url)
    item.signing_secret_encrypted = encrypt_subscription_secret(item, secret)
    item.signing_secret_hint = f"whsec_…{secret[-6:]}"
    db.add(item)
    _flush_unique(
        db,
        detail="A webhook subscription with this name already exists in the tenant",
    )
    _audit(
        db,
        request,
        current_user,
        action="outbound_webhook_created",
        entity_type="outbound_webhook_subscription",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={
            "target_host": target_host,
            "event_types": event_types,
            "status": item.status,
        },
    )
    db.commit()
    db.refresh(item)
    return _subscription_response(item, signing_secret=secret)


@router.patch("/webhooks/{subscription_id}")
def update_outbound_webhook(
    subscription_id: str,
    payload: OutboundWebhookUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.webhooks.manage")
    item = _subscription(db, subscription_id, current_user, lock=True)
    if item.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Webhook subscription changed; current version is {item.version}",
        )
    if item.status == "REVOKED" and payload.status != "REVOKED":
        raise HTTPException(
            status_code=409,
            detail="Revoked webhook subscription cannot reactivate",
        )
    before = {
        "name": item.name,
        "status": item.status,
        "target_hint": item.target_hint,
        "event_types": _json_list(item.event_types_json),
    }
    if payload.target_url is not None:
        try:
            target_url, target_host, target_hint = validate_outbound_target_url(
                payload.target_url
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        item.target_url_encrypted = encrypt_subscription_target(item, target_url)
        item.target_host = target_host
        item.target_hint = target_hint
        item.target_version += 1
        item.last_tested_target_version = None
        if item.status == "ACTIVE":
            item.status = "PAUSED"
    if payload.event_types is not None:
        try:
            item.event_types_json = canonical_json(
                validate_event_types(payload.event_types)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    updates = payload.model_dump(
        exclude={"expected_version", "reason", "target_url", "event_types"},
        exclude_unset=True,
    )
    for key, value in updates.items():
        if isinstance(value, str):
            value = value.strip()
        if key == "name" and value is not None:
            value = _name(value, label="Webhook name")
        setattr(item, key, value)
    if item.status == "ACTIVE" and (
        item.last_tested_target_version != item.target_version
        or item.last_tested_secret_version != item.signing_secret_version
    ):
        raise HTTPException(
            status_code=409,
            detail="Test the current target and signing secret before activation",
        )
    now = datetime.now(UTC)
    if item.status == "REVOKED":
        item.target_url_encrypted = None
        item.signing_secret_encrypted = None
        item.signing_secret_hint = None
    item.version += 1
    item.updated_by_id = current_user.id
    item.updated_at = now
    _audit(
        db,
        request,
        current_user,
        action="outbound_webhook_updated",
        entity_type="outbound_webhook_subscription",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "before": before,
            "after": {
                "name": item.name,
                "status": item.status,
                "target_hint": item.target_hint,
                "event_types": _json_list(item.event_types_json),
            },
            "reason": payload.reason.strip(),
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A webhook subscription with this name already exists in the tenant",
        ) from exc
    db.refresh(item)
    return _subscription_response(item)


@router.post("/webhooks/{subscription_id}/rotate-secret")
def rotate_outbound_webhook_secret(
    subscription_id: str,
    payload: ReasonRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.webhooks.manage")
    item = _subscription(db, subscription_id, current_user, lock=True)
    if item.status == "REVOKED":
        raise HTTPException(status_code=409, detail="Webhook subscription is revoked")
    secret = new_signing_secret()
    item.signing_secret_encrypted = encrypt_subscription_secret(item, secret)
    item.signing_secret_hint = f"whsec_…{secret[-6:]}"
    item.signing_secret_version += 1
    item.last_tested_secret_version = None
    if item.status == "ACTIVE":
        item.status = "PAUSED"
    item.version += 1
    item.updated_by_id = current_user.id
    item.updated_at = datetime.now(UTC)
    _audit(
        db,
        request,
        current_user,
        action="outbound_webhook_secret_rotated",
        entity_type="outbound_webhook_subscription",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "secret_version": item.signing_secret_version,
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    db.refresh(item)
    return _subscription_response(item, signing_secret=secret)


@router.post(
    "/webhooks/{subscription_id}/test",
    status_code=status.HTTP_202_ACCEPTED,
)
def test_outbound_webhook(
    subscription_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.webhooks.manage")
    item = _subscription(db, subscription_id, current_user, lock=True)
    if item.status == "REVOKED":
        raise HTTPException(status_code=409, detail="Webhook subscription is revoked")
    test_id = str(uuid.uuid4())
    deliveries = queue_outbound_webhook_event(
        db,
        tenant_id=item.tenant_id,
        subscription_id=item.id,
        event_id=test_id,
        event_type="webhook.test",
        data={
            "message": "SBS AI ITSM outbound webhook connection test",
            "subscription_id": item.id,
        },
        idempotency_key=f"test:{test_id}",
        is_test=True,
    )
    if not deliveries:
        raise HTTPException(status_code=409, detail="Test delivery could not queue")
    delivery = deliveries[0]
    _audit(
        db,
        request,
        current_user,
        action="outbound_webhook_test_queued",
        entity_type="outbound_webhook_delivery",
        entity_id=delivery.id,
        tenant_id=item.tenant_id,
        metadata={"subscription_id": item.id},
    )
    db.commit()
    db.refresh(delivery)
    return _delivery_response(delivery)


@router.get("/deliveries")
def list_outbound_webhook_deliveries(
    tenant_id: str | None = None,
    subscription_id: str | None = None,
    delivery_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1_000),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "integration.platform.webhooks.read")
    statement = select(OutboundWebhookDelivery)
    if not is_saas_root(current_user):
        statement = statement.where(
            OutboundWebhookDelivery.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(OutboundWebhookDelivery.tenant_id == tenant_id)
    if subscription_id:
        statement = statement.where(
            OutboundWebhookDelivery.subscription_id == subscription_id
        )
    if delivery_status:
        statement = statement.where(
            OutboundWebhookDelivery.status == delivery_status.upper()
        )
    items = db.scalars(
        statement.order_by(OutboundWebhookDelivery.created_at.desc()).limit(limit)
    ).all()
    return [_delivery_response(item) for item in items]


@router.post(
    "/deliveries/{delivery_id}/replay",
    status_code=status.HTTP_202_ACCEPTED,
)
def replay_outbound_webhook(
    delivery_id: str,
    payload: ReasonRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.webhooks.replay")
    original = _delivery(db, delivery_id, current_user, lock=True)
    try:
        replay = replay_outbound_webhook_delivery(db, original)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="outbound_webhook_delivery_replayed",
        entity_type="outbound_webhook_delivery",
        entity_id=replay.id,
        tenant_id=replay.tenant_id,
        metadata={
            "original_delivery_id": original.id,
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    db.refresh(replay)
    return _delivery_response(replay)


@router.get("/dashboard")
def integration_platform_dashboard(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.observability.read")
    account_filters = []
    subscription_filters = []
    delivery_filters = []
    request_filters = []
    if not is_saas_root(current_user):
        account_filters.append(
            IntegrationServiceAccount.tenant_id == current_user.tenant_id
        )
        subscription_filters.append(
            OutboundWebhookSubscription.tenant_id == current_user.tenant_id
        )
        delivery_filters.append(
            OutboundWebhookDelivery.tenant_id == current_user.tenant_id
        )
        request_filters.append(
            IntegrationApiRequestLog.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        account_filters.append(IntegrationServiceAccount.tenant_id == tenant_id)
        subscription_filters.append(
            OutboundWebhookSubscription.tenant_id == tenant_id
        )
        delivery_filters.append(OutboundWebhookDelivery.tenant_id == tenant_id)
        request_filters.append(IntegrationApiRequestLog.tenant_id == tenant_id)
    account_counts = {
        row[0]: int(row[1])
        for row in db.execute(
            select(IntegrationServiceAccount.status, func.count())
            .where(*account_filters)
            .group_by(IntegrationServiceAccount.status)
        ).all()
    }
    subscription_counts = {
        row[0]: int(row[1])
        for row in db.execute(
            select(OutboundWebhookSubscription.status, func.count())
            .where(*subscription_filters)
            .group_by(OutboundWebhookSubscription.status)
        ).all()
    }
    delivery_counts = {
        row[0]: int(row[1])
        for row in db.execute(
            select(OutboundWebhookDelivery.status, func.count())
            .where(*delivery_filters)
            .group_by(OutboundWebhookDelivery.status)
        ).all()
    }
    allowed_requests = int(
        db.scalar(
            select(func.count())
            .select_from(IntegrationApiRequestLog)
            .where(*request_filters, IntegrationApiRequestLog.outcome == "ALLOWED")
        )
        or 0
    )
    denied_requests = int(
        db.scalar(
            select(func.count())
            .select_from(IntegrationApiRequestLog)
            .where(*request_filters, IntegrationApiRequestLog.outcome == "DENIED")
        )
        or 0
    )
    avg_latency = db.scalar(
        select(func.avg(OutboundWebhookDelivery.response_time_ms)).where(
            *delivery_filters,
            OutboundWebhookDelivery.status == "SUCCEEDED",
        )
    )
    return {
        "service_accounts": account_counts,
        "webhook_subscriptions": subscription_counts,
        "deliveries": delivery_counts,
        "api_requests": {
            "allowed": allowed_requests,
            "denied": denied_requests,
        },
        "average_delivery_latency_ms": round(float(avg_latency or 0), 2),
        "outbound_allowed_hosts_configured": bool(
            get_settings().integration_outbound_webhook_allowed_hosts
        ),
    }


@router.get("/connector-contract")
def connector_sdk_contract(
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, object]:
    require_permissions(current_user, "integration.platform.accounts.read")
    return {
        "contract_version": "2026-07-29",
        "event_format": "CloudEvents 1.0 structured JSON",
        "service_token": {
            "authorization": "Authorization: Bearer sbs_svc_<prefix>_<secret>",
            "plaintext_returned_once": True,
            "scopes": SERVICE_ACCOUNT_SCOPES,
        },
        "sdk_endpoints": {
            "whoami": "GET /api/v1/integration-platform/sdk/v1/whoami",
            "publish_event": "POST /api/v1/integration-platform/sdk/v1/events",
            "read_ticket": "GET /api/v1/integration-platform/sdk/v1/tickets/{id}",
            "read_asset": "GET /api/v1/integration-platform/sdk/v1/assets/{id}",
        },
        "outbound_signature": {
            "algorithm": "HMAC-SHA256",
            "base": "<X-SBS-Timestamp>.<raw-body>",
            "header": "X-SBS-Signature: v1=<lowercase-hex>",
            "delivery_header": "X-SBS-Delivery-ID",
            "replay_header": "Idempotency-Key",
        },
        "retryable_http_statuses": [408, 425, 429, "5xx"],
        "redirects": "rejected",
    }


def _sdk_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
    *,
    required_scope: str | None,
) -> ServiceAccountPrincipal:
    raw_token = (
        credentials.credentials
        if credentials and credentials.scheme.lower() == "bearer"
        else ""
    )
    try:
        return authenticate_service_token(
            db,
            raw_token,
            required_scope=required_scope,
            request_id=get_correlation_id() or str(uuid.uuid4()),
            method=request.method,
            path=request.url.path,
            source_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ServiceTokenError as exc:
        db.commit()
        headers = {"WWW-Authenticate": "Bearer"}
        if exc.status_code == 429:
            headers["Retry-After"] = "60"
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
            headers=headers,
        ) from exc


@router.get("/sdk/v1/whoami")
def sdk_whoami(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    principal = _sdk_principal(
        request,
        credentials,
        db,
        required_scope=None,
    )
    db.commit()
    return {
        "tenant_id": principal.tenant_id,
        "service_account_id": principal.service_account_id,
        "client_id": principal.client_id,
        "name": principal.name,
        "scopes": principal.scopes,
    }


@router.post("/sdk/v1/events", status_code=status.HTTP_202_ACCEPTED)
def sdk_publish_event(
    payload: SdkEventCreate,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    principal = _sdk_principal(
        request,
        credentials,
        db,
        required_scope="integration.events.write",
    )
    if len(canonical_json(payload.data).encode("utf-8")) > (
        get_settings().integration_outbound_webhook_max_payload_bytes
    ):
        db.commit()
        raise HTTPException(status_code=413, detail="Event payload is too large")
    try:
        with db.begin_nested():
            event = create_sdk_event(
                db,
                principal,
                event_type=payload.event_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                data=payload.data,
                idempotency_key=payload.idempotency_key,
            )
    except ValueError as exc:
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(event)
    return {
        "accepted": True,
        "event_id": event.id,
        "correlation_id": event.correlation_id,
        "status": event.status,
    }


@router.get("/sdk/v1/tickets/{ticket_id}")
def sdk_read_ticket(
    ticket_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    principal = _sdk_principal(
        request,
        credentials,
        db,
        required_scope="tickets.read",
    )
    item = db.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.tenant_id == principal.tenant_id,
        )
    )
    if item is None:
        db.commit()
        raise HTTPException(status_code=404, detail="Ticket not found")
    response = {
        "id": item.id,
        "ticket_number": item.ticket_number,
        "title": item.title,
        "category": item.category,
        "priority": item.priority,
        "status": item.status,
        "assignee_name": item.assignee_name,
        "asset_id": item.asset_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    db.commit()
    return response


@router.get("/sdk/v1/assets/{asset_id}")
def sdk_read_asset(
    asset_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    principal = _sdk_principal(
        request,
        credentials,
        db,
        required_scope="assets.read",
    )
    item = db.scalar(
        select(Asset).where(
            Asset.id == asset_id,
            Asset.tenant_id == principal.tenant_id,
        )
    )
    if item is None:
        db.commit()
        raise HTTPException(status_code=404, detail="Asset not found")
    response = {
        "id": item.id,
        "asset_tag": item.asset_tag,
        "name": item.name,
        "ci_class_code": item.ci_class_code,
        "lifecycle_status": item.lifecycle_status,
        "criticality": item.criticality,
        "environment": item.environment,
        "support_group": item.support_group,
        "serial_number": item.serial_number,
        "location": item.location,
        "updated_at": item.updated_at,
    }
    db.commit()
    return response
