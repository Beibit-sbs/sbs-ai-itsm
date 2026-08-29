from __future__ import annotations

import asyncio
from datetime import timedelta
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_runtime_controls import (
    AiDataPolicy,
    AiUsageBudget,
    AiUsageLedger,
)
from app.models.tenant import Tenant
from app.services.ai import classify_ticket_text
from app.services.ai.provider import (
    BaseLLMProvider,
    ClassificationResult,
)
from app.services.ai_runtime_controls import (
    classify_data,
    execution_decision,
    record_provider_result,
    record_usage,
    utcnow,
)


def _id() -> str:
    return str(uuid.uuid4())


def _tenant(db: Session, slug: str = "runtime-controls") -> str:
    tenant_id = _id()
    db.add(Tenant(id=tenant_id, name=slug.title(), slug=slug, status="active"))
    db.commit()
    return tenant_id


def test_data_classification_is_conservative() -> None:
    assert classify_data("Обычная инструкция") == "INTERNAL"
    assert classify_data("Почта ivan@example.com") == "CONFIDENTIAL"
    assert classify_data("О тикете", source_types={"ticket"}) == "CONFIDENTIAL"
    assert classify_data("Restricted", restricted_source=True) == "RESTRICTED"


def test_external_processing_is_disabled_without_explicit_policy(
    db_session: Session,
) -> None:
    tenant_id = _tenant(db_session)
    decision = execution_decision(
        db_session,
        tenant_id=tenant_id,
        provider="openai",
        data_classification="INTERNAL",
        projected_cost_usd=0.01,
    )
    assert decision.external_allowed is False
    assert decision.reason == "external_processing_disabled"


def test_residency_and_classification_policy_fail_closed(db_session: Session) -> None:
    tenant_id = _tenant(db_session, "residency")
    db_session.add(
        AiDataPolicy(
            id=_id(),
            tenant_id=tenant_id,
            external_processing_enabled=True,
            allowed_providers_json='["openai"]',
            provider_regions_json='{"openai":"eu"}',
            maximum_external_classification="INTERNAL",
            pii_redaction_required=True,
        )
    )
    db_session.add(AiUsageBudget(id=_id(), tenant_id=tenant_id))
    db_session.commit()
    allowed = execution_decision(
        db_session,
        tenant_id=tenant_id,
        provider="openai",
        data_classification="INTERNAL",
        projected_cost_usd=0,
        cost_rates_configured=True,
    )
    assert allowed.external_allowed is True
    assert allowed.provider_region == "eu"
    blocked_class = execution_decision(
        db_session,
        tenant_id=tenant_id,
        provider="openai",
        data_classification="CONFIDENTIAL",
        projected_cost_usd=0,
        cost_rates_configured=True,
    )
    assert blocked_class.reason == "data_classification_blocked"
    blocked_provider = execution_decision(
        db_session,
        tenant_id=tenant_id,
        provider="gemini",
        data_classification="INTERNAL",
        projected_cost_usd=0,
        cost_rates_configured=True,
    )
    assert blocked_provider.reason == "provider_not_allowed"


def test_hard_budget_blocks_before_provider_call(db_session: Session) -> None:
    tenant_id = _tenant(db_session, "budget")
    db_session.add_all(
        [
            AiDataPolicy(
                id=_id(),
                tenant_id=tenant_id,
                external_processing_enabled=True,
                allowed_providers_json='["openai"]',
                provider_regions_json='{"openai":"eu"}',
                maximum_external_classification="CONFIDENTIAL",
            ),
            AiUsageBudget(
                id=_id(),
                tenant_id=tenant_id,
                monthly_request_limit=1,
                daily_request_limit=1,
                monthly_cost_limit_usd=1,
                warning_percent=80,
                hard_limit_enabled=True,
            ),
        ]
    )
    record_usage(
        db_session,
        tenant_id=tenant_id,
        user_id=None,
        operation="test",
        requested_provider="openai",
        provider="openai",
        model="test",
        provider_region="eu",
        data_classification="INTERNAL",
        pii_redacted=True,
        input_text="input",
        output_text="output",
        estimated_cost_usd=0.1,
        latency_ms=1,
        outcome="SUCCESS",
        fallback_reason=None,
        prompt_version_id=None,
    )
    db_session.commit()
    decision = execution_decision(
        db_session,
        tenant_id=tenant_id,
        provider="openai",
        data_classification="INTERNAL",
        projected_cost_usd=0,
        cost_rates_configured=True,
    )
    assert decision.external_allowed is False
    assert decision.reason == "monthly_request_budget_exceeded"


