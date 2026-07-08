from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.security import hash_password
from app.db.session import get_db
from app.models.external_system import ExternalSystem
from app.models.import_job import ImportJob
from app.models.integration_credential import IntegrationCredential
from app.models.integration_event_log import IntegrationEventLog
from app.models.integration_mapping import IntegrationMapping
from app.models.ticket import Ticket
from app.models.user import User
from app.models.webhook_endpoint import WebhookEndpoint
from app.services.audit import log_audit
from app.services.integrations.providers import create_integration_event, get_provider, list_provider_metadata
from app.services.rbac import is_saas_root, require_permissions
from app.services.service_desk import next_ticket_number

router = APIRouter(prefix="/integrations")


class ExternalSystemResponse(BaseModel):
    id: str
    tenant_id: str | None
    code: str
    name: str
    system_type: str
    base_url: str | None
    status: str
    is_enabled: bool
    last_health_status: str | None
    last_health_checked_at: datetime | None
    description: str | None
    created_at: datetime
    updated_at: datetime
    capabilities: list[str] = Field(default_factory=list)


class ExternalSystemCreateRequest(BaseModel):
    tenant_id: str | None = None
    code: str
    name: str
    system_type: str
    base_url: str | None = None
    status: str = "planned"
    is_enabled: bool = False
    description: str | None = None


class ExternalSystemPatchRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    status: str | None = None
    is_enabled: bool | None = None
    description: str | None = None


class ProviderCapabilitiesResponse(BaseModel):
    code: str
    name: str
    status: str
    capabilities: list[str]


class IntegrationEventResponse(BaseModel):
    id: str
    tenant_id: str | None
    external_system_id: str | None
    direction: str
    event_type: str
    status: str
    request_summary: dict[str, Any]
    response_summary: dict[str, Any]
    error_message: str | None
    correlation_id: str | None
    created_at: datetime


class ImportJobResponse(BaseModel):
    id: str
    tenant_id: str | None
    external_system_id: str | None
    job_type: str
    status: str
    records_total: int
    records_success: int
    records_failed: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime


class CreateImportJobRequest(BaseModel):
    external_system_id: str
    job_type: str


class WebhookEndpointResponse(BaseModel):
    id: str
    tenant_id: str | None
    name: str
    path: str
    target_system: str
    is_active: bool
    secret_ref: str | None
    created_at: datetime
    updated_at: datetime


class WebhookEndpointCreateRequest(BaseModel):
    name: str
    path: str
    target_system: str
    is_active: bool = True
    secret_ref: str | None = None


class WebhookEndpointPatchRequest(BaseModel):
    name: str | None = None
    path: str | None = None
    target_system: str | None = None
    is_active: bool | None = None
    secret_ref: str | None = None


class SimulateWebhookRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    create_demo_ticket: bool = False


class IntegrationMappingResponse(BaseModel):
    id: str
    tenant_id: str | None
    external_system_id: str | None
    source_entity: str
    target_entity: str
    mapping_json: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class IntegrationMappingCreateRequest(BaseModel):
    external_system_id: str | None = None
    source_entity: str
    target_entity: str
    mapping_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class IntegrationMappingPatchRequest(BaseModel):
    source_entity: str | None = None
    target_entity: str | None = None
    mapping_json: dict[str, Any] | None = None
    is_active: bool | None = None


class MockActionRequest(BaseModel):
    external_system_id: str | None = None
    create_demo_ticket: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.get(User, current_user.id)


def _tenant_scope(current_user: AuthUserResponse) -> str | None:
    return None if is_saas_root(current_user) else current_user.tenant_id


def _filter_by_tenant(statement: Select, model: Any, current_user: AuthUserResponse):
    if is_saas_root(current_user):
        return statement
    return statement.where(model.tenant_id == current_user.tenant_id)


