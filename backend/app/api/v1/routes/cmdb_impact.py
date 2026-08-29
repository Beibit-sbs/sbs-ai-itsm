from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import struct
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.cmdb_impact import CMDBImpactAssessment
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.user import User
from app.services.audit import log_audit
from app.services.cmdb_impact import (
    build_impact_result,
    graph_revision_hash,
    resolve_entity_roots,
)
from app.services.cmdb_schema import canonical_json
from app.services.rbac import (
    can_read_ticket,
    is_saas_root,
    require_permissions,
)


router = APIRouter(prefix="/cmdb/impact")
EntityType = Literal["TICKET", "PROBLEM", "CHANGE", "RELEASE"]
Direction = Literal["UPSTREAM", "DOWNSTREAM", "BOTH"]


class ImpactPreviewRequest(BaseModel):
    tenant_id: str | None = None
    root_ci_ids: list[str] = Field(min_length=1, max_length=100)
    direction: Direction = "UPSTREAM"
    max_depth: int = Field(default=5, ge=1, le=12)


class ImpactAssessmentRequest(BaseModel):
    tenant_id: str | None = None
    root_ci_ids: list[str] = Field(default_factory=list, max_length=100)
    direction: Direction = "UPSTREAM"
    max_depth: int = Field(default=5, ge=1, le=12)
    expected_entity_version: int | None = Field(default=None, ge=1)


class ImpactNodeResponse(BaseModel):
    id: str
    asset_tag: str
    name: str
    ci_class_id: str | None
    ci_class_code: str | None
    ci_class_name: str | None
    lifecycle_status: str
    criticality: str
    environment: str
    support_group: str | None
    depth: int
    is_root: bool


class ImpactEdgeResponse(BaseModel):
    id: str
    relationship_type_id: str
    relationship_type_code: str
    relationship_type_name: str
    forward_label: str
    reverse_label: str
    source_ci_id: str
    target_ci_id: str


class ChangeCollisionResponse(BaseModel):
    change_id: str
    change_number: str
    title: str
    status: str
    risk_level: str
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    window_overlap: bool
    collision_type: str
    shared_ci_ids: list[str]
    shared_asset_tags: list[str]


class ImpactAnalysisResponse(BaseModel):
    tenant_id: str
    root_ci_ids: list[str]
    direction: str
    max_depth: int
    graph_hash: str
    nodes: list[ImpactNodeResponse]
    edges: list[ImpactEdgeResponse]
    truncated: bool
    cache_hits: int
    computed_at: datetime
    entity_type: str | None
    entity_id: str | None
    severity: str
    severity_reasons: list[str]
    customer_impact: bool
    impacted_ci_count: int
    impacted_service_count: int
    critical_ci_count: int
    production_ci_count: int
    services: list[ImpactNodeResponse]
    critical_cis: list[ImpactNodeResponse]
    collisions: list[ChangeCollisionResponse]
    collision_count: int


class ImpactAssessmentResponse(BaseModel):
    id: str
    tenant_id: str
    entity_type: str
    entity_id: str
    entity_version: int | None
    root_ci_ids: list[str]
    direction: str
    max_depth: int
    graph_hash: str
    severity: str
    impacted_ci_count: int
    impacted_service_count: int
    critical_ci_count: int
    collision_count: int
    snapshot_hash: str
    status: str
    created_by_id: str | None
    created_at: datetime
    graph_is_stale: bool
    entity_is_stale: bool
    integrity_valid: bool
    is_stale: bool
    snapshot: ImpactAnalysisResponse


_ENTITY_PERMISSIONS = {
    "TICKET": "tickets.read",
    "PROBLEM": "problems.read",
    "CHANGE": "changes.read",
    "RELEASE": "assets.read",
}


def _clean_ids(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in values if item.strip()))


def _tenant_scope(
    db: Session,
    current_user: AuthUserResponse,
    requested_tenant_id: str | None,
) -> str:
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        if (
            requested_tenant_id
            and requested_tenant_id != current_user.tenant_id
        ):
            raise HTTPException(status_code=404, detail="Tenant not found")
        return current_user.tenant_id
    if not requested_tenant_id:
        raise HTTPException(
            status_code=422,
            detail="tenant_id is required for SaaS Root impact analysis",
        )
    if db.get(Tenant, requested_tenant_id) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested_tenant_id


def _require_entity_permission(
    current_user: AuthUserResponse,
    entity_type: str,
) -> None:
    require_permissions(
        current_user,
        "assets.read",
        _ENTITY_PERMISSIONS[entity_type],
    )


def _assert_entity_access(
    db: Session,
    current_user: AuthUserResponse,
    *,
    entity_type: str,
    entity_id: str,
    tenant_id: str,
) -> None:
    if (
        not is_saas_root(current_user)
        and current_user.tenant_id != tenant_id
    ):
        raise HTTPException(status_code=404, detail="Entity not found")
    if entity_type == "TICKET":
        ticket = db.get(Ticket, entity_id)
        if ticket is None or not can_read_ticket(current_user, ticket):
            raise HTTPException(status_code=404, detail="Entity not found")


