from __future__ import annotations

from datetime import UTC, datetime
import json
import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.ci_class import (
    ConfigurationItemClass,
    ConfigurationItemClassVersion,
)
from app.models.cmdb_reconciliation import (
    CIDuplicateCandidate,
    CMDBFieldOwnership,
    CMDBReconciliationRecord,
    CMDBReconciliationRun,
    CMDBSource,
)
from app.models.external_system import ExternalSystem
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.cmdb_reconciliation import (
    ReconciliationConflict,
    apply_reconciliation,
    dismiss_duplicate_candidate,
    merge_duplicate_candidate,
    preview_reconciliation,
    validate_source_definition,
)
from app.services.cmdb_schema import canonical_json
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/cmdb")
_CODE_PATTERN = re.compile(r"[^A-Z0-9_-]+")


class CMDBSourceCreate(BaseModel):
    tenant_id: str | None = None
    external_system_id: str | None = None
    default_class_id: str | None = None
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5_000)
    source_type: Literal["FILE", "API", "DISCOVERY", "MANUAL"]
    priority: int = Field(default=100, ge=1, le=1_000)
    identification_rules: list[str] = Field(min_length=1, max_length=10)
    authoritative_fields: list[str] = Field(default_factory=list, max_length=100)
    claim_unowned_fields: bool = False
    stale_after_hours: int = Field(default=24, ge=1, le=87_600)


class CMDBSourceUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    external_system_id: str | None = None
    default_class_id: str | None = None
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5_000)
    source_type: Literal["FILE", "API", "DISCOVERY", "MANUAL"] | None = None
    priority: int | None = Field(default=None, ge=1, le=1_000)
    identification_rules: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=10,
    )
    authoritative_fields: list[str] | None = Field(
        default=None,
        max_length=100,
    )
    claim_unowned_fields: bool | None = None
    stale_after_hours: int | None = Field(default=None, ge=1, le=87_600)
    status: Literal["ACTIVE", "INACTIVE"] | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class CMDBSourceResponse(BaseModel):
    id: str
    tenant_id: str
    external_system_id: str | None
    external_system_name: str | None
    default_class_id: str | None
    default_class_name: str | None
    code: str
    name: str
    description: str | None
    source_type: str
    priority: int
    identification_rules: list[str]
    authoritative_fields: list[str]
    claim_unowned_fields: bool
    stale_after_hours: int
    status: str
    version: int
    is_stale: bool
    last_run_at: datetime | None
    last_success_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CMDBInputRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=255)
    ci_class_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    asset_tag: str | None = Field(default=None, min_length=2, max_length=32)
    inventory_number: str | None = Field(default=None, max_length=80)
    serial_number: str | None = Field(default=None, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    original_type: str | None = Field(default=None, max_length=120)
    lifecycle_status: Literal[
        "PLANNING",
        "ORDERED",
        "IN_STOCK",
        "ACTIVE",
        "MAINTENANCE",
        "RETIRED",
        "DISPOSED",
    ] | None = None
    owner_user_id: str | None = None
    support_group: str | None = Field(default=None, max_length=160)
    criticality: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
    environment: Literal[
        "PRODUCTION",
        "STAGING",
        "TEST",
        "DEVELOPMENT",
        "OTHER",
    ] | None = None
    location: str | None = Field(default=None, max_length=200)
    condition: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=10_000)
    assigned_to_name: str | None = Field(default=None, max_length=200)
    purchase_date: datetime | None = None
    purchase_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    current_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    depreciation_amount: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    residual_value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    purchase_year: int | None = Field(default=None, ge=1900, le=2200)
    verification_status: str | None = Field(default=None, max_length=64)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ReconciliationPreviewRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    records: list[CMDBInputRecord] = Field(min_length=1, max_length=500)


class ReconciliationRecordResponse(BaseModel):
    id: str
    row_number: int
    external_id: str
    outcome: str
    matched_ci_id: str | None
    candidate_ids: list[str]
    errors: list[str]
    normalized: dict[str, Any]
    applied_at: datetime | None
    created_at: datetime


class ReconciliationRunResponse(BaseModel):
    id: str
    tenant_id: str
    source_id: str
    source_code: str
    source_name: str
    idempotency_key: str
    payload_hash: str
    mode: str
    status: str
    input_count: int
    create_count: int
    update_count: int
    unchanged_count: int
    ambiguous_count: int
    invalid_count: int
    skipped_count: int
    summary: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    records: list[ReconciliationRecordResponse] | None = None


