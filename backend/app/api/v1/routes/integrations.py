from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.external_system import ExternalSystem
from app.models.import_job import ImportJob
from app.models.integration_credential import IntegrationCredential
from app.models.integration_event_log import IntegrationEventLog
from app.models.integration_mapping import IntegrationMapping
from app.models.user import User
from app.models.webhook_endpoint import WebhookEndpoint
from app.services.audit import log_audit
from app.services.integrations import (
    check_system_health,
    create_event_log,
    export_entity_mock,
    get_provider,
    list_provider_metadata,
    process_inbound_webhook,
    retry_integration_event,
    run_import_job,
    validate_mapping,
)
from app.services.rbac import is_saas_root, require_permissions

router = APIRouter(prefix="/integrations")


SYSTEM_TYPES = {"one_c", "telegram", "email", "ldap", "zimbra", "platonus", "moodle", "custom_api", "webhook", "file_import"}
SYSTEM_STATUS = {"active", "disabled", "error", "mock", "demo", "planned"}
HEALTH_STATUS = {"unknown", "healthy", "degraded", "down", "simulated"}
DIRECTIONS = {"inbound", "outbound"}
EVENT_STATUS = {
    "queued",
    "success",
    "failed",
    "skipped",
    "retrying",
    "simulated",
    "simulated_failed",
}
JOB_STATUS = {
    "pending",
    "running",
    "completed",
    "failed",
    "completed_with_errors",
    "dry_run",
    "simulated",
    "simulated_with_errors",
}
JOB_TYPES = {"assets", "tickets", "users", "knowledge", "generic", "ldap_users_preview", "zimbra_mailboxes_preview", "platonus_users_preview", "moodle_users_preview", "smtp_notifications_preview"}


def _require_legacy_demo(feature: str) -> None:
    if not get_settings().demo_mode:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                f"Legacy mock {feature} is disabled outside demo mode. "
                "Use the production integration-platform control plane."
            ),
        )
MAPPING_TYPES = {"asset_import", "ticket_import", "user_import", "webhook_event", "export"}
CREDENTIAL_TYPES = {"api_token", "basic_auth", "webhook_secret", "oauth_mock", "ldap_bind_mock"}


class PageResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


class ExternalSystemResponse(BaseModel):
    id: str
    tenant_id: str | None
    name: str
    code: str
    system_type: str
    base_url: str | None
    status: str
    health_status: str
    is_mock: bool
    is_enabled: bool
    last_health_check_at: datetime | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error_message: str | None
    config: dict[str, Any]
    created_by_id: str | None
    created_at: datetime
    updated_at: datetime


class ExternalSystemCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    system_type: str = Field(min_length=1, max_length=50)
    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    base_url: str | None = Field(default=None, max_length=2_048)
    status: str = "mock"
    health_status: str = "unknown"
    is_mock: bool = True
    is_enabled: bool | None = None
    description: str | None = Field(default=None, max_length=2_000)
    config: dict[str, Any] | None = None


class ExternalSystemPatchRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    status: str | None = None
    health_status: str | None = None
    is_mock: bool | None = None
    is_enabled: bool | None = None
    config: dict[str, Any] | None = None


class CredentialResponse(BaseModel):
    id: str
    external_system_id: str
    credential_type: str
    secret_ref: str | None
    masked_value: str | None
    is_active: bool
    created_by_id: str | None
    rotated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CredentialCreateRequest(BaseModel):
    credential_type: str
    secret_value: str = Field(min_length=1)


class WebhookResponse(BaseModel):
    id: str
    external_system_id: str | None
    name: str
    path: str
    event_type: str
    is_active: bool
    secret_required: bool
    last_received_at: datetime | None
    success_count: int
    failure_count: int
    created_at: datetime
    updated_at: datetime


class WebhookCreateRequest(BaseModel):
    external_system_id: str | None = None
    name: str
    path: str
    event_type: str
    is_active: bool = True
    secret_required: bool = False


class WebhookPatchRequest(BaseModel):
    external_system_id: str | None = None
    name: str | None = None
    path: str | None = None
    event_type: str | None = None
    is_active: bool | None = None
    secret_required: bool | None = None


class EventResponse(BaseModel):
    id: str
    external_system_id: str | None
    direction: str
    event_type: str
    entity_type: str | None
    entity_id: str | None
    status: str
    payload: dict[str, Any]
    response_payload: dict[str, Any]
    error_message: str | None
    attempt_count: int
    next_retry_at: datetime | None
    created_at: datetime
    processed_at: datetime | None


