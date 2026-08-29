from __future__ import annotations

import json
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.ai_governance import (
    AiEvaluationCase,
    AiEvaluationDataset,
    AiEvaluationRun,
    AiPromptPolicy,
    AiPromptRollout,
    AiPromptVersion,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.ai.provider import get_provider
from app.services.ai_governance import (
    AiGovernanceError,
    canonical_json,
    digest,
    governance_dashboard,
    json_value,
    prompt_content_hash,
    prompt_integrity_valid,
    run_evaluation,
    utcnow,
    validate_case,
    validate_prompt,
)
from app.services.audit import log_audit
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/ai/governance")


class PolicyCreate(BaseModel):
    tenant_id: str | None = None
    code: str = Field(min_length=3, max_length=120, pattern=r"^[a-z][a-z0-9_.-]+$")
    name: str = Field(min_length=3, max_length=240)
    description: str | None = Field(default=None, max_length=4_000)
    use_case: Literal["ticket_classification", "grounded_answer"]


class VersionCreate(BaseModel):
    system_prompt: str = Field(min_length=20, max_length=30_000)
    provider: Literal["mock", "openai", "gemini"]
    model: str = Field(min_length=2, max_length=160)
    parameters: dict[str, Any] = Field(default_factory=dict)
    change_summary: str = Field(min_length=3, max_length=2_000)


class DatasetCreate(BaseModel):
    tenant_id: str | None = None
    code: str = Field(min_length=3, max_length=120, pattern=r"^[a-z][a-z0-9_.-]+$")
    name: str = Field(min_length=3, max_length=240)
    description: str | None = Field(default=None, max_length=4_000)
    use_case: Literal["ticket_classification", "grounded_answer"]


class CaseCreate(BaseModel):
    case_key: str = Field(min_length=2, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    input_text: str = Field(min_length=3, max_length=20_000)
    sources: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    expected: dict[str, Any]
    forbidden_terms: list[str] = Field(default_factory=list, max_length=50)
    weight: float = Field(default=1.0, gt=0, le=10)


class EvaluationRequest(BaseModel):
    dataset_id: str
    baseline_version_id: str | None = None
    thresholds: dict[str, float] = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    comment: str = Field(min_length=3, max_length=2_000)


class RolloutRequest(BaseModel):
    canary_percent: int = Field(default=10, ge=0, le=100)
    reason: str = Field(min_length=3, max_length=2_000)


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
        raise HTTPException(status_code=404, detail="AI governance resource not found")


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


def _policy(db: Session, item_id: str, user: AuthUserResponse) -> AiPromptPolicy:
    item = db.get(AiPromptPolicy, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Prompt policy not found")
    _scope(user, item.tenant_id)
    return item


def _version(db: Session, item_id: str, user: AuthUserResponse) -> AiPromptVersion:
    item = db.get(AiPromptVersion, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    _scope(user, item.tenant_id)
    return item


def _dataset(db: Session, item_id: str, user: AuthUserResponse) -> AiEvaluationDataset:
    item = db.get(AiEvaluationDataset, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evaluation dataset not found")
    _scope(user, item.tenant_id)
    return item


def _policy_out(item: AiPromptPolicy) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "use_case": item.use_case,
        "status": item.status,
        "active_version_id": item.active_version_id,
        "revision": item.revision,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _version_out(item: AiPromptVersion) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "policy_id": item.policy_id,
        "version_number": item.version_number,
        "status": item.status,
        "system_prompt": item.system_prompt,
        "provider": item.provider,
        "model": item.model,
        "parameters": json_value(item.parameters_json, {}),
        "content_sha256": item.content_sha256,
        "change_summary": item.change_summary,
        "evaluation_run_id": item.evaluation_run_id,
        "reviewed_by_id": item.reviewed_by_id,
        "review_comment": item.review_comment,
        "reviewed_at": item.reviewed_at,
        "activated_at": item.activated_at,
        "created_at": item.created_at,
    }


@router.get("/dashboard")
def dashboard(
    tenant_id: str | None = Query(default=None),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.governance.read")
    return governance_dashboard(db, _tenant(db, user, tenant_id))


@router.get("/policies")
def list_policies(
    tenant_id: str | None = Query(default=None),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "ai.governance.read")
    scope = _tenant(db, user, tenant_id)
    return [
        _policy_out(item)
        for item in db.scalars(
            select(AiPromptPolicy)
            .where(AiPromptPolicy.tenant_id == scope)
            .order_by(AiPromptPolicy.code)
        ).all()
    ]


@router.post("/policies", status_code=201)
def create_policy(
    payload: PolicyCreate,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.governance.manage")
    tenant_id = _tenant(db, user, payload.tenant_id)
    existing_use_case = db.scalar(
        select(AiPromptPolicy.id).where(
            AiPromptPolicy.tenant_id == tenant_id,
            AiPromptPolicy.use_case == payload.use_case,
            AiPromptPolicy.status == "ACTIVE",
        )
    )
    if existing_use_case:
        raise HTTPException(
            status_code=409,
            detail="An active prompt policy already exists for this use case",
        )
    item = AiPromptPolicy(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        use_case=payload.use_case,
        status="ACTIVE",
        created_by_id=user.id,
    )
    db.add(item)
    _audit(db, request, user, "ai.prompt.policy.create", "ai_prompt_policy", item.id, tenant_id, {"code": item.code, "use_case": item.use_case})
    db.commit()
    db.refresh(item)
    return _policy_out(item)


@router.get("/policies/{policy_id}/versions")
def list_versions(
    policy_id: str,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "ai.governance.read")
    policy = _policy(db, policy_id, user)
    return [
        _version_out(item)
        for item in db.scalars(
            select(AiPromptVersion)
            .where(AiPromptVersion.policy_id == policy.id)
            .order_by(AiPromptVersion.version_number.desc())
        ).all()
    ]


@router.post("/policies/{policy_id}/versions", status_code=201)
def create_version(
    policy_id: str,
    payload: VersionCreate,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.governance.manage")
    policy = _policy(db, policy_id, user)
    try:
        validate_prompt(payload.system_prompt, payload.parameters)
    except AiGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    number = (db.scalar(select(func.max(AiPromptVersion.version_number)).where(AiPromptVersion.policy_id == policy.id)) or 0) + 1
    item = AiPromptVersion(
        id=str(uuid.uuid4()),
        tenant_id=policy.tenant_id,
        policy_id=policy.id,
        version_number=number,
        status="DRAFT",
        system_prompt=payload.system_prompt,
        provider=payload.provider,
        model=payload.model,
        parameters_json=canonical_json(payload.parameters),
        content_sha256=prompt_content_hash(payload.system_prompt, payload.provider, payload.model, payload.parameters),
        change_summary=payload.change_summary,
        created_by_id=user.id,
    )
    db.add(item)
    _audit(db, request, user, "ai.prompt.version.create", "ai_prompt_version", item.id, policy.tenant_id, {"version": number, "hash": item.content_sha256})
    db.commit()
    db.refresh(item)
    return _version_out(item)


@router.get("/datasets")
def list_datasets(
    tenant_id: str | None = Query(default=None),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "ai.governance.read")
    scope = _tenant(db, user, tenant_id)
    return [
        {
            "id": item.id, "code": item.code, "name": item.name,
            "use_case": item.use_case, "status": item.status,
            "description": item.description, "revision": item.revision,
        }
        for item in db.scalars(select(AiEvaluationDataset).where(AiEvaluationDataset.tenant_id == scope).order_by(AiEvaluationDataset.code)).all()
    ]


@router.post("/datasets", status_code=201)
def create_dataset(
    payload: DatasetCreate,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.governance.manage")
    tenant_id = _tenant(db, user, payload.tenant_id)
    item = AiEvaluationDataset(
        id=str(uuid.uuid4()), tenant_id=tenant_id, code=payload.code,
        name=payload.name, description=payload.description,
        use_case=payload.use_case, status="DRAFT", created_by_id=user.id,
    )
    db.add(item)
    _audit(db, request, user, "ai.evaluation.dataset.create", "ai_evaluation_dataset", item.id, tenant_id, {"code": item.code})
    db.commit()
    return {"id": item.id, "code": item.code, "name": item.name, "use_case": item.use_case, "status": item.status}


@router.post("/datasets/{dataset_id}/cases", status_code=201)
def create_case(
    dataset_id: str,
    payload: CaseCreate,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.governance.manage")
    dataset = _dataset(db, dataset_id, user)
    if dataset.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail="Dataset is archived")
    try:
        validate_case(input_text=payload.input_text, sources=payload.sources, expected=payload.expected, forbidden_terms=payload.forbidden_terms)
    except AiGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    content = {"input": payload.input_text, "sources": payload.sources, "expected": payload.expected, "forbidden_terms": payload.forbidden_terms}
    item = AiEvaluationCase(
        id=str(uuid.uuid4()), tenant_id=dataset.tenant_id,
        dataset_id=dataset.id, case_key=payload.case_key,
        input_text=payload.input_text, sources_json=canonical_json(payload.sources),
        expected_json=canonical_json(payload.expected),
        forbidden_terms_json=canonical_json(payload.forbidden_terms),
        weight=payload.weight, content_sha256=digest(content),
    )
    db.add(item)
    dataset.revision += 1
    _audit(db, request, user, "ai.evaluation.case.create", "ai_evaluation_case", item.id, dataset.tenant_id, {"case_key": item.case_key, "hash": item.content_sha256})
    db.commit()
    return {"id": item.id, "case_key": item.case_key, "content_sha256": item.content_sha256}


@router.get("/datasets/{dataset_id}/cases")
def list_cases(
    dataset_id: str,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "ai.governance.read")
    dataset = _dataset(db, dataset_id, user)
    return [
        {
            "id": item.id,
            "case_key": item.case_key,
            "input_text": item.input_text,
            "sources": json.loads(item.sources_json),
            "expected": json.loads(item.expected_json),
            "forbidden_terms": json.loads(item.forbidden_terms_json),
            "weight": item.weight,
            "is_active": item.is_active,
            "content_sha256": item.content_sha256,
        }
        for item in db.scalars(
            select(AiEvaluationCase)
            .where(AiEvaluationCase.dataset_id == dataset.id)
            .order_by(AiEvaluationCase.case_key)
        ).all()
    ]


@router.get("/evaluation-runs")
def list_evaluation_runs(
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "ai.governance.read")
    scope = _tenant(db, user, tenant_id)
    return [
        {
            "id": item.id,
            "prompt_version_id": item.prompt_version_id,
            "dataset_id": item.dataset_id,
            "baseline_version_id": item.baseline_version_id,
            "status": item.status,
            "passed": item.passed,
            "case_count": item.case_count,
            "metrics": json.loads(item.metrics_json),
            "regression": json.loads(item.regression_json),
            "evidence_sha256": item.evidence_sha256,
            "started_at": item.started_at,
            "completed_at": item.completed_at,
        }
        for item in db.scalars(
            select(AiEvaluationRun)
            .where(AiEvaluationRun.tenant_id == scope)
            .order_by(AiEvaluationRun.created_at.desc())
            .limit(limit)
        ).all()
    ]


@router.post("/versions/{version_id}/evaluate")
async def evaluate_version(
    version_id: str,
    payload: EvaluationRequest,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.governance.evaluate")
    version = _version(db, version_id, user)
    dataset = _dataset(db, payload.dataset_id, user)
    policy = _policy(db, version.policy_id, user)
    if dataset.use_case != policy.use_case:
        raise HTTPException(status_code=422, detail="Dataset use case does not match prompt policy")
    baseline = _version(db, payload.baseline_version_id, user) if payload.baseline_version_id else None
    provider = get_provider()
    if version.provider != provider.name or version.model != provider.model:
        raise HTTPException(
            status_code=409,
            detail="Prompt version provider/model does not match the configured active provider",
        )
    try:
        run = await run_evaluation(db, version=version, dataset=dataset, baseline=baseline, thresholds=payload.thresholds, provider=provider, actor_id=user.id)
    except AiGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(db, request, user, "ai.evaluation.run", "ai_evaluation_run", run.id, version.tenant_id, {"passed": run.passed, "evidence_sha256": run.evidence_sha256})
    db.commit()
    return {"id": run.id, "status": run.status, "passed": run.passed, "case_count": run.case_count, "metrics": json.loads(run.metrics_json), "regression": json.loads(run.regression_json), "evidence_sha256": run.evidence_sha256}


@router.post("/versions/{version_id}/review")
def review_version(
    version_id: str,
    payload: ReviewRequest,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.governance.approve")
    version = _version(db, version_id, user)
    if version.created_by_id == user.id:
        raise HTTPException(status_code=409, detail="Independent reviewer is required")
    if version.status != "EVALUATED":
        raise HTTPException(status_code=409, detail="Only a passed evaluated version can be reviewed")
    evaluation = (
        db.get(AiEvaluationRun, version.evaluation_run_id)
        if version.evaluation_run_id
        else None
    )
    if (
        evaluation is None
        or not evaluation.passed
        or evaluation.prompt_version_id != version.id
        or not prompt_integrity_valid(version)
    ):
        raise HTTPException(
            status_code=409,
            detail="Passed evaluation evidence and prompt integrity are required",
        )
    version.status = payload.decision
    version.reviewed_by_id = user.id
    version.review_comment = payload.comment
    version.reviewed_at = utcnow()
    _audit(db, request, user, "ai.prompt.version.review", "ai_prompt_version", version.id, version.tenant_id, {"decision": payload.decision, "hash": version.content_sha256})
    db.commit()
    return _version_out(version)


@router.post("/versions/{version_id}/rollout")
def rollout_version(
    version_id: str,
    payload: RolloutRequest,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.governance.deploy")
    version = _version(db, version_id, user)
    policy = _policy(db, version.policy_id, user)
    if version.status != "APPROVED" or user.id in {
        version.created_by_id,
        version.reviewed_by_id,
    }:
        raise HTTPException(
            status_code=409,
            detail="Deployment actor must be independent from author and reviewer",
        )
    if not prompt_integrity_valid(version):
        raise HTTPException(status_code=409, detail="Prompt version integrity failed")
    previous = db.get(AiPromptVersion, policy.active_version_id) if policy.active_version_id else None
    rollout = AiPromptRollout(
        id=str(uuid.uuid4()), tenant_id=version.tenant_id, policy_id=policy.id,
        prompt_version_id=version.id, previous_version_id=previous.id if previous else None,
        status="CANARY" if payload.canary_percent < 100 else "ACTIVE",
        canary_percent=payload.canary_percent, requested_by_id=version.created_by_id,
        approved_by_id=user.id, reason=payload.reason,
        metrics_snapshot_json="{}", activated_at=utcnow(),
    )
    db.add(rollout)
    if payload.canary_percent == 100:
        if previous:
            previous.status = "RETIRED"
            previous.retired_at = utcnow()
        version.status = "ACTIVE"
        version.activated_by_id = user.id
        version.activated_at = utcnow()
        policy.active_version_id = version.id
        policy.revision += 1
    _audit(db, request, user, "ai.prompt.rollout", "ai_prompt_rollout", rollout.id, version.tenant_id, {"canary_percent": payload.canary_percent, "version_hash": version.content_sha256})
    db.commit()
    return {"id": rollout.id, "status": rollout.status, "canary_percent": rollout.canary_percent, "previous_version_id": rollout.previous_version_id}


@router.post("/rollouts/{rollout_id}/rollback")
def rollback_rollout(
    rollout_id: str,
    request: Request,
    reason: str = Query(min_length=3, max_length=2_000),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.governance.deploy")
    rollout = db.get(AiPromptRollout, rollout_id)
    if rollout is None:
        raise HTTPException(status_code=404, detail="Rollout not found")
    _scope(user, rollout.tenant_id)
    if rollout.status not in {"CANARY", "ACTIVE"}:
        raise HTTPException(status_code=409, detail="Rollout cannot be rolled back")
    policy = db.get(AiPromptPolicy, rollout.policy_id)
    current = db.get(AiPromptVersion, rollout.prompt_version_id)
    previous = db.get(AiPromptVersion, rollout.previous_version_id) if rollout.previous_version_id else None
    rollout.status = "ROLLED_BACK"
    rollout.reason = f"{rollout.reason}\nROLLBACK: {reason}"
    rollout.rolled_back_at = utcnow()
    if current and current.status == "ACTIVE":
        current.status = "RETIRED"
        current.retired_at = utcnow()
    if policy:
        policy.active_version_id = previous.id if previous else None
        policy.revision += 1
    if previous:
        previous.status = "ACTIVE"
        previous.retired_at = None
    _audit(db, request, user, "ai.prompt.rollout.rollback", "ai_prompt_rollout", rollout.id, rollout.tenant_id, {"reason": reason, "restored_version_id": rollout.previous_version_id})
    db.commit()
    return {"id": rollout.id, "status": rollout.status, "restored_version_id": rollout.previous_version_id}