class CIReferenceResponse(BaseModel):
    id: str
    asset_tag: str
    name: str
    ci_class_name: str | None
    lifecycle_status: str
    version: int


class DuplicateCandidateResponse(BaseModel):
    id: str
    tenant_id: str
    run_id: str
    record_id: str | None
    primary: CIReferenceResponse
    duplicate: CIReferenceResponse
    confidence: float
    reasons: list[str]
    status: str
    version: int
    resolution_reason: str | None
    resolved_by_id: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DuplicateDismissRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


class DuplicateMergeRequest(DuplicateDismissRequest):
    expected_primary_version: int = Field(ge=1)
    expected_duplicate_version: int = Field(ge=1)


class DuplicateMergeResponse(BaseModel):
    candidate: DuplicateCandidateResponse
    merge_summary: dict[str, int]


class FieldOwnershipResponse(BaseModel):
    id: str
    field_name: str
    source_id: str
    source_code: str
    source_name: str
    external_id: str
    source_priority: int
    value_hash: str
    observed_at: datetime
    updated_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _age_seconds(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return (_now() - value).total_seconds()


def _json_list(value: str) -> list[Any]:
    try:
        result = json.loads(value)
    except json.JSONDecodeError:
        return []
    return result if isinstance(result, list) else []


def _json_dict(value: str) -> dict[str, Any]:
    try:
        result = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return result if isinstance(result, dict) else {}


def _code(value: str) -> str:
    normalized = _CODE_PATTERN.sub("_", value.strip().upper()).strip("_")
    if len(normalized) < 2:
        raise HTTPException(status_code=422, detail="CMDB source code is invalid")
    return normalized


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
            detail="tenant_id is required for SaaS Root source administration",
        )
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _check_scope(
    current_user: AuthUserResponse,
    tenant_id: str,
    *,
    message: str,
) -> None:
    if not is_saas_root(current_user) and tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail=message)


def _source_or_404(
    db: Session,
    source_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> CMDBSource:
    statement = select(CMDBSource).where(CMDBSource.id == source_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    source = db.scalar(statement)
    if source is None:
        raise HTTPException(status_code=404, detail="CMDB source not found")
    _check_scope(current_user, source.tenant_id, message="CMDB source not found")
    return source


def _run_or_404(
    db: Session,
    run_id: str,
    current_user: AuthUserResponse,
) -> CMDBReconciliationRun:
    run = db.get(CMDBReconciliationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="CMDB reconciliation run not found")
    _check_scope(
        current_user,
        run.tenant_id,
        message="CMDB reconciliation run not found",
    )
    return run


def _candidate_or_404(
    db: Session,
    candidate_id: str,
    current_user: AuthUserResponse,
) -> CIDuplicateCandidate:
    candidate = db.get(CIDuplicateCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="CI duplicate candidate not found")
    _check_scope(
        current_user,
        candidate.tenant_id,
        message="CI duplicate candidate not found",
    )
    return candidate


def _class_in_tenant(
    db: Session,
    class_id: str | None,
    tenant_id: str,
) -> ConfigurationItemClass | None:
    if class_id is None:
        return None
    ci_class = db.get(ConfigurationItemClass, class_id)
    if ci_class is None or ci_class.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="Default CI class is unavailable")
    published = db.scalar(
        select(ConfigurationItemClassVersion.id).where(
            ConfigurationItemClassVersion.ci_class_id == ci_class.id,
            ConfigurationItemClassVersion.status == "PUBLISHED",
        )
    )
    if published is None:
        raise HTTPException(status_code=422, detail="Default CI class is not published")
    return ci_class


def _external_system_in_tenant(
    db: Session,
    external_system_id: str | None,
    tenant_id: str,
) -> ExternalSystem | None:
    if external_system_id is None:
        return None
    system = db.get(ExternalSystem, external_system_id)
    if system is None or system.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="External system is unavailable")
    return system


