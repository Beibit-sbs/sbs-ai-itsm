from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.asset_discovery import (
    AssetDiscoveryConnector,
    AssetDiscoveryRun,
    AssetDiscoveryStaleCandidate,
)
from app.models.cmdb_reconciliation import CMDBSource
from app.models.tenant import Tenant
from app.models.user import User
from app.services.asset_discovery import (
    AssetDiscoveryError,
    decide_stale_candidate,
    discovery_credential_hint,
    encrypt_discovery_credential,
    enqueue_discovery_run,
    fetch_discovery_records,
    validate_discovery_configuration,
    validate_discovery_credential,
)
from app.services.audit import log_audit
from app.services.cmdb_schema import canonical_json
from app.services.cmdb_reconciliation import ReconciliationConflict
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/asset-discovery")


class DiscoveryConnectorCreate(BaseModel):
    tenant_id: str | None = None
    cmdb_source_id: str
    name: str = Field(min_length=2, max_length=160)
    provider: Literal[
        "INTUNE",
        "AZURE_RESOURCE_GRAPH",
        "SCCM_ADMIN_SERVICE",
        "LANSWEEPER_DATA_API",
    ]
    auth_type: Literal[
        "OAUTH_CLIENT_CREDENTIALS",
        "API_TOKEN",
        "BASIC",
        "BEARER",
    ]
    base_url: str | None = Field(default=None, max_length=2_000)
    credential: dict[str, str]
    configuration: dict[str, Any] = Field(default_factory=dict)
    schedule_minutes: int = Field(default=60, ge=5, le=43_200)
    auto_apply: bool = False
    missing_threshold_runs: int = Field(default=3, ge=1, le=100)
    max_records: int = Field(default=5_000, ge=1, le=50_000)


class DiscoveryConnectorUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    base_url: str | None = Field(default=None, max_length=2_000)
    configuration: dict[str, Any] | None = None
    schedule_minutes: int | None = Field(default=None, ge=5, le=43_200)
    auto_apply: bool | None = None
    missing_threshold_runs: int | None = Field(default=None, ge=1, le=100)
    max_records: int | None = Field(default=None, ge=1, le=50_000)
    status: Literal["DRAFT", "ACTIVE", "PAUSED", "REVOKED"] | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class DiscoveryCredentialRotate(BaseModel):
    credential: dict[str, str]
    reason: str = Field(min_length=3, max_length=2_000)


class DiscoveryRunCreate(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)


class DiscoveryRunRetry(BaseModel):
    reason: str = Field(min_length=3, max_length=2_000)


class StaleCandidateDecision(BaseModel):
    expected_version: int = Field(ge=1)
    decision: Literal["RETIRE", "DISMISS"]
    reason: str = Field(min_length=3, max_length=2_000)


class DiscoveryConnectorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    cmdb_source_id: str
    cmdb_source_code: str
    cmdb_source_name: str
    name: str
    provider: str
    status: str
    auth_type: str
    base_url: str | None
    credential_configured: bool
    credential_hint: str | None
    credential_version: int
    last_tested_credential_version: int | None
    configuration: dict[str, Any]
    schedule_minutes: int
    auto_apply: bool
    missing_threshold_runs: int
    max_records: int
    version: int
    next_run_at: datetime | None
    last_started_at: datetime | None
    last_completed_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    successful_runs: int
    failed_runs: int
    discovered_records: int
    created_at: datetime
    updated_at: datetime


class DiscoveryRunResponse(BaseModel):
    id: str
    tenant_id: str
    connector_id: str
    connector_name: str
    provider: str
    idempotency_key: str
    trigger_type: str
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: datetime
    pages_fetched: int
    records_fetched: int
    complete_snapshot: bool
    reconciliation_run_ids: list[str]
    created_count: int
    updated_count: int
    unchanged_count: int
    ambiguous_count: int
    invalid_count: int
    missing_count: int
    stale_count: int
    provider_request_id: str | None
    result: dict[str, Any]
    last_error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StaleCandidateResponse(BaseModel):
    id: str
    tenant_id: str
    connector_id: str
    connector_name: str
    source_identity_id: str
    asset_id: str
    asset_tag: str
    asset_name: str
    external_id: str
    status: str
    missing_run_count: int
    first_missing_at: datetime
    last_missing_at: datetime
    version: int
    decision_reason: str | None
    decided_by_id: str | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


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
            detail="tenant_id is required for SaaS Root discovery administration",
        )
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _scope(current_user: AuthUserResponse, tenant_id: str, message: str) -> None:
    if not is_saas_root(current_user) and current_user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=message)


