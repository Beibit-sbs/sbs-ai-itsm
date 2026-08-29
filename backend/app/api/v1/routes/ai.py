from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.ai_suggestion import AiSuggestion
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.services.ai import analyze_text_with_provider, describe_provider_status
from app.services.knowledge_ai import (
    accept_suggestion,
    analyze_text_with_mock_ai,
    article_payload,
    create_article_from_ticket,
    get_suggestions_for_ticket,
    reject_suggestion,
)
from app.services.notifications import create_ticket_event_notification
from app.services.rbac import (
    can_read_ticket,
    has_permission,
    is_saas_root,
    require_permissions,
)

router = APIRouter(prefix="/ai")


class AiRelatedArticle(BaseModel):
    id: str
    article_number: str
    title: str
    summary: str


class AiSimilarTicket(BaseModel):
    id: str
    ticket_number: str | None
    title: str
    status: str


class AiSuggestionResponse(BaseModel):
    id: str
    ticket_id: str | None
    input_text: str
    recommended_category: str
    recommended_priority: str
    recommended_asset_type: str | None
    recommended_article_id: str | None
    summary: str
    possible_cause: str
    suggested_solution: str
    recommended_assignee: str
    confidence: str
    confidence_value: float | None = None
    suggestion_type: str = "resolution"
    rationale: str | None = None
    status: str = "proposed"
    accepted_by_id: str | None = None
    accepted_at: datetime | None = None
    rejected_by_id: str | None = None
    rejected_at: datetime | None = None
    related_articles: list[AiRelatedArticle] = Field(default_factory=list)
    similar_tickets: list[AiSimilarTicket] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    requested_provider: str | None = None
    provider: str | None = None
    model: str | None = None
    provider_mock: bool | None = None
    fallback_used: bool | None = None
    execution_mode: str | None = None
    created_at: datetime


class AiAnalyzeTicketRequest(BaseModel):
    input_text: str = Field(min_length=3, max_length=20_000)
    ticket_id: str | None = None
    tenant_id: str | None = None


class AiCreateArticleResponse(BaseModel):
    id: str
    article_number: str
    title: str
    summary: str
    status: str
    visibility: str


class AiSuggestionDecisionRequest(BaseModel):
    rationale: str | None = None


class AiSuggestionDecisionResponse(BaseModel):
    id: str
    status: str
    accepted_by_id: str | None
    accepted_at: datetime | None
    rejected_by_id: str | None
    rejected_at: datetime | None
    rationale: str | None


def _can_read_ai_ticket(
    current_user: AuthUserResponse,
    ticket: Ticket,
) -> bool:
    return can_read_ticket(current_user, ticket)


def _ticket_for_ai(
    db: Session,
    ticket_id: str,
    current_user: AuthUserResponse,
) -> Ticket:
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None or not _can_read_ai_ticket(current_user, ticket):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def _ai_tenant_id(
    db: Session,
    current_user: AuthUserResponse,
    *,
    ticket: Ticket | None,
    requested: str | None,
) -> str:
    if ticket is not None:
        if requested and requested != ticket.tenant_id:
            raise HTTPException(status_code=422, detail="tenant_id does not match ticket")
        return ticket.tenant_id
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        if requested and requested != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return current_user.tenant_id
    if not requested or db.get(Tenant, requested) is None:
        raise HTTPException(
            status_code=422,
            detail="A valid tenant_id is required for SaaS Root AI analysis",
        )
    return requested


