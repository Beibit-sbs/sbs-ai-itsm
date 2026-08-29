from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.change_request import ChangeRequest
from app.models.release_governance import (
    ReleaseChangeLink,
    ReleaseDecision,
    ReleaseDependency,
    ReleaseDeployment,
    ReleaseEnvironment,
    ReleaseGate,
    ReleasePackage,
    ReleaseRecord,
    ReleaseTimeline,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.rbac import is_saas_root, require_permissions
from app.services.release_governance import (
    ACTIVE_DEPLOYMENT_STATUSES,
    AUTOMATED_GATE_TYPES,
    ELIGIBLE_CHANGE_STATUSES,
    add_timeline,
    aware,
    default_gates,
    dependency_would_cycle,
    now_utc,
    previous_environment_ready,
    release_metrics,
    release_readiness,
)


router = APIRouter(prefix="/releases")

EDITABLE_RELEASE_STATUSES = {"DRAFT", "PLANNING"}
TERMINAL_RELEASE_STATUSES = {"RELEASED", "FAILED", "ROLLED_BACK", "CANCELLED"}


class ReleaseCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=3, max_length=255)
    version_name: str = Field(min_length=1, max_length=100)
    release_type: Literal["MAJOR", "MINOR", "PATCH", "HOTFIX"] = "MINOR"
    service_name: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=10, max_length=20_000)
    scope: str = Field(min_length=10, max_length=20_000)
    release_notes: str | None = Field(default=None, max_length=20_000)
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    target_release_at: datetime
    window_start_at: datetime | None = None
    window_end_at: datetime | None = None
    validation_plan: str = Field(min_length=10, max_length=20_000)
    rollback_plan: str = Field(min_length=10, max_length=20_000)
    communication_plan: str = Field(min_length=10, max_length=20_000)
    owner_id: str | None = None


class ReleaseUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=3, max_length=255)
    version_name: str | None = Field(default=None, min_length=1, max_length=100)
    release_type: Literal["MAJOR", "MINOR", "PATCH", "HOTFIX"] | None = None
    service_name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, min_length=10, max_length=20_000)
    scope: str | None = Field(default=None, min_length=10, max_length=20_000)
    release_notes: str | None = Field(default=None, max_length=20_000)
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
    target_release_at: datetime | None = None
    window_start_at: datetime | None = None
    window_end_at: datetime | None = None
    validation_plan: str | None = Field(
        default=None,
        min_length=10,
        max_length=20_000,
    )
    rollback_plan: str | None = Field(
        default=None,
        min_length=10,
        max_length=20_000,
    )
    communication_plan: str | None = Field(
        default=None,
        min_length=10,
        max_length=20_000,
    )
    owner_id: str | None = None


class ReleaseTransition(BaseModel):
    expected_version: int = Field(ge=1)
    action: Literal["SUBMIT", "MARK_READY", "PUBLISH", "CANCEL"]
    comment: str = Field(min_length=3, max_length=10_000)


class ChangeLinkCreate(BaseModel):
    change_id: str
    sequence: int = Field(ge=1, le=10_000)
    is_mandatory: bool = True
    notes: str | None = Field(default=None, max_length=5_000)


class PackageCreate(BaseModel):
    component_name: str = Field(min_length=2, max_length=200)
    package_type: Literal[
        "APPLICATION",
        "DATABASE",
        "CONFIGURATION",
        "INFRASTRUCTURE",
        "DOCUMENTATION",
    ]
    version_name: str = Field(min_length=1, max_length=100)
    artifact_uri: str = Field(min_length=3, max_length=1_000)
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    build_reference: str | None = Field(default=None, max_length=500)
    dependencies: list[dict[str, object]] = Field(
        default_factory=list,
        max_length=100,
    )


class PackageUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    verification_status: Literal["PENDING", "VERIFIED", "FAILED"]
    evidence: str | None = Field(default=None, max_length=20_000)


class DependencyCreate(BaseModel):
    dependency_release_id: str
    dependency_type: Literal["REQUIRES", "BLOCKS", "FOLLOWS"] = "REQUIRES"
    notes: str | None = Field(default=None, max_length=5_000)


class EnvironmentCreate(BaseModel):
    tenant_id: str | None = None
    code: str = Field(
        min_length=2,
        max_length=50,
        pattern=r"^[A-Z0-9][A-Z0-9_-]+$",
    )
    name: str = Field(min_length=2, max_length=120)
    environment_type: Literal[
        "DEVELOPMENT",
        "TEST",
        "STAGING",
        "PRODUCTION",
        "DR",
    ]
    promotion_order: int = Field(ge=1, le=100)
    requires_approval: bool = False
    requires_smoke_test: bool = True
    is_production: bool = False
    is_active: bool = True


class EnvironmentUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=120)
    promotion_order: int | None = Field(default=None, ge=1, le=100)
    requires_approval: bool | None = None
    requires_smoke_test: bool | None = None
    is_active: bool | None = None


class GateCreate(BaseModel):
    code: str = Field(
        min_length=2,
        max_length=80,
        pattern=r"^[A-Z0-9][A-Z0-9_-]+$",
    )
    name: str = Field(min_length=3, max_length=200)
    gate_type: Literal["TEST", "SECURITY", "BUSINESS", "MANUAL"]
    is_mandatory: bool = True


class GateDecision(BaseModel):
    expected_version: int = Field(ge=1)
    status: Literal["PASSED", "FAILED", "WAIVED"]
    evidence: str = Field(min_length=3, max_length=20_000)
    comment: str = Field(min_length=3, max_length=5_000)


class GoNoGoDecision(BaseModel):
    expected_version: int = Field(ge=1)
    decision: Literal["GO", "NO_GO", "CONDITIONAL"]
    comment: str = Field(min_length=3, max_length=10_000)
    conditions: list[dict[str, object]] = Field(default_factory=list, max_length=100)


class DeploymentCreate(BaseModel):
    environment_id: str
    scheduled_at: datetime
    deployment_reference: str | None = Field(default=None, max_length=1_000)


