from __future__ import annotations

import json
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.ai_runtime_controls import (
    AiDataPolicy,
    AiProviderCircuit,
    AiUsageBudget,
    AiUsageLedger,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.ai_runtime_controls import runtime_dashboard, utcnow
from app.services.audit import log_audit
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/ai/runtime-controls")


class DataPolicyUpdate(BaseModel):
    tenant_id: str | None = None
    expected_revision: int = Field(default=0, ge=0)
    external_processing_enabled: bool
    allowed_providers: list[Literal["openai", "gemini"]] = Field(max_length=2)
    provider_regions: dict[str, str]
    maximum_external_classification: Literal[
        "PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"
    ] = "INTERNAL"
    pii_redaction_required: bool = True
    allow_reversible_redaction: bool = True
    retention_days: int = Field(default=180, ge=30, le=2_555)


class BudgetUpdate(BaseModel):
    tenant_id: str | None = None
    expected_revision: int = Field(default=0, ge=0)
    monthly_request_limit: int = Field(ge=0, le=10_000_000)
    monthly_cost_limit_usd: float = Field(ge=0, le=1_000_000)
    daily_request_limit: int = Field(ge=0, le=1_000_000)
    warning_percent: int = Field(default=80, ge=1, le=100)
    hard_limit_enabled: bool = True


class RetentionPurgeRequest(BaseModel):
    tenant_id: str | None = None
    confirm: bool
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


@router.get("/dashboard")
def dashboard(
    tenant_id: str | None = Query(default=None),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.runtime.read")
    return runtime_dashboard(db, _tenant(db, user, tenant_id))


@router.put("/data-policy")
def update_data_policy(
    payload: DataPolicyUpdate,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.runtime.manage")
    tenant_id = _tenant(db, user, payload.tenant_id)
    if set(payload.provider_regions) - set(payload.allowed_providers):
        raise HTTPException(
            status_code=422,
            detail="Regions may be configured only for allowed providers",
        )
    if payload.external_processing_enabled and any(
        not payload.provider_regions.get(provider, "").strip()
        for provider in payload.allowed_providers
    ):
        raise HTTPException(
            status_code=422,
            detail="Every allowed external provider requires an explicit region",
        )
    item = db.scalar(
        select(AiDataPolicy).where(AiDataPolicy.tenant_id == tenant_id)
    )
    if item is None:
        if payload.expected_revision != 0:
            raise HTTPException(status_code=409, detail="Data policy revision conflict")
        item = AiDataPolicy(id=str(uuid.uuid4()), tenant_id=tenant_id)
        db.add(item)
    elif item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Data policy revision conflict")
    item.external_processing_enabled = payload.external_processing_enabled
    item.allowed_providers_json = json.dumps(
        sorted(set(payload.allowed_providers)), separators=(",", ":")
    )
    item.provider_regions_json = json.dumps(
        payload.provider_regions, separators=(",", ":"), sort_keys=True
    )
    item.maximum_external_classification = payload.maximum_external_classification
    item.pii_redaction_required = payload.pii_redaction_required
    item.allow_reversible_redaction = payload.allow_reversible_redaction
    item.retention_days = payload.retention_days
    item.updated_by_id = user.id
    item.revision = 1 if payload.expected_revision == 0 else item.revision + 1
    _audit(
        db, request, user, "ai.runtime.data_policy.update", "ai_data_policy",
        item.id, tenant_id,
        {
            "external_processing_enabled": item.external_processing_enabled,
            "allowed_providers": sorted(set(payload.allowed_providers)),
            "provider_regions": payload.provider_regions,
            "maximum_external_classification": item.maximum_external_classification,
            "pii_redaction_required": item.pii_redaction_required,
            "retention_days": item.retention_days,
            "revision": item.revision,
        },
    )
    db.commit()
    return {
        "id": item.id,
        "revision": item.revision,
        "external_processing_enabled": item.external_processing_enabled,
        "allowed_providers": json.loads(item.allowed_providers_json),
        "provider_regions": json.loads(item.provider_regions_json),
        "maximum_external_classification": item.maximum_external_classification,
        "pii_redaction_required": item.pii_redaction_required,
        "allow_reversible_redaction": item.allow_reversible_redaction,
        "retention_days": item.retention_days,
    }


@router.put("/budget")
def update_budget(
    payload: BudgetUpdate,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.runtime.manage")
    tenant_id = _tenant(db, user, payload.tenant_id)
    item = db.scalar(
        select(AiUsageBudget).where(AiUsageBudget.tenant_id == tenant_id)
    )
    if item is None:
        if payload.expected_revision != 0:
            raise HTTPException(status_code=409, detail="Budget revision conflict")
        item = AiUsageBudget(id=str(uuid.uuid4()), tenant_id=tenant_id)
        db.add(item)
    elif item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Budget revision conflict")
    item.monthly_request_limit = payload.monthly_request_limit
    item.monthly_cost_limit_usd = payload.monthly_cost_limit_usd
    item.daily_request_limit = payload.daily_request_limit
    item.warning_percent = payload.warning_percent
    item.hard_limit_enabled = payload.hard_limit_enabled
    item.updated_by_id = user.id
    item.revision = 1 if payload.expected_revision == 0 else item.revision + 1
    _audit(
        db, request, user, "ai.runtime.budget.update", "ai_usage_budget",
        item.id, tenant_id,
        {
            "monthly_request_limit": item.monthly_request_limit,
            "monthly_cost_limit_usd": item.monthly_cost_limit_usd,
            "daily_request_limit": item.daily_request_limit,
            "warning_percent": item.warning_percent,
            "hard_limit_enabled": item.hard_limit_enabled,
            "revision": item.revision,
        },
    )
    db.commit()
    return {
        "id": item.id,
        "revision": item.revision,
        "monthly_request_limit": item.monthly_request_limit,
        "monthly_cost_limit_usd": item.monthly_cost_limit_usd,
        "daily_request_limit": item.daily_request_limit,
        "warning_percent": item.warning_percent,
        "hard_limit_enabled": item.hard_limit_enabled,
    }


@router.get("/usage")
def list_usage(
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "ai.runtime.audit")
    scope = _tenant(db, user, tenant_id)
    items = db.scalars(
        select(AiUsageLedger)
        .where(AiUsageLedger.tenant_id == scope)
        .order_by(AiUsageLedger.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": item.id,
            "user_id": item.user_id,
            "operation": item.operation,
            "requested_provider": item.requested_provider,
            "provider": item.provider,
            "model": item.model,
            "provider_region": item.provider_region,
            "data_classification": item.data_classification,
            "pii_redacted": item.pii_redacted,
            "input_sha256": item.input_sha256,
            "output_sha256": item.output_sha256,
            "input_tokens_estimated": item.input_tokens_estimated,
            "output_tokens_estimated": item.output_tokens_estimated,
            "estimated_cost_usd": item.estimated_cost_usd,
            "latency_ms": item.latency_ms,
            "outcome": item.outcome,
            "fallback_reason": item.fallback_reason,
            "prompt_version_id": item.prompt_version_id,
            "correlation_sha256": item.correlation_sha256,
            "created_at": item.created_at,
        }
        for item in items
    ]


@router.post("/circuits/{provider}/reset")
def reset_circuit(
    provider: Literal["openai", "gemini"],
    request: Request,
    tenant_id: str | None = Query(default=None),
    reason: str = Query(min_length=3, max_length=2_000),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.runtime.manage")
    scope = _tenant(db, user, tenant_id)
    item = db.scalar(
        select(AiProviderCircuit).where(
            AiProviderCircuit.tenant_id == scope,
            AiProviderCircuit.provider == provider,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Provider circuit not found")
    item.state = "CLOSED"
    item.consecutive_failures = 0
    item.opened_at = None
    item.open_until = None
    item.probe_started_at = None
    item.last_failure_code = None
    item.last_success_at = utcnow()
    item.revision += 1
    _audit(
        db, request, user, "ai.runtime.circuit.reset", "ai_provider_circuit",
        item.id, scope, {"provider": provider, "reason": reason, "revision": item.revision},
    )
    db.commit()
    return {
        "provider": item.provider,
        "state": item.state,
        "consecutive_failures": item.consecutive_failures,
        "revision": item.revision,
    }


@router.post("/retention/purge")
def purge_retention(
    payload: RetentionPurgeRequest,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "ai.runtime.manage")
    _tenant(db, user, payload.tenant_id)
    raise HTTPException(
        status_code=409,
        detail=(
            "Direct AI purge is disabled. Use the controlled data-governance "
            "preview, four-eyes approval, and execution workflow for "
            "AI_CONVERSATIONS or AI_PROMPTS_RESPONSES."
        ),
    )
