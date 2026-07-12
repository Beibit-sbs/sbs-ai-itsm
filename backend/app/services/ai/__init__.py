"""AI service package.

The top-level module exposes the classification entry point used by API
handlers. Provider selection is transparent: if no API key is configured, a
deterministic keyword-based mock provider is used and the service still works.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_suggestion import AiSuggestion
from app.services.ai.pii import RedactionResult, redact_pii, restore_pii
from app.services.ai.provider import (
    BaseLLMProvider,
    ClassificationResult,
    ProviderStatus,
    describe_provider_status,
    get_provider,
)

__all__ = [
    "BaseLLMProvider",
    "ClassificationResult",
    "ProviderStatus",
    "RedactionResult",
    "analyze_text_with_provider",
    "classify_ticket_text",
    "describe_provider_status",
    "get_provider",
    "redact_pii",
    "restore_pii",
]


_PRIORITY_UPPERCASE = {
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
    "critical": "CRITICAL",
}


async def classify_ticket_text(
    db: Session,  # noqa: ARG001 - reserved for future DB-backed heuristics
    text: str,
    *,
    provider: BaseLLMProvider | None = None,
    apply_pii_redaction: bool | None = None,
) -> ClassificationResult:
    """Classify ticket text using the configured provider.

    Falls back to the mock provider if the configured one is unavailable. PII
    redaction is applied by default and controlled by settings.
    """

    from app.core.config import get_settings

    settings = get_settings()
    if apply_pii_redaction is None:
        apply_pii_redaction = bool(settings.ai_pii_redaction)

    provider_instance = provider or get_provider()
    if apply_pii_redaction and not provider_instance.is_mock:
        redacted = redact_pii(text)
        result = await provider_instance.classify_ticket(redacted.text)
        # Restore any leaked tokens in the model's textual output so users see
        # their original values.
        result.summary = restore_pii(result.summary, redacted.tokens)
        result.possible_cause = restore_pii(result.possible_cause, redacted.tokens)
        result.suggested_solution = restore_pii(result.suggested_solution, redacted.tokens)
        return result
    return await provider_instance.classify_ticket(text)


def _to_confidence_label(value: float) -> str:
    return f"{int(max(0.0, min(1.0, value)) * 100)}%"


async def analyze_text_with_provider(
    db: Session,
    text: str,
    *,
    ticket_id: str | None = None,
    provider: BaseLLMProvider | None = None,
) -> dict[str, Any]:
    """Full-featured analysis pipeline used by the /ai/classify endpoint.

    Runs the configured LLM provider, persists an AiSuggestion row and enriches
    the response with related knowledge articles and similar tickets — matching
    the response shape of the legacy /ai/analyze-ticket endpoint.
    """

    from app.services.knowledge_ai import _related_articles, _similar_tickets

    classification = await classify_ticket_text(db, text, provider=provider)

    provider_instance = provider or get_provider()
    recommended_category = classification.category
    ticket_category = None  # LLM path does not emit a rule-based ticket_category key
    related_articles = _related_articles(db, ticket_category, recommended_category)
    similar_tickets = _similar_tickets(db, ticket_category)

    suggestion = AiSuggestion(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        input_text=text,
        recommended_category=recommended_category[:200],
        recommended_priority=_PRIORITY_UPPERCASE.get(classification.priority, "MEDIUM"),
        recommended_asset_type=None,
        recommended_article_id=related_articles[0].id if related_articles else None,
        summary=classification.summary[:800],
        possible_cause=classification.possible_cause[:800],
        suggested_solution=classification.suggested_solution[:1200],
        recommended_assignee="AI-recommended assignee",
        confidence=_to_confidence_label(classification.confidence),
        confidence_value=classification.confidence,
        suggestion_type="resolution",
        rationale=f"{classification.provider}:{classification.model}",
        status="proposed",
        created_at=datetime.now(UTC),
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    return {
        "id": suggestion.id,
        "ticket_id": suggestion.ticket_id,
        "input_text": suggestion.input_text,
        "recommended_category": suggestion.recommended_category,
        "recommended_priority": suggestion.recommended_priority,
        "recommended_asset_type": suggestion.recommended_asset_type,
        "recommended_article_id": suggestion.recommended_article_id,
        "summary": suggestion.summary,
        "possible_cause": suggestion.possible_cause,
        "suggested_solution": suggestion.suggested_solution,
        "recommended_assignee": suggestion.recommended_assignee,
        "confidence": suggestion.confidence,
        "confidence_value": suggestion.confidence_value,
        "suggestion_type": suggestion.suggestion_type,
        "rationale": suggestion.rationale,
        "status": suggestion.status,
        "accepted_by_id": suggestion.accepted_by_id,
        "accepted_at": suggestion.accepted_at,
        "rejected_by_id": suggestion.rejected_by_id,
        "rejected_at": suggestion.rejected_at,
        "related_articles": [
            {
                "id": article.id,
                "article_number": article.article_number,
                "title": article.title,
                "summary": article.summary,
            }
            for article in related_articles
        ],
        "similar_tickets": [
            {
                "id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "title": ticket.title,
                "status": ticket.status,
            }
            for ticket in similar_tickets
        ],
        "next_actions": [
            "Проверить сопутствующие статьи базы знаний.",
            "Согласовать рекомендацию с ответственным инженером.",
            "После применения решения обновить историю тикета и статус AI-подсказки.",
        ],
        "provider": classification.provider,
        "model": classification.model,
        "provider_mock": provider_instance.is_mock,
        "created_at": suggestion.created_at,
    }