def _connector(
    db: Session,
    connector_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> AssetDiscoveryConnector:
    statement = select(AssetDiscoveryConnector).where(
        AssetDiscoveryConnector.id == connector_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Discovery connector not found")
    _scope(current_user, item.tenant_id, "Discovery connector not found")
    return item


def _run(
    db: Session,
    run_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> AssetDiscoveryRun:
    statement = select(AssetDiscoveryRun).where(AssetDiscoveryRun.id == run_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    _scope(current_user, item.tenant_id, "Discovery run not found")
    return item


def _candidate(
    db: Session,
    candidate_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> AssetDiscoveryStaleCandidate:
    statement = select(AssetDiscoveryStaleCandidate).where(
        AssetDiscoveryStaleCandidate.id == candidate_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Stale candidate not found")
    _scope(current_user, item.tenant_id, "Stale candidate not found")
    return item


def _connector_response(
    db: Session,
    item: AssetDiscoveryConnector,
) -> DiscoveryConnectorResponse:
    source = db.get(CMDBSource, item.cmdb_source_id)
    if source is None:
        raise HTTPException(status_code=409, detail="Connector CMDB source is missing")
    return DiscoveryConnectorResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        cmdb_source_id=item.cmdb_source_id,
        cmdb_source_code=source.code,
        cmdb_source_name=source.name,
        name=item.name,
        provider=item.provider,
        status=item.status,
        auth_type=item.auth_type,
        base_url=item.base_url,
        credential_configured=bool(item.credential_encrypted),
        credential_hint=item.credential_hint,
        credential_version=item.credential_version,
        last_tested_credential_version=item.last_tested_credential_version,
        configuration=_json_object(item.configuration_json),
        schedule_minutes=item.schedule_minutes,
        auto_apply=item.auto_apply,
        missing_threshold_runs=item.missing_threshold_runs,
        max_records=item.max_records,
        version=item.version,
        next_run_at=item.next_run_at,
        last_started_at=item.last_started_at,
        last_completed_at=item.last_completed_at,
        last_success_at=item.last_success_at,
        last_failure_at=item.last_failure_at,
        last_error=item.last_error,
        successful_runs=item.successful_runs,
        failed_runs=item.failed_runs,
        discovered_records=item.discovered_records,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _run_response(db: Session, item: AssetDiscoveryRun) -> DiscoveryRunResponse:
    connector = db.get(AssetDiscoveryConnector, item.connector_id)
    if connector is None:
        raise HTTPException(status_code=409, detail="Run connector is missing")
    return DiscoveryRunResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        connector_id=item.connector_id,
        connector_name=connector.name,
        provider=connector.provider,
        idempotency_key=item.idempotency_key,
        trigger_type=item.trigger_type,
        status=item.status,
        attempts=item.attempts,
        max_attempts=item.max_attempts,
        next_attempt_at=item.next_attempt_at,
        pages_fetched=item.pages_fetched,
        records_fetched=item.records_fetched,
        complete_snapshot=item.complete_snapshot,
        reconciliation_run_ids=_json_list(item.reconciliation_run_ids_json),
        created_count=item.created_count,
        updated_count=item.updated_count,
        unchanged_count=item.unchanged_count,
        ambiguous_count=item.ambiguous_count,
        invalid_count=item.invalid_count,
        missing_count=item.missing_count,
        stale_count=item.stale_count,
        provider_request_id=item.provider_request_id,
        result=_json_object(item.result_json),
        last_error=item.last_error,
        started_at=item.started_at,
        completed_at=item.completed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _candidate_response(
    db: Session,
    item: AssetDiscoveryStaleCandidate,
) -> StaleCandidateResponse:
    connector = db.get(AssetDiscoveryConnector, item.connector_id)
    asset = db.get(Asset, item.asset_id)
    if connector is None or asset is None:
        raise HTTPException(status_code=409, detail="Stale candidate references are missing")
    return StaleCandidateResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        connector_id=item.connector_id,
        connector_name=connector.name,
        source_identity_id=item.source_identity_id,
        asset_id=item.asset_id,
        asset_tag=asset.asset_tag,
        asset_name=asset.name,
        external_id=item.external_id,
        status=item.status,
        missing_run_count=item.missing_run_count,
        first_missing_at=item.first_missing_at,
        last_missing_at=item.last_missing_at,
        version=item.version,
        decision_reason=item.decision_reason,
        decided_by_id=item.decided_by_id,
        decided_at=item.decided_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


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


@router.get("/connectors", response_model=list[DiscoveryConnectorResponse])
def list_discovery_connectors(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DiscoveryConnectorResponse]:
    require_permissions(current_user, "asset.discovery.read")
    statement = select(AssetDiscoveryConnector)
    if not is_saas_root(current_user):
        statement = statement.where(
            AssetDiscoveryConnector.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(AssetDiscoveryConnector.tenant_id == tenant_id)
    rows = db.scalars(
        statement.order_by(AssetDiscoveryConnector.name)
    ).all()
    return [_connector_response(db, item) for item in rows]


@router.post(
    "/connectors",
    response_model=DiscoveryConnectorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_discovery_connector(
    payload: DiscoveryConnectorCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscoveryConnectorResponse:
    require_permissions(current_user, "asset.discovery.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    source = db.get(CMDBSource, payload.cmdb_source_id)
    if (
        source is None
        or source.tenant_id != tenant_id
        or source.source_type != "DISCOVERY"
    ):
        raise HTTPException(
            status_code=422,
            detail="An active DISCOVERY CMDB source in this tenant is required",
        )
    if source.status != "ACTIVE":
        raise HTTPException(status_code=422, detail="CMDB source is inactive")
    if db.scalar(
        select(AssetDiscoveryConnector.id).where(
            AssetDiscoveryConnector.cmdb_source_id == source.id
        )
    ):
        raise HTTPException(
            status_code=409,
            detail="This CMDB source already has a discovery connector",
        )
    try:
        credential = validate_discovery_credential(
            payload.provider,
            payload.auth_type,
            payload.credential,
        )
        base_url, configuration = validate_discovery_configuration(
            payload.provider,
            payload.base_url,
            payload.configuration,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = datetime.now(UTC)
    item = AssetDiscoveryConnector(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        cmdb_source_id=source.id,
        name=payload.name.strip(),
        provider=payload.provider,
        status="DRAFT",
        auth_type=payload.auth_type,
        base_url=base_url,
        credential_hint=discovery_credential_hint(payload.auth_type, credential),
        credential_version=1,
        configuration_json=canonical_json(configuration),
        schedule_minutes=payload.schedule_minutes,
        auto_apply=payload.auto_apply,
        missing_threshold_runs=payload.missing_threshold_runs,
        max_records=payload.max_records,
        version=1,
        successful_runs=0,
        failed_runs=0,
        discovered_records=0,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    item.credential_encrypted = encrypt_discovery_credential(item, credential)
    db.add(item)
    db.flush()
    _audit(
        db,
        request,
        current_user,
        action="asset_discovery_connector_created",
        entity_type="asset_discovery_connector",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={
            "provider": item.provider,
            "auth_type": item.auth_type,
            "cmdb_source_id": source.id,
            "schedule_minutes": item.schedule_minutes,
            "auto_apply": item.auto_apply,
        },
    )
    db.commit()
    db.refresh(item)
    return _connector_response(db, item)


@router.patch(
    "/connectors/{connector_id}",
    response_model=DiscoveryConnectorResponse,
)
def update_discovery_connector(
    connector_id: str,
    payload: DiscoveryConnectorUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscoveryConnectorResponse:
    require_permissions(current_user, "asset.discovery.manage")
    item = _connector(db, connector_id, current_user, lock=True)
    if item.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Discovery connector changed; current version is {item.version}",
        )
    if item.status == "REVOKED" and payload.status != "REVOKED":
        raise HTTPException(status_code=409, detail="Revoked connector cannot reactivate")
    configuration = (
        payload.configuration
        if payload.configuration is not None
        else _json_object(item.configuration_json)
    )
    base_url_input = (
        payload.base_url
        if "base_url" in payload.model_fields_set
        else item.base_url
    )
    try:
        base_url, configuration = validate_discovery_configuration(
            item.provider,
            base_url_input,
            configuration,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    before = {
        "name": item.name,
        "status": item.status,
        "schedule_minutes": item.schedule_minutes,
        "auto_apply": item.auto_apply,
        "missing_threshold_runs": item.missing_threshold_runs,
        "max_records": item.max_records,
        "version": item.version,
    }
    updates = payload.model_dump(
        exclude={"expected_version", "reason", "configuration", "base_url"},
        exclude_unset=True,
    )
    for key, value in updates.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(item, key, value)
    item.base_url = base_url
    item.configuration_json = canonical_json(configuration)
    if item.status == "ACTIVE":
        if not item.credential_encrypted:
            raise HTTPException(
                status_code=409,
                detail="Credential is required before activation",
            )
        if item.last_tested_credential_version != item.credential_version:
            raise HTTPException(
                status_code=409,
                detail="Test the current credential successfully before activation",
            )
        item.next_run_at = item.next_run_at or datetime.now(UTC)
    elif item.status in {"PAUSED", "REVOKED"}:
        item.next_run_at = None
    if item.status == "REVOKED":
        item.credential_encrypted = None
        item.credential_hint = None
        due_runs = db.scalars(
            select(AssetDiscoveryRun).where(
                AssetDiscoveryRun.connector_id == item.id,
                AssetDiscoveryRun.status.in_({"QUEUED", "RETRY"}),
            )
        ).all()
        for due in due_runs:
            due.status = "CANCELLED"
            due.completed_at = datetime.now(UTC)
            due.updated_at = due.completed_at
    item.version += 1
    item.updated_by_id = current_user.id
    item.updated_at = datetime.now(UTC)
    _audit(
        db,
        request,
        current_user,
        action="asset_discovery_connector_updated",
        entity_type="asset_discovery_connector",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "before": before,
            "after": {
                "name": item.name,
                "status": item.status,
                "schedule_minutes": item.schedule_minutes,
                "auto_apply": item.auto_apply,
                "missing_threshold_runs": item.missing_threshold_runs,
                "max_records": item.max_records,
                "version": item.version,
            },
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    db.refresh(item)
    return _connector_response(db, item)


@router.post(
    "/connectors/{connector_id}/rotate-credential",
    response_model=DiscoveryConnectorResponse,
)
def rotate_discovery_credential(
    connector_id: str,
    payload: DiscoveryCredentialRotate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscoveryConnectorResponse:
    require_permissions(current_user, "asset.discovery.manage")
    item = _connector(db, connector_id, current_user, lock=True)
    if item.status == "REVOKED":
        raise HTTPException(status_code=409, detail="Connector is revoked")
    try:
        credential = validate_discovery_credential(
            item.provider,
            item.auth_type,
            payload.credential,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item.credential_encrypted = encrypt_discovery_credential(item, credential)
    item.credential_hint = discovery_credential_hint(item.auth_type, credential)
    item.credential_version += 1
    item.last_tested_credential_version = None
    item.version += 1
    item.last_error = None
    if item.status == "ACTIVE":
        item.status = "PAUSED"
        item.next_run_at = None
    item.updated_by_id = current_user.id
    item.updated_at = datetime.now(UTC)
    _audit(
        db,
        request,
        current_user,
        action="asset_discovery_credential_rotated",
        entity_type="asset_discovery_connector",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "provider": item.provider,
            "credential_version": item.credential_version,
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    db.refresh(item)
    return _connector_response(db, item)


@router.post("/connectors/{connector_id}/test")
def test_discovery_connector(
    connector_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "asset.discovery.manage")
    item = _connector(db, connector_id, current_user)
    if item.status == "REVOKED":
        raise HTTPException(status_code=409, detail="Connector is revoked")
    try:
        result = fetch_discovery_records(item, max_records=1)
    except Exception as exc:
        public_error = (
            str(exc)
            if isinstance(exc, AssetDiscoveryError)
            else f"{exc.__class__.__name__}: connection test failed"
        )
        item.last_failure_at = datetime.now(UTC)
        item.last_error = public_error[:2_000]
        item.updated_at = item.last_failure_at
        _audit(
            db,
            request,
            current_user,
            action="asset_discovery_connector_test_failed",
            entity_type="asset_discovery_connector",
            entity_id=item.id,
            tenant_id=item.tenant_id,
            metadata={"provider": item.provider, "error": public_error[:500]},
        )
        db.commit()
        raise HTTPException(status_code=502, detail=public_error) from exc
    now = datetime.now(UTC)
    item.last_success_at = now
    item.last_tested_credential_version = item.credential_version
    item.last_error = None
    item.updated_at = now
    sample = result.records[0] if result.records else None
    _audit(
        db,
        request,
        current_user,
        action="asset_discovery_connector_test_succeeded",
        entity_type="asset_discovery_connector",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"provider": item.provider, "records_returned": len(result.records)},
    )
    db.commit()
    return {
        "ok": True,
        "provider": item.provider,
        "pages": result.pages,
        "records_returned": len(result.records),
        "sample": (
            {
                "external_id": sample.get("external_id"),
                "name": sample.get("name"),
                "original_type": sample.get("original_type"),
            }
            if sample
            else None
        ),
    }


@router.post(
    "/connectors/{connector_id}/runs",
    response_model=DiscoveryRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_discovery_run(
    connector_id: str,
    payload: DiscoveryRunCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscoveryRunResponse:
    require_permissions(current_user, "asset.discovery.run")
    item = _connector(db, connector_id, current_user, lock=True)
    if item.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Connector must be active")
    pending_run = db.scalar(
        select(AssetDiscoveryRun).where(
            AssetDiscoveryRun.connector_id == item.id,
            AssetDiscoveryRun.status.in_({"QUEUED", "RUNNING", "RETRY"}),
        )
    )
    if pending_run is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Discovery run {pending_run.id} is already pending",
        )
    run = enqueue_discovery_run(
        db,
        item,
        trigger_type="MANUAL",
        requested_by_id=current_user.id,
        idempotency_key=payload.idempotency_key,
    )
    item.next_run_at = datetime.now(UTC) + timedelta(minutes=item.schedule_minutes)
    _audit(
        db,
        request,
        current_user,
        action="asset_discovery_run_queued",
        entity_type="asset_discovery_run",
        entity_id=run.id,
        tenant_id=item.tenant_id,
        metadata={"connector_id": item.id, "provider": item.provider},
    )
    db.commit()
    db.refresh(run)
    return _run_response(db, run)


@router.get("/runs", response_model=list[DiscoveryRunResponse])
def list_discovery_runs(
    tenant_id: str | None = None,
    connector_id: str | None = None,
    run_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DiscoveryRunResponse]:
    require_permissions(current_user, "asset.discovery.read")
    statement = select(AssetDiscoveryRun)
    if not is_saas_root(current_user):
        statement = statement.where(
            AssetDiscoveryRun.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(AssetDiscoveryRun.tenant_id == tenant_id)
    if connector_id:
        statement = statement.where(AssetDiscoveryRun.connector_id == connector_id)
    if run_status:
        statement = statement.where(AssetDiscoveryRun.status == run_status.upper())
    rows = db.scalars(
        statement.order_by(AssetDiscoveryRun.created_at.desc()).limit(limit)
    ).all()
    return [_run_response(db, item) for item in rows]


@router.post(
    "/runs/{run_id}/retry",
    response_model=DiscoveryRunResponse,
)
def retry_discovery_run(
    run_id: str,
    payload: DiscoveryRunRetry,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscoveryRunResponse:
    require_permissions(current_user, "asset.discovery.run")
    item = _run(db, run_id, current_user, lock=True)
    connector = db.get(AssetDiscoveryConnector, item.connector_id)
    if connector is None or connector.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Connector is not active")
    if item.status not in {"FAILED", "DEAD_LETTER", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Run is not recoverable")
    pending_run = db.scalar(
        select(AssetDiscoveryRun.id).where(
            AssetDiscoveryRun.connector_id == item.connector_id,
            AssetDiscoveryRun.id != item.id,
            AssetDiscoveryRun.status.in_({"QUEUED", "RUNNING", "RETRY"}),
        )
    )
    if pending_run is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Discovery run {pending_run} is already pending",
        )
    item.status = "QUEUED"
    item.attempts = 0
    item.next_attempt_at = datetime.now(UTC)
    item.last_error = None
    item.completed_at = None
    item.updated_at = item.next_attempt_at
    _audit(
        db,
        request,
        current_user,
        action="asset_discovery_run_retried",
        entity_type="asset_discovery_run",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"connector_id": item.connector_id, "reason": payload.reason.strip()},
    )
    db.commit()
    db.refresh(item)
    return _run_response(db, item)


@router.get(
    "/stale-candidates",
    response_model=list[StaleCandidateResponse],
)
def list_stale_candidates(
    tenant_id: str | None = None,
    connector_id: str | None = None,
    candidate_status: str | None = Query(default="OPEN", alias="status"),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[StaleCandidateResponse]:
    require_permissions(current_user, "asset.discovery.read")
    statement = select(AssetDiscoveryStaleCandidate)
    if not is_saas_root(current_user):
        statement = statement.where(
            AssetDiscoveryStaleCandidate.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(
            AssetDiscoveryStaleCandidate.tenant_id == tenant_id
        )
    if connector_id:
        statement = statement.where(
            AssetDiscoveryStaleCandidate.connector_id == connector_id
        )
    if candidate_status:
        statement = statement.where(
            AssetDiscoveryStaleCandidate.status == candidate_status.upper()
        )
    rows = db.scalars(
        statement.order_by(AssetDiscoveryStaleCandidate.last_missing_at.desc())
    ).all()
    return [_candidate_response(db, item) for item in rows]


@router.post(
    "/stale-candidates/{candidate_id}/decision",
    response_model=StaleCandidateResponse,
)
def decide_discovery_stale_candidate(
    candidate_id: str,
    payload: StaleCandidateDecision,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StaleCandidateResponse:
    require_permissions(current_user, "asset.discovery.review")
    item = _candidate(db, candidate_id, current_user, lock=True)
    try:
        decide_stale_candidate(
            db,
            item,
            decision=payload.decision,
            expected_version=payload.expected_version,
            actor_id=current_user.id,
            reason=payload.reason,
        )
    except (ValueError, ReconciliationConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action=f"asset_discovery_stale_{payload.decision.lower()}",
        entity_type="asset_discovery_stale_candidate",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "asset_id": item.asset_id,
            "external_id": item.external_id,
            "decision": payload.decision,
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    db.refresh(item)
    return _candidate_response(db, item)


@router.get("/dashboard")
def discovery_dashboard(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "asset.discovery.read")
    connector_filters = []
    run_filters = []
    stale_filters = []
    if not is_saas_root(current_user):
        connector_filters.append(
            AssetDiscoveryConnector.tenant_id == current_user.tenant_id
        )
        run_filters.append(AssetDiscoveryRun.tenant_id == current_user.tenant_id)
        stale_filters.append(
            AssetDiscoveryStaleCandidate.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        connector_filters.append(AssetDiscoveryConnector.tenant_id == tenant_id)
        run_filters.append(AssetDiscoveryRun.tenant_id == tenant_id)
        stale_filters.append(AssetDiscoveryStaleCandidate.tenant_id == tenant_id)
    connector_counts = {
        row[0]: int(row[1])
        for row in db.execute(
            select(AssetDiscoveryConnector.status, func.count())
            .where(*connector_filters)
            .group_by(AssetDiscoveryConnector.status)
        ).all()
    }
    run_counts = {
        row[0]: int(row[1])
        for row in db.execute(
            select(AssetDiscoveryRun.status, func.count())
            .where(*run_filters)
            .group_by(AssetDiscoveryRun.status)
        ).all()
    }
    open_stale = int(
        db.scalar(
            select(func.count())
            .select_from(AssetDiscoveryStaleCandidate)
            .where(
                *stale_filters,
                AssetDiscoveryStaleCandidate.status == "OPEN",
            )
        )
        or 0
    )
    return {
        "connectors": connector_counts,
        "runs": run_counts,
        "open_stale_candidates": open_stale,
        "unhealthy_connectors": int(
            db.scalar(
                select(func.count())
                .select_from(AssetDiscoveryConnector)
                .where(
                    *connector_filters,
                    AssetDiscoveryConnector.status == "ACTIVE",
                    AssetDiscoveryConnector.last_error.is_not(None),
                )
            )
            or 0
        ),
    }