def _source_response(db: Session, source: CMDBSource) -> CMDBSourceResponse:
    external_system = (
        db.get(ExternalSystem, source.external_system_id)
        if source.external_system_id
        else None
    )
    ci_class = (
        db.get(ConfigurationItemClass, source.default_class_id)
        if source.default_class_id
        else None
    )
    age = _age_seconds(source.last_success_at)
    stale = age is None or age > source.stale_after_hours * 3600
    return CMDBSourceResponse(
        id=source.id,
        tenant_id=source.tenant_id,
        external_system_id=source.external_system_id,
        external_system_name=external_system.name if external_system else None,
        default_class_id=source.default_class_id,
        default_class_name=ci_class.name if ci_class else None,
        code=source.code,
        name=source.name,
        description=source.description,
        source_type=source.source_type,
        priority=source.priority,
        identification_rules=[
            str(item) for item in _json_list(source.identification_rules_json)
        ],
        authoritative_fields=[
            str(item) for item in _json_list(source.authoritative_fields_json)
        ],
        claim_unowned_fields=source.claim_unowned_fields,
        stale_after_hours=source.stale_after_hours,
        status=source.status,
        version=source.version,
        is_stale=stale,
        last_run_at=source.last_run_at,
        last_success_at=source.last_success_at,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _record_response(
    record: CMDBReconciliationRecord,
) -> ReconciliationRecordResponse:
    return ReconciliationRecordResponse(
        id=record.id,
        row_number=record.row_number,
        external_id=record.external_id,
        outcome=record.outcome,
        matched_ci_id=record.matched_ci_id,
        candidate_ids=[
            str(item) for item in _json_list(record.candidate_ids_json)
        ],
        errors=[str(item) for item in _json_list(record.errors_json)],
        normalized=_json_dict(record.normalized_json),
        applied_at=record.applied_at,
        created_at=record.created_at,
    )


def _run_response(
    db: Session,
    run: CMDBReconciliationRun,
    *,
    include_records: bool = False,
) -> ReconciliationRunResponse:
    source = db.get(CMDBSource, run.source_id)
    if source is None:
        raise HTTPException(status_code=409, detail="CMDB run source is missing")
    records = None
    if include_records:
        records = [
            _record_response(item)
            for item in db.scalars(
                select(CMDBReconciliationRecord)
                .where(CMDBReconciliationRecord.run_id == run.id)
                .order_by(CMDBReconciliationRecord.row_number)
            ).all()
        ]
    return ReconciliationRunResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        source_id=run.source_id,
        source_code=source.code,
        source_name=source.name,
        idempotency_key=run.idempotency_key,
        payload_hash=run.payload_hash,
        mode=run.mode,
        status=run.status,
        input_count=run.input_count,
        create_count=run.create_count,
        update_count=run.update_count,
        unchanged_count=run.unchanged_count,
        ambiguous_count=run.ambiguous_count,
        invalid_count=run.invalid_count,
        skipped_count=run.skipped_count,
        summary=_json_dict(run.summary_json),
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        records=records,
    )


def _ci_reference(asset: Asset | None) -> CIReferenceResponse:
    if asset is None:
        raise HTTPException(status_code=409, detail="Duplicate candidate CI is missing")
    return CIReferenceResponse(
        id=asset.id,
        asset_tag=asset.asset_tag,
        name=asset.name,
        ci_class_name=asset.ci_class_name,
        lifecycle_status=asset.lifecycle_status,
        version=asset.ci_version,
    )