def _entity_context(
    db: Session,
    current_user: AuthUserResponse,
    *,
    entity_type: str,
    entity_id: str,
    requested_tenant_id: str | None,
    lock: bool,
) -> tuple[str, list[str], int | None]:
    _require_entity_permission(current_user, entity_type)
    if entity_type == "RELEASE":
        return _tenant_scope(db, current_user, requested_tenant_id), [], None
    try:
        tenant_id, roots, entity_version = resolve_entity_roots(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            lock=lock,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_entity_access(
        db,
        current_user,
        entity_type=entity_type,
        entity_id=entity_id,
        tenant_id=tenant_id,
    )
    return tenant_id, roots, entity_version


def _lock_assessment_scope(
    db: Session,
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    digest = hashlib.sha256(
        f"{tenant_id}:{entity_type}:{entity_id}".encode()
    ).digest()[:8]
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": struct.unpack(">q", digest)[0]},
    )


def _current_entity_version(
    db: Session,
    assessment: CMDBImpactAssessment,
) -> tuple[bool, int | None]:
    if assessment.entity_type == "RELEASE":
        return True, None
    try:
        tenant_id, _, version = resolve_entity_roots(
            db,
            entity_type=assessment.entity_type,
            entity_id=assessment.entity_id,
        )
    except ValueError:
        return False, None
    return tenant_id == assessment.tenant_id, version


def _assessment_response(
    db: Session,
    assessment: CMDBImpactAssessment,
    *,
    current_graph_hash: str | None = None,
) -> ImpactAssessmentResponse:
    snapshot = json.loads(assessment.snapshot_json)
    if not isinstance(snapshot, dict):
        raise HTTPException(
            status_code=500,
            detail="Stored impact assessment is invalid",
        )
    current_hash = current_graph_hash or graph_revision_hash(
        db,
        assessment.tenant_id,
    )
    entity_available, current_version = _current_entity_version(
        db,
        assessment,
    )
    graph_is_stale = current_hash != assessment.graph_hash
    entity_is_stale = (
        not entity_available
        or (
            assessment.entity_version is not None
            and current_version != assessment.entity_version
        )
    )
    calculated_hash = hashlib.sha256(
        assessment.snapshot_json.encode()
    ).hexdigest()
    integrity_valid = calculated_hash == assessment.snapshot_hash
    try:
        roots = json.loads(assessment.root_ci_ids_json)
    except json.JSONDecodeError:
        roots = []
    return ImpactAssessmentResponse(
        id=assessment.id,
        tenant_id=assessment.tenant_id,
        entity_type=assessment.entity_type,
        entity_id=assessment.entity_id,
        entity_version=assessment.entity_version,
        root_ci_ids=roots if isinstance(roots, list) else [],
        direction=assessment.direction,
        max_depth=assessment.max_depth,
        graph_hash=assessment.graph_hash,
        severity=assessment.severity,
        impacted_ci_count=assessment.impacted_ci_count,
        impacted_service_count=assessment.impacted_service_count,
        critical_ci_count=assessment.critical_ci_count,
        collision_count=assessment.collision_count,
        snapshot_hash=assessment.snapshot_hash,
        status=assessment.status,
        created_by_id=assessment.created_by_id,
        created_at=assessment.created_at,
        graph_is_stale=graph_is_stale,
        entity_is_stale=entity_is_stale,
        integrity_valid=integrity_valid,
        is_stale=graph_is_stale or entity_is_stale or not integrity_valid,
        snapshot=ImpactAnalysisResponse.model_validate(snapshot),
    )


def _assessment_or_404(
    db: Session,
    current_user: AuthUserResponse,
    *,
    entity_type: str,
    entity_id: str,
    status_value: str | None = None,
) -> CMDBImpactAssessment:
    statement = select(CMDBImpactAssessment).where(
        CMDBImpactAssessment.entity_type == entity_type,
        CMDBImpactAssessment.entity_id == entity_id,
    )
    if status_value:
        statement = statement.where(
            CMDBImpactAssessment.status == status_value
        )
    if not is_saas_root(current_user):
        statement = statement.where(
            CMDBImpactAssessment.tenant_id == current_user.tenant_id
        )
    assessment = db.scalar(
        statement.order_by(CMDBImpactAssessment.created_at.desc())
    )
    if assessment is None:
        raise HTTPException(status_code=404, detail="Impact assessment not found")
    return assessment


@router.post("/preview", response_model=ImpactAnalysisResponse)
def preview_impact(
    payload: ImpactPreviewRequest,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ImpactAnalysisResponse:
    require_permissions(current_user, "assets.read")
    tenant_id = _tenant_scope(db, current_user, payload.tenant_id)
    try:
        result = build_impact_result(
            db,
            tenant_id=tenant_id,
            root_ci_ids=_clean_ids(payload.root_ci_ids),
            direction=payload.direction,
            max_depth=payload.max_depth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return ImpactAnalysisResponse.model_validate(result)


@router.post(
    "/assessments/{entity_type}/{entity_id}",
    response_model=ImpactAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_impact_assessment(
    entity_type: EntityType,
    entity_id: str,
    payload: ImpactAssessmentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ImpactAssessmentResponse:
    tenant_id, linked_roots, entity_version = _entity_context(
        db,
        current_user,
        entity_type=entity_type,
        entity_id=entity_id,
        requested_tenant_id=payload.tenant_id,
        lock=True,
    )
    if entity_version is not None:
        if payload.expected_entity_version is None:
            raise HTTPException(
                status_code=422,
                detail="expected_entity_version is required",
            )
        if payload.expected_entity_version != entity_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Entity was updated by another operator; "
                    f"current version is {entity_version}"
                ),
            )
    roots = _clean_ids([*linked_roots, *payload.root_ci_ids])
    if not roots:
        raise HTTPException(
            status_code=422,
            detail="At least one linked or explicit root CI is required",
        )
    _lock_assessment_scope(
        db,
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    try:
        result = build_impact_result(
            db,
            tenant_id=tenant_id,
            root_ci_ids=roots,
            direction=payload.direction,
            max_depth=payload.max_depth,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    current_rows = db.scalars(
        select(CMDBImpactAssessment).where(
            CMDBImpactAssessment.tenant_id == tenant_id,
            CMDBImpactAssessment.entity_type == entity_type,
            CMDBImpactAssessment.entity_id == entity_id,
            CMDBImpactAssessment.status == "CURRENT",
        )
    ).all()
    for current in current_rows:
        current.status = "SUPERSEDED"
    if current_rows:
        db.flush()

    snapshot_json = canonical_json(result)
    assessment = CMDBImpactAssessment(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_version=entity_version,
        root_ci_ids_json=canonical_json(roots),
        direction=payload.direction,
        max_depth=payload.max_depth,
        graph_hash=str(result["graph_hash"]),
        severity=str(result["severity"]),
        impacted_ci_count=int(result["impacted_ci_count"]),
        impacted_service_count=int(result["impacted_service_count"]),
        critical_ci_count=int(result["critical_ci_count"]),
        collision_count=int(result["collision_count"]),
        snapshot_json=snapshot_json,
        snapshot_hash=hashlib.sha256(snapshot_json.encode()).hexdigest(),
        status="CURRENT",
        created_by_id=current_user.id,
        created_at=datetime.now(UTC),
    )
    db.add(assessment)
    log_audit(
        db,
        action="cmdb.impact.assessed",
        entity_type="cmdb_impact_assessment",
        entity_id=assessment.id,
        actor_user=db.get(User, current_user.id),
        actor_email=current_user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={
            "subject_type": entity_type,
            "subject_id": entity_id,
            "entity_version": entity_version,
            "root_ci_ids": roots,
            "graph_hash": result["graph_hash"],
            "severity": result["severity"],
            "impacted_ci_count": result["impacted_ci_count"],
            "collision_count": result["collision_count"],
        },
    )
    db.commit()
    db.refresh(assessment)
    return _assessment_response(
        db,
        assessment,
        current_graph_hash=str(result["graph_hash"]),
    )


@router.get(
    "/assessments/{entity_type}/{entity_id}/latest",
    response_model=ImpactAssessmentResponse,
)
def latest_impact_assessment(
    entity_type: EntityType,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> ImpactAssessmentResponse:
    _require_entity_permission(current_user, entity_type)
    assessment = _assessment_or_404(
        db,
        current_user,
        entity_type=entity_type,
        entity_id=entity_id,
        status_value="CURRENT",
    )
    return _assessment_response(db, assessment)


@router.get(
    "/assessments/{entity_type}/{entity_id}",
    response_model=list[ImpactAssessmentResponse],
)
def impact_assessment_history(
    entity_type: EntityType,
    entity_id: str,
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[ImpactAssessmentResponse]:
    _require_entity_permission(current_user, entity_type)
    reference = _assessment_or_404(
        db,
        current_user,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    statement = select(CMDBImpactAssessment).where(
        CMDBImpactAssessment.tenant_id == reference.tenant_id,
        CMDBImpactAssessment.entity_type == entity_type,
        CMDBImpactAssessment.entity_id == entity_id,
    )
    rows = db.scalars(
        statement.order_by(CMDBImpactAssessment.created_at.desc()).limit(limit)
    ).all()
    current_hash = graph_revision_hash(db, reference.tenant_id)
    return [
        _assessment_response(
            db,
            assessment,
            current_graph_hash=current_hash,
        )
        for assessment in rows
    ]