def test_circuit_opens_and_moves_to_half_open(db_session: Session) -> None:
    tenant_id = _tenant(db_session, "circuit")
    item = record_provider_result(
        db_session,
        tenant_id=tenant_id,
        provider="openai",
        success=False,
        failure_code="timeout",
    )
    assert item is not None
    item.failure_threshold = 2
    record_provider_result(
        db_session,
        tenant_id=tenant_id,
        provider="openai",
        success=False,
        failure_code="timeout",
    )
    db_session.commit()
    assert item.state == "OPEN"
    item.open_until = utcnow() - timedelta(seconds=1)
    db_session.commit()
    db_session.add(
        AiDataPolicy(
            id=_id(),
            tenant_id=tenant_id,
            external_processing_enabled=True,
            allowed_providers_json='["openai"]',
            provider_regions_json='{"openai":"eu"}',
            maximum_external_classification="INTERNAL",
        )
    )
    db_session.add(AiUsageBudget(id=_id(), tenant_id=tenant_id))
    db_session.commit()
    decision = execution_decision(
        db_session,
        tenant_id=tenant_id,
        provider="openai",
        data_classification="INTERNAL",
        projected_cost_usd=0,
        cost_rates_configured=True,
    )
    assert decision.external_allowed is True
    assert item.state == "HALF_OPEN"


class ExternalProvider(BaseLLMProvider):
    name = "openai"
    model = "test-model"

    async def classify_ticket(self, text: str) -> ClassificationResult:
        raise AssertionError("External provider must not be called")


def test_classification_uses_local_fallback_and_hash_only_ledger(
    db_session: Session,
) -> None:
    tenant_id = _tenant(db_session, "fallback")
    result = asyncio.run(
        classify_ticket_text(
            db_session,
            "Не работает интернет для ivan@example.com",
            tenant_id=tenant_id,
            actor_id=None,
            provider=ExternalProvider(),
        )
    )
    db_session.commit()
    usage = db_session.scalar(
        select(AiUsageLedger).where(AiUsageLedger.tenant_id == tenant_id)
    )
    assert result.provider == "mock"
    assert usage is not None
    assert usage.outcome == "BLOCKED"
    assert usage.fallback_reason == "external_processing_disabled"
    assert usage.input_sha256
    assert not hasattr(usage, "input_text")
    assert not hasattr(usage, "output_text")


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_runtime_policy_api_uses_optimistic_revision(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        headers = {"Authorization": f"Bearer {token}"}
        created = client.put(
            "/api/v1/ai/runtime-controls/data-policy",
            headers=headers,
            json={
                "expected_revision": 0,
                "external_processing_enabled": True,
                "allowed_providers": ["openai"],
                "provider_regions": {"openai": "eu"},
                "maximum_external_classification": "INTERNAL",
                "pii_redaction_required": True,
                "allow_reversible_redaction": True,
                "retention_days": 180,
            },
        )
        assert created.status_code == 200, created.text
        conflict = client.put(
            "/api/v1/ai/runtime-controls/data-policy",
            headers=headers,
            json={
                "expected_revision": 0,
                "external_processing_enabled": False,
                "allowed_providers": [],
                "provider_regions": {},
                "maximum_external_classification": "INTERNAL",
                "pii_redaction_required": True,
                "allow_reversible_redaction": True,
                "retention_days": 180,
            },
        )
    assert conflict.status_code == 409
