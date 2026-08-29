"""AI service package.

The top-level module exposes the classification entry point used by API
handlers. Provider selection is transparent: if no API key is configured, a
deterministic keyword-based mock provider is used and the service still works.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_suggestion import AiSuggestion
from app.services.ai.pii import RedactionResult, redact_pii, restore_pii
from app.services.ai.provider import (
    BaseLLMProvider,
    ClassificationResult,
    MockLLMProvider,
    PROVIDER_MOCK,
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
    tenant_id: str | None = None,
    routing_key: str | None = None,
    actor_id: str | None = None,
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

    requested_provider = provider or get_provider()
    provider_instance = requested_provider
    governed_prompt = None
    if tenant_id:
        from app.services.ai_governance import effective_prompt

        governed_prompt = effective_prompt(
            db,
            tenant_id=tenant_id,
            use_case="ticket_classification",
            routing_key=routing_key or text,
        )

    decision = None
    data_classification = "INTERNAL"
    parameters: dict[str, Any] = {}
    if tenant_id:
        from app.services.ai_governance import json_value
        from app.services.ai_runtime_controls import (
            classify_data,
            estimate_cost,
            execution_decision,
        )

        data_classification = classify_data(text)
        if governed_prompt is not None:
            parsed_parameters = json_value(governed_prompt.parameters_json, {})
            parameters = parsed_parameters if isinstance(parsed_parameters, dict) else {}
        projected_cost = estimate_cost(
            input_text=text,
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
            contains_pii=bool(redact_pii(text).tokens),
            cost_rates_configured={
                "input_cost_per_million",
                "output_cost_per_million",
            }.issubset(parameters),
        )
        if not requested_provider.is_mock and not decision.external_allowed:
            provider_instance = MockLLMProvider(requested_provider.timeout)

    async def _classify(value: str) -> ClassificationResult:
        if (
            governed_prompt is not None
            and governed_prompt.provider == provider_instance.name
            and governed_prompt.model == provider_instance.model
        ):
            return await provider_instance.classify_ticket_with_prompt(
                value,
                governed_prompt.system_prompt,
            )
        return await provider_instance.classify_ticket(value)

    started = time.perf_counter()
    should_redact = bool(
        apply_pii_redaction
        or (decision is not None and decision.pii_redaction_required)
    )
    if should_redact and not provider_instance.is_mock:
        redacted = redact_pii(text)
        result = await _classify(redacted.text)
        # Restore any leaked tokens in the model's textual output so users see
        # their original values.
        result.summary = restore_pii(result.summary, redacted.tokens)
        result.possible_cause = restore_pii(result.possible_cause, redacted.tokens)
        result.suggested_solution = restore_pii(result.suggested_solution, redacted.tokens)
    else:
        result = await _classify(text)
    if tenant_id:
        from app.services.ai_runtime_controls import (
            estimate_cost,
            record_provider_result,
            record_usage,
        )

        provider_success = (
            requested_provider.is_mock
            or result.provider == requested_provider.name
        )
        if not requested_provider.is_mock and decision and decision.external_allowed:
            record_provider_result(
                db,
                tenant_id=tenant_id,
                provider=requested_provider.name,
                success=provider_success,
                failure_code=None if provider_success else "provider_fallback",
            )
        output = " ".join(
            (
                result.category,
                result.priority,
                result.summary,
                result.possible_cause,
                result.suggested_solution,
            )
        )
        actual_cost = (
            estimate_cost(
                input_text=text,
                output_text=output,
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
        blocked_reason = (
            decision.reason
            if decision is not None
            and not requested_provider.is_mock
            and not decision.external_allowed
            else None
        )
        record_usage(
            db,
            tenant_id=tenant_id,
            user_id=actor_id,
            operation="ticket_classification",
            requested_provider=requested_provider.name,
            provider=result.provider,
            model=result.model,
            provider_region=decision.provider_region if decision else "local",
            data_classification=data_classification,
            pii_redacted=should_redact,
            input_text=text,
            output_text=output,
            estimated_cost_usd=actual_cost,
            latency_ms=round((time.perf_counter() - started) * 1000),
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
            correlation_key=routing_key,
        )
    return result


def _to_confidence_label(value: float) -> str:
    return f"{int(max(0.0, min(1.0, value)) * 100)}%"


async def analyze_text_with_provider(
    db: Session,
    text: str,
    *,
    ticket_id: str | None = None,
    tenant_id: str | None = None,
    provider: BaseLLMProvider | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Full-featured analysis pipeline used by the /ai/classify endpoint.

    Runs the configured LLM provider, persists an AiSuggestion row and enriches
    the response with related knowledge articles and similar tickets — matching
    the response shape of the legacy /ai/analyze-ticket endpoint.
    """

    from app.services.knowledge_ai import _related_articles, _similar_tickets

    classification = await classify_ticket_text(
        db,
        text,
        tenant_id=tenant_id,
        routing_key=ticket_id or text[:120],
        actor_id=actor_id,
        provider=provider,
    )

    provider_instance = provider or get_provider()
    recommended_category = classification.category
    ticket_category = None  # LLM path does not emit a rule-based ticket_category key
    related_articles = _related_articles(
        db,
        ticket_category,
        recommended_category,
        tenant_id,
    )
    similar_tickets = _similar_tickets(db, ticket_category, tenant_id)

    suggestion = AiSuggestion(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
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
        "requested_provider": provider_instance.name,
        "provider_mock": classification.provider == PROVIDER_MOCK,
        "fallback_used": classification.provider != provider_instance.name,
        "execution_mode": (
            "LOCAL_SIMULATION"
            if classification.provider == PROVIDER_MOCK
            else "EXTERNAL_PROVIDER"
        ),
        "created_at": suggestion.created_at,
    }
