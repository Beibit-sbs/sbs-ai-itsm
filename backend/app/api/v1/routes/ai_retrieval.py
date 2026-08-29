from __future__ import annotations

import json
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.ai_retrieval import (
    AiRetrievalIngestionRun,
    AiRetrievalQueryLog,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.ai.pii import redact_pii, restore_pii
from app.services.ai.provider import PROVIDER_MOCK, MockLLMProvider, get_provider
from app.services.ai_governance import effective_prompt, json_value
from app.services.ai_runtime_controls import (
    classify_data,
    estimate_cost,
    execution_decision,
    record_provider_result,
    record_usage,
)
from app.services.ai_retrieval import (
    RAG_SOURCE_TYPES,
    SOURCE_PERMISSIONS,
    RagError,
    RagSafetyError,
    create_query_log,
    retrieval_dashboard,
    retrieve_authorized_context,
    synchronize_retrieval_index,
)
from app.services.audit import log_audit
from app.services.rbac import has_permission, is_saas_root, require_permissions


router = APIRouter(prefix="/ai/rag")
RagSourceType = Literal["knowledge", "ticket", "problem", "change", "asset"]


class RagSyncRequest(BaseModel):
    tenant_id: str | None = None
    source_types: list[RagSourceType] = Field(
        default_factory=lambda: list(RAG_SOURCE_TYPES),
        min_length=1,
    )


class RagQueryRequest(BaseModel):
    tenant_id: str | None = None
    query: str = Field(min_length=3, max_length=4_000)
    source_types: list[RagSourceType] = Field(
        default_factory=lambda: list(RAG_SOURCE_TYPES),
        min_length=1,
    )
    limit: int = Field(default=6, ge=1, le=20)
    minimum_score: float = Field(default=0.12, ge=0.0, le=1.0)


class RagCitationResponse(BaseModel):
    citation_id: str
    source_type: str
    source_id: str
    source_key: str
    title: str
    url_path: str
    excerpt: str
    score: float
    content_sha256: str
    source_updated_at: str
    indexed_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagSearchResponse(BaseModel):
    citations: list[RagCitationResponse]
    retrieved_count: int
    permission_denied_count: int
    stale_count: int
    unsafe_source_count: int
    latency_ms: int


class RagAnswerResponse(RagSearchResponse):
    answer: str
    requested_provider: str
    provider: str
    model: str
    provider_mock: bool
    fallback_used: bool
    execution_mode: str
    grounded: bool
    rationale: str


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
            detail="tenant_id is required for SaaS Root AI retrieval operations",
        )
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _audit(
    db: Session,
    request: Request,
    current_user: AuthUserResponse,
    *,
    action: str,
    entity_id: str,
    tenant_id: str,
    metadata: dict[str, object],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type="ai_retrieval",
        entity_id=entity_id,
        actor_user=db.get(User, current_user.id),
        actor_email=current_user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _unique_redaction(
    text: str,
    prefix: str,
) -> tuple[str, dict[str, str]]:
    result = redact_pii(text)
    redacted = result.text
    tokens: dict[str, str] = {}
    for token, original in result.tokens.items():
        unique = f"<{prefix}_{token.strip('<>')}>"
        redacted = redacted.replace(token, unique)
        tokens[unique] = original
    return redacted, tokens


def _provider_payload(
    query: str,
    citations: list[dict[str, Any]],
    *,
    redact: bool,
) -> tuple[str, list[dict[str, str]], dict[str, str]]:
    if redact:
        question, tokens = _unique_redaction(query, "Q")
    else:
        question, tokens = query, {}
    sources: list[dict[str, str]] = []
    for index, citation in enumerate(citations, start=1):
        content = str(citation["excerpt"])
        title = str(citation["title"])
        if redact:
            title, title_tokens = _unique_redaction(title, f"S{index}T")
            content, content_tokens = _unique_redaction(content, f"S{index}")
            tokens.update(title_tokens)
            tokens.update(content_tokens)
        sources.append(
            {
                "citation_id": str(citation["citation_id"]),
                "title": title,
                "content": content,
            }
        )
    return question, sources, tokens


@router.get("/meta")
def rag_meta(
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, object]:
    require_permissions(current_user, "ai.rag.use")
    allowed = [
        source_type
        for source_type in RAG_SOURCE_TYPES
        if has_permission(current_user, SOURCE_PERMISSIONS[source_type])
    ]
    return {
        "source_types": list(RAG_SOURCE_TYPES),
        "allowed_source_types": allowed,
        "can_manage": has_permission(current_user, "ai.rag.manage"),
        "can_audit": has_permission(current_user, "ai.rag.audit"),
        "privacy": {
            "stores_raw_query": False,
            "stores_raw_answer": False,
            "live_acl_recheck": True,
            "prompt_injection_filter": True,
        },
    }


@router.get("/dashboard")
def get_rag_dashboard(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "ai.rag.read")
    return retrieval_dashboard(db, _tenant_id(db, current_user, tenant_id))


@router.get("/ingestion-runs")
def list_ingestion_runs(
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "ai.rag.read")
    scoped_tenant_id = _tenant_id(db, current_user, tenant_id)
    items = db.scalars(
        select(AiRetrievalIngestionRun)
        .where(AiRetrievalIngestionRun.tenant_id == scoped_tenant_id)
        .order_by(AiRetrievalIngestionRun.started_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": item.id,
            "status": item.status,
            "source_types": json.loads(item.source_types_json),
            "scanned_count": item.scanned_count,
            "indexed_count": item.indexed_count,
            "updated_count": item.updated_count,
            "unchanged_count": item.unchanged_count,
            "deleted_count": item.deleted_count,
            "error_message": item.error_message,
            "requested_by_id": item.requested_by_id,
            "started_at": item.started_at,
            "completed_at": item.completed_at,
        }
        for item in items
    ]


@router.post("/ingestion/sync")
def sync_ingestion(
    payload: RagSyncRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "ai.rag.manage")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    try:
        run, counts = synchronize_retrieval_index(
            db,
            tenant_id=tenant_id,
            source_types=set(payload.source_types),
            actor_id=current_user.id,
            settings=get_settings(),
        )
    except RagError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db,
        request,
        current_user,
        action="ai.rag.ingestion.sync",
        entity_id=run.id,
        tenant_id=tenant_id,
        metadata={
            "source_types": sorted(set(payload.source_types)),
            **counts,
        },
    )
    db.commit()
    return {
        "id": run.id,
        "status": run.status,
        "source_types": sorted(set(payload.source_types)),
        **counts,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }


@router.post("/search", response_model=RagSearchResponse)
def search_rag(
    payload: RagQueryRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RagSearchResponse:
    require_permissions(current_user, "ai.rag.use")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    try:
        result = retrieve_authorized_context(
            db,
            tenant_id=tenant_id,
            current_user=current_user,
            query=payload.query,
            source_types=set(payload.source_types),
            limit=payload.limit,
            minimum_score=payload.minimum_score,
            settings=get_settings(),
        )
    except RagSafetyError as exc:
        create_query_log(
            db,
            tenant_id=tenant_id,
            user_id=current_user.id,
            query=payload.query,
            source_types=payload.source_types,
            citations=[],
            answer=None,
            provider="blocked",
            model="prompt-injection-policy-v1",
            permission_denied_count=0,
            stale_count=0,
            injection_detected=True,
            grounded=False,
            latency_ms=0,
        )
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RagError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    create_query_log(
        db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        query=payload.query,
        source_types=payload.source_types,
        citations=result["citations"],
        answer=None,
        provider="retrieval-only",
        model="hybrid-sparse-v1",
        permission_denied_count=result["permission_denied_count"],
        stale_count=result["stale_count"],
        injection_detected=False,
        grounded=bool(result["citations"]),
        latency_ms=result["latency_ms"],
    )
    db.commit()
    return RagSearchResponse(**result)


@router.post("/ask", response_model=RagAnswerResponse)
async def ask_rag(
    payload: RagQueryRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RagAnswerResponse:
    require_permissions(current_user, "ai.rag.use")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    started = time.perf_counter()
    try:
        result = retrieve_authorized_context(
            db,
            tenant_id=tenant_id,
            current_user=current_user,
            query=payload.query,
            source_types=set(payload.source_types),
            limit=payload.limit,
            minimum_score=payload.minimum_score,
            settings=get_settings(),
        )
    except RagSafetyError as exc:
        create_query_log(
            db,
            tenant_id=tenant_id,
            user_id=current_user.id,
            query=payload.query,
            source_types=payload.source_types,
            citations=[],
            answer=None,
            provider="blocked",
            model="prompt-injection-policy-v1",
            permission_denied_count=0,
            stale_count=0,
            injection_detected=True,
            grounded=False,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        _audit(
            db,
            request,
            current_user,
            action="ai.rag.query.blocked",
            entity_id=current_user.id,
            tenant_id=tenant_id,
            metadata={"reason": "prompt_injection", "source_types": payload.source_types},
        )
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RagError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    settings = get_settings()
    requested_provider = get_provider()
    governed_prompt = effective_prompt(
        db,
        tenant_id=tenant_id,
        use_case="grounded_answer",
        routing_key=current_user.id,
    )
    system_prompt = (
        governed_prompt.system_prompt
        if governed_prompt is not None
        and governed_prompt.provider == requested_provider.name
        and governed_prompt.model == requested_provider.model
        else None
    )
    parameters = (
        json_value(governed_prompt.parameters_json, {})
        if governed_prompt is not None
        else {}
    )
    if not isinstance(parameters, dict):
        parameters = {}
    data_classification = classify_data(
        payload.query,
        source_types=set(payload.source_types),
    )
    projected_cost = estimate_cost(
        input_text=payload.query
        + "".join(str(item["excerpt"]) for item in result["citations"]),
        input_cost_per_million=float(
            parameters.get("input_cost_per_million", 0.0)
        ),
    )
    decision = execution_decision(
        db,
        tenant_id=tenant_id,
        provider=requested_provider.name,
        data_classification=data_classification,
        projected_cost_usd=projected_cost,
        contains_pii=bool(
            redact_pii(
                payload.query
                + "".join(str(item["excerpt"]) for item in result["citations"])
            ).tokens
        ),
        cost_rates_configured={
            "input_cost_per_million",
            "output_cost_per_million",
        }.issubset(parameters),
    )
    provider = requested_provider
    if not requested_provider.is_mock and not decision.external_allowed:
        provider = MockLLMProvider(requested_provider.timeout)
        system_prompt = None
    should_redact = bool(
        settings.ai_pii_redaction or decision.pii_redaction_required
    )
    question, provider_sources, tokens = _provider_payload(
        payload.query,
        result["citations"],
        redact=should_redact,
    )
    answer = await provider.answer_grounded(
        question,
        provider_sources,
        system_prompt=system_prompt,
    )
    restored_answer = restore_pii(answer.answer, tokens)
    cited = set(answer.citation_ids)
    used_citations = [
        citation
        for citation in result["citations"]
        if citation["citation_id"] in cited
    ]
    grounded = bool(answer.grounded and used_citations)
    latency_ms = round((time.perf_counter() - started) * 1000)
    provider_mock = answer.provider == PROVIDER_MOCK
    fallback_used = answer.provider != requested_provider.name
    execution_mode = (
        "LOCAL_SIMULATION" if provider_mock else "EXTERNAL_PROVIDER"
    )
    provider_success = (
        requested_provider.is_mock
        or answer.provider == requested_provider.name
    )
    if not requested_provider.is_mock and decision.external_allowed:
        record_provider_result(
            db,
            tenant_id=tenant_id,
            provider=requested_provider.name,
            success=provider_success,
            failure_code=None if provider_success else "provider_fallback",
        )
    blocked_reason = (
        decision.reason
        if not requested_provider.is_mock and not decision.external_allowed
        else None
    )
    actual_cost = (
        estimate_cost(
            input_text=payload.query
            + "".join(str(item["excerpt"]) for item in result["citations"]),
            output_text=restored_answer,
            input_cost_per_million=float(
                parameters.get("input_cost_per_million", 0.0)
            ),
            output_cost_per_million=float(
                parameters.get("output_cost_per_million", 0.0)
            ),
        )
        if provider_success and not requested_provider.is_mock
        else 0.0
    )
    record_usage(
        db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        operation="grounded_answer",
        requested_provider=requested_provider.name,
        provider=answer.provider,
        model=answer.model,
        provider_region=decision.provider_region,
        data_classification=data_classification,
        pii_redacted=should_redact,
        input_text=payload.query,
        output_text=restored_answer,
        estimated_cost_usd=actual_cost,
        latency_ms=latency_ms,
        outcome=(
            "SUCCESS"
            if provider_success
            else "BLOCKED"
            if blocked_reason
            else "FALLBACK"
        ),
        fallback_reason=blocked_reason
        or (None if provider_success else "provider_fallback"),
        prompt_version_id=governed_prompt.id if governed_prompt else None,
        correlation_key=current_user.id,
    )
    create_query_log(
        db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        query=payload.query,
        source_types=payload.source_types,
        citations=used_citations,
        answer=restored_answer,
        provider=answer.provider,
        model=answer.model,
        permission_denied_count=result["permission_denied_count"],
        stale_count=result["stale_count"],
        injection_detected=False,
        grounded=grounded,
        latency_ms=latency_ms,
    )
    _audit(
        db,
        request,
        current_user,
        action="ai.rag.query",
        entity_id=current_user.id,
        tenant_id=tenant_id,
        metadata={
            "source_types": payload.source_types,
            "requested_provider": requested_provider.name,
            "provider": answer.provider,
            "model": answer.model,
            "provider_mock": provider_mock,
            "fallback_used": fallback_used,
            "execution_mode": execution_mode,
            "retrieved_count": len(used_citations),
            "grounded": grounded,
            "raw_content_logged": False,
        },
    )
    db.commit()
    return RagAnswerResponse(
        answer=restored_answer,
        requested_provider=requested_provider.name,
        provider=answer.provider,
        model=answer.model,
        provider_mock=provider_mock,
        fallback_used=fallback_used,
        execution_mode=execution_mode,
        grounded=grounded,
        rationale=answer.rationale,
        citations=[RagCitationResponse(**item) for item in used_citations],
        retrieved_count=len(used_citations),
        permission_denied_count=result["permission_denied_count"],
        stale_count=result["stale_count"],
        unsafe_source_count=result["unsafe_source_count"],
        latency_ms=latency_ms,
    )


@router.get("/query-logs")
def list_query_logs(
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(current_user, "ai.rag.audit")
    scoped_tenant_id = _tenant_id(db, current_user, tenant_id)
    items = db.scalars(
        select(AiRetrievalQueryLog)
        .where(AiRetrievalQueryLog.tenant_id == scoped_tenant_id)
        .order_by(AiRetrievalQueryLog.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": item.id,
            "user_id": item.user_id,
            "query_sha256": item.query_sha256,
            "query_preview_redacted": item.query_preview_redacted,
            "source_types": json.loads(item.source_types_json),
            "citation_evidence": json.loads(item.citation_evidence_json),
            "answer_sha256": item.answer_sha256,
            "provider": item.provider,
            "model": item.model,
            "retrieved_count": item.retrieved_count,
            "permission_denied_count": item.permission_denied_count,
            "stale_count": item.stale_count,
            "injection_detected": item.injection_detected,
            "grounded": item.grounded,
            "no_result": item.no_result,
            "latency_ms": item.latency_ms,
            "created_at": item.created_at,
        }
        for item in items
    ]
