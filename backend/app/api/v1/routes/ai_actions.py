from __future__ import annotations

from datetime import timedelta
import json
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.ai_actions import (
    AiActionExecution,
    AiActionPolicy,
    AiActionProposal,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.ai_actions import (
    ACTION_SPECS,
    AiActionError,
    aware,
    canonical_json,
    digest,
    execute_proposal,
    json_value,
    rollback_execution,
    safe_citation_evidence,
    target_fingerprint,
    utcnow,
    validate_parameters,
)
from app.services.ai_retrieval import detects_prompt_injection
from app.services.audit import log_audit
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/ai/actions")
ActionType = Literal[
    "ticket.update", "ticket.classify", "knowledge.draft", "runbook.draft"
]


class ActionPolicyUpdate(BaseModel):
    tenant_id: str | None = None
    expected_revision: int = Field(default=0, ge=0)
    enabled: bool = True
    allowed_actions: list[ActionType] = Field(min_length=1, max_length=4)
    independent_approval_for_high_risk: bool = True
    proposal_ttl_minutes: int = Field(default=1_440, ge=5, le=10_080)


class ProposalCreate(BaseModel):
    tenant_id: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=120)
    action_type: ActionType
    target_id: str | None = Field(default=None, max_length=120)
    parameters: dict[str, Any]
    source_query: str | None = Field(default=None, max_length=4_000)
    citations: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    rationale: str = Field(min_length=3, max_length=4_000)


class DecisionRequest(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    comment: str = Field(min_length=3, max_length=2_000)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2_000)


_ACTION_EXECUTION_PERMISSIONS = {
    "ticket.update": ("tickets.read", "tickets.update"),
    "ticket.classify": ("tickets.read", "tickets.update"),
    "knowledge.draft": ("knowledge.create",),
    "runbook.draft": ("automation.runbooks.create",),
}


def _tenant(db: Session, user: AuthUserResponse, requested: str | None) -> str:
    if not is_saas_root(user):
        if not user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        if requested and requested != user.tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return user.tenant_id
    if not requested or db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="A valid tenant_id is required")
    return requested


def _scope(user: AuthUserResponse, tenant_id: str) -> None:
    if not is_saas_root(user) and user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="AI action proposal not found")


