from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.ticket import Ticket
from app.services.knowledge_ai import analyze_text_with_mock_ai, article_payload, create_article_from_ticket, get_suggestions_for_ticket
from app.services.notifications import create_ticket_event_notification
from app.services.rbac import require_permissions

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
    related_articles: list[AiRelatedArticle] = Field(default_factory=list)
    similar_tickets: list[AiSimilarTicket] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    created_at: datetime


class AiAnalyzeTicketRequest(BaseModel):
    input_text: str
    ticket_id: str | None = None


class AiCreateArticleResponse(BaseModel):
    id: str
    article_number: str
    title: str
    summary: str
    status: str
    visibility: str


@router.post("/analyze-ticket", response_model=AiSuggestionResponse)
def analyze_ticket(
    request: AiAnalyzeTicketRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiSuggestionResponse:
    require_permissions(current_user, "ai.use")
    payload = analyze_text_with_mock_ai(db, request.input_text, request.ticket_id)
    if request.ticket_id:
        ticket = db.scalar(select(Ticket).where(Ticket.id == request.ticket_id))
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
    return [AiSuggestionResponse(**item) for item in get_suggestions_for_ticket(db, ticket_id)]


@router.post("/create-article-from-ticket/{ticket_id}", response_model=AiCreateArticleResponse, status_code=status.HTTP_201_CREATED)
def create_article_by_ticket(
    ticket_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiCreateArticleResponse:
    require_permissions(current_user, "knowledge.create")
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

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
