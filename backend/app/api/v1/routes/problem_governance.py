from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.api.v1.routes.problems import (
    _audit_request,
    _get_problem,
    _record_history,
)
from app.db.session import get_db
from app.models.problem import Problem
from app.models.problem_governance import (
    KnownErrorUsage,
    ProblemCorrectiveAction,
    ProblemRCA,
    ProblemTrendSignal,
)
from app.models.problem_link import ProblemTicketLink
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.user import User
from app.services.audit import log_audit
from app.services.problem_governance import aware, now_utc, scan_ticket_trends, validate_rca
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/problem-governance")


class RCAUpsert(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    method: Literal["FIVE_WHYS", "ISHIKAWA", "FAULT_TREE", "CUSTOM"]
    problem_statement: str = Field(min_length=10, max_length=20_000)
    five_whys: list[dict[str, object]] = Field(default_factory=list, max_length=10)
    ishikawa: dict[str, list[str]] = Field(default_factory=dict)
    fault_tree: dict[str, object] = Field(default_factory=dict)
    contributing_factors: list[dict[str, object]] = Field(
        default_factory=list, max_length=100
    )
    evidence: list[dict[str, object]] = Field(default_factory=list, max_length=100)
    conclusion: str = Field(min_length=10, max_length=30_000)


class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class RCAApproval(VersionRequest):
    decision: Literal["APPROVED", "REJECTED"]
    comment: str = Field(min_length=3, max_length=5_000)


class ActionCreate(BaseModel):
    action_type: Literal["CORRECTIVE", "PREVENTIVE", "DETECTION"]
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10, max_length=20_000)
    is_required: bool = True
    owner_id: str | None = None
    due_at: datetime
    effectiveness_criteria: str = Field(min_length=10, max_length=20_000)


class ActionUpdate(VersionRequest):
    status: Literal[
        "OPEN",
        "IN_PROGRESS",
        "IMPLEMENTED",
        "VERIFIED",
        "INEFFECTIVE",
        "CANCELLED",
    ]
    implementation_evidence: str | None = Field(default=None, max_length=20_000)
    review_due_at: datetime | None = None
    effectiveness_score: int | None = Field(default=None, ge=0, le=100)
    effectiveness_evidence: str | None = Field(default=None, max_length=20_000)


class TrendDisposition(VersionRequest):
    action: Literal["ACKNOWLEDGE", "DISMISS", "CONVERT"]
    comment: str = Field(min_length=3, max_length=5_000)
    owner_id: str | None = None


class KnownErrorUsageCreate(BaseModel):
    ticket_id: str | None = None
    usage_type: Literal["VIEWED", "APPLIED", "HELPFUL", "NOT_HELPFUL"]
    minutes_saved: int = Field(default=0, ge=0, le=100_000)
    avoided_escalation: bool = False
    comment: str | None = Field(default=None, max_length=5_000)


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
    return current_user.tenant_id


def _actor(db: Session, current_user: AuthUserResponse) -> User:
    actor = db.get(User, current_user.id)
    if actor is None:
        raise HTTPException(status_code=403, detail="User account not found")
    return actor


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