def _duplicate_response(
    db: Session,
    candidate: CIDuplicateCandidate,
) -> DuplicateCandidateResponse:
    return DuplicateCandidateResponse(
        id=candidate.id,
        tenant_id=candidate.tenant_id,
        run_id=candidate.run_id,
        record_id=candidate.record_id,
        primary=_ci_reference(db.get(Asset, candidate.primary_ci_id)),
        duplicate=_ci_reference(db.get(Asset, candidate.duplicate_ci_id)),
        confidence=candidate.confidence,
        reasons=[
            str(item) for item in _json_list(candidate.reasons_json)
        ],
        status=candidate.status,
        version=candidate.version,
        resolution_reason=candidate.resolution_reason,
        resolved_by_id=candidate.resolved_by_id,
        resolved_at=candidate.resolved_at,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
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


@router.get("/sources", response_model=list[CMDBSourceResponse])
def list_cmdb_sources(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CMDBSourceResponse]:
    require_permissions(current_user, "assets.read")
    statement = select(CMDBSource)
    if not is_saas_root(current_user):
        statement = statement.where(CMDBSource.tenant_id == current_user.tenant_id)
    elif tenant_id:
        statement = statement.where(CMDBSource.tenant_id == tenant_id)
    sources = db.scalars(
        statement.order_by(CMDBSource.priority, CMDBSource.name)
    ).all()
    return [_source_response(db, source) for source in sources]


@router.post(
    "/sources",
    response_model=CMDBSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_cmdb_source(
    payload: CMDBSourceCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CMDBSourceResponse:
    require_permissions(current_user, "assets.update")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    ci_class = _class_in_tenant(db, payload.default_class_id, tenant_id)
    external_system = _external_system_in_tenant(
        db,
        payload.external_system_id,
        tenant_id,
    )
    try:
        rules, fields = validate_source_definition(
            payload.identification_rules,
            payload.authoritative_fields,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    code = _code(payload.code)
    if db.scalar(
        select(CMDBSource.id).where(
            CMDBSource.tenant_id == tenant_id,
            CMDBSource.code == code,
        )
    ):
        raise HTTPException(status_code=409, detail="CMDB source code already exists")
    now = _now()
    source = CMDBSource(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        external_system_id=external_system.id if external_system else None,
        default_class_id=ci_class.id if ci_class else None,
        code=code,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        source_type=payload.source_type,
        priority=payload.priority,
        identification_rules_json=canonical_json(rules),
        authoritative_fields_json=canonical_json(fields),
        claim_unowned_fields=payload.claim_unowned_fields,
        stale_after_hours=payload.stale_after_hours,
        status="ACTIVE",
        version=1,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(source)
    db.flush()
    _audit(
        db,
        request,
        current_user,
        action="cmdb_source_created",
        entity_type="cmdb_source",
        entity_id=source.id,
        tenant_id=tenant_id,
        metadata={
            "code": code,
            "source_type": source.source_type,
            "priority": source.priority,
            "identification_rules": rules,
            "authoritative_fields": fields,
        },
    )
    db.commit()
    db.refresh(source)
    return _source_response(db, source)


@router.patch("/sources/{source_id}", response_model=CMDBSourceResponse)
def update_cmdb_source(
    source_id: str,
    payload: CMDBSourceUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CMDBSourceResponse:
    require_permissions(current_user, "assets.update")
    source = _source_or_404(db, source_id, current_user, lock=True)
    if source.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"CMDB source changed; current version is {source.version}",
        )
    updates = payload.model_dump(
        exclude={"expected_version", "reason"},
        exclude_unset=True,
    )
    if "default_class_id" in updates:
        _class_in_tenant(db, updates["default_class_id"], source.tenant_id)
    if "external_system_id" in updates:
        _external_system_in_tenant(
            db,
            updates["external_system_id"],
            source.tenant_id,
        )
    rules = (
        updates.get("identification_rules")
        or [
            str(item)
            for item in _json_list(source.identification_rules_json)
        ]
    )
    fields = (
        updates.get("authoritative_fields")
        if "authoritative_fields" in updates
        else [
            str(item)
            for item in _json_list(source.authoritative_fields_json)
        ]
    )
    try:
        rules, fields = validate_source_definition(rules, fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    before = {
        "external_system_id": source.external_system_id,
        "default_class_id": source.default_class_id,
        "name": source.name,
        "source_type": source.source_type,
        "priority": source.priority,
        "identification_rules": _json_list(source.identification_rules_json),
        "authoritative_fields": _json_list(source.authoritative_fields_json),
        "claim_unowned_fields": source.claim_unowned_fields,
        "stale_after_hours": source.stale_after_hours,
        "status": source.status,
        "version": source.version,
    }
    for field_name, value in updates.items():
        if field_name == "identification_rules":
            source.identification_rules_json = canonical_json(rules)
        elif field_name == "authoritative_fields":
            source.authoritative_fields_json = canonical_json(fields)
        else:
            if isinstance(value, str):
                value = value.strip()
            setattr(source, field_name, value)
    source.version += 1
    source.updated_by_id = current_user.id
    source.updated_at = _now()
    _audit(
        db,
        request,
        current_user,
        action="cmdb_source_updated",
        entity_type="cmdb_source",
        entity_id=source.id,
        tenant_id=source.tenant_id,
        metadata={
            "before": before,
            "after": updates,
            "version": source.version,
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    db.refresh(source)
    return _source_response(db, source)


@router.post(
    "/sources/{source_id}/reconciliation/preview",
    response_model=ReconciliationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def preview_cmdb_reconciliation(
    source_id: str,
    payload: ReconciliationPreviewRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReconciliationRunResponse:
    require_permissions(current_user, "assets.update")
    source = _source_or_404(db, source_id, current_user)
    serialized_records = [
        record.model_dump(mode="json", exclude_none=True)
        for record in payload.records
    ]
    try:
        run = preview_reconciliation(
            db,
            source=source,
            idempotency_key=payload.idempotency_key,
            records=serialized_records,
            actor_id=current_user.id,
        )
    except ReconciliationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="cmdb_reconciliation_previewed",
        entity_type="cmdb_reconciliation_run",
        entity_id=run.id,
        tenant_id=run.tenant_id,
        metadata={
            "source_id": source.id,
            "idempotency_key": run.idempotency_key,
            "payload_hash": run.payload_hash,
            "summary": _json_dict(run.summary_json),
        },
    )
    db.commit()
    db.refresh(run)
    return _run_response(db, run, include_records=True)


@router.get(
    "/reconciliation-runs",
    response_model=list[ReconciliationRunResponse],
)
def list_reconciliation_runs(
    tenant_id: str | None = None,
    source_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReconciliationRunResponse]:
    require_permissions(current_user, "assets.read")
    statement = select(CMDBReconciliationRun)
    if not is_saas_root(current_user):
        statement = statement.where(
            CMDBReconciliationRun.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(CMDBReconciliationRun.tenant_id == tenant_id)
    if source_id:
        statement = statement.where(CMDBReconciliationRun.source_id == source_id)
    runs = db.scalars(
        statement.order_by(CMDBReconciliationRun.created_at.desc()).limit(limit)
    ).all()
    return [_run_response(db, run) for run in runs]


@router.get(
    "/reconciliation-runs/{run_id}",
    response_model=ReconciliationRunResponse,
)
def get_reconciliation_run(
    run_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReconciliationRunResponse:
    require_permissions(current_user, "assets.read")
    run = _run_or_404(db, run_id, current_user)
    return _run_response(db, run, include_records=True)


@router.post(
    "/reconciliation-runs/{run_id}/apply",
    response_model=ReconciliationRunResponse,
)
def apply_cmdb_reconciliation(
    run_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReconciliationRunResponse:
    require_permissions(current_user, "assets.update")
    scoped_run = _run_or_404(db, run_id, current_user)
    try:
        run = apply_reconciliation(
            db,
            run_id=scoped_run.id,
            actor_id=current_user.id,
        )
    except ReconciliationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="cmdb_reconciliation_applied",
        entity_type="cmdb_reconciliation_run",
        entity_id=run.id,
        tenant_id=run.tenant_id,
        metadata={
            "source_id": run.source_id,
            "status": run.status,
            "summary": _json_dict(run.summary_json),
        },
    )
    db.commit()
    db.refresh(run)
    return _run_response(db, run, include_records=True)


@router.get(
    "/duplicate-candidates",
    response_model=list[DuplicateCandidateResponse],
)
def list_duplicate_candidates(
    tenant_id: str | None = None,
    candidate_status: Literal["OPEN", "MERGED", "DISMISSED"] = "OPEN",
    limit: int = Query(default=100, ge=1, le=500),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DuplicateCandidateResponse]:
    require_permissions(current_user, "assets.read")
    statement = select(CIDuplicateCandidate).where(
        CIDuplicateCandidate.status == candidate_status
    )
    if not is_saas_root(current_user):
        statement = statement.where(
            CIDuplicateCandidate.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        statement = statement.where(CIDuplicateCandidate.tenant_id == tenant_id)
    candidates = db.scalars(
        statement.order_by(
            CIDuplicateCandidate.confidence.desc(),
            CIDuplicateCandidate.created_at.desc(),
        ).limit(limit)
    ).all()
    return [_duplicate_response(db, candidate) for candidate in candidates]


@router.post(
    "/duplicate-candidates/{candidate_id}/dismiss",
    response_model=DuplicateCandidateResponse,
)
def dismiss_ci_duplicate(
    candidate_id: str,
    payload: DuplicateDismissRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DuplicateCandidateResponse:
    require_permissions(current_user, "assets.update")
    scoped = _candidate_or_404(db, candidate_id, current_user)
    try:
        candidate = dismiss_duplicate_candidate(
            db,
            candidate_id=scoped.id,
            expected_version=payload.expected_version,
            actor_id=current_user.id,
            reason=payload.reason,
        )
    except ReconciliationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="ci_duplicate_dismissed",
        entity_type="ci_duplicate_candidate",
        entity_id=candidate.id,
        tenant_id=candidate.tenant_id,
        metadata={
            "primary_ci_id": candidate.primary_ci_id,
            "duplicate_ci_id": candidate.duplicate_ci_id,
            "reason": payload.reason.strip(),
            "version": candidate.version,
        },
    )
    db.commit()
    db.refresh(candidate)
    return _duplicate_response(db, candidate)


@router.post(
    "/duplicate-candidates/{candidate_id}/merge",
    response_model=DuplicateMergeResponse,
)
def merge_ci_duplicate(
    candidate_id: str,
    payload: DuplicateMergeRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DuplicateMergeResponse:
    require_permissions(current_user, "assets.update")
    scoped = _candidate_or_404(db, candidate_id, current_user)
    try:
        candidate, merge_summary = merge_duplicate_candidate(
            db,
            candidate_id=scoped.id,
            expected_version=payload.expected_version,
            expected_primary_version=payload.expected_primary_version,
            expected_duplicate_version=payload.expected_duplicate_version,
            actor_id=current_user.id,
            reason=payload.reason,
        )
    except ReconciliationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="ci_duplicate_merged",
        entity_type="ci_duplicate_candidate",
        entity_id=candidate.id,
        tenant_id=candidate.tenant_id,
        metadata={
            "primary_ci_id": candidate.primary_ci_id,
            "duplicate_ci_id": candidate.duplicate_ci_id,
            "reason": payload.reason.strip(),
            "merge_summary": merge_summary,
            "version": candidate.version,
        },
    )
    db.commit()
    db.refresh(candidate)
    return DuplicateMergeResponse(
        candidate=_duplicate_response(db, candidate),
        merge_summary=merge_summary,
    )


@router.get(
    "/items/{ci_id}/field-ownership",
    response_model=list[FieldOwnershipResponse],
)
def list_ci_field_ownership(
    ci_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FieldOwnershipResponse]:
    require_permissions(current_user, "assets.read")
    asset = db.get(Asset, ci_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Configuration item not found")
    if not asset.tenant_id:
        raise HTTPException(status_code=409, detail="Configuration item has no tenant")
    _check_scope(
        current_user,
        asset.tenant_id,
        message="Configuration item not found",
    )
    rows = db.scalars(
        select(CMDBFieldOwnership)
        .where(CMDBFieldOwnership.asset_id == asset.id)
        .order_by(CMDBFieldOwnership.field_name)
    ).all()
    source_ids = {row.source_id for row in rows}
    sources = {
        source.id: source
        for source in db.scalars(
            select(CMDBSource).where(CMDBSource.id.in_(source_ids))
        ).all()
    } if source_ids else {}
    return [
        FieldOwnershipResponse(
            id=row.id,
            field_name=row.field_name,
            source_id=row.source_id,
            source_code=sources[row.source_id].code,
            source_name=sources[row.source_id].name,
            external_id=row.external_id,
            source_priority=row.source_priority,
            value_hash=row.value_hash,
            observed_at=row.observed_at,
            updated_at=row.updated_at,
        )
        for row in rows
        if row.source_id in sources
    ]


@router.get("/source-health")
def get_cmdb_source_health(
    tenant_id: str | None = None,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    require_permissions(current_user, "assets.read")
    statement = select(CMDBSource)
    if not is_saas_root(current_user):
        statement = statement.where(CMDBSource.tenant_id == current_user.tenant_id)
    elif tenant_id:
        statement = statement.where(CMDBSource.tenant_id == tenant_id)
    sources = db.scalars(statement).all()
    stale = sum(
        (age := _age_seconds(source.last_success_at)) is None
        or age > source.stale_after_hours * 3600
        for source in sources
        if source.status == "ACTIVE"
    )
    open_duplicates_statement = select(func.count(CIDuplicateCandidate.id)).where(
        CIDuplicateCandidate.status == "OPEN"
    )
    if not is_saas_root(current_user):
        open_duplicates_statement = open_duplicates_statement.where(
            CIDuplicateCandidate.tenant_id == current_user.tenant_id
        )
    elif tenant_id:
        open_duplicates_statement = open_duplicates_statement.where(
            CIDuplicateCandidate.tenant_id == tenant_id
        )
    return {
        "total_sources": len(sources),
        "active_sources": sum(source.status == "ACTIVE" for source in sources),
        "stale_sources": stale,
        "open_duplicate_candidates": (
            db.scalar(open_duplicates_statement) or 0
        ),
    }