def _suggestion_for_user(
    db: Session,
    suggestion_id: str,
    current_user: AuthUserResponse,
) -> AiSuggestion:
    suggestion = db.scalar(
        select(AiSuggestion).where(AiSuggestion.id == suggestion_id)
    )
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.ticket_id:
        _ticket_for_ai(db, suggestion.ticket_id, current_user)
    elif (
        not is_saas_root(current_user)
        and suggestion.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return suggestion


@router.post("/analyze-ticket", response_model=AiSuggestionResponse)
def analyze_ticket(
    request: AiAnalyzeTicketRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiSuggestionResponse:
    require_permissions(current_user, "ai.use")
    ticket = (
        _ticket_for_ai(db, request.ticket_id, current_user)
        if request.ticket_id
        else None
    )
    tenant_id = _ai_tenant_id(
        db,
        current_user,
        ticket=ticket,
        requested=request.tenant_id,
    )
    payload = analyze_text_with_mock_ai(
        db,
        request.input_text,
        request.ticket_id,
        tenant_id=tenant_id,
    )
    if ticket is not None:
        create_ticket_event_notification(
            db,
            event_code="ai_recommendation_ready",
            ticket=ticket,
            actor_name=current_user.full_name,
        )
        db.commit()
    return AiSuggestionResponse(**payload)


class AiProviderInfoResponse(BaseModel):
    configured_provider: str
    active_provider: str
    model: str
    ready: bool
    external_configured: bool
    execution_mode: str
    api_key_configured: bool
    pii_redaction_enabled: bool
    request_timeout_seconds: float
    reason: str | None = None
    fallback_provider: str | None = None
    supported_providers: list[str] = Field(default_factory=list)


_PROVIDER_STATUS_PERMS = (
    "admin.settings.read",
    "admin.users.read",
    "security.audit.read",
    "ai.use",
    "ai.rag.use",
    "ai.actions.read",
)


def _require_provider_status_access(current_user: AuthUserResponse) -> None:
    if is_saas_root(current_user):
        return
    if not any(has_permission(current_user, perm) for perm in _PROVIDER_STATUS_PERMS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission to read AI provider status",
        )


@router.get("/provider-status", response_model=AiProviderInfoResponse)
def get_ai_provider_status(
    current_user: AuthUserResponse = Depends(get_current_user),
) -> AiProviderInfoResponse:
    _require_provider_status_access(current_user)
    info = describe_provider_status()
    return AiProviderInfoResponse(
        configured_provider=info.configured_provider,
        active_provider=info.active_provider,
        model=info.model,
        ready=info.ready,
        external_configured=info.external_configured,
        execution_mode=info.execution_mode,
        api_key_configured=info.api_key_configured,
        pii_redaction_enabled=info.pii_redaction_enabled,
        request_timeout_seconds=info.request_timeout_seconds,
        reason=info.reason,
        fallback_provider=info.fallback_provider,
        supported_providers=info.supported_providers,
    )


@router.post("/classify", response_model=AiSuggestionResponse)
async def classify_ticket(
    request: AiAnalyzeTicketRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiSuggestionResponse:
    require_permissions(current_user, "ai.use")
    ticket = (
        _ticket_for_ai(db, request.ticket_id, current_user)
        if request.ticket_id
        else None
    )
    tenant_id = _ai_tenant_id(
        db,
        current_user,
        ticket=ticket,
        requested=request.tenant_id,
    )
    payload = await analyze_text_with_provider(
        db,
        request.input_text,
        ticket_id=request.ticket_id,
        tenant_id=tenant_id,
        actor_id=current_user.id,
    )
    if ticket is not None:
        create_ticket_event_notification(
            db,
            event_code="ai_recommendation_ready",
            ticket=ticket,
            actor_name=current_user.full_name,
        )
        db.commit()
    return AiSuggestionResponse(**payload)


@router.get("/suggestions/{ticket_id}", response_model=list[AiSuggestionResponse])
def list_suggestions(ticket_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AiSuggestionResponse]:
    require_permissions(current_user, "ai.view_suggestions")
    ticket = _ticket_for_ai(db, ticket_id, current_user)
    return [
        AiSuggestionResponse(**item)
        for item in get_suggestions_for_ticket(
            db,
            ticket_id,
            tenant_id=ticket.tenant_id,
        )
    ]


@router.post("/suggestions/{suggestion_id}/accept", response_model=AiSuggestionDecisionResponse)
def accept_ai_suggestion(
    suggestion_id: str,
    request: AiSuggestionDecisionRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiSuggestionDecisionResponse:
    require_permissions(current_user, "ai.accept_suggestion")
    suggestion = _suggestion_for_user(db, suggestion_id, current_user)
    if request.rationale:
        suggestion.rationale = request.rationale
    suggestion = accept_suggestion(db, suggestion, current_user.id)
    return AiSuggestionDecisionResponse(
        id=suggestion.id,
        status=suggestion.status,
        accepted_by_id=suggestion.accepted_by_id,
        accepted_at=suggestion.accepted_at,
        rejected_by_id=suggestion.rejected_by_id,
        rejected_at=suggestion.rejected_at,
        rationale=suggestion.rationale,
    )


@router.post("/suggestions/{suggestion_id}/reject", response_model=AiSuggestionDecisionResponse)
def reject_ai_suggestion(
    suggestion_id: str,
    request: AiSuggestionDecisionRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiSuggestionDecisionResponse:
    require_permissions(current_user, "ai.reject_suggestion")
    suggestion = _suggestion_for_user(db, suggestion_id, current_user)
    suggestion = reject_suggestion(db, suggestion, current_user.id, request.rationale)
    return AiSuggestionDecisionResponse(
        id=suggestion.id,
        status=suggestion.status,
        accepted_by_id=suggestion.accepted_by_id,
        accepted_at=suggestion.accepted_at,
        rejected_by_id=suggestion.rejected_by_id,
        rejected_at=suggestion.rejected_at,
        rationale=suggestion.rationale,
    )


@router.post("/create-article-from-ticket/{ticket_id}", response_model=AiCreateArticleResponse, status_code=status.HTTP_201_CREATED)
def create_article_by_ticket(
    ticket_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiCreateArticleResponse:
    require_permissions(current_user, "knowledge.create")
    ticket = _ticket_for_ai(db, ticket_id, current_user)

    article = create_article_from_ticket(db, ticket, current_user.full_name)
    payload = article_payload(article)
    return AiCreateArticleResponse(
        id=str(payload["id"]),
        article_number=str(payload["article_number"]),
        title=str(payload["title"]),
        summary=str(payload["summary"]),
        status=str(payload["status"]),
        visibility=str(payload["visibility"]),
    )
