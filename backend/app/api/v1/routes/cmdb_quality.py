from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.asset import Asset
from app.models.asset_history import AssetHistory
from app.models.cmdb_quality import (
    CMDBCertificationCampaign,
    CMDBCertificationItem,
    CMDBQualityFinding,
    CMDBQualitySnapshot,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.cmdb_quality import (
    assets_for_certification_scope,
    certification_asset_snapshot,
    scan_quality,
    upsert_certification_rejection_finding,
)
from app.services.cmdb_schema import canonical_json
from app.services.rbac import has_permission, is_saas_root, require_permissions


router = APIRouter(prefix="/cmdb/quality")


class QualityScanRequest(BaseModel):
    tenant_id: str | None = None


class QualityFindingUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    owner_user_id: str | None = None
    due_at: datetime | None = None
    finding_status: Literal[
        "OPEN",
        "IN_PROGRESS",
        "RESOLVED",
        "WAIVED",
    ] | None = None
    resolution_note: str | None = Field(default=None, max_length=5_000)


class CertificationScope(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=5_000)
    ci_class_ids: list[str] = Field(default_factory=list, max_length=500)
    criticalities: list[
        Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    ] = Field(default_factory=list)
    environments: list[
        Literal["PRODUCTION", "STAGING", "TEST", "DEVELOPMENT", "OTHER"]
    ] = Field(default_factory=list)
    lifecycle_statuses: list[str] = Field(default_factory=list, max_length=20)
    only_without_owner: bool = False
    default_certifier_user_id: str | None = None


class CertificationCampaignCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)
    due_at: datetime
    scope: CertificationScope


class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class CampaignCancelRequest(VersionRequest):
    reason: str = Field(min_length=3, max_length=2_000)


class CertificationDecisionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    decision: Literal["CERTIFIED", "REJECTED"]
    note: str = Field(min_length=3, max_length=5_000)


class QualitySnapshotResponse(BaseModel):
    id: str
    tenant_id: str
    overall_score: float
    completeness_score: float
    correctness_score: float
    freshness_score: float
    duplicate_score: float
    orphan_score: float
    ci_count: int
    open_finding_count: int
    critical_finding_count: int
    resolved_finding_count: int
    result: dict[str, Any]
    result_hash: str
    integrity_valid: bool
    created_by_id: str | None
    created_at: datetime


class QualityFindingResponse(BaseModel):
    id: str
    tenant_id: str
    rule_code: str
    dimension: str
    subject_type: str
    subject_id: str
    asset_id: str | None
    asset_tag: str | None
    asset_name: str | None
    title: str
    details: str
    evidence: dict[str, Any]
    severity: str
    status: str
    owner_user_id: str | None
    owner_name: str | None
    owner_email: str | None
    due_at: datetime | None
    overdue: bool
    age_days: int
    first_detected_at: datetime
    last_detected_at: datetime
    occurrence_count: int
    resolution_note: str | None
    resolved_by_id: str | None
    resolved_at: datetime | None
    last_snapshot_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class CertificationItemResponse(BaseModel):
    id: str
    tenant_id: str
    campaign_id: str
    asset_id: str
    asset_tag: str
    asset_name: str
    asset_version: int
    current_asset_version: int
    asset_changed: bool
    asset_snapshot: dict[str, Any]
    asset_snapshot_hash: str
    integrity_valid: bool
    certifier_user_id: str | None
    certifier_name: str | None
    status: str
    decision_note: str | None
    decided_by_id: str | None
    decided_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class CertificationCampaignResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    scope: dict[str, Any]
    status: str
    due_at: datetime
    overdue: bool
    activated_at: datetime | None
    completed_at: datetime | None
    created_by_id: str | None
    version: int
    total_items: int
    pending_items: int
    certified_items: int
    rejected_items: int
    progress_percent: float
    items: list[CertificationItemResponse] | None
    created_at: datetime
    updated_at: datetime