class ImportJobResponse(BaseModel):
    id: str
    external_system_id: str | None
    job_type: str
    status: str
    source_filename: str | None
    total_rows: int
    success_rows: int
    failed_rows: int
    records_total: int
    records_success: int
    records_failed: int
    error_report: dict[str, Any]
    dry_run: bool
    created_by_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class ImportJobCreateRequest(BaseModel):
    external_system_id: str | None = None
    job_type: str = Field(min_length=1, max_length=100)
    source_filename: str | None = Field(default=None, max_length=255)
    dry_run: bool = True


class MappingResponse(BaseModel):
    id: str
    external_system_id: str | None
    mapping_type: str
    source_field: str | None
    target_field: str | None
    transform_rule: str | None
    is_required: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MappingCreateRequest(BaseModel):
    external_system_id: str
    mapping_type: str
    source_field: str
    target_field: str
    transform_rule: str | None = None
    is_required: bool = False
    is_active: bool = True


class MappingPatchRequest(BaseModel):
    mapping_type: str | None = None
    source_field: str | None = None
    target_field: str | None = None
    transform_rule: str | None = None
    is_required: bool | None = None
    is_active: bool | None = None


class ExportRequest(BaseModel):
    external_system_id: str = Field(min_length=1, max_length=100)
    entity_type: str = Field(min_length=1, max_length=100)
    entity_id: str = Field(min_length=1, max_length=100)
    dry_run: bool = True


class WebhookTestRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    create_demo_ticket: bool = False