class DeploymentAction(BaseModel):
    expected_version: int = Field(ge=1)
    action: Literal["START", "VALIDATE", "SUCCEED", "FAIL", "ROLLBACK", "CANCEL"]
    deployment_evidence: str | None = Field(default=None, max_length=20_000)
    validation_evidence: str | None = Field(default=None, max_length=20_000)
    smoke_test_status: Literal["PENDING", "PASSED", "FAILED"] | None = None
    failure_reason: str | None = Field(default=None, max_length=20_000)
    rollback_evidence: str | None = Field(default=None, max_length=20_000)


def _tenant_id(
    db: Session,
    current_user: AuthUserResponse,
    requested: str | None = None,
    *,
    required_for_root: bool = False,
) -> str | None:
    if is_saas_root(current_user):
        if required_for_root and not requested:
            raise HTTPException(status_code=422, detail="tenant_id is required")
        if requested and db.get(Tenant, requested) is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return requested
    if requested and requested != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not current_user.tenant_id:
        raise HTTPException(status_code=422, detail="Tenant context is required")
    return current_user.tenant_id


def _actor(db: Session, current_user: AuthUserResponse) -> User:
    user = db.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=403, detail="User account not found")
    return user


def _release(
    db: Session,
    release_id: str,
    current_user: AuthUserResponse,
) -> ReleaseRecord:
    item = db.get(ReleaseRecord, release_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if not is_saas_root(current_user) and item.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Release not found")
    return item


def _version(current: int, expected: int, entity: str) -> None:
    if current != expected:
        raise HTTPException(
            status_code=409,
            detail=f"{entity} version conflict; current version is {current}",
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
    metadata: dict[str, object] | None = None,
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


def _commit(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc


def _validate_window(
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> None:
    if (starts_at is None) != (ends_at is None):
        raise HTTPException(
            status_code=422,
            detail="Both window_start_at and window_end_at are required",
        )
    if starts_at and ends_at and aware(ends_at) <= aware(starts_at):
        raise HTTPException(
            status_code=422,
            detail="Release window end must be after start",
        )


def _environment_response(item: ReleaseEnvironment) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "code": item.code,
        "name": item.name,
        "environment_type": item.environment_type,
        "promotion_order": item.promotion_order,
        "requires_approval": item.requires_approval,
        "requires_smoke_test": item.requires_smoke_test,
        "is_production": item.is_production,
        "is_active": item.is_active,
        "current_version": item.current_version,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _package_response(item: ReleasePackage) -> dict[str, Any]:
    return {
        "id": item.id,
        "component_name": item.component_name,
        "package_type": item.package_type,
        "version_name": item.version_name,
        "artifact_uri": item.artifact_uri,
        "checksum_sha256": item.checksum_sha256,
        "build_reference": item.build_reference,
        "dependencies": item.dependencies_json,
        "verification_status": item.verification_status,
        "verification_evidence": item.verification_evidence,
        "verified_at": item.verified_at,
        "version": item.version,
        "created_at": item.created_at,
    }


def _deployment_response(
    item: ReleaseDeployment,
    environment: ReleaseEnvironment,
) -> dict[str, Any]:
    return {
        "id": item.id,
        "release_id": item.release_id,
        "environment": _environment_response(environment),
        "status": item.status,
        "scheduled_at": item.scheduled_at,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "deployed_version": item.deployed_version,
        "previous_version": item.previous_version,
        "deployment_reference": item.deployment_reference,
        "deployment_evidence": item.deployment_evidence,
        "validation_evidence": item.validation_evidence,
        "smoke_test_status": item.smoke_test_status,
        "rollback_evidence": item.rollback_evidence,
        "failure_reason": item.failure_reason,
        "operator_name": item.operator_name,
        "version": item.version,
    }


def _base_response(
    db: Session,
    item: ReleaseRecord,
) -> dict[str, Any]:
    counts = {
        "change_count": int(
            db.scalar(
                select(func.count(ReleaseChangeLink.id)).where(
                    ReleaseChangeLink.release_id == item.id
                )
            )
            or 0
        ),
        "package_count": int(
            db.scalar(
                select(func.count(ReleasePackage.id)).where(
                    ReleasePackage.release_id == item.id
                )
            )
            or 0
        ),
        "deployment_count": int(
            db.scalar(
                select(func.count(ReleaseDeployment.id)).where(
                    ReleaseDeployment.release_id == item.id
                )
            )
            or 0
        ),
    }
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "release_number": item.release_number,
        "name": item.name,
        "version_name": item.version_name,
        "release_type": item.release_type,
        "status": item.status,
        "service_name": item.service_name,
        "description": item.description,
        "scope": item.scope,
        "release_notes": item.release_notes,
        "risk_level": item.risk_level,
        "target_release_at": item.target_release_at,
        "window_start_at": item.window_start_at,
        "window_end_at": item.window_end_at,
        "validation_plan": item.validation_plan,
        "rollback_plan": item.rollback_plan,
        "communication_plan": item.communication_plan,
        "owner_id": item.owner_id,
        "owner_name": item.owner_name,
        "go_no_go_status": item.go_no_go_status,
        "approved_decision_id": item.approved_decision_id,
        "actual_released_at": item.actual_released_at,
        "completed_at": item.completed_at,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        **counts,
    }


def _detail_response(db: Session, item: ReleaseRecord) -> dict[str, Any]:
    response = _base_response(db, item)
    change_rows = db.execute(
        select(ReleaseChangeLink, ChangeRequest)
        .join(ChangeRequest, ChangeRequest.id == ReleaseChangeLink.change_id)
        .where(ReleaseChangeLink.release_id == item.id)
        .order_by(ReleaseChangeLink.sequence)
    ).all()
    response["changes"] = [
        {
            "link_id": link.id,
            "sequence": link.sequence,
            "is_mandatory": link.is_mandatory,
            "notes": link.notes,
            "change_id": change.id,
            "change_number": change.change_number,
            "title": change.title,
            "status": change.status,
            "risk_level": change.risk_level,
            "planned_start_at": change.planned_start_at,
            "planned_end_at": change.planned_end_at,
        }
        for link, change in change_rows
    ]
    packages = db.scalars(
        select(ReleasePackage)
        .where(ReleasePackage.release_id == item.id)
        .order_by(ReleasePackage.component_name)
    ).all()
    response["packages"] = [_package_response(package) for package in packages]
    dependency_rows = db.execute(
        select(ReleaseDependency, ReleaseRecord)
        .join(
            ReleaseRecord,
            ReleaseRecord.id == ReleaseDependency.dependency_release_id,
        )
        .where(ReleaseDependency.release_id == item.id)
        .order_by(ReleaseRecord.target_release_at)
    ).all()
    response["dependencies"] = [
        {
            "id": dependency.id,
            "dependency_type": dependency.dependency_type,
            "notes": dependency.notes,
            "release_id": target.id,
            "release_number": target.release_number,
            "name": target.name,
            "version_name": target.version_name,
            "status": target.status,
        }
        for dependency, target in dependency_rows
    ]
    deployment_rows = db.execute(
        select(ReleaseDeployment, ReleaseEnvironment)
        .join(
            ReleaseEnvironment,
            ReleaseEnvironment.id == ReleaseDeployment.environment_id,
        )
        .where(ReleaseDeployment.release_id == item.id)
        .order_by(ReleaseEnvironment.promotion_order)
    ).all()
    response["deployments"] = [
        _deployment_response(deployment, environment)
        for deployment, environment in deployment_rows
    ]
    decisions = db.scalars(
        select(ReleaseDecision)
        .where(ReleaseDecision.release_id == item.id)
        .order_by(ReleaseDecision.created_at.desc())
    ).all()
    response["decisions"] = [
        {
            "id": decision.id,
            "decision": decision.decision,
            "comment": decision.comment,
            "conditions": decision.conditions_json,
            "readiness_snapshot": decision.readiness_snapshot_json,
            "decided_by_name": decision.decided_by_name,
            "created_at": decision.created_at,
        }
        for decision in decisions
    ]
    response["readiness"] = release_readiness(db, item)
    return response


@router.get("/environments")
def list_environments(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "changes.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(ReleaseEnvironment)
    if scoped_tenant:
        statement = statement.where(ReleaseEnvironment.tenant_id == scoped_tenant)
    items = db.scalars(
        statement.order_by(
            ReleaseEnvironment.tenant_id,
            ReleaseEnvironment.promotion_order,
        )
    ).all()
    return [_environment_response(item) for item in items]


@router.post(
    "/environments",
    status_code=status.HTTP_201_CREATED,
)
def create_environment(
    payload: EnvironmentCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    tenant_id = _tenant_id(
        db,
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    assert tenant_id is not None
    if payload.is_production and payload.environment_type != "PRODUCTION":
        raise HTTPException(
            status_code=422,
            detail="Production target must use the PRODUCTION environment type",
        )
    if payload.environment_type == "PRODUCTION" and not payload.is_production:
        raise HTTPException(
            status_code=422,
            detail="PRODUCTION environment type must be marked production",
        )
    item = ReleaseEnvironment(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=payload.code.upper(),
        name=payload.name,
        environment_type=payload.environment_type,
        promotion_order=payload.promotion_order,
        requires_approval=payload.requires_approval,
        requires_smoke_test=payload.requires_smoke_test,
        is_production=payload.is_production,
        is_active=payload.is_active,
        version=1,
        created_by_id=current_user.id,
    )
    db.add(item)
    _audit(
        db,
        request,
        current_user,
        action="release.environment_created",
        entity_type="release_environment",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"code": item.code},
    )
    _commit(db, "Environment code or promotion order already exists")
    db.refresh(item)
    return _environment_response(item)


@router.patch("/environments/{environment_id}")
def update_environment(
    environment_id: str,
    payload: EnvironmentUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    item = db.get(ReleaseEnvironment, environment_id)
    if item is None or (
        not is_saas_root(current_user) and item.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Environment not found")
    _version(item.version, payload.expected_version, "Environment")
    for field, value in payload.model_dump(
        exclude_unset=True,
        exclude={"expected_version"},
    ).items():
        setattr(item, field, value)
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="release.environment_updated",
        entity_type="release_environment",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"version": item.version},
    )
    _commit(db, "Environment promotion order already exists")
    db.refresh(item)
    return _environment_response(item)


@router.get("/calendar")
def release_calendar(
    starts_at: datetime,
    ends_at: datetime,
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.read")
    if aware(ends_at) <= aware(starts_at):
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
    if aware(ends_at) - aware(starts_at) > timedelta(days=366):
        raise HTTPException(status_code=422, detail="Calendar range is limited to 366 days")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    release_statement = select(ReleaseRecord).where(
        ReleaseRecord.target_release_at >= starts_at,
        ReleaseRecord.target_release_at < ends_at,
    )
    deployment_statement = (
        select(ReleaseDeployment, ReleaseEnvironment, ReleaseRecord)
        .join(
            ReleaseEnvironment,
            ReleaseEnvironment.id == ReleaseDeployment.environment_id,
        )
        .join(ReleaseRecord, ReleaseRecord.id == ReleaseDeployment.release_id)
        .where(
            ReleaseDeployment.scheduled_at >= starts_at,
            ReleaseDeployment.scheduled_at < ends_at,
        )
    )
    if scoped_tenant:
        release_statement = release_statement.where(
            ReleaseRecord.tenant_id == scoped_tenant
        )
        deployment_statement = deployment_statement.where(
            ReleaseDeployment.tenant_id == scoped_tenant
        )
    releases = db.scalars(
        release_statement.order_by(ReleaseRecord.target_release_at)
    ).all()
    deployments = db.execute(
        deployment_statement.order_by(ReleaseDeployment.scheduled_at)
    ).all()
    return {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "releases": [
            {
                "id": item.id,
                "release_number": item.release_number,
                "name": item.name,
                "version_name": item.version_name,
                "service_name": item.service_name,
                "status": item.status,
                "risk_level": item.risk_level,
                "target_release_at": item.target_release_at,
            }
            for item in releases
        ],
        "deployments": [
            {
                "id": deployment.id,
                "release_id": release.id,
                "release_number": release.release_number,
                "release_name": release.name,
                "environment_name": environment.name,
                "is_production": environment.is_production,
                "status": deployment.status,
                "scheduled_at": deployment.scheduled_at,
            }
            for deployment, environment, release in deployments
        ],
    }


@router.get("/analytics")
def analytics(
    days: int = Query(default=90, ge=7, le=730),
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    ends_at = now_utc()
    return release_metrics(
        db,
        scoped_tenant,
        starts_at=ends_at - timedelta(days=days),
        ends_at=ends_at,
    )


@router.get("")
def list_releases(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    release_status: str | None = Query(default=None, alias="status"),
    service_name: str | None = Query(default=None, max_length=200),
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    filters = []
    if scoped_tenant:
        filters.append(ReleaseRecord.tenant_id == scoped_tenant)
    if release_status:
        filters.append(ReleaseRecord.status == release_status.upper())
    if service_name:
        filters.append(ReleaseRecord.service_name == service_name)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                ReleaseRecord.release_number.ilike(pattern),
                ReleaseRecord.name.ilike(pattern),
                ReleaseRecord.version_name.ilike(pattern),
                ReleaseRecord.service_name.ilike(pattern),
            )
        )
    total = int(
        db.scalar(select(func.count(ReleaseRecord.id)).where(*filters)) or 0
    )
    items = db.scalars(
        select(ReleaseRecord)
        .where(*filters)
        .order_by(ReleaseRecord.target_release_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_base_response(db, item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_release(
    payload: ReleaseCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.create")
    tenant_id = _tenant_id(
        db,
        current_user,
        payload.tenant_id,
        required_for_root=True,
    )
    assert tenant_id is not None
    _validate_window(payload.window_start_at, payload.window_end_at)
    actor = _actor(db, current_user)
    owner = actor
    if payload.owner_id:
        candidate = db.get(User, payload.owner_id)
        if candidate is None or candidate.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Release owner not found")
        owner = candidate
    instant = now_utc()
    item = ReleaseRecord(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        release_number=f"REL-{instant.year}-{uuid.uuid4().hex[:8].upper()}",
        name=payload.name,
        version_name=payload.version_name,
        release_type=payload.release_type,
        status="DRAFT",
        service_name=payload.service_name,
        description=payload.description,
        scope=payload.scope,
        release_notes=payload.release_notes,
        risk_level=payload.risk_level,
        target_release_at=payload.target_release_at,
        window_start_at=payload.window_start_at,
        window_end_at=payload.window_end_at,
        validation_plan=payload.validation_plan,
        rollback_plan=payload.rollback_plan,
        communication_plan=payload.communication_plan,
        owner_id=owner.id,
        owner_name=owner.full_name,
        created_by_id=current_user.id,
        go_no_go_status="PENDING",
        version=1,
    )
    db.add(item)
    db.flush()
    db.add_all(default_gates(item))
    add_timeline(
        db,
        item,
        event_type="CREATED",
        message="Release record created",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        to_status="DRAFT",
    )
    _audit(
        db,
        request,
        current_user,
        action="release.created",
        entity_type="release",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={"release_number": item.release_number},
    )
    _commit(db, "Release version already exists for this service")
    db.refresh(item)
    return _detail_response(db, item)


@router.get("/{release_id}")
def get_release(
    release_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.read")
    return _detail_response(db, _release(db, release_id, current_user))


@router.patch("/{release_id}")
def update_release(
    release_id: str,
    payload: ReleaseUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.update")
    item = _release(db, release_id, current_user)
    if item.status not in EDITABLE_RELEASE_STATUSES:
        raise HTTPException(status_code=409, detail="Release is no longer editable")
    _version(item.version, payload.expected_version, "Release")
    updates = payload.model_dump(
        exclude_unset=True,
        exclude={"expected_version", "owner_id"},
    )
    next_start = updates.get("window_start_at", item.window_start_at)
    next_end = updates.get("window_end_at", item.window_end_at)
    _validate_window(next_start, next_end)
    for field, value in updates.items():
        setattr(item, field, value)
    if "owner_id" in payload.model_fields_set:
        if not payload.owner_id:
            raise HTTPException(status_code=422, detail="Release owner is required")
        owner = db.get(User, payload.owner_id)
        if owner is None or owner.tenant_id != item.tenant_id:
            raise HTTPException(status_code=404, detail="Release owner not found")
        item.owner_id = owner.id
        item.owner_name = owner.full_name
    item.version += 1
    item.updated_at = now_utc()
    add_timeline(
        db,
        item,
        event_type="UPDATED",
        message="Release plan updated",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        metadata={"version": item.version},
    )
    _audit(
        db,
        request,
        current_user,
        action="release.updated",
        entity_type="release",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"version": item.version},
    )
    _commit(db, "Release update conflicts with existing data")
    db.refresh(item)
    return _detail_response(db, item)


@router.get("/{release_id}/readiness")
def readiness(
    release_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.read")
    return release_readiness(db, _release(db, release_id, current_user))


@router.get("/{release_id}/timeline")
def timeline(
    release_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "changes.read")
    item = _release(db, release_id, current_user)
    events = db.scalars(
        select(ReleaseTimeline)
        .where(ReleaseTimeline.release_id == item.id)
        .order_by(ReleaseTimeline.created_at.desc(), ReleaseTimeline.id.desc())
    ).all()
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "message": event.message,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "metadata": event.metadata_json,
            "actor_name": event.actor_name,
            "created_at": event.created_at,
        }
        for event in events
    ]


@router.post(
    "/{release_id}/changes",
    status_code=status.HTTP_201_CREATED,
)
def add_change(
    release_id: str,
    payload: ChangeLinkCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.update")
    item = _release(db, release_id, current_user)
    if item.status not in EDITABLE_RELEASE_STATUSES:
        raise HTTPException(status_code=409, detail="Release scope is frozen")
    change = db.get(ChangeRequest, payload.change_id)
    if change is None or change.tenant_id != item.tenant_id:
        raise HTTPException(status_code=404, detail="Change not found")
    if change.status not in ELIGIBLE_CHANGE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail="Only approved or later-stage changes can enter a release",
        )
    link = ReleaseChangeLink(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        release_id=item.id,
        change_id=change.id,
        sequence=payload.sequence,
        is_mandatory=payload.is_mandatory,
        notes=payload.notes,
        added_by_id=current_user.id,
    )
    db.add(link)
    item.version += 1
    add_timeline(
        db,
        item,
        event_type="CHANGE_LINKED",
        message=f"{change.change_number} added to the release train",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        metadata={"change_id": change.id, "sequence": payload.sequence},
    )
    _audit(
        db,
        request,
        current_user,
        action="release.change_linked",
        entity_type="release",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"change_id": change.id},
    )
    _commit(db, "Change or sequence is already present in this release")
    return _detail_response(db, item)


@router.delete("/{release_id}/changes/{link_id}")
def remove_change(
    release_id: str,
    link_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.update")
    item = _release(db, release_id, current_user)
    if item.status not in EDITABLE_RELEASE_STATUSES:
        raise HTTPException(status_code=409, detail="Release scope is frozen")
    link = db.get(ReleaseChangeLink, link_id)
    if link is None or link.release_id != item.id:
        raise HTTPException(status_code=404, detail="Release change link not found")
    db.delete(link)
    item.version += 1
    add_timeline(
        db,
        item,
        event_type="CHANGE_REMOVED",
        message="Change removed from the release train",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        metadata={"change_id": link.change_id},
    )
    _audit(
        db,
        request,
        current_user,
        action="release.change_removed",
        entity_type="release",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"change_id": link.change_id},
    )
    db.commit()
    return _detail_response(db, item)


@router.post(
    "/{release_id}/packages",
    status_code=status.HTTP_201_CREATED,
)
def add_package(
    release_id: str,
    payload: PackageCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.update")
    item = _release(db, release_id, current_user)
    if item.status not in EDITABLE_RELEASE_STATUSES:
        raise HTTPException(status_code=409, detail="Release package set is frozen")
    package = ReleasePackage(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        release_id=item.id,
        component_name=payload.component_name,
        package_type=payload.package_type,
        version_name=payload.version_name,
        artifact_uri=payload.artifact_uri,
        checksum_sha256=payload.checksum_sha256.lower(),
        build_reference=payload.build_reference,
        dependencies_json=payload.dependencies,
        verification_status="PENDING",
        version=1,
    )
    db.add(package)
    item.version += 1
    add_timeline(
        db,
        item,
        event_type="PACKAGE_ADDED",
        message=f"Package {package.component_name} added",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        metadata={"package_id": package.id, "checksum": package.checksum_sha256},
    )
    _audit(
        db,
        request,
        current_user,
        action="release.package_added",
        entity_type="release_package",
        entity_id=package.id,
        tenant_id=item.tenant_id,
        metadata={"release_id": item.id},
    )
    _commit(db, "A package for this component already exists")
    return _detail_response(db, item)


@router.patch("/{release_id}/packages/{package_id}")
def verify_package(
    release_id: str,
    package_id: str,
    payload: PackageUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    item = _release(db, release_id, current_user)
    package = db.get(ReleasePackage, package_id)
    if package is None or package.release_id != item.id:
        raise HTTPException(status_code=404, detail="Release package not found")
    _version(package.version, payload.expected_version, "Package")
    if payload.verification_status != "PENDING" and not payload.evidence:
        raise HTTPException(
            status_code=422,
            detail="Package verification requires evidence",
        )
    package.verification_status = payload.verification_status
    package.verification_evidence = payload.evidence
    package.verified_by_id = (
        current_user.id if payload.verification_status != "PENDING" else None
    )
    package.verified_at = (
        now_utc() if payload.verification_status != "PENDING" else None
    )
    package.version += 1
    item.version += 1
    add_timeline(
        db,
        item,
        event_type="PACKAGE_VERIFIED",
        message=(
            f"Package {package.component_name}: "
            f"{package.verification_status.lower()}"
        ),
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        metadata={"package_id": package.id},
    )
    _audit(
        db,
        request,
        current_user,
        action="release.package_verified",
        entity_type="release_package",
        entity_id=package.id,
        tenant_id=item.tenant_id,
        metadata={"status": package.verification_status},
    )
    db.commit()
    return _detail_response(db, item)


@router.post(
    "/{release_id}/dependencies",
    status_code=status.HTTP_201_CREATED,
)
def add_dependency(
    release_id: str,
    payload: DependencyCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.update")
    item = _release(db, release_id, current_user)
    if item.status not in EDITABLE_RELEASE_STATUSES:
        raise HTTPException(status_code=409, detail="Release dependencies are frozen")
    dependency = db.get(ReleaseRecord, payload.dependency_release_id)
    if dependency is None or dependency.tenant_id != item.tenant_id:
        raise HTTPException(status_code=404, detail="Dependency release not found")
    if dependency_would_cycle(
        db,
        release_id=item.id,
        dependency_release_id=dependency.id,
    ):
        raise HTTPException(
            status_code=422,
            detail="Release dependency would create a cycle",
        )
    link = ReleaseDependency(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        release_id=item.id,
        dependency_release_id=dependency.id,
        dependency_type=payload.dependency_type,
        notes=payload.notes,
        created_by_id=current_user.id,
    )
    db.add(link)
    item.version += 1
    add_timeline(
        db,
        item,
        event_type="DEPENDENCY_ADDED",
        message=f"Dependency {dependency.release_number} added",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        metadata={"dependency_release_id": dependency.id},
    )
    _audit(
        db,
        request,
        current_user,
        action="release.dependency_added",
        entity_type="release",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"dependency_release_id": dependency.id},
    )
    _commit(db, "Release dependency already exists")
    return _detail_response(db, item)


@router.delete("/{release_id}/dependencies/{dependency_id}")
def remove_dependency(
    release_id: str,
    dependency_id: str,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.update")
    item = _release(db, release_id, current_user)
    if item.status not in EDITABLE_RELEASE_STATUSES:
        raise HTTPException(status_code=409, detail="Release dependencies are frozen")
    link = db.get(ReleaseDependency, dependency_id)
    if link is None or link.release_id != item.id:
        raise HTTPException(status_code=404, detail="Release dependency not found")
    db.delete(link)
    item.version += 1
    add_timeline(
        db,
        item,
        event_type="DEPENDENCY_REMOVED",
        message="Release dependency removed",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        metadata={"dependency_release_id": link.dependency_release_id},
    )
    _audit(
        db,
        request,
        current_user,
        action="release.dependency_removed",
        entity_type="release",
        entity_id=item.id,
        tenant_id=item.tenant_id,
    )
    db.commit()
    return _detail_response(db, item)


@router.post(
    "/{release_id}/gates",
    status_code=status.HTTP_201_CREATED,
)
def add_gate(
    release_id: str,
    payload: GateCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    item = _release(db, release_id, current_user)
    if item.status not in EDITABLE_RELEASE_STATUSES:
        raise HTTPException(status_code=409, detail="Release gates are frozen")
    gate = ReleaseGate(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        release_id=item.id,
        code=payload.code.upper(),
        name=payload.name,
        gate_type=payload.gate_type,
        is_mandatory=payload.is_mandatory,
        status="PENDING",
        version=1,
    )
    db.add(gate)
    item.version += 1
    add_timeline(
        db,
        item,
        event_type="GATE_ADDED",
        message=f"Readiness gate {gate.name} added",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
    )
    _audit(
        db,
        request,
        current_user,
        action="release.gate_added",
        entity_type="release_gate",
        entity_id=gate.id,
        tenant_id=item.tenant_id,
        metadata={"release_id": item.id},
    )
    _commit(db, "Release gate code already exists")
    return _detail_response(db, item)


@router.patch("/{release_id}/gates/{gate_id}")
def decide_gate(
    release_id: str,
    gate_id: str,
    payload: GateDecision,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    item = _release(db, release_id, current_user)
    if item.status not in {"PLANNING", "READY", "APPROVED"}:
        raise HTTPException(
            status_code=409,
            detail="Gates can be decided only before deployment starts",
        )
    gate = db.get(ReleaseGate, gate_id)
    if gate is None or gate.release_id != item.id:
        raise HTTPException(status_code=404, detail="Release gate not found")
    if gate.gate_type in AUTOMATED_GATE_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Automated gate status is derived from release evidence",
        )
    _version(gate.version, payload.expected_version, "Release gate")
    if payload.status == "WAIVED" and len(payload.comment.strip()) < 10:
        raise HTTPException(
            status_code=422,
            detail="Gate waiver requires a substantive justification",
        )
    gate.status = payload.status
    gate.evidence = payload.evidence
    gate.decision_comment = payload.comment
    gate.decided_by_id = current_user.id
    gate.decided_by_name = current_user.full_name
    gate.decided_at = now_utc()
    gate.version += 1
    item.version += 1
    add_timeline(
        db,
        item,
        event_type="GATE_DECIDED",
        message=f"{gate.name}: {gate.status.lower()}",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        metadata={"gate_id": gate.id, "status": gate.status},
    )
    _audit(
        db,
        request,
        current_user,
        action="release.gate_decided",
        entity_type="release_gate",
        entity_id=gate.id,
        tenant_id=item.tenant_id,
        metadata={"status": gate.status},
    )
    db.commit()
    return _detail_response(db, item)


@router.post("/{release_id}/decision")
def decide_go_no_go(
    release_id: str,
    payload: GoNoGoDecision,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.approve")
    item = _release(db, release_id, current_user)
    if item.status != "READY":
        raise HTTPException(status_code=409, detail="Release is not ready for decision")
    _version(item.version, payload.expected_version, "Release")
    if current_user.id in {item.owner_id, item.created_by_id}:
        raise HTTPException(
            status_code=409,
            detail="Release owner or author cannot make the go/no-go decision",
        )
    if payload.decision == "CONDITIONAL" and not payload.conditions:
        raise HTTPException(
            status_code=422,
            detail="Conditional approval requires explicit conditions",
        )
    readiness_snapshot = release_readiness(db, item)
    if payload.decision in {"GO", "CONDITIONAL"} and not readiness_snapshot["ready"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Release readiness gate failed",
                "readiness": readiness_snapshot,
            },
        )
    decision = ReleaseDecision(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        release_id=item.id,
        decision=payload.decision,
        comment=payload.comment,
        conditions_json=payload.conditions,
        readiness_snapshot_json=jsonable_encoder(readiness_snapshot),
        decided_by_id=current_user.id,
        decided_by_name=current_user.full_name,
    )
    db.add(decision)
    if payload.decision == "CONDITIONAL":
        for index, condition in enumerate(payload.conditions, start=1):
            control = str(condition.get("control") or f"Condition {index}")
            db.add(
                ReleaseGate(
                    id=str(uuid.uuid4()),
                    tenant_id=item.tenant_id,
                    release_id=item.id,
                    code=f"CONDITION_{index:03d}",
                    name=f"Go condition: {control}"[:200],
                    gate_type="MANUAL",
                    is_mandatory=True,
                    status="PENDING",
                    version=1,
                )
            )
    previous = item.status
    if payload.decision == "NO_GO":
        item.status = "PLANNING"
        item.go_no_go_status = "NO_GO"
        item.approved_decision_id = None
    else:
        item.status = "APPROVED"
        item.go_no_go_status = payload.decision
        item.approved_decision_id = decision.id
    item.version += 1
    add_timeline(
        db,
        item,
        event_type="GO_NO_GO_DECIDED",
        message=f"Go/no-go decision: {payload.decision}",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        from_status=previous,
        to_status=item.status,
        metadata={"decision_id": decision.id, "conditions": payload.conditions},
    )
    _audit(
        db,
        request,
        current_user,
        action="release.go_no_go_decided",
        entity_type="release",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"decision": payload.decision},
    )
    db.commit()
    return _detail_response(db, item)


@router.post(
    "/{release_id}/deployments",
    status_code=status.HTTP_201_CREATED,
)
def plan_deployment(
    release_id: str,
    payload: DeploymentCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.schedule")
    item = _release(db, release_id, current_user)
    if item.status not in {"APPROVED", "DEPLOYING"}:
        raise HTTPException(
            status_code=409,
            detail="Deployment can be planned only after a go decision",
        )
    environment = db.get(ReleaseEnvironment, payload.environment_id)
    if (
        environment is None
        or environment.tenant_id != item.tenant_id
        or not environment.is_active
    ):
        raise HTTPException(status_code=404, detail="Deployment environment not found")
    if environment.is_production:
        if not item.window_start_at or not item.window_end_at:
            raise HTTPException(
                status_code=422,
                detail="Production deployment requires an approved release window",
            )
        if not (
            aware(item.window_start_at)
            <= aware(payload.scheduled_at)
            <= aware(item.window_end_at)
        ):
            raise HTTPException(
                status_code=422,
                detail="Production deployment must be scheduled inside the release window",
            )
    deployment = ReleaseDeployment(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        release_id=item.id,
        environment_id=environment.id,
        status="PLANNED",
        scheduled_at=payload.scheduled_at,
        deployed_version=item.version_name,
        previous_version=environment.current_version,
        deployment_reference=payload.deployment_reference,
        smoke_test_status="PENDING",
        version=1,
    )
    db.add(deployment)
    item.version += 1
    add_timeline(
        db,
        item,
        event_type="DEPLOYMENT_PLANNED",
        message=f"Deployment planned for {environment.name}",
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        metadata={"deployment_id": deployment.id, "environment_id": environment.id},
    )
    _audit(
        db,
        request,
        current_user,
        action="release.deployment_planned",
        entity_type="release_deployment",
        entity_id=deployment.id,
        tenant_id=item.tenant_id,
        metadata={"release_id": item.id, "environment": environment.code},
    )
    _commit(db, "A deployment for this environment already exists")
    return _detail_response(db, item)


@router.patch("/{release_id}/deployments/{deployment_id}")
def update_deployment(
    release_id: str,
    deployment_id: str,
    payload: DeploymentAction,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "changes.execute")
    item = _release(db, release_id, current_user)
    deployment = db.get(ReleaseDeployment, deployment_id)
    if deployment is None or deployment.release_id != item.id:
        raise HTTPException(status_code=404, detail="Deployment not found")
    environment = db.get(ReleaseEnvironment, deployment.environment_id)
    if environment is None:
        raise HTTPException(status_code=409, detail="Deployment environment is missing")
    _version(deployment.version, payload.expected_version, "Deployment")
    instant = now_utc()
    previous_status = deployment.status
    if payload.action == "START":
        if deployment.status != "PLANNED":
            raise HTTPException(status_code=409, detail="Deployment is not planned")
        if item.status not in {"APPROVED", "DEPLOYING"}:
            raise HTTPException(status_code=409, detail="Release is not approved")
        current_readiness = release_readiness(db, item)
        if not current_readiness["ready"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Release readiness changed after approval",
                    "readiness": current_readiness,
                },
            )
        active = db.scalar(
            select(ReleaseDeployment).where(
                ReleaseDeployment.release_id == item.id,
                ReleaseDeployment.id != deployment.id,
                ReleaseDeployment.status.in_(ACTIVE_DEPLOYMENT_STATUSES),
            )
        )
        if active:
            raise HTTPException(
                status_code=409,
                detail="Another release deployment is still active",
            )
        promoted, previous_name = previous_environment_ready(db, item, environment)
        if not promoted:
            raise HTTPException(
                status_code=409,
                detail=f"Previous environment {previous_name} has not succeeded",
            )
        if environment.is_production and not (
            item.window_start_at
            and item.window_end_at
            and aware(item.window_start_at) <= instant <= aware(item.window_end_at)
        ):
            raise HTTPException(
                status_code=409,
                detail="Production deployment is outside the approved release window",
            )
        deployment.status = "IN_PROGRESS"
        deployment.started_at = instant
        deployment.operator_id = current_user.id
        deployment.operator_name = current_user.full_name
        item.status = "DEPLOYING"
    elif payload.action == "VALIDATE":
        if deployment.status != "IN_PROGRESS":
            raise HTTPException(status_code=409, detail="Deployment is not running")
        if not payload.deployment_evidence:
            raise HTTPException(
                status_code=422,
                detail="Deployment evidence is required before validation",
            )
        deployment.status = "VALIDATING"
        deployment.deployment_evidence = payload.deployment_evidence
        deployment.smoke_test_status = payload.smoke_test_status or "PENDING"
    elif payload.action == "SUCCEED":
        if deployment.status not in {"IN_PROGRESS", "VALIDATING"}:
            raise HTTPException(status_code=409, detail="Deployment is not active")
        deployment_evidence = (
            payload.deployment_evidence or deployment.deployment_evidence
        )
        if not deployment_evidence or not payload.validation_evidence:
            raise HTTPException(
                status_code=422,
                detail="Successful deployment requires deployment and validation evidence",
            )
        smoke_status = payload.smoke_test_status or deployment.smoke_test_status
        if environment.requires_smoke_test and smoke_status != "PASSED":
            raise HTTPException(
                status_code=422,
                detail="Required smoke test has not passed",
            )
        deployment.status = "SUCCEEDED"
        deployment.deployment_evidence = deployment_evidence
        deployment.validation_evidence = payload.validation_evidence
        deployment.smoke_test_status = smoke_status
        deployment.completed_at = instant
        environment.current_version = deployment.deployed_version
        environment.version += 1
        item.status = "VALIDATING" if environment.is_production else "DEPLOYING"
    elif payload.action == "FAIL":
        if deployment.status not in {"IN_PROGRESS", "VALIDATING"}:
            raise HTTPException(status_code=409, detail="Deployment is not active")
        if not payload.failure_reason:
            raise HTTPException(
                status_code=422,
                detail="Failed deployment requires a failure reason",
            )
        deployment.status = "FAILED"
        deployment.failure_reason = payload.failure_reason
        deployment.deployment_evidence = (
            payload.deployment_evidence or deployment.deployment_evidence
        )
        deployment.completed_at = instant
        item.status = "FAILED"
    elif payload.action == "ROLLBACK":
        if deployment.status not in {"FAILED", "SUCCEEDED", "VALIDATING"}:
            raise HTTPException(
                status_code=409,
                detail="Deployment cannot be rolled back from its current state",
            )
        if not payload.rollback_evidence:
            raise HTTPException(
                status_code=422,
                detail="Rollback requires recovery evidence",
            )
        deployment.status = "ROLLED_BACK"
        deployment.rollback_evidence = payload.rollback_evidence
        deployment.completed_at = instant
        environment.current_version = deployment.previous_version
        environment.version += 1
        item.status = "ROLLED_BACK"
        item.completed_at = instant
    elif payload.action == "CANCEL":
        if deployment.status != "PLANNED":
            raise HTTPException(
                status_code=409,
                detail="Only a planned deployment can be cancelled",
            )
        deployment.status = "CANCELLED"
        deployment.completed_at = instant
    deployment.version += 1
    item.version += 1
    add_timeline(
        db,
        item,
        event_type=f"DEPLOYMENT_{payload.action}",
        message=(
            f"{environment.name} deployment: "
            f"{previous_status.lower()} → {deployment.status.lower()}"
        ),
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        metadata={
            "deployment_id": deployment.id,
            "environment_id": environment.id,
        },
    )
    _audit(
        db,
        request,
        current_user,
        action=f"release.deployment_{payload.action.lower()}",
        entity_type="release_deployment",
        entity_id=deployment.id,
        tenant_id=item.tenant_id,
        metadata={"release_id": item.id, "status": deployment.status},
    )
    db.commit()
    return _detail_response(db, item)


@router.post("/{release_id}/transition")
def transition_release(
    release_id: str,
    payload: ReleaseTransition,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    permission = (
        "changes.execute"
        if payload.action == "PUBLISH"
        else "changes.submit"
    )
    require_permissions(current_user, permission)
    item = _release(db, release_id, current_user)
    _version(item.version, payload.expected_version, "Release")
    previous = item.status
    if payload.action == "SUBMIT":
        if item.status != "DRAFT":
            raise HTTPException(status_code=409, detail="Release is not a draft")
        item.status = "PLANNING"
    elif payload.action == "MARK_READY":
        if item.status != "PLANNING":
            raise HTTPException(status_code=409, detail="Release is not in planning")
        snapshot = release_readiness(db, item)
        structural_blockers = [
            gate["code"]
            for gate in snapshot["gates"]
            if gate["gate_type"] in AUTOMATED_GATE_TYPES
            and gate["status"] != "PASSED"
        ]
        failed_checks = [
            check["code"] for check in snapshot["checks"] if not check["passed"]
        ]
        if structural_blockers or failed_checks:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Release plan is structurally incomplete",
                    "blocking": structural_blockers + failed_checks,
                },
            )
        item.status = "READY"
    elif payload.action == "PUBLISH":
        if item.status != "VALIDATING":
            raise HTTPException(
                status_code=409,
                detail="Release is not in final validation",
            )
        rows = db.execute(
            select(ReleaseDeployment, ReleaseEnvironment)
            .join(
                ReleaseEnvironment,
                ReleaseEnvironment.id == ReleaseDeployment.environment_id,
            )
            .where(ReleaseDeployment.release_id == item.id)
        ).all()
        production = [
            deployment
            for deployment, environment in rows
            if environment.is_production
        ]
        unfinished = [
            deployment
            for deployment, _ in rows
            if deployment.status not in {"SUCCEEDED", "CANCELLED"}
        ]
        if (
            not production
            or not all(deployment.status == "SUCCEEDED" for deployment in production)
            or unfinished
        ):
            raise HTTPException(
                status_code=422,
                detail="All planned deployments and production validation must succeed",
            )
        item.status = "RELEASED"
        item.actual_released_at = now_utc()
        item.completed_at = item.actual_released_at
    elif payload.action == "CANCEL":
        if item.status in TERMINAL_RELEASE_STATUSES or item.status in {
            "DEPLOYING",
            "VALIDATING",
        }:
            raise HTTPException(
                status_code=409,
                detail="Release cannot be cancelled from its current state",
            )
        active = db.scalar(
            select(ReleaseDeployment).where(
                ReleaseDeployment.release_id == item.id,
                ReleaseDeployment.status.in_(ACTIVE_DEPLOYMENT_STATUSES),
            )
        )
        if active:
            raise HTTPException(
                status_code=409,
                detail="Active deployment must be resolved before cancellation",
            )
        item.status = "CANCELLED"
        item.completed_at = now_utc()
    item.version += 1
    add_timeline(
        db,
        item,
        event_type=f"RELEASE_{payload.action}",
        message=payload.comment,
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        from_status=previous,
        to_status=item.status,
    )
    _audit(
        db,
        request,
        current_user,
        action=f"release.{payload.action.lower()}",
        entity_type="release",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"from_status": previous, "to_status": item.status},
    )
    db.commit()
    return _detail_response(db, item)