def _audit(
    db: Session,
    request: Request,
    user: AuthUserResponse,
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
        actor_user=db.get(User, user.id),
        actor_email=user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _proposal(
    db: Session,
    proposal_id: str,
    user: AuthUserResponse,
    *,
    lock: bool = False,
) -> AiActionProposal:
    statement = select(AiActionProposal).where(AiActionProposal.id == proposal_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="AI action proposal not found")
    _scope(user, item.tenant_id)
    return item


def _out(item: AiActionProposal) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "proposal_number": item.proposal_number,
        "idempotency_key": item.idempotency_key,
        "action_type": item.action_type,
        "risk_level": item.risk_level,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "target_fingerprint": item.target_fingerprint,
        "parameters": json_value(item.parameters_json, {}),
        "parameters_sha256": item.parameters_sha256,
        "citation_evidence": json_value(item.citation_evidence_json, []),
        "rationale": item.rationale,
        "status": item.status,
        "created_by_id": item.created_by_id,
        "reviewed_by_id": item.reviewed_by_id,
        "review_comment": item.review_comment,
        "reviewed_at": item.reviewed_at,
        "executed_by_id": item.executed_by_id,
        "executed_at": item.executed_at,
        "expires_at": item.expires_at,
        "error_code": item.error_code,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/meta")
def meta(
    tenant_id: str | None = Query(default=None),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.actions.read")
    scope = _tenant(db, user, tenant_id)
    policy = db.scalar(
        select(AiActionPolicy).where(AiActionPolicy.tenant_id == scope)
    )
    counts = {
        status: db.scalar(
            select(func.count(AiActionProposal.id)).where(
                AiActionProposal.tenant_id == scope,
                AiActionProposal.status == status,
            )
        )
        or 0
        for status in ("PROPOSED", "APPROVED", "EXECUTED", "FAILED", "ROLLED_BACK")
    }
    return {
        "server_action_allowlist": list(ACTION_SPECS),
        "policy": (
            {
                "id": policy.id,
                "enabled": policy.enabled,
                "allowed_actions": json.loads(policy.allowed_actions_json),
                "independent_approval_for_high_risk": policy.independent_approval_for_high_risk,
                "proposal_ttl_minutes": policy.proposal_ttl_minutes,
                "revision": policy.revision,
            }
            if policy
            else None
        ),
        "counts": counts,
    }


@router.put("/policy")
def update_policy(
    payload: ActionPolicyUpdate,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.actions.manage")
    scope = _tenant(db, user, payload.tenant_id)
    allowed = sorted(set(payload.allowed_actions))
    if set(allowed) - set(ACTION_SPECS):
        raise HTTPException(status_code=422, detail="Unsupported action type")
    item = db.scalar(
        select(AiActionPolicy).where(AiActionPolicy.tenant_id == scope)
    )
    if item is None:
        if payload.expected_revision != 0:
            raise HTTPException(status_code=409, detail="Action policy revision conflict")
        item = AiActionPolicy(id=str(uuid.uuid4()), tenant_id=scope)
        db.add(item)
    elif item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Action policy revision conflict")
    item.enabled = payload.enabled
    item.allowed_actions_json = canonical_json(allowed)
    item.independent_approval_for_high_risk = payload.independent_approval_for_high_risk
    item.proposal_ttl_minutes = payload.proposal_ttl_minutes
    item.updated_by_id = user.id
    item.revision = 1 if payload.expected_revision == 0 else item.revision + 1
    _audit(
        db, request, user, "ai.actions.policy.update", "ai_action_policy",
        item.id, scope,
        {
            "enabled": item.enabled,
            "allowed_actions": allowed,
            "independent_approval_for_high_risk": item.independent_approval_for_high_risk,
            "proposal_ttl_minutes": item.proposal_ttl_minutes,
            "revision": item.revision,
        },
    )
    db.commit()
    return {
        "id": item.id,
        "enabled": item.enabled,
        "allowed_actions": allowed,
        "independent_approval_for_high_risk": item.independent_approval_for_high_risk,
        "proposal_ttl_minutes": item.proposal_ttl_minutes,
        "revision": item.revision,
    }


@router.get("/proposals")
def list_proposals(
    tenant_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "ai.actions.read")
    scope = _tenant(db, user, tenant_id)
    statement = select(AiActionProposal).where(AiActionProposal.tenant_id == scope)
    if status_filter:
        statement = statement.where(AiActionProposal.status == status_filter.upper())
    items = db.scalars(
        statement.order_by(AiActionProposal.created_at.desc()).limit(limit)
    ).all()
    return [_out(item) for item in items]


@router.post("/proposals", status_code=201)
def create_proposal(
    payload: ProposalCreate,
    request: Request,
    response: Response,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.actions.propose")
    scope = _tenant(db, user, payload.tenant_id)
    policy = db.scalar(
        select(AiActionPolicy).where(AiActionPolicy.tenant_id == scope)
    )
    if policy is None or not policy.enabled:
        raise HTTPException(status_code=409, detail="Guarded AI actions are not enabled")
    if payload.action_type not in set(json_value(policy.allowed_actions_json, [])):
        raise HTTPException(status_code=403, detail="Action type is not allowed by tenant policy")
    require_permissions(user, *_ACTION_EXECUTION_PERMISSIONS[payload.action_type])
    if detects_prompt_injection(payload.rationale):
        raise HTTPException(status_code=422, detail="Proposal rationale contains prompt injection")
    try:
        parameters = validate_parameters(payload.action_type, dict(payload.parameters))
        citations = safe_citation_evidence(payload.citations)
        fingerprint = target_fingerprint(
            db, scope, payload.action_type, payload.target_id
        )
    except AiActionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    existing = db.scalar(
        select(AiActionProposal).where(
            AiActionProposal.tenant_id == scope,
            AiActionProposal.idempotency_key == payload.idempotency_key,
        )
    )
    parameters_hash = digest(parameters)
    if existing:
        if (
            existing.parameters_sha256 == parameters_hash
            and existing.action_type == payload.action_type
            and existing.target_id == payload.target_id
        ):
            response.status_code = 200
            return _out(existing)
        raise HTTPException(status_code=409, detail="Idempotency key payload conflict")
    now = utcnow()
    item = AiActionProposal(
        id=str(uuid.uuid4()),
        tenant_id=scope,
        proposal_number=f"AIA-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
        idempotency_key=payload.idempotency_key,
        action_type=payload.action_type,
        risk_level=str(ACTION_SPECS[payload.action_type]["risk"]),
        target_type=str(ACTION_SPECS[payload.action_type]["target_type"]),
        target_id=payload.target_id,
        target_fingerprint=fingerprint,
        parameters_json=canonical_json(parameters),
        parameters_sha256=parameters_hash,
        source_query_sha256=digest(payload.source_query) if payload.source_query else None,
        citation_evidence_json=canonical_json(citations),
        rationale=payload.rationale,
        status="PROPOSED",
        created_by_id=user.id,
        expires_at=now + timedelta(minutes=policy.proposal_ttl_minutes),
    )
    db.add(item)
    _audit(
        db, request, user, "ai.actions.proposal.create", "ai_action_proposal",
        item.id, scope,
        {
            "proposal_number": item.proposal_number,
            "action_type": item.action_type,
            "risk_level": item.risk_level,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "parameters_sha256": item.parameters_sha256,
            "citation_count": len(citations),
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Proposal conflict") from exc
    db.refresh(item)
    return _out(item)


@router.post("/proposals/{proposal_id}/decision")
def decide_proposal(
    proposal_id: str,
    payload: DecisionRequest,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.actions.approve")
    item = _proposal(db, proposal_id, user, lock=True)
    if item.status != "PROPOSED":
        raise HTTPException(status_code=409, detail="Proposal is not pending review")
    if aware(item.expires_at) <= utcnow():
        item.status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=409, detail="Proposal has expired")
    policy = db.scalar(
        select(AiActionPolicy).where(AiActionPolicy.tenant_id == item.tenant_id)
    )
    if (
        payload.decision == "APPROVED"
        and item.risk_level == "HIGH"
        and (policy is None or policy.independent_approval_for_high_risk)
        and item.created_by_id == user.id
    ):
        raise HTTPException(status_code=409, detail="Independent approval is required")
    item.status = payload.decision
    item.reviewed_by_id = user.id
    item.review_comment = payload.comment
    item.reviewed_at = utcnow()
    _audit(
        db, request, user, "ai.actions.proposal.decision", "ai_action_proposal",
        item.id, item.tenant_id,
        {
            "decision": payload.decision,
            "parameters_sha256": item.parameters_sha256,
            "target_fingerprint": item.target_fingerprint,
        },
    )
    db.commit()
    return _out(item)


@router.post("/proposals/{proposal_id}/execute")
def execute_action(
    proposal_id: str,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.actions.execute")
    item = _proposal(db, proposal_id, user, lock=True)
    require_permissions(user, *_ACTION_EXECUTION_PERMISSIONS[item.action_type])
    policy = db.scalar(
        select(AiActionPolicy).where(AiActionPolicy.tenant_id == item.tenant_id)
    )
    if (
        policy is None
        or not policy.enabled
        or item.action_type not in set(json_value(policy.allowed_actions_json, []))
    ):
        raise HTTPException(status_code=409, detail="Action is no longer allowed")
    try:
        execution = execute_proposal(
            db, item, actor_id=user.id, actor_name=user.full_name
        )
    except AiActionError as exc:
        item.status = "FAILED"
        item.error_code = str(exc)[:120]
        _audit(
            db, request, user, "ai.actions.execution.failed", "ai_action_proposal",
            item.id, item.tenant_id,
            {"error_code": item.error_code, "parameters_sha256": item.parameters_sha256},
        )
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db, request, user, "ai.actions.execution.succeeded", "ai_action_execution",
        execution.id, item.tenant_id,
        {
            "proposal_id": item.id,
            "action_type": item.action_type,
            "target_type": execution.target_type,
            "target_id": execution.target_id,
            "before_sha256": execution.before_sha256,
            "after_sha256": execution.after_sha256,
        },
    )
    db.commit()
    return {
        "id": execution.id,
        "proposal_id": execution.proposal_id,
        "status": execution.status,
        "target_type": execution.target_type,
        "target_id": execution.target_id,
        "before_sha256": execution.before_sha256,
        "after_sha256": execution.after_sha256,
        "result": json.loads(execution.result_json),
    }


@router.post("/proposals/{proposal_id}/rollback")
def rollback_action(
    proposal_id: str,
    payload: ReasonRequest,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.actions.rollback")
    item = _proposal(db, proposal_id, user, lock=True)
    execution = db.scalar(
        select(AiActionExecution).where(AiActionExecution.proposal_id == item.id)
    )
    if execution is None:
        raise HTTPException(status_code=404, detail="Action execution not found")
    try:
        rollback_execution(
            db,
            execution,
            item,
            actor_id=user.id,
            actor_name=user.full_name,
            reason=payload.reason,
        )
    except AiActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db, request, user, "ai.actions.execution.rolled_back", "ai_action_execution",
        execution.id, item.tenant_id,
        {
            "proposal_id": item.id,
            "reason": payload.reason,
            "before_sha256": execution.before_sha256,
            "after_sha256": execution.after_sha256,
        },
    )
    db.commit()
    return {
        "id": execution.id,
        "proposal_id": item.id,
        "status": execution.status,
        "rollback_reason": execution.rollback_reason,
        "rolled_back_at": execution.rolled_back_at,
    }