def _rca_response(item: ProblemRCA) -> dict[str, Any]:
    return {
        "id": item.id,
        "problem_id": item.problem_id,
        "method": item.method,
        "status": item.status,
        "problem_statement": item.problem_statement,
        "five_whys": item.five_whys_json,
        "ishikawa": item.ishikawa_json,
        "fault_tree": item.fault_tree_json,
        "contributing_factors": item.contributing_factors_json,
        "evidence": item.evidence_json,
        "conclusion": item.conclusion,
        "prepared_by_id": item.prepared_by_id,
        "prepared_by_name": item.prepared_by_name,
        "submitted_at": item.submitted_at,
        "approved_by_id": item.approved_by_id,
        "approved_by_name": item.approved_by_name,
        "approved_at": item.approved_at,
        "approval_comment": item.approval_comment,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _action_response(item: ProblemCorrectiveAction) -> dict[str, Any]:
    return {
        field: getattr(item, field)
        for field in (
            "id",
            "problem_id",
            "action_type",
            "title",
            "description",
            "status",
            "is_required",
            "owner_id",
            "owner_name",
            "due_at",
            "effectiveness_criteria",
            "implementation_evidence",
            "implemented_at",
            "review_due_at",
            "effectiveness_score",
            "effectiveness_evidence",
            "reviewed_by_name",
            "reviewed_at",
            "version",
            "created_at",
            "updated_at",
        )
    }


def _trend_response(item: ProblemTrendSignal) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "signal_type": item.signal_type,
        "signature": item.signature,
        "title": item.title,
        "service_name": item.service_name,
        "category": item.category,
        "window_start_at": item.window_start_at,
        "window_end_at": item.window_end_at,
        "baseline_count": item.baseline_count,
        "current_count": item.current_count,
        "growth_percent": item.growth_percent,
        "score": item.score,
        "incident_ids": item.incident_ids_json,
        "evidence": item.evidence_json,
        "status": item.status,
        "problem_id": item.problem_id,
        "disposition_comment": item.disposition_comment,
        "disposition_by_name": item.disposition_by_name,
        "disposition_at": item.disposition_at,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/problems/{problem_id}/rca")
def get_rca(
    problem_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.read")
    problem = _get_problem(db, problem_id, current_user)
    item = db.scalar(select(ProblemRCA).where(ProblemRCA.problem_id == problem.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Structured RCA not found")
    return _rca_response(item)


@router.put("/problems/{problem_id}/rca")
def save_rca(
    problem_id: str,
    payload: RCAUpsert,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.investigate")
    problem = _get_problem(db, problem_id, current_user)
    item = db.scalar(select(ProblemRCA).where(ProblemRCA.problem_id == problem.id))
    if item is None:
        if payload.expected_version is not None:
            raise HTTPException(status_code=409, detail="Structured RCA does not exist")
        item = ProblemRCA(
            id=str(uuid.uuid4()),
            tenant_id=problem.tenant_id,
            problem_id=problem.id,
            method=payload.method,
            status="DRAFT",
            problem_statement=payload.problem_statement,
            five_whys_json=payload.five_whys,
            ishikawa_json=payload.ishikawa,
            fault_tree_json=payload.fault_tree,
            contributing_factors_json=payload.contributing_factors,
            evidence_json=payload.evidence,
            conclusion=payload.conclusion,
            prepared_by_id=current_user.id,
            prepared_by_name=current_user.full_name,
            version=1,
        )
        db.add(item)
    else:
        if item.status not in {"DRAFT", "REJECTED"}:
            raise HTTPException(status_code=409, detail="RCA is under governance review")
        if payload.expected_version is None:
            raise HTTPException(status_code=409, detail="expected_version is required")
        _version(item.version, payload.expected_version, "Structured RCA")
        item.method = payload.method
        item.problem_statement = payload.problem_statement
        item.five_whys_json = payload.five_whys
        item.ishikawa_json = payload.ishikawa
        item.fault_tree_json = payload.fault_tree
        item.contributing_factors_json = payload.contributing_factors
        item.evidence_json = payload.evidence
        item.conclusion = payload.conclusion
        item.status = "DRAFT"
        item.version += 1
        item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="problem.rca_saved",
        entity_type="problem_rca",
        entity_id=item.id,
        tenant_id=problem.tenant_id,
        metadata={"problem_id": problem.id, "method": item.method},
    )
    db.commit()
    db.refresh(item)
    return _rca_response(item)


@router.post("/problems/{problem_id}/rca/submit")
def submit_rca(
    problem_id: str,
    payload: VersionRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.investigate")
    problem = _get_problem(db, problem_id, current_user)
    item = db.scalar(select(ProblemRCA).where(ProblemRCA.problem_id == problem.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Structured RCA not found")
    _version(item.version, payload.expected_version, "Structured RCA")
    if item.status not in {"DRAFT", "REJECTED"}:
        raise HTTPException(status_code=409, detail="RCA cannot be submitted")
    errors = validate_rca(item)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    item.status = "SUBMITTED"
    item.submitted_at = now_utc()
    item.version += 1
    _audit(
        db,
        request,
        current_user,
        action="problem.rca_submitted",
        entity_type="problem_rca",
        entity_id=item.id,
        tenant_id=problem.tenant_id,
    )
    db.commit()
    db.refresh(item)
    return _rca_response(item)


@router.post("/problems/{problem_id}/rca/decision")
def decide_rca(
    problem_id: str,
    payload: RCAApproval,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.resolve")
    problem = _get_problem(db, problem_id, current_user)
    item = db.scalar(select(ProblemRCA).where(ProblemRCA.problem_id == problem.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Structured RCA not found")
    _version(item.version, payload.expected_version, "Structured RCA")
    if item.status != "SUBMITTED":
        raise HTTPException(status_code=409, detail="RCA is not submitted")
    if item.prepared_by_id == current_user.id:
        raise HTTPException(status_code=409, detail="RCA author cannot approve it")
    item.status = payload.decision
    item.approved_by_id = current_user.id
    item.approved_by_name = current_user.full_name
    item.approved_at = now_utc()
    item.approval_comment = payload.comment
    item.version += 1
    if payload.decision == "APPROVED":
        problem.root_cause = item.conclusion
        problem.version += 1
        _record_history(
            db,
            problem,
            current_user,
            event_type="STRUCTURED_RCA_APPROVED",
            message=f"{item.method} RCA approved independently",
            metadata={"rca_id": item.id},
        )
    _audit_request(
        db,
        request,
        problem,
        current_user,
        "problems.rca_decided",
        {"rca_id": item.id, "decision": payload.decision},
    )
    db.commit()
    db.refresh(item)
    return _rca_response(item)


@router.get("/problems/{problem_id}/actions")
def list_actions(
    problem_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "problems.read")
    problem = _get_problem(db, problem_id, current_user)
    items = db.scalars(
        select(ProblemCorrectiveAction)
        .where(ProblemCorrectiveAction.problem_id == problem.id)
        .order_by(ProblemCorrectiveAction.due_at)
    ).all()
    return [_action_response(item) for item in items]


@router.post("/problems/{problem_id}/actions", status_code=status.HTTP_201_CREATED)
def create_action(
    problem_id: str,
    payload: ActionCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.investigate")
    problem = _get_problem(db, problem_id, current_user)
    owner = _actor(db, current_user)
    if payload.owner_id:
        candidate = db.get(User, payload.owner_id)
        if candidate is None or candidate.tenant_id != problem.tenant_id:
            raise HTTPException(status_code=404, detail="Action owner not found")
        owner = candidate
    item = ProblemCorrectiveAction(
        id=str(uuid.uuid4()),
        tenant_id=problem.tenant_id,
        problem_id=problem.id,
        action_type=payload.action_type,
        title=payload.title,
        description=payload.description,
        status="OPEN",
        is_required=payload.is_required,
        owner_id=owner.id,
        owner_name=owner.full_name,
        due_at=payload.due_at,
        effectiveness_criteria=payload.effectiveness_criteria,
        version=1,
    )
    db.add(item)
    _audit(
        db,
        request,
        current_user,
        action="problem.corrective_action_created",
        entity_type="problem_corrective_action",
        entity_id=item.id,
        tenant_id=problem.tenant_id,
        metadata={"problem_id": problem.id},
    )
    db.commit()
    db.refresh(item)
    return _action_response(item)


@router.patch("/problems/{problem_id}/actions/{action_id}")
def update_action(
    problem_id: str,
    action_id: str,
    payload: ActionUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.investigate")
    problem = _get_problem(db, problem_id, current_user)
    item = db.get(ProblemCorrectiveAction, action_id)
    if item is None or item.problem_id != problem.id:
        raise HTTPException(status_code=404, detail="Corrective action not found")
    _version(item.version, payload.expected_version, "Corrective action")
    if payload.status == "IMPLEMENTED" and not payload.implementation_evidence:
        raise HTTPException(status_code=422, detail="Implementation evidence is required")
    if payload.status in {"VERIFIED", "INEFFECTIVE"}:
        if payload.effectiveness_score is None or not payload.effectiveness_evidence:
            raise HTTPException(
                status_code=422,
                detail="Effectiveness review requires score and evidence",
            )
        if item.owner_id == current_user.id:
            raise HTTPException(
                status_code=409,
                detail="Action owner cannot review their own effectiveness",
            )
    item.status = payload.status
    if payload.implementation_evidence:
        item.implementation_evidence = payload.implementation_evidence
    if payload.status == "IMPLEMENTED":
        item.implemented_at = now_utc()
        item.review_due_at = payload.review_due_at or now_utc() + timedelta(days=14)
    if payload.status in {"VERIFIED", "INEFFECTIVE"}:
        item.effectiveness_score = payload.effectiveness_score
        item.effectiveness_evidence = payload.effectiveness_evidence
        item.reviewed_by_id = current_user.id
        item.reviewed_by_name = current_user.full_name
        item.reviewed_at = now_utc()
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action="problem.corrective_action_updated",
        entity_type="problem_corrective_action",
        entity_id=item.id,
        tenant_id=problem.tenant_id,
        metadata={"status": item.status},
    )
    db.commit()
    db.refresh(item)
    return _action_response(item)


@router.get("/trends")
def list_trends(
    tenant_id: str | None = Query(default=None),
    signal_status: str | None = Query(default=None, alias="status"),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "problems.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(ProblemTrendSignal)
    if scoped_tenant:
        statement = statement.where(ProblemTrendSignal.tenant_id == scoped_tenant)
    if signal_status:
        statement = statement.where(
            ProblemTrendSignal.status == signal_status.upper()
        )
    items = db.scalars(
        statement.order_by(
            ProblemTrendSignal.score.desc(),
            ProblemTrendSignal.updated_at.desc(),
        )
    ).all()
    return [_trend_response(item) for item in items]


@router.post("/trends/scan")
def scan_trends(
    request: Request,
    tenant_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=7, le=180),
    minimum_occurrences: int = Query(default=3, ge=2, le=100),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.investigate")
    scoped_tenant = _tenant_id(
        db, current_user, tenant_id, required_for_root=True
    )
    assert scoped_tenant is not None
    signals = scan_ticket_trends(
        db,
        scoped_tenant,
        days=days,
        minimum_occurrences=minimum_occurrences,
    )
    _audit(
        db,
        request,
        current_user,
        action="problem.trends_scanned",
        entity_type="problem_trend_signal",
        entity_id="scan",
        tenant_id=scoped_tenant,
        metadata={"days": days, "signals": len(signals)},
    )
    db.commit()
    return {"signals_created_or_refreshed": len(signals)}


@router.patch("/trends/{signal_id}")
def dispose_trend(
    signal_id: str,
    payload: TrendDisposition,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.investigate")
    item = db.get(ProblemTrendSignal, signal_id)
    if item is None or (
        not is_saas_root(current_user) and item.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Trend signal not found")
    _version(item.version, payload.expected_version, "Trend signal")
    item.disposition_comment = payload.comment
    item.disposition_by_id = current_user.id
    item.disposition_by_name = current_user.full_name
    item.disposition_at = now_utc()
    if payload.action == "ACKNOWLEDGE":
        item.status = "ACKNOWLEDGED"
    elif payload.action == "DISMISS":
        item.status = "DISMISSED"
    else:
        owner = _actor(db, current_user)
        if payload.owner_id:
            candidate = db.get(User, payload.owner_id)
            if candidate is None or candidate.tenant_id != item.tenant_id:
                raise HTTPException(status_code=404, detail="Problem owner not found")
            owner = candidate
        problem = Problem(
            id=str(uuid.uuid4()),
            tenant_id=item.tenant_id,
            problem_number=f"PRB-{now_utc().year}-{uuid.uuid4().hex[:8].upper()}",
            title=item.title,
            description=(
                f"Proactive problem created from trend signal {item.signature}. "
                f"{payload.comment}"
            ),
            problem_type="PROACTIVE",
            status="NEW",
            service_name=item.service_name,
            category=item.category,
            impact_level="HIGH" if item.score >= 75 else "MEDIUM",
            urgency_level="HIGH" if item.score >= 75 else "MEDIUM",
            priority="P2" if item.score >= 75 else "P3",
            detection_source="TREND_ANALYTICS",
            symptoms=f"{item.current_count} recurring incidents in trend window.",
            workaround_status="NONE",
            created_by_id=current_user.id,
            created_by_name=current_user.full_name,
            created_by_email=current_user.email,
            owner_id=owner.id,
            owner_name=owner.full_name,
            first_observed_at=item.window_start_at,
            version=1,
        )
        db.add(problem)
        db.flush()
        for ticket_id in item.incident_ids_json:
            db.add(
                ProblemTicketLink(
                    id=str(uuid.uuid4()),
                    tenant_id=item.tenant_id,
                    problem_id=problem.id,
                    ticket_id=ticket_id,
                )
            )
        _record_history(
            db,
            problem,
            current_user,
            event_type="TREND_CONVERTED",
            message="Trend signal converted into a proactive Problem",
            metadata={"trend_signal_id": item.id},
        )
        item.problem_id = problem.id
        item.status = "CONVERTED"
    item.version += 1
    item.updated_at = now_utc()
    _audit(
        db,
        request,
        current_user,
        action=f"problem.trend_{payload.action.lower()}",
        entity_type="problem_trend_signal",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"problem_id": item.problem_id},
    )
    db.commit()
    db.refresh(item)
    return _trend_response(item)


@router.post(
    "/known-errors/{problem_id}/usage",
    status_code=status.HTTP_201_CREATED,
)
def record_known_error_usage(
    problem_id: str,
    payload: KnownErrorUsageCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.read")
    problem = _get_problem(db, problem_id, current_user)
    if problem.known_error_published_at is None:
        raise HTTPException(status_code=409, detail="Known Error is not published")
    if payload.ticket_id:
        ticket = db.get(Ticket, payload.ticket_id)
        if ticket is None or ticket.tenant_id != problem.tenant_id:
            raise HTTPException(status_code=404, detail="Ticket not found")
    item = KnownErrorUsage(
        id=str(uuid.uuid4()),
        tenant_id=problem.tenant_id,
        problem_id=problem.id,
        ticket_id=payload.ticket_id,
        usage_type=payload.usage_type,
        minutes_saved=payload.minutes_saved,
        avoided_escalation=payload.avoided_escalation,
        comment=payload.comment,
        actor_id=current_user.id,
        actor_name=current_user.full_name,
    )
    db.add(item)
    _audit(
        db,
        request,
        current_user,
        action="problem.known_error_used",
        entity_type="known_error_usage",
        entity_id=item.id,
        tenant_id=problem.tenant_id,
        metadata={"problem_id": problem.id, "usage_type": payload.usage_type},
    )
    db.commit()
    return {"id": item.id, "created_at": item.created_at}


@router.get("/known-errors/metrics")
def known_error_metrics(
    tenant_id: str | None = Query(default=None),
    days: int = Query(default=90, ge=7, le=730),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    starts_at = now_utc() - timedelta(days=days)
    filters = [KnownErrorUsage.created_at >= starts_at]
    if scoped_tenant:
        filters.append(KnownErrorUsage.tenant_id == scoped_tenant)
    rows = list(db.scalars(select(KnownErrorUsage).where(*filters)).all())
    helpful = sum(item.usage_type == "HELPFUL" for item in rows)
    unhelpful = sum(item.usage_type == "NOT_HELPFUL" for item in rows)
    return {
        "period_start": starts_at,
        "period_end": now_utc(),
        "views": sum(item.usage_type == "VIEWED" for item in rows),
        "applications": sum(item.usage_type == "APPLIED" for item in rows),
        "helpful": helpful,
        "not_helpful": unhelpful,
        "helpfulness_percent": round(helpful * 100 / max(1, helpful + unhelpful), 1),
        "minutes_saved": sum(item.minutes_saved for item in rows),
        "avoided_escalations": sum(item.avoided_escalation for item in rows),
    }


@router.get("/analytics")
def analytics(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "problems.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    tenant_filters = (
        [ProblemCorrectiveAction.tenant_id == scoped_tenant]
        if scoped_tenant
        else []
    )
    actions = list(
        db.scalars(select(ProblemCorrectiveAction).where(*tenant_filters)).all()
    )
    now = now_utc()
    return {
        "total_actions": len(actions),
        "open_actions": sum(
            item.status in {"OPEN", "IN_PROGRESS", "IMPLEMENTED"} for item in actions
        ),
        "overdue_actions": sum(
            item.status in {"OPEN", "IN_PROGRESS"} and aware(item.due_at) < now
            for item in actions
        ),
        "verified_effective": sum(item.status == "VERIFIED" for item in actions),
        "ineffective": sum(item.status == "INEFFECTIVE" for item in actions),
        "average_effectiveness_score": round(
            sum(item.effectiveness_score or 0 for item in actions)
            / max(1, sum(item.effectiveness_score is not None for item in actions)),
            1,
        ),
        "open_trend_signals": int(
            db.scalar(
                select(func.count(ProblemTrendSignal.id)).where(
                    ProblemTrendSignal.status.in_({"OPEN", "ACKNOWLEDGED"}),
                    *(
                        [ProblemTrendSignal.tenant_id == scoped_tenant]
                        if scoped_tenant
                        else []
                    ),
                )
            )
            or 0
        ),
    }