class QualityOverviewResponse(BaseModel):
    latest: QualitySnapshotResponse | None
    trend: list[QualitySnapshotResponse]
    open_findings: int
    overdue_findings: int
    unassigned_findings: int
    active_campaigns: int
    overdue_campaigns: int


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
            detail="tenant_id is required for SaaS Root quality governance",
        )
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _snapshot_response(
    snapshot: CMDBQualitySnapshot,
) -> QualitySnapshotResponse:
    result = _json_object(snapshot.result_json)
    return QualitySnapshotResponse(
        id=snapshot.id,
        tenant_id=snapshot.tenant_id,
        overall_score=snapshot.overall_score,
        completeness_score=snapshot.completeness_score,
        correctness_score=snapshot.correctness_score,
        freshness_score=snapshot.freshness_score,
        duplicate_score=snapshot.duplicate_score,
        orphan_score=snapshot.orphan_score,
        ci_count=snapshot.ci_count,
        open_finding_count=snapshot.open_finding_count,
        critical_finding_count=snapshot.critical_finding_count,
        resolved_finding_count=snapshot.resolved_finding_count,
        result=result,
        result_hash=snapshot.result_hash,
        integrity_valid=(
            hashlib.sha256(snapshot.result_json.encode()).hexdigest()
            == snapshot.result_hash
        ),
        created_by_id=snapshot.created_by_id,
        created_at=snapshot.created_at,
    )


def _finding_response(
    db: Session,
    finding: CMDBQualityFinding,
) -> QualityFindingResponse:
    asset = db.get(Asset, finding.asset_id) if finding.asset_id else None
    owner = (
        db.get(User, finding.owner_user_id)
        if finding.owner_user_id
        else None
    )
    now = _now()
    return QualityFindingResponse(
        id=finding.id,
        tenant_id=finding.tenant_id,
        rule_code=finding.rule_code,
        dimension=finding.dimension,
        subject_type=finding.subject_type,
        subject_id=finding.subject_id,
        asset_id=finding.asset_id,
        asset_tag=asset.asset_tag if asset else None,
        asset_name=asset.name if asset else None,
        title=finding.title,
        details=finding.details,
        evidence=_json_object(finding.evidence_json),
        severity=finding.severity,
        status=finding.status,
        owner_user_id=finding.owner_user_id,
        owner_name=owner.full_name if owner else None,
        owner_email=owner.email if owner else None,
        due_at=finding.due_at,
        overdue=(
            finding.status in {"OPEN", "IN_PROGRESS"}
            and finding.due_at is not None
            and _aware(finding.due_at) < now
        ),
        age_days=max(0, (now - _aware(finding.first_detected_at)).days),
        first_detected_at=finding.first_detected_at,
        last_detected_at=finding.last_detected_at,
        occurrence_count=finding.occurrence_count,
        resolution_note=finding.resolution_note,
        resolved_by_id=finding.resolved_by_id,
        resolved_at=finding.resolved_at,
        last_snapshot_id=finding.last_snapshot_id,
        version=finding.version,
        created_at=finding.created_at,
        updated_at=finding.updated_at,
    )