def _parse_json(value: str | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not value:
        return fallback or {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return fallback or {}
    return parsed if isinstance(parsed, dict) else (fallback or {})


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.get(User, current_user.id)


def _tenant_scope(current_user: AuthUserResponse) -> str | None:
    return None if is_saas_root(current_user) else current_user.tenant_id


def _filter_by_tenant(statement: Select, model: Any, current_user: AuthUserResponse) -> Select:
    if is_saas_root(current_user):
        return statement
    return statement.where((model.tenant_id == current_user.tenant_id) | (model.tenant_id.is_(None)))


def _validate(value: str, allowed: set[str], field: str) -> None:
    if value not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field}")


def _mask_secret(raw_secret: str) -> str:
    if len(raw_secret) <= 4:
        return "*" * len(raw_secret)
    return f"{'*' * (len(raw_secret) - 4)}{raw_secret[-4:]}"


def _system_response(item: ExternalSystem) -> ExternalSystemResponse:
    return ExternalSystemResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        name=item.name,
        code=item.code,
        system_type=item.system_type,
        base_url=item.base_url,
        status=item.status,
        health_status=item.health_status,
        is_mock=item.is_mock,
        is_enabled=item.is_enabled,
        last_health_check_at=item.last_health_check_at,
        last_success_at=item.last_success_at,
        last_error_at=item.last_error_at,
        last_error_message=item.last_error_message,
        config=_parse_json(item.config_json),
        created_by_id=item.created_by_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _credential_response(item: IntegrationCredential) -> CredentialResponse:
    return CredentialResponse(
        id=item.id,
        external_system_id=item.external_system_id,
        credential_type=item.credential_type,
        secret_ref=item.secret_ref,
        masked_value=item.masked_value,
        is_active=item.is_active,
        created_by_id=item.created_by_id,
        rotated_at=item.rotated_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _webhook_response(item: WebhookEndpoint) -> WebhookResponse:
    return WebhookResponse(
        id=item.id,
        external_system_id=item.external_system_id,
        name=item.name,
        path=item.path,
        event_type=item.event_type,
        is_active=item.is_active,
        secret_required=item.secret_required,
        last_received_at=item.last_received_at,
        success_count=item.success_count,
        failure_count=item.failure_count,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _event_response(item: IntegrationEventLog) -> EventResponse:
    return EventResponse(
        id=item.id,
        external_system_id=item.external_system_id,
        direction=item.direction,
        event_type=item.event_type,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        status=item.status,
        payload=_parse_json(item.payload_json, _parse_json(item.request_summary)),
        response_payload=_parse_json(item.response_payload_json, _parse_json(item.response_summary)),
        error_message=item.error_message,
        attempt_count=item.attempt_count,
        next_retry_at=item.next_retry_at,
        created_at=item.created_at,
        processed_at=item.processed_at,
    )


def _job_response(item: ImportJob) -> ImportJobResponse:
    return ImportJobResponse(
        id=item.id,
        external_system_id=item.external_system_id,
        job_type=item.job_type,
        status=item.status,
        source_filename=item.source_filename,
        total_rows=item.total_rows,
        success_rows=item.success_rows,
        failed_rows=item.failed_rows,
        records_total=item.records_total,
        records_success=item.records_success,
        records_failed=item.records_failed,
        error_report=_parse_json(item.error_report_json),
        dry_run=item.dry_run,
        created_by_id=item.created_by_id,
        started_at=item.started_at,
        finished_at=item.finished_at,
        created_at=item.created_at,
    )


def _mapping_response(item: IntegrationMapping) -> MappingResponse:
    return MappingResponse(
        id=item.id,
        external_system_id=item.external_system_id,
        mapping_type=item.mapping_type,
        source_field=item.source_field,
        target_field=item.target_field,
        transform_rule=item.transform_rule,
        is_required=item.is_required,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _paginate(statement: Select, db: Session, page: int, page_size: int) -> tuple[list[Any], int]:
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    items = db.scalars(statement.offset((page - 1) * page_size).limit(page_size)).all()
    return items, total


@router.get("/providers")
def list_providers(current_user: AuthUserResponse = Depends(get_current_user)) -> list[dict[str, Any]]:
    require_permissions(current_user, "integrations.read")
    return list_provider_metadata()


@router.get("/runtime-capabilities")
def integration_runtime_capabilities(
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, bool]:
    if not is_saas_root(current_user) and not any(
        permission.startswith("integrations.")
        for permission in current_user.permissions
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing integrations permission",
        )
    return {
        "production_control_plane_enabled": True,
        "legacy_demo_enabled": get_settings().demo_mode,
    }


@router.get("/providers/{provider_code}/capabilities")
def get_provider_capabilities(provider_code: str, current_user: AuthUserResponse = Depends(get_current_user)) -> dict[str, Any]:
    require_permissions(current_user, "integrations.read")
    return get_provider(provider_code).get_capabilities()


@router.get("/systems")
def list_systems(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    system_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    health_status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    paged: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> Any:
    require_permissions(current_user, "integrations.read")
    statement = _filter_by_tenant(select(ExternalSystem).order_by(ExternalSystem.created_at.desc()), ExternalSystem, current_user)
    if system_type:
        statement = statement.where(ExternalSystem.system_type == system_type)
    if status_filter:
        statement = statement.where(ExternalSystem.status == status_filter)
    if health_status:
        statement = statement.where(ExternalSystem.health_status == health_status)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(or_(ExternalSystem.name.ilike(pattern), ExternalSystem.code.ilike(pattern)))
    if not paged:
        items = db.scalars(statement).all()
        return [_system_response(item).model_dump() for item in items]
    items, total = _paginate(statement, db, page, page_size)
    return {"items": [_system_response(item).model_dump() for item in items], "total": total, "page": page, "page_size": page_size}


@router.post("/systems", status_code=status.HTTP_201_CREATED)
def create_system(
    request: ExternalSystemCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExternalSystemResponse:
    require_permissions(current_user, "integrations.create")
    _require_legacy_demo("system configuration")
    _validate(request.system_type, SYSTEM_TYPES, "system_type")
    _validate(request.status, SYSTEM_STATUS, "status")
    _validate(request.health_status, HEALTH_STATUS, "health_status")
    now = datetime.now(UTC)
    code = request.code or f"{request.system_type}_{uuid.uuid4().hex[:8]}"
    if db.scalar(select(ExternalSystem).where(ExternalSystem.code == code)) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="External system code already exists")
    item = ExternalSystem(
        id=str(uuid.uuid4()),
        tenant_id=_tenant_scope(current_user),
        code=code,
        name=request.name,
        system_type=request.system_type,
        base_url=request.base_url,
        status=request.status,
        health_status=request.health_status,
        is_mock=request.is_mock,
        description=request.description,
        config_json=json.dumps(request.config, ensure_ascii=False) if request.config is not None else None,
        created_by_id=current_user.id,
        is_enabled=request.is_enabled if request.is_enabled is not None else request.status in {"active", "demo"},
        last_health_status=request.health_status,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    log_audit(
        db,
        action="integration_system_created",
        entity_type="external_system",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        actor_email=current_user.email,
        tenant_id=item.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"system_type": item.system_type, "status": item.status},
    )
    db.commit()
    db.refresh(item)
    return _system_response(item)


@router.get("/systems/{system_id}", response_model=ExternalSystemResponse)
def get_system(system_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> ExternalSystemResponse:
    require_permissions(current_user, "integrations.read")
    item = db.scalar(_filter_by_tenant(select(ExternalSystem).where(ExternalSystem.id == system_id), ExternalSystem, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External system not found")
    return _system_response(item)


@router.patch("/systems/{system_id}", response_model=ExternalSystemResponse)
def patch_system(
    system_id: str,
    request: ExternalSystemPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExternalSystemResponse:
    require_permissions(current_user, "integrations.update")
    _require_legacy_demo("system configuration")
    item = db.scalar(_filter_by_tenant(select(ExternalSystem).where(ExternalSystem.id == system_id), ExternalSystem, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External system not found")
    updates = request.model_dump(exclude_unset=True)
    if "status" in updates:
        _validate(str(updates["status"]), SYSTEM_STATUS, "status")
    if "health_status" in updates:
        _validate(str(updates["health_status"]), HEALTH_STATUS, "health_status")
    for field_name, value in updates.items():
        if field_name == "config":
            item.config_json = json.dumps(value, ensure_ascii=False)
            continue
        setattr(item, field_name, value)
    item.updated_at = datetime.now(UTC)
    log_audit(
        db,
        action="integration_system_updated",
        entity_type="external_system",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        actor_email=current_user.email,
        tenant_id=item.tenant_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"updated_fields": list(updates.keys())},
    )
    db.commit()
    db.refresh(item)
    return _system_response(item)


@router.post("/systems/{system_id}/enable", response_model=ExternalSystemResponse)
def enable_system(
    system_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExternalSystemResponse:
    require_permissions(current_user, "integrations.update")
    _require_legacy_demo("system activation")
    item = db.scalar(_filter_by_tenant(select(ExternalSystem).where(ExternalSystem.id == system_id), ExternalSystem, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External system not found")
    item.is_enabled = True
    item.status = "active"
    item.updated_at = datetime.now(UTC)
    log_audit(db, action="integration_system_enabled", entity_type="external_system", entity_id=item.id, actor_user=_actor(db, current_user), actor_email=current_user.email, tenant_id=item.tenant_id, ip_address=http_request.client.host if http_request.client else None, user_agent=http_request.headers.get("user-agent"), metadata={"status": item.status})
    db.commit()
    db.refresh(item)
    return _system_response(item)


@router.post("/systems/{system_id}/disable", response_model=ExternalSystemResponse)
def disable_system(
    system_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExternalSystemResponse:
    require_permissions(current_user, "integrations.update")
    item = db.scalar(_filter_by_tenant(select(ExternalSystem).where(ExternalSystem.id == system_id), ExternalSystem, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External system not found")
    item.is_enabled = False
    item.status = "disabled"
    item.updated_at = datetime.now(UTC)
    log_audit(db, action="integration_system_disabled", entity_type="external_system", entity_id=item.id, actor_user=_actor(db, current_user), actor_email=current_user.email, tenant_id=item.tenant_id, ip_address=http_request.client.host if http_request.client else None, user_agent=http_request.headers.get("user-agent"), metadata={"status": item.status})
    db.commit()
    db.refresh(item)
    return _system_response(item)


@router.post("/systems/{system_id}/health-check")
def health_check_system(
    system_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.health_check")
    _require_legacy_demo("health check")
    user = _actor(db, current_user)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    result = check_system_health(db, system_id, user)
    log_audit(
        db,
        action="integration_health_check_executed",
        entity_type="external_system",
        entity_id=system_id,
        actor_user=user,
        actor_email=user.email,
        tenant_id=user.tenant_id,
        metadata={"health_status": result.get("health_status")},
    )
    db.commit()
    status_value = result.get("result", {}).get("status")
    return {"status": status_value or "ok", **result}


@router.get("/systems/{system_id}/credentials")
def list_credentials(system_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[CredentialResponse]:
    require_permissions(current_user, "integrations.credentials.read")
    system = db.scalar(_filter_by_tenant(select(ExternalSystem).where(ExternalSystem.id == system_id), ExternalSystem, current_user))
    if system is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External system not found")
    items = db.scalars(select(IntegrationCredential).where(IntegrationCredential.external_system_id == system.id).order_by(IntegrationCredential.created_at.desc())).all()
    return [_credential_response(item) for item in items]


@router.post("/systems/{system_id}/credentials", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
def create_credential(
    system_id: str,
    request: CredentialCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CredentialResponse:
    require_permissions(current_user, "integrations.credentials.manage")
    _require_legacy_demo("credential storage")
    _validate(request.credential_type, CREDENTIAL_TYPES, "credential_type")
    system = db.scalar(_filter_by_tenant(select(ExternalSystem).where(ExternalSystem.id == system_id), ExternalSystem, current_user))
    if system is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External system not found")
    now = datetime.now(UTC)
    item = IntegrationCredential(
        id=str(uuid.uuid4()),
        tenant_id=system.tenant_id,
        external_system_id=system.id,
        credential_type=request.credential_type,
        auth_type=request.credential_type,
        secret_ref=f"mock://secrets/{system.code}/{uuid.uuid4().hex[:8]}",
        masked_value=_mask_secret(request.secret_value),
        is_active=True,
        created_by_id=current_user.id,
        rotated_at=now,
        last_rotated_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    log_audit(db, action="integration_credential_created", entity_type="integration_credential", entity_id=item.id, actor_user=_actor(db, current_user), actor_email=current_user.email, tenant_id=system.tenant_id, ip_address=http_request.client.host if http_request.client else None, user_agent=http_request.headers.get("user-agent"), metadata={"credential_type": item.credential_type})
    db.commit()
    db.refresh(item)
    return _credential_response(item)


@router.post("/credentials/{credential_id}/rotate", response_model=CredentialResponse)
def rotate_credential(
    credential_id: str,
    request: CredentialCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CredentialResponse:
    require_permissions(current_user, "integrations.credentials.manage")
    _require_legacy_demo("credential storage")
    item = db.get(IntegrationCredential, credential_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    system = db.scalar(_filter_by_tenant(select(ExternalSystem).where(ExternalSystem.id == item.external_system_id), ExternalSystem, current_user))
    if system is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    now = datetime.now(UTC)
    item.credential_type = request.credential_type
    item.auth_type = request.credential_type
    item.secret_ref = f"mock://secrets/{system.code}/{uuid.uuid4().hex[:8]}"
    item.masked_value = _mask_secret(request.secret_value)
    item.rotated_at = now
    item.last_rotated_at = now
    item.updated_at = now
    log_audit(db, action="integration_credential_rotated", entity_type="integration_credential", entity_id=item.id, actor_user=_actor(db, current_user), actor_email=current_user.email, tenant_id=system.tenant_id, ip_address=http_request.client.host if http_request.client else None, user_agent=http_request.headers.get("user-agent"), metadata={"credential_type": item.credential_type})
    db.commit()
    db.refresh(item)
    return _credential_response(item)


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(credential_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    require_permissions(current_user, "integrations.credentials.manage")
    item = db.get(IntegrationCredential, credential_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    system = db.scalar(_filter_by_tenant(select(ExternalSystem).where(ExternalSystem.id == item.external_system_id), ExternalSystem, current_user))
    if system is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/webhooks")
def list_webhooks(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    event_type: str | None = Query(default=None),
    paged: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> Any:
    require_permissions(current_user, "integrations.webhooks.read")
    statement = _filter_by_tenant(select(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc()), WebhookEndpoint, current_user)
    if event_type:
        statement = statement.where(WebhookEndpoint.event_type == event_type)
    if not paged:
        items = db.scalars(statement).all()
        return [_webhook_response(item).model_dump() for item in items]
    items, total = _paginate(statement, db, page, page_size)
    return {"items": [_webhook_response(item).model_dump() for item in items], "total": total, "page": page, "page_size": page_size}


@router.post("/webhooks", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
def create_webhook(
    request: WebhookCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WebhookResponse:
    require_permissions(current_user, "integrations.webhooks.manage")
    _require_legacy_demo("webhook endpoint")
    now = datetime.now(UTC)
    item = WebhookEndpoint(
        id=str(uuid.uuid4()),
        tenant_id=_tenant_scope(current_user),
        external_system_id=request.external_system_id,
        name=request.name,
        path=request.path,
        event_type=request.event_type,
        target_system="webhook",
        is_active=request.is_active,
        secret_required=request.secret_required,
        success_count=0,
        failure_count=0,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    log_audit(db, action="integration_webhook_created", entity_type="webhook_endpoint", entity_id=item.id, actor_user=_actor(db, current_user), actor_email=current_user.email, tenant_id=item.tenant_id, ip_address=http_request.client.host if http_request.client else None, user_agent=http_request.headers.get("user-agent"), metadata={"path": item.path, "event_type": item.event_type})
    db.commit()
    db.refresh(item)
    return _webhook_response(item)


@router.patch("/webhooks/{webhook_id}", response_model=WebhookResponse)
def patch_webhook(
    webhook_id: str,
    request: WebhookPatchRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WebhookResponse:
    require_permissions(current_user, "integrations.webhooks.manage")
    _require_legacy_demo("webhook endpoint")
    item = db.scalar(_filter_by_tenant(select(WebhookEndpoint).where(WebhookEndpoint.id == webhook_id), WebhookEndpoint, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")
    updates = request.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        setattr(item, field_name, value)
    item.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(item)
    return _webhook_response(item)


@router.post("/webhooks/{webhook_id}/test")
def test_webhook(
    webhook_id: str,
    request: WebhookTestRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.webhooks.manage")
    _require_legacy_demo("webhook endpoint")
    endpoint = db.scalar(_filter_by_tenant(select(WebhookEndpoint).where(WebhookEndpoint.id == webhook_id), WebhookEndpoint, current_user))
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")
    user = _actor(db, current_user)
    event = process_inbound_webhook(
        db,
        endpoint,
        request.payload,
        user,
        simulated=True,
    )
    db.commit()
    response_payload: dict[str, Any] = {"status": "simulated", "event_id": event.id}
    if request.create_demo_ticket:
        response_payload["demo_ticket_id"] = str(uuid.uuid4())
    return response_payload


@router.post(
    "/inbound/{path:path}",
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
def inbound_webhook(
    path: str,
    request: WebhookTestRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.webhooks.manage")
    _require_legacy_demo("inbound webhook")
    normalized_path = f"/{path.lstrip('/')}"
    endpoint = db.scalar(
        _filter_by_tenant(
            select(WebhookEndpoint).where(
                WebhookEndpoint.path == normalized_path,
                WebhookEndpoint.is_active.is_(True),
            ),
            WebhookEndpoint,
            current_user,
        )
    )
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")
    event = process_inbound_webhook(
        db,
        endpoint,
        request.payload,
        _actor(db, current_user),
        simulated=True,
    )
    db.commit()
    return {"status": "simulated", "event_id": event.id}


@router.get("/events")
def list_events(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    direction: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    event_type: str | None = Query(default=None),
    external_system_id: str | None = Query(default=None),
    paged: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> Any:
    require_permissions(current_user, "integrations.events.read")
    statement = _filter_by_tenant(select(IntegrationEventLog).order_by(IntegrationEventLog.created_at.desc()), IntegrationEventLog, current_user)
    if direction:
        _validate(direction, DIRECTIONS, "direction")
        statement = statement.where(IntegrationEventLog.direction == direction)
    if status_filter:
        _validate(status_filter, EVENT_STATUS, "status")
        statement = statement.where(IntegrationEventLog.status == status_filter)
    if event_type:
        statement = statement.where(IntegrationEventLog.event_type == event_type)
    if external_system_id:
        statement = statement.where(IntegrationEventLog.external_system_id == external_system_id)
    if not paged:
        items = db.scalars(statement).all()
        return [_event_response(item).model_dump() for item in items]
    items, total = _paginate(statement, db, page, page_size)
    return {"items": [_event_response(item).model_dump() for item in items], "total": total, "page": page, "page_size": page_size}


@router.get("/events/{event_id}", response_model=EventResponse)
def get_event(event_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> EventResponse:
    require_permissions(current_user, "integrations.events.read")
    item = db.scalar(_filter_by_tenant(select(IntegrationEventLog).where(IntegrationEventLog.id == event_id), IntegrationEventLog, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration event not found")
    return _event_response(item)


@router.post("/events/{event_id}/retry", response_model=EventResponse)
def retry_event_endpoint(
    event_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EventResponse:
    require_permissions(current_user, "integrations.events.retry")
    _require_legacy_demo("event retry")
    user = _actor(db, current_user)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    try:
        event = retry_integration_event(db, event_id, user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(event)
    return _event_response(event)


@router.get("/import-jobs")
def list_import_jobs(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    job_type: str | None = Query(default=None),
    paged: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> Any:
    require_permissions(current_user, "integrations.import_jobs.read")
    statement = _filter_by_tenant(select(ImportJob).order_by(ImportJob.created_at.desc()), ImportJob, current_user)
    if status_filter:
        _validate(status_filter, JOB_STATUS, "status")
        statement = statement.where(ImportJob.status == status_filter)
    if job_type:
        statement = statement.where(ImportJob.job_type == job_type)
    if not paged:
        items = db.scalars(statement).all()
        return [_job_response(item).model_dump() for item in items]
    items, total = _paginate(statement, db, page, page_size)
    return {"items": [_job_response(item).model_dump() for item in items], "total": total, "page": page, "page_size": page_size}


@router.post("/import-jobs", response_model=ImportJobResponse, status_code=status.HTTP_201_CREATED)
def create_import_job(
    request: ImportJobCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImportJobResponse:
    require_permissions(current_user, "integrations.import_jobs.run")
    _require_legacy_demo("import preview")
    if request.job_type not in JOB_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid job_type")
    now = datetime.now(UTC)
    item = ImportJob(
        id=str(uuid.uuid4()),
        tenant_id=_tenant_scope(current_user),
        external_system_id=request.external_system_id,
        job_type=request.job_type,
        status="pending",
        source_filename=request.source_filename,
        total_rows=0,
        success_rows=0,
        failed_rows=0,
        records_total=0,
        records_success=0,
        records_failed=0,
        error_report_json=json.dumps({}, ensure_ascii=False),
        dry_run=request.dry_run,
        created_by_id=current_user.id,
        started_at=None,
        finished_at=None,
        error_message=None,
        created_at=now,
    )
    db.add(item)
    log_audit(db, action="integration_import_job_created", entity_type="import_job", entity_id=item.id, actor_user=_actor(db, current_user), actor_email=current_user.email, tenant_id=item.tenant_id, ip_address=http_request.client.host if http_request.client else None, user_agent=http_request.headers.get("user-agent"), metadata={"job_type": item.job_type, "dry_run": item.dry_run})
    db.commit()
    db.refresh(item)
    return _job_response(item)


@router.get("/import-jobs/{job_id}", response_model=ImportJobResponse)
def get_import_job(job_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> ImportJobResponse:
    require_permissions(current_user, "integrations.import_jobs.read")
    item = db.scalar(_filter_by_tenant(select(ImportJob).where(ImportJob.id == job_id), ImportJob, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found")
    return _job_response(item)


@router.post("/import-jobs/{job_id}/dry-run", response_model=ImportJobResponse)
def dry_run_import_job_endpoint(
    job_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImportJobResponse:
    require_permissions(current_user, "integrations.import_jobs.run")
    _require_legacy_demo("import preview")
    user = _actor(db, current_user)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    try:
        item = run_import_job(db, job_id, dry_run=True, current_user=user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(item)
    return _job_response(item)


@router.post("/import-jobs/{job_id}/run", response_model=ImportJobResponse)
def run_import_job_endpoint(
    job_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImportJobResponse:
    require_permissions(current_user, "integrations.import_jobs.run")
    _require_legacy_demo("import preview")
    user = _actor(db, current_user)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    try:
        item = run_import_job(db, job_id, dry_run=False, current_user=user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(item)
    return _job_response(item)


@router.get("/mappings")
def list_mappings(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    paged: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> Any:
    require_permissions(current_user, "integrations.mappings.read")
    statement = _filter_by_tenant(select(IntegrationMapping).order_by(IntegrationMapping.created_at.desc()), IntegrationMapping, current_user)
    if not paged:
        items = db.scalars(statement).all()
        return [_mapping_response(item).model_dump() for item in items]
    items, total = _paginate(statement, db, page, page_size)
    return {"items": [_mapping_response(item).model_dump() for item in items], "total": total, "page": page, "page_size": page_size}


@router.post("/mappings", response_model=MappingResponse, status_code=status.HTTP_201_CREATED)
def create_mapping(
    request: MappingCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MappingResponse:
    require_permissions(current_user, "integrations.mappings.manage")
    _require_legacy_demo("mapping configuration")
    _validate(request.mapping_type, MAPPING_TYPES, "mapping_type")
    now = datetime.now(UTC)
    item = IntegrationMapping(
        id=str(uuid.uuid4()),
        tenant_id=_tenant_scope(current_user),
        external_system_id=request.external_system_id,
        mapping_type=request.mapping_type,
        source_field=request.source_field,
        target_field=request.target_field,
        transform_rule=request.transform_rule,
        is_required=request.is_required,
        source_entity=request.source_field,
        target_entity=request.target_field,
        mapping_json=json.dumps({request.source_field: request.target_field}, ensure_ascii=False),
        is_active=request.is_active,
        created_at=now,
        updated_at=now,
    )
    valid, error = validate_mapping(item, {request.source_field: "sample"})
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error or "Invalid mapping")
    db.add(item)
    log_audit(db, action="integration_mapping_created", entity_type="integration_mapping", entity_id=item.id, actor_user=_actor(db, current_user), actor_email=current_user.email, tenant_id=item.tenant_id, ip_address=http_request.client.host if http_request.client else None, user_agent=http_request.headers.get("user-agent"), metadata={"mapping_type": item.mapping_type})
    db.commit()
    db.refresh(item)
    return _mapping_response(item)


@router.patch("/mappings/{mapping_id}", response_model=MappingResponse)
def patch_mapping(
    mapping_id: str,
    request: MappingPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MappingResponse:
    require_permissions(current_user, "integrations.mappings.manage")
    _require_legacy_demo("mapping configuration")
    item = db.scalar(_filter_by_tenant(select(IntegrationMapping).where(IntegrationMapping.id == mapping_id), IntegrationMapping, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration mapping not found")
    updates = request.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        setattr(item, field_name, value)
    if item.source_field and item.target_field:
        item.mapping_json = json.dumps({item.source_field: item.target_field}, ensure_ascii=False)
        item.source_entity = item.source_field
        item.target_entity = item.target_field
    item.updated_at = datetime.now(UTC)
    log_audit(db, action="integration_mapping_updated", entity_type="integration_mapping", entity_id=item.id, actor_user=_actor(db, current_user), actor_email=current_user.email, tenant_id=item.tenant_id, ip_address=http_request.client.host if http_request.client else None, user_agent=http_request.headers.get("user-agent"), metadata={"updated_fields": list(updates.keys())})
    db.commit()
    db.refresh(item)
    return _mapping_response(item)


@router.delete("/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(mapping_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    require_permissions(current_user, "integrations.mappings.manage")
    item = db.scalar(_filter_by_tenant(select(IntegrationMapping).where(IntegrationMapping.id == mapping_id), IntegrationMapping, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration mapping not found")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/export")
def export_entity(
    request: ExportRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.export")
    _require_legacy_demo("export preview")
    user = _actor(db, current_user)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    try:
        result = export_entity_mock(
            db,
            request.external_system_id,
            request.entity_type,
            request.entity_id,
            user,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    db.commit()
    return {
        "dry_run": True,
        "requested_dry_run": request.dry_run,
        **result,
    }


# Backward compatibility wrappers for previous integration foundation frontend.
@router.post("/systems/{system_id}/test-connection")
def test_connection_legacy(system_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_permissions(current_user, "integrations.health_check")
    _require_legacy_demo("connection test")
    system = db.scalar(_filter_by_tenant(select(ExternalSystem).where(ExternalSystem.id == system_id), ExternalSystem, current_user))
    if system is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External system not found")
    result = get_provider(system.system_type).test_connection()
    create_event_log(
        db,
        direction="outbound",
        event_type="integration_test_connection",
        payload={"system_id": system.id, "system_type": system.system_type},
        external_system_id=system.id,
        status="simulated" if result.get("status") == "simulated" else "failed",
        response_payload=result,
        processed_at=datetime.now(UTC),
    )
    db.commit()
    return result


@router.post("/webhooks/{webhook_id}/simulate")
def simulate_webhook_legacy(
    webhook_id: str,
    request: WebhookTestRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return test_webhook(webhook_id, request, current_user, db)


@router.post("/mock/ldap/pull-users")
def mock_ldap_legacy(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_permissions(current_user, "integrations.import_jobs.run")
    _require_legacy_demo("LDAP preview")
    payload = {"records_total": 5, "users": [{"email": "rector@university.local"}]}
    create_event_log(db, direction="inbound", event_type="mock_ldap_pull_users", payload=payload, status="simulated")
    db.commit()
    return payload


@router.post("/mock/zimbra/pull-mailboxes")
def mock_zimbra_legacy(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_permissions(current_user, "integrations.import_jobs.run")
    _require_legacy_demo("Zimbra preview")
    payload = {"records_total": 4, "mailboxes": [{"email": "support@university.kz"}]}
    create_event_log(db, direction="inbound", event_type="mock_zimbra_pull_mailboxes", payload=payload, status="simulated")
    db.commit()
    return payload


@router.post("/mock/platonus/pull-users")
def mock_platonus_legacy(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_permissions(current_user, "integrations.import_jobs.run")
    _require_legacy_demo("Platonus preview")
    payload = {"records_total": 4, "users": [{"email": "dean@university.local"}]}
    create_event_log(db, direction="inbound", event_type="mock_platonus_pull_users", payload=payload, status="simulated")
    db.commit()
    return payload


@router.post("/mock/moodle/pull-users")
def mock_moodle_legacy(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_permissions(current_user, "integrations.import_jobs.run")
    _require_legacy_demo("Moodle preview")
    payload = {"records_total": 3, "users": [{"email": "student.one@university.local"}]}
    create_event_log(db, direction="inbound", event_type="mock_moodle_pull_users", payload=payload, status="simulated")
    db.commit()
    return payload


@router.post("/mock/webhook/receive")
def mock_webhook_legacy(request: WebhookTestRequest, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    require_permissions(current_user, "integrations.webhooks.manage")
    _require_legacy_demo("webhook simulation")
    create_event_log(db, direction="inbound", event_type="mock_webhook_receive", payload=request.payload, status="simulated")
    db.commit()
    return {"status": "simulated", "payload": request.payload}