def _parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _system_response(item: ExternalSystem) -> ExternalSystemResponse:
    provider = get_provider(item.system_type)
    return ExternalSystemResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        code=item.code,
        name=item.name,
        system_type=item.system_type,
        base_url=item.base_url,
        status=item.status,
        is_enabled=item.is_enabled,
        last_health_status=item.last_health_status,
        last_health_checked_at=item.last_health_checked_at,
        description=item.description,
        created_at=item.created_at,
        updated_at=item.updated_at,
        capabilities=provider.descriptor.capabilities,
    )


def _event_response(item: IntegrationEventLog) -> IntegrationEventResponse:
    return IntegrationEventResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        external_system_id=item.external_system_id,
        direction=item.direction,
        event_type=item.event_type,
        status=item.status,
        request_summary=_parse_json(item.request_summary),
        response_summary=_parse_json(item.response_summary),
        error_message=item.error_message,
        correlation_id=item.correlation_id,
        created_at=item.created_at,
    )


def _import_job_response(item: ImportJob) -> ImportJobResponse:
    return ImportJobResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        external_system_id=item.external_system_id,
        job_type=item.job_type,
        status=item.status,
        records_total=item.records_total,
        records_success=item.records_success,
        records_failed=item.records_failed,
        started_at=item.started_at,
        finished_at=item.finished_at,
        error_message=item.error_message,
        created_at=item.created_at,
    )


def _webhook_response(item: WebhookEndpoint) -> WebhookEndpointResponse:
    return WebhookEndpointResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        name=item.name,
        path=item.path,
        target_system=item.target_system,
        is_active=item.is_active,
        secret_ref=item.secret_ref,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _mapping_response(item: IntegrationMapping) -> IntegrationMappingResponse:
    return IntegrationMappingResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        external_system_id=item.external_system_id,
        source_entity=item.source_entity,
        target_entity=item.target_entity,
        mapping_json=_parse_json(item.mapping_json),
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _load_system(db: Session, system_id: str, current_user: AuthUserResponse) -> ExternalSystem:
    statement = _filter_by_tenant(select(ExternalSystem).where(ExternalSystem.id == system_id), ExternalSystem, current_user)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External system not found")
    return item