def _item_response(
    db: Session,
    item: CMDBCertificationItem,
) -> CertificationItemResponse:
    asset = db.get(Asset, item.asset_id)
    if asset is None or asset.tenant_id != item.tenant_id:
        raise HTTPException(status_code=500, detail="Certification CI is unavailable")
    certifier = (
        db.get(User, item.certifier_user_id)
        if item.certifier_user_id
        else None
    )
    integrity_valid = (
        hashlib.sha256(item.asset_snapshot_json.encode()).hexdigest()
        == item.asset_snapshot_hash
    )
    return CertificationItemResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        campaign_id=item.campaign_id,
        asset_id=item.asset_id,
        asset_tag=asset.asset_tag,
        asset_name=asset.name,
        asset_version=item.asset_version,
        current_asset_version=asset.ci_version,
        asset_changed=asset.ci_version != item.asset_version,
        asset_snapshot=_json_object(item.asset_snapshot_json),
        asset_snapshot_hash=item.asset_snapshot_hash,
        integrity_valid=integrity_valid,
        certifier_user_id=item.certifier_user_id,
        certifier_name=certifier.full_name if certifier else None,
        status=item.status,
        decision_note=item.decision_note,
        decided_by_id=item.decided_by_id,
        decided_at=item.decided_at,
        version=item.version,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _campaign_response(
    db: Session,
    campaign: CMDBCertificationCampaign,
    *,
    include_items: bool,
) -> CertificationCampaignResponse:
    items = db.scalars(
        select(CMDBCertificationItem)
        .where(CMDBCertificationItem.campaign_id == campaign.id)
        .order_by(CMDBCertificationItem.created_at)
    ).all()
    counts = {
        item: sum(row.status == item for row in items)
        for item in ("PENDING", "CERTIFIED", "REJECTED")
    }
    decided = counts["CERTIFIED"] + counts["REJECTED"]
    return CertificationCampaignResponse(
        id=campaign.id,
        tenant_id=campaign.tenant_id,
        name=campaign.name,
        description=campaign.description,
        scope=_json_object(campaign.scope_json),
        status=campaign.status,
        due_at=campaign.due_at,
        overdue=(
            campaign.status == "ACTIVE"
            and _aware(campaign.due_at) < _now()
        ),
        activated_at=campaign.activated_at,
        completed_at=campaign.completed_at,
        created_by_id=campaign.created_by_id,
        version=campaign.version,
        total_items=len(items),
        pending_items=counts["PENDING"],
        certified_items=counts["CERTIFIED"],
        rejected_items=counts["REJECTED"],
        progress_percent=(
            round(100 * decided / len(items), 2) if items else 0.0
        ),
        items=(
            [_item_response(db, item) for item in items]
            if include_items
            else None
        ),
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


def _finding_or_404(
    db: Session,
    finding_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> CMDBQualityFinding:
    statement = select(CMDBQualityFinding).where(
        CMDBQualityFinding.id == finding_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    finding = db.scalar(statement)
    if finding is None or (
        not is_saas_root(current_user)
        and finding.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Quality finding not found")
    return finding


def _campaign_or_404(
    db: Session,
    campaign_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> CMDBCertificationCampaign:
    statement = select(CMDBCertificationCampaign).where(
        CMDBCertificationCampaign.id == campaign_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    campaign = db.scalar(statement)
    if campaign is None or (
        not is_saas_root(current_user)
        and campaign.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(
            status_code=404,
            detail="Certification campaign not found",
        )
    return campaign


def _assert_version(actual: int, expected: int, subject: str) -> None:
    if actual != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{subject} was updated; current version is {actual}",
        )


def _user_in_tenant(
    db: Session,
    user_id: str | None,
    tenant_id: str,
) -> User | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or user.tenant_id != tenant_id or not user.is_active:
        raise HTTPException(status_code=422, detail="User is unavailable")
    return user


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


@router.get("/summary", response_model=QualityOverviewResponse)
def quality_summary(
    tenant_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> QualityOverviewResponse:
    require_permissions(current_user, "assets.read")
    scope = _tenant_id(db, current_user, tenant_id)
    snapshots = db.scalars(
        select(CMDBQualitySnapshot)
        .where(CMDBQualitySnapshot.tenant_id == scope)
        .order_by(CMDBQualitySnapshot.created_at.desc())
        .limit(12)
    ).all()
    now = _now()
    open_findings = db.scalar(
        select(func.count(CMDBQualityFinding.id)).where(
            CMDBQualityFinding.tenant_id == scope,
            CMDBQualityFinding.status.in_({"OPEN", "IN_PROGRESS"}),
        )
    ) or 0
    overdue_findings = db.scalar(
        select(func.count(CMDBQualityFinding.id)).where(
            CMDBQualityFinding.tenant_id == scope,
            CMDBQualityFinding.status.in_({"OPEN", "IN_PROGRESS"}),
            CMDBQualityFinding.due_at < now,
        )
    ) or 0
    unassigned = db.scalar(
        select(func.count(CMDBQualityFinding.id)).where(
            CMDBQualityFinding.tenant_id == scope,
            CMDBQualityFinding.status.in_({"OPEN", "IN_PROGRESS"}),
            CMDBQualityFinding.owner_user_id.is_(None),
        )
    ) or 0
    active_campaigns = db.scalar(
        select(func.count(CMDBCertificationCampaign.id)).where(
            CMDBCertificationCampaign.tenant_id == scope,
            CMDBCertificationCampaign.status == "ACTIVE",
        )
    ) or 0
    overdue_campaigns = db.scalar(
        select(func.count(CMDBCertificationCampaign.id)).where(
            CMDBCertificationCampaign.tenant_id == scope,
            CMDBCertificationCampaign.status == "ACTIVE",
            CMDBCertificationCampaign.due_at < now,
        )
    ) or 0
    return QualityOverviewResponse(
        latest=_snapshot_response(snapshots[0]) if snapshots else None,
        trend=[_snapshot_response(item) for item in reversed(snapshots)],
        open_findings=open_findings,
        overdue_findings=overdue_findings,
        unassigned_findings=unassigned,
        active_campaigns=active_campaigns,
        overdue_campaigns=overdue_campaigns,
    )


@router.post("/scan", response_model=QualitySnapshotResponse)
def run_quality_scan(
    payload: QualityScanRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> QualitySnapshotResponse:
    require_permissions(current_user, "assets.verify")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    snapshot = scan_quality(
        db,
        tenant_id=tenant_id,
        actor_user_id=current_user.id,
    )
    _audit(
        db,
        request,
        current_user,
        action="cmdb.quality.scanned",
        entity_type="cmdb_quality_snapshot",
        entity_id=snapshot.id,
        tenant_id=tenant_id,
        metadata={
            "overall_score": snapshot.overall_score,
            "open_finding_count": snapshot.open_finding_count,
            "critical_finding_count": snapshot.critical_finding_count,
            "result_hash": snapshot.result_hash,
        },
    )
    db.commit()
    db.refresh(snapshot)
    return _snapshot_response(snapshot)


@router.get("/findings", response_model=list[QualityFindingResponse])
def list_quality_findings(
    tenant_id: str | None = None,
    finding_status: str = Query(default="OPEN"),
    dimension: str | None = None,
    severity: str | None = None,
    owner_user_id: str | None = None,
    q: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[QualityFindingResponse]:
    require_permissions(current_user, "assets.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statement = select(CMDBQualityFinding).where(
        CMDBQualityFinding.tenant_id == scope
    )
    if finding_status == "OPEN":
        statement = statement.where(
            CMDBQualityFinding.status.in_({"OPEN", "IN_PROGRESS"})
        )
    elif finding_status != "ALL":
        statement = statement.where(
            CMDBQualityFinding.status == finding_status
        )
    if dimension and dimension != "ALL":
        statement = statement.where(CMDBQualityFinding.dimension == dimension)
    if severity and severity != "ALL":
        statement = statement.where(CMDBQualityFinding.severity == severity)
    if owner_user_id:
        statement = statement.where(
            CMDBQualityFinding.owner_user_id == owner_user_id
        )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            CMDBQualityFinding.title.ilike(pattern)
            | CMDBQualityFinding.rule_code.ilike(pattern)
        )
    findings = db.scalars(
        statement.order_by(
            CMDBQualityFinding.due_at.asc(),
            CMDBQualityFinding.first_detected_at.asc(),
        ).limit(limit)
    ).all()
    return [_finding_response(db, finding) for finding in findings]


@router.patch(
    "/findings/{finding_id}",
    response_model=QualityFindingResponse,
)
def update_quality_finding(
    finding_id: str,
    payload: QualityFindingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> QualityFindingResponse:
    require_permissions(current_user, "assets.update")
    finding = _finding_or_404(db, finding_id, current_user, lock=True)
    _assert_version(finding.version, payload.expected_version, "Finding")
    updates = payload.model_dump(exclude_unset=True)
    updates.pop("expected_version", None)
    now = _now()
    if "owner_user_id" in updates:
        _user_in_tenant(db, updates["owner_user_id"], finding.tenant_id)
        finding.owner_user_id = updates["owner_user_id"]
    if "due_at" in updates:
        finding.due_at = updates["due_at"]
    if "finding_status" in updates:
        next_status = updates["finding_status"]
        note = (updates.get("resolution_note") or "").strip()
        if next_status in {"RESOLVED", "WAIVED"} and len(note) < 3:
            raise HTTPException(
                status_code=422,
                detail="resolution_note is required for resolved or waived findings",
            )
        finding.status = next_status
        if next_status in {"RESOLVED", "WAIVED"}:
            finding.resolution_note = note
            finding.resolved_by_id = current_user.id
            finding.resolved_at = now
        else:
            finding.resolution_note = None
            finding.resolved_by_id = None
            finding.resolved_at = None
    elif "resolution_note" in updates:
        finding.resolution_note = (
            (updates["resolution_note"] or "").strip() or None
        )
    finding.version += 1
    finding.updated_at = now
    _audit(
        db,
        request,
        current_user,
        action="cmdb.quality.finding_updated",
        entity_type="cmdb_quality_finding",
        entity_id=finding.id,
        tenant_id=finding.tenant_id,
        metadata={
            "status": finding.status,
            "owner_user_id": finding.owner_user_id,
            "due_at": finding.due_at.isoformat() if finding.due_at else None,
            "rule_code": finding.rule_code,
        },
    )
    db.commit()
    db.refresh(finding)
    return _finding_response(db, finding)


@router.get(
    "/campaigns",
    response_model=list[CertificationCampaignResponse],
)
def list_certification_campaigns(
    tenant_id: str | None = None,
    campaign_status: str | None = None,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[CertificationCampaignResponse]:
    require_permissions(current_user, "assets.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statement = select(CMDBCertificationCampaign).where(
        CMDBCertificationCampaign.tenant_id == scope
    )
    if campaign_status and campaign_status != "ALL":
        statement = statement.where(
            CMDBCertificationCampaign.status == campaign_status
        )
    campaigns = db.scalars(
        statement.order_by(CMDBCertificationCampaign.created_at.desc())
    ).all()
    return [
        _campaign_response(db, campaign, include_items=False)
        for campaign in campaigns
    ]


@router.post(
    "/campaigns",
    response_model=CertificationCampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_certification_campaign(
    payload: CertificationCampaignCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> CertificationCampaignResponse:
    require_permissions(current_user, "assets.update")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    due_at = _aware(payload.due_at)
    if due_at <= _now():
        raise HTTPException(status_code=422, detail="due_at must be in the future")
    scope = payload.scope.model_dump()
    _user_in_tenant(
        db,
        scope.get("default_certifier_user_id"),
        tenant_id,
    )
    try:
        assets_for_certification_scope(db, tenant_id=tenant_id, scope=scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = _now()
    campaign = CMDBCertificationCampaign(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=payload.name.strip(),
        description=(
            payload.description.strip() if payload.description else None
        ),
        scope_json=canonical_json(scope),
        status="DRAFT",
        due_at=due_at,
        created_by_id=current_user.id,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(campaign)
    _audit(
        db,
        request,
        current_user,
        action="cmdb.certification.campaign_created",
        entity_type="cmdb_certification_campaign",
        entity_id=campaign.id,
        tenant_id=tenant_id,
        metadata={"name": campaign.name, "due_at": due_at.isoformat(), "scope": scope},
    )
    db.commit()
    db.refresh(campaign)
    return _campaign_response(db, campaign, include_items=False)


@router.get(
    "/campaigns/{campaign_id}",
    response_model=CertificationCampaignResponse,
)
def get_certification_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> CertificationCampaignResponse:
    require_permissions(current_user, "assets.read")
    return _campaign_response(
        db,
        _campaign_or_404(db, campaign_id, current_user),
        include_items=True,
    )


@router.post(
    "/campaigns/{campaign_id}/activate",
    response_model=CertificationCampaignResponse,
)
def activate_certification_campaign(
    campaign_id: str,
    payload: VersionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> CertificationCampaignResponse:
    require_permissions(current_user, "assets.update")
    campaign = _campaign_or_404(
        db,
        campaign_id,
        current_user,
        lock=True,
    )
    _assert_version(campaign.version, payload.expected_version, "Campaign")
    if campaign.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Campaign is not a draft")
    if _aware(campaign.due_at) <= _now():
        raise HTTPException(
            status_code=409,
            detail="Campaign due date has passed; create a new campaign",
        )
    scope = _json_object(campaign.scope_json)
    try:
        assets = assets_for_certification_scope(
            db,
            tenant_id=campaign.tenant_id,
            scope=scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    default_certifier = _user_in_tenant(
        db,
        scope.get("default_certifier_user_id"),
        campaign.tenant_id,
    )
    now = _now()
    for asset in assets:
        snapshot = certification_asset_snapshot(asset)
        snapshot_json = canonical_json(snapshot)
        asset_owner = (
            db.get(User, asset.owner_user_id)
            if asset.owner_user_id
            else None
        )
        owner_is_valid = bool(
            asset_owner
            and asset_owner.tenant_id == campaign.tenant_id
            and asset_owner.is_active
        )
        db.add(
            CMDBCertificationItem(
                id=str(uuid.uuid4()),
                tenant_id=campaign.tenant_id,
                campaign_id=campaign.id,
                asset_id=asset.id,
                asset_version=asset.ci_version,
                asset_snapshot_json=snapshot_json,
                asset_snapshot_hash=hashlib.sha256(
                    snapshot_json.encode()
                ).hexdigest(),
                certifier_user_id=(
                    asset.owner_user_id
                    if owner_is_valid
                    else (
                        default_certifier.id if default_certifier else None
                    )
                ),
                status="PENDING",
                version=1,
                created_at=now,
                updated_at=now,
            )
        )
    campaign.status = "ACTIVE"
    campaign.activated_at = now
    campaign.version += 1
    campaign.updated_at = now
    _audit(
        db,
        request,
        current_user,
        action="cmdb.certification.campaign_activated",
        entity_type="cmdb_certification_campaign",
        entity_id=campaign.id,
        tenant_id=campaign.tenant_id,
        metadata={"item_count": len(assets), "version": campaign.version},
    )
    db.commit()
    db.refresh(campaign)
    return _campaign_response(db, campaign, include_items=True)


@router.post(
    "/campaigns/{campaign_id}/items/{item_id}/decision",
    response_model=CertificationCampaignResponse,
)
def decide_certification_item(
    campaign_id: str,
    item_id: str,
    payload: CertificationDecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> CertificationCampaignResponse:
    require_permissions(current_user, "assets.verify")
    campaign = _campaign_or_404(
        db,
        campaign_id,
        current_user,
        lock=True,
    )
    if campaign.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Campaign is not active")
    statement = select(CMDBCertificationItem).where(
        CMDBCertificationItem.id == item_id,
        CMDBCertificationItem.campaign_id == campaign.id,
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Certification item not found")
    _assert_version(item.version, payload.expected_version, "Certification item")
    if item.status != "PENDING":
        raise HTTPException(status_code=409, detail="Item already has a decision")
    if (
        item.certifier_user_id
        and item.certifier_user_id != current_user.id
        and not is_saas_root(current_user)
        and not has_permission(current_user, "assets.update")
    ):
        raise HTTPException(
            status_code=403,
            detail="Certification item is assigned to another user",
        )
    asset = db.get(Asset, item.asset_id)
    if asset is None or asset.tenant_id != campaign.tenant_id:
        raise HTTPException(status_code=409, detail="Certification CI is unavailable")
    if payload.decision == "CERTIFIED" and asset.ci_version != item.asset_version:
        raise HTTPException(
            status_code=409,
            detail=(
                "CI changed after campaign activation; "
                "a new certification snapshot is required"
            ),
        )
    if (
        payload.decision == "CERTIFIED"
        and hashlib.sha256(item.asset_snapshot_json.encode()).hexdigest()
        != item.asset_snapshot_hash
    ):
        raise HTTPException(
            status_code=409,
            detail="Certification snapshot integrity check failed",
        )
    now = _now()
    item.status = payload.decision
    item.decision_note = payload.note.strip()
    item.decided_by_id = current_user.id
    item.decided_at = now
    item.version += 1
    item.updated_at = now
    if payload.decision == "CERTIFIED":
        old_verification = asset.verification_status
        asset.verification_status = "verified"
        asset.last_verified_at = now
        db.add(
            AssetHistory(
                id=str(uuid.uuid4()),
                asset_id=asset.id,
                actor_id=current_user.id,
                action="cmdb_certified",
                old_value={"verification_status": old_verification},
                new_value={
                    "verification_status": "verified",
                    "campaign_id": campaign.id,
                    "certification_item_id": item.id,
                    "certified_ci_version": item.asset_version,
                },
                comment=item.decision_note,
                created_at=now,
            )
        )
    else:
        upsert_certification_rejection_finding(
            db,
            tenant_id=campaign.tenant_id,
            asset=asset,
            campaign_id=campaign.id,
            item_id=item.id,
            note=item.decision_note,
            owner_user_id=item.certifier_user_id,
        )
    _audit(
        db,
        request,
        current_user,
        action="cmdb.certification.item_decided",
        entity_type="cmdb_certification_item",
        entity_id=item.id,
        tenant_id=campaign.tenant_id,
        metadata={
            "campaign_id": campaign.id,
            "asset_id": asset.id,
            "decision": item.status,
            "certified_ci_version": item.asset_version,
        },
    )
    db.commit()
    db.refresh(campaign)
    return _campaign_response(db, campaign, include_items=True)


@router.post(
    "/campaigns/{campaign_id}/complete",
    response_model=CertificationCampaignResponse,
)
def complete_certification_campaign(
    campaign_id: str,
    payload: VersionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> CertificationCampaignResponse:
    require_permissions(current_user, "assets.update")
    campaign = _campaign_or_404(
        db,
        campaign_id,
        current_user,
        lock=True,
    )
    _assert_version(campaign.version, payload.expected_version, "Campaign")
    if campaign.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Campaign is not active")
    pending = db.scalar(
        select(func.count(CMDBCertificationItem.id)).where(
            CMDBCertificationItem.campaign_id == campaign.id,
            CMDBCertificationItem.status == "PENDING",
        )
    ) or 0
    if pending:
        raise HTTPException(
            status_code=409,
            detail=f"Campaign still has {pending} pending items",
        )
    now = _now()
    campaign.status = "COMPLETED"
    campaign.completed_at = now
    campaign.version += 1
    campaign.updated_at = now
    _audit(
        db,
        request,
        current_user,
        action="cmdb.certification.campaign_completed",
        entity_type="cmdb_certification_campaign",
        entity_id=campaign.id,
        tenant_id=campaign.tenant_id,
        metadata={"version": campaign.version},
    )
    db.commit()
    db.refresh(campaign)
    return _campaign_response(db, campaign, include_items=True)


@router.post(
    "/campaigns/{campaign_id}/cancel",
    response_model=CertificationCampaignResponse,
)
def cancel_certification_campaign(
    campaign_id: str,
    payload: CampaignCancelRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUserResponse = Depends(get_current_user),
) -> CertificationCampaignResponse:
    require_permissions(current_user, "assets.update")
    campaign = _campaign_or_404(
        db,
        campaign_id,
        current_user,
        lock=True,
    )
    _assert_version(campaign.version, payload.expected_version, "Campaign")
    if campaign.status not in {"DRAFT", "ACTIVE"}:
        raise HTTPException(status_code=409, detail="Campaign cannot be cancelled")
    campaign.status = "CANCELLED"
    campaign.version += 1
    campaign.updated_at = _now()
    _audit(
        db,
        request,
        current_user,
        action="cmdb.certification.campaign_cancelled",
        entity_type="cmdb_certification_campaign",
        entity_id=campaign.id,
        tenant_id=campaign.tenant_id,
        metadata={"reason": payload.reason.strip(), "version": campaign.version},
    )
    db.commit()
    db.refresh(campaign)
    return _campaign_response(db, campaign, include_items=True)