def _log_integration_audit(
    db: Session,
    request: Request,
    current_user: AuthUserResponse,
    action: str,
    entity_type: str,
    entity_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    log_audit(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user=_actor(db, current_user),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _create_demo_ticket(db: Session, tenant_id: str | None, title: str, description: str, requester_email: str, requester_name: str, category: str) -> Ticket:
    ticket = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ticket_number=next_ticket_number(db),
        title=title,
        description=description,
        requester_email=requester_email,
        requester_name=requester_name,
        department="Integrations",
        location="Integration Hub",
        category=category,
        priority="MEDIUM",
        status="NEW",
        assignee_name="Integration Desk",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(ticket)
    db.flush()
    return ticket


@router.get("/systems", response_model=list[ExternalSystemResponse])
def list_systems(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    system_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[ExternalSystemResponse]:
    require_permissions(current_user, "integrations.read")
    statement = _filter_by_tenant(select(ExternalSystem).order_by(ExternalSystem.created_at.asc()), ExternalSystem, current_user)
    if system_type:
        statement = statement.where(ExternalSystem.system_type == system_type)
    if status_filter:
        statement = statement.where(ExternalSystem.status == status_filter)
    return [_system_response(item) for item in db.scalars(statement).all()]


@router.get("/systems/{system_id}", response_model=ExternalSystemResponse)
def get_system(system_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> ExternalSystemResponse:
    require_permissions(current_user, "integrations.read")
    return _system_response(_load_system(db, system_id, current_user))


@router.post("/systems", response_model=ExternalSystemResponse, status_code=status.HTTP_201_CREATED)
def create_system(
    request: ExternalSystemCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExternalSystemResponse:
    require_permissions(current_user, "integrations.manage")
    if db.scalar(select(ExternalSystem).where(ExternalSystem.code == request.code)) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="External system code already exists")
    now = datetime.now(UTC)
    item = ExternalSystem(
        id=str(uuid.uuid4()),
        tenant_id=request.tenant_id if is_saas_root(current_user) else current_user.tenant_id,
        code=request.code,
        name=request.name,
        system_type=request.system_type,
        base_url=request.base_url,
        status=request.status,
        is_enabled=request.is_enabled,
        description=request.description,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    _log_integration_audit(db, http_request, current_user, "integration_system_created", "external_system", item.id, {"code": item.code, "type": item.system_type})
    db.commit()
    db.refresh(item)
    return _system_response(item)


@router.patch("/systems/{system_id}", response_model=ExternalSystemResponse)
def patch_system(
    system_id: str,
    request: ExternalSystemPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExternalSystemResponse:
    require_permissions(current_user, "integrations.manage")
    item = _load_system(db, system_id, current_user)
    updates = request.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        setattr(item, field_name, value)
    item.updated_at = datetime.now(UTC)
    _log_integration_audit(db, http_request, current_user, "integration_system_updated", "external_system", item.id, {"updated_fields": list(updates.keys())})
    db.commit()
    db.refresh(item)
    return _system_response(item)


@router.post("/systems/{system_id}/health-check")
def health_check_system(
    system_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.health_check")
    item = _load_system(db, system_id, current_user)
    provider = get_provider(item.system_type)
    result = provider.health_check()
    item.last_health_status = str(result.get("status", "unknown"))
    item.last_health_checked_at = datetime.now(UTC)
    create_integration_event(
        db,
        tenant_id=item.tenant_id,
        external_system_id=item.id,
        direction="outbound",
        event_type="health_check",
        status=item.last_health_status,
        request_summary={"system_code": item.code},
        response_summary=result,
    )
    _log_integration_audit(db, http_request, current_user, "integration_health_check_executed", "external_system", item.id, {"result": item.last_health_status})
    db.commit()
    return {"system_id": item.id, **result}


@router.post("/systems/{system_id}/test-connection")
def test_connection_system(
    system_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.test_connection")
    item = _load_system(db, system_id, current_user)
    provider = get_provider(item.system_type)
    result = provider.test_connection()
    create_integration_event(
        db,
        tenant_id=item.tenant_id,
        external_system_id=item.id,
        direction="outbound",
        event_type="test_connection",
        status=str(result.get("status", "unknown")),
        request_summary={"system_code": item.code},
        response_summary=result,
    )
    _log_integration_audit(db, http_request, current_user, "integration_test_connection_executed", "external_system", item.id, {"result": result.get("status")})
    db.commit()
    return {"system_id": item.id, **result}


@router.get("/providers", response_model=list[ProviderCapabilitiesResponse])
def list_providers(current_user: AuthUserResponse = Depends(get_current_user)) -> list[ProviderCapabilitiesResponse]:
    require_permissions(current_user, "integrations.read")
    return [ProviderCapabilitiesResponse(**item) for item in list_provider_metadata()]


@router.get("/providers/{provider_code}/capabilities", response_model=ProviderCapabilitiesResponse)
def get_provider_capabilities(provider_code: str, current_user: AuthUserResponse = Depends(get_current_user)) -> ProviderCapabilitiesResponse:
    require_permissions(current_user, "integrations.read")
    return ProviderCapabilitiesResponse(**get_provider(provider_code).get_capabilities())


@router.get("/events", response_model=list[IntegrationEventResponse])
def list_events(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[IntegrationEventResponse]:
    require_permissions(current_user, "integrations.events.read")
    statement = _filter_by_tenant(select(IntegrationEventLog).order_by(IntegrationEventLog.created_at.desc()), IntegrationEventLog, current_user)
    return [_event_response(item) for item in db.scalars(statement).all()]


@router.get("/events/{event_id}", response_model=IntegrationEventResponse)
def get_event(event_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> IntegrationEventResponse:
    require_permissions(current_user, "integrations.events.read")
    statement = _filter_by_tenant(select(IntegrationEventLog).where(IntegrationEventLog.id == event_id), IntegrationEventLog, current_user)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration event not found")
    return _event_response(item)


@router.get("/import-jobs", response_model=list[ImportJobResponse])
def list_import_jobs(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ImportJobResponse]:
    require_permissions(current_user, "integrations.read")
    statement = _filter_by_tenant(select(ImportJob).order_by(ImportJob.created_at.desc()), ImportJob, current_user)
    return [_import_job_response(item) for item in db.scalars(statement).all()]


@router.post("/import-jobs", response_model=ImportJobResponse, status_code=status.HTTP_201_CREATED)
def create_import_job(
    request: CreateImportJobRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImportJobResponse:
    require_permissions(current_user, "integrations.import")
    system = _load_system(db, request.external_system_id, current_user)
    provider = get_provider(system.system_type)
    started_at = datetime.now(UTC)
    preview_payload = provider.pull_users() if "users" in request.job_type else provider.pull_mailboxes()
    records_total = int(preview_payload.get("records_total", 0))
    item = ImportJob(
        id=str(uuid.uuid4()),
        tenant_id=system.tenant_id,
        external_system_id=system.id,
        job_type=request.job_type,
        status="completed",
        records_total=records_total,
        records_success=records_total,
        records_failed=0,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        error_message=None,
        created_at=started_at,
    )
    db.add(item)
    create_integration_event(
        db,
        tenant_id=system.tenant_id,
        external_system_id=system.id,
        direction="inbound",
        event_type=request.job_type,
        status="completed",
        request_summary={"system_code": system.code},
        response_summary=preview_payload,
    )
    _log_integration_audit(db, http_request, current_user, "integration_import_job_created", "import_job", item.id, {"job_type": item.job_type})
    db.commit()
    db.refresh(item)
    return _import_job_response(item)


@router.get("/import-jobs/{job_id}", response_model=ImportJobResponse)
def get_import_job(job_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> ImportJobResponse:
    require_permissions(current_user, "integrations.read")
    statement = _filter_by_tenant(select(ImportJob).where(ImportJob.id == job_id), ImportJob, current_user)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found")
    return _import_job_response(item)


@router.get("/webhooks", response_model=list[WebhookEndpointResponse])
def list_webhooks(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[WebhookEndpointResponse]:
    require_permissions(current_user, "integrations.webhooks.read")
    statement = _filter_by_tenant(select(WebhookEndpoint).order_by(WebhookEndpoint.created_at.asc()), WebhookEndpoint, current_user)
    return [_webhook_response(item) for item in db.scalars(statement).all()]


@router.post("/webhooks", response_model=WebhookEndpointResponse, status_code=status.HTTP_201_CREATED)
def create_webhook(
    request: WebhookEndpointCreateRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WebhookEndpointResponse:
    require_permissions(current_user, "integrations.webhooks.manage")
    now = datetime.now(UTC)
    item = WebhookEndpoint(
        id=str(uuid.uuid4()),
        tenant_id=_tenant_scope(current_user),
        name=request.name,
        path=request.path,
        target_system=request.target_system,
        is_active=request.is_active,
        secret_ref=request.secret_ref,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _webhook_response(item)


@router.patch("/webhooks/{webhook_id}", response_model=WebhookEndpointResponse)
def patch_webhook(
    webhook_id: str,
    request: WebhookEndpointPatchRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WebhookEndpointResponse:
    require_permissions(current_user, "integrations.webhooks.manage")
    statement = _filter_by_tenant(select(WebhookEndpoint).where(WebhookEndpoint.id == webhook_id), WebhookEndpoint, current_user)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")
    updates = request.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        setattr(item, field_name, value)
    item.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(item)
    return _webhook_response(item)


@router.post("/webhooks/{webhook_id}/simulate")
def simulate_webhook(
    webhook_id: str,
    request: SimulateWebhookRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.webhooks.manage")
    statement = _filter_by_tenant(select(WebhookEndpoint).where(WebhookEndpoint.id == webhook_id), WebhookEndpoint, current_user)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")
    provider = get_provider("webhook")
    result = provider.receive_event(request.payload)
    demo_ticket_id = None
    if request.create_demo_ticket:
        ticket = _create_demo_ticket(
            db,
            item.tenant_id,
            title=f"Webhook event from {item.name}",
            description=f"Mock webhook received on {item.path}",
            requester_email="webhook@sbs.local",
            requester_name="Webhook Gateway",
            category="INTEGRATION_WEBHOOK",
        )
        demo_ticket_id = ticket.id
        result["demo_ticket_id"] = demo_ticket_id
    create_integration_event(
        db,
        tenant_id=item.tenant_id,
        external_system_id=None,
        direction="inbound",
        event_type="webhook_simulation",
        status="accepted",
        request_summary=request.payload,
        response_summary=result,
    )
    _log_integration_audit(db, http_request, current_user, "integration_webhook_simulated", "webhook_endpoint", item.id, {"demo_ticket_id": demo_ticket_id})
    db.commit()
    return result


@router.get("/mappings", response_model=list[IntegrationMappingResponse])
def list_mappings(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[IntegrationMappingResponse]:
    require_permissions(current_user, "integrations.mappings.read")
    statement = _filter_by_tenant(select(IntegrationMapping).order_by(IntegrationMapping.created_at.asc()), IntegrationMapping, current_user)
    return [_mapping_response(item) for item in db.scalars(statement).all()]


@router.post("/mappings", response_model=IntegrationMappingResponse, status_code=status.HTTP_201_CREATED)
def create_mapping(
    request: IntegrationMappingCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IntegrationMappingResponse:
    require_permissions(current_user, "integrations.mappings.manage")
    now = datetime.now(UTC)
    item = IntegrationMapping(
        id=str(uuid.uuid4()),
        tenant_id=_tenant_scope(current_user),
        external_system_id=request.external_system_id,
        source_entity=request.source_entity,
        target_entity=request.target_entity,
        mapping_json=json.dumps(request.mapping_json, ensure_ascii=False),
        is_active=request.is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    _log_integration_audit(db, http_request, current_user, "integration_mapping_created", "integration_mapping", item.id, {"source": item.source_entity, "target": item.target_entity})
    db.commit()
    db.refresh(item)
    return _mapping_response(item)


@router.patch("/mappings/{mapping_id}", response_model=IntegrationMappingResponse)
def patch_mapping(
    mapping_id: str,
    request: IntegrationMappingPatchRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IntegrationMappingResponse:
    require_permissions(current_user, "integrations.mappings.manage")
    statement = _filter_by_tenant(select(IntegrationMapping).where(IntegrationMapping.id == mapping_id), IntegrationMapping, current_user)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration mapping not found")
    updates = request.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        if field_name == "mapping_json" and value is not None:
            item.mapping_json = json.dumps(value, ensure_ascii=False)
        else:
            setattr(item, field_name, value)
    item.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(item)
    return _mapping_response(item)


def _resolve_external_system(db: Session, system_id: str | None, system_type: str, tenant_id: str | None) -> ExternalSystem | None:
    if system_id:
        return db.get(ExternalSystem, system_id)
    statement = select(ExternalSystem).where(ExternalSystem.system_type == system_type)
    if tenant_id is not None:
        statement = statement.where(ExternalSystem.tenant_id == tenant_id)
    return db.scalar(statement)


@router.post("/mock/ldap/pull-users")
def mock_ldap_pull_users(
    request: MockActionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.import")
    provider = get_provider("ldap")
    payload = provider.pull_users()
    system = _resolve_external_system(db, request.external_system_id, "ldap", _tenant_scope(current_user))
    job = ImportJob(
        id=str(uuid.uuid4()),
        tenant_id=_tenant_scope(current_user),
        external_system_id=system.id if system else None,
        job_type="ldap_users_preview",
        status="completed",
        records_total=payload["records_total"],
        records_success=payload["records_total"],
        records_failed=0,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        error_message=None,
        created_at=datetime.now(UTC),
    )
    db.add(job)
    create_integration_event(db, tenant_id=_tenant_scope(current_user), external_system_id=system.id if system else None, direction="inbound", event_type="mock_ldap_pull_users", status="completed", request_summary=request.payload, response_summary=payload)
    _log_integration_audit(db, http_request, current_user, "mock_ldap_pull_users", "import_job", job.id, {"records_total": payload["records_total"]})
    db.commit()
    return payload


@router.post("/mock/zimbra/pull-mailboxes")
def mock_zimbra_pull_mailboxes(
    request: MockActionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.import")
    provider = get_provider("zimbra")
    payload = provider.pull_mailboxes()
    system = _resolve_external_system(db, request.external_system_id, "zimbra", _tenant_scope(current_user))
    if request.create_demo_ticket:
        mailbox = payload["mailboxes"][1]
        ticket = _create_demo_ticket(
            db,
            _tenant_scope(current_user),
            title=f"Mailbox issue: {mailbox['email']}",
            description="Mock mailbox health issue imported from Zimbra.",
            requester_email=mailbox["email"],
            requester_name="Mailbox Monitor",
            category="MAIL",
        )
        payload["demo_ticket_id"] = ticket.id
    create_integration_event(db, tenant_id=_tenant_scope(current_user), external_system_id=system.id if system else None, direction="inbound", event_type="mock_zimbra_pull_mailboxes", status="completed", request_summary=request.payload, response_summary=payload)
    _log_integration_audit(db, http_request, current_user, "mock_zimbra_pull_mailboxes", "external_system", system.id if system else None, {"records_total": payload["records_total"]})
    db.commit()
    return payload


@router.post("/mock/platonus/pull-users")
def mock_platonus_pull_users(
    request: MockActionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.import")
    provider = get_provider("platonus")
    payload = provider.pull_users()
    system = _resolve_external_system(db, request.external_system_id, "platonus", _tenant_scope(current_user))
    create_integration_event(db, tenant_id=_tenant_scope(current_user), external_system_id=system.id if system else None, direction="inbound", event_type="mock_platonus_pull_users", status="completed", request_summary=request.payload, response_summary=payload)
    _log_integration_audit(db, http_request, current_user, "mock_platonus_pull_users", "external_system", system.id if system else None, {"groups": payload.get("groups", [])})
    db.commit()
    return payload


@router.post("/mock/moodle/pull-users")
def mock_moodle_pull_users(
    request: MockActionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.import")
    provider = get_provider("moodle")
    payload = provider.pull_users()
    system = _resolve_external_system(db, request.external_system_id, "moodle", _tenant_scope(current_user))
    create_integration_event(db, tenant_id=_tenant_scope(current_user), external_system_id=system.id if system else None, direction="inbound", event_type="mock_moodle_pull_users", status="completed", request_summary=request.payload, response_summary=payload)
    _log_integration_audit(db, http_request, current_user, "mock_moodle_pull_users", "external_system", system.id if system else None, {"courses": payload.get("courses", [])})
    db.commit()
    return payload


@router.post("/mock/webhook/receive")
def mock_webhook_receive(
    request: MockActionRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "integrations.webhooks.manage")
    provider = get_provider("webhook")
    payload = provider.receive_event(request.payload)
    if request.create_demo_ticket:
        ticket = _create_demo_ticket(
            db,
            _tenant_scope(current_user),
            title="Webhook integration event",
            description="Demo ticket created from mock webhook receive action.",
            requester_email="webhook@sbs.local",
            requester_name="Webhook Source",
            category="INTEGRATION_WEBHOOK",
        )
        payload["demo_ticket_id"] = ticket.id
    create_integration_event(db, tenant_id=_tenant_scope(current_user), external_system_id=None, direction="inbound", event_type="mock_webhook_receive", status="accepted", request_summary=request.payload, response_summary=payload)
    db.commit()
    return payload
