from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai_runtime_controls import (
    AiDataPolicy,
    AiProviderCircuit,
    AiUsageBudget,
    AiUsageLedger,
)
from app.services.ai.pii import redact_pii


CLASSIFICATION_RANK = {
    "PUBLIC": 0,
    "INTERNAL": 1,
    "CONFIDENTIAL": 2,
    "RESTRICTED": 3,
}


@dataclass(slots=True)
class AiExecutionDecision:
    external_allowed: bool
    reason: str | None
    data_classification: str
    provider_region: str | None
    pii_redaction_required: bool
    projected_cost_usd: float


def utcnow() -> datetime:
    return datetime.now(UTC)


def digest_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def json_value(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def classify_data(
    text: str,
    *,
    source_types: set[str] | None = None,
    restricted_source: bool = False,
) -> str:
    if restricted_source:
        return "RESTRICTED"
    if source_types and source_types & {"ticket", "problem", "change", "asset"}:
        return "CONFIDENTIAL"
    if redact_pii(text).tokens:
        return "CONFIDENTIAL"
    return "INTERNAL"


def estimate_tokens(value: str) -> int:
    return max(1, math.ceil(len(value or "") / 4))


def estimate_cost(
    *,
    input_text: str,
    output_text: str = "",
    input_cost_per_million: float = 0.0,
    output_cost_per_million: float = 0.0,
) -> float:
    return round(
        estimate_tokens(input_text) / 1_000_000 * input_cost_per_million
        + estimate_tokens(output_text) / 1_000_000 * output_cost_per_million,
        8,
    )


def _period_start(now: datetime, *, daily: bool) -> datetime:
    if daily:
        return datetime(now.year, now.month, now.day, tzinfo=UTC)
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def usage_totals(db: Session, tenant_id: str, now: datetime | None = None) -> dict[str, float]:
    current = now or utcnow()
    month_start = _period_start(current, daily=False)
    day_start = _period_start(current, daily=True)
    monthly = db.execute(
        select(
            func.count(AiUsageLedger.id),
            func.coalesce(func.sum(AiUsageLedger.estimated_cost_usd), 0.0),
        ).where(
            AiUsageLedger.tenant_id == tenant_id,
            AiUsageLedger.created_at >= month_start,
        )
    ).one()
    daily_requests = db.scalar(
        select(func.count(AiUsageLedger.id)).where(
            AiUsageLedger.tenant_id == tenant_id,
            AiUsageLedger.created_at >= day_start,
        )
    ) or 0
    return {
        "monthly_requests": float(monthly[0]),
        "monthly_cost_usd": float(monthly[1]),
        "daily_requests": float(daily_requests),
    }


def _circuit(
    db: Session,
    tenant_id: str,
    provider: str,
    *,
    lock: bool = False,
) -> AiProviderCircuit | None:
    statement = select(AiProviderCircuit).where(
            AiProviderCircuit.tenant_id == tenant_id,
            AiProviderCircuit.provider == provider,
        )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    return db.scalar(statement)


def execution_decision(
    db: Session,
    *,
    tenant_id: str,
    provider: str,
    data_classification: str,
    projected_cost_usd: float,
    contains_pii: bool = False,
    cost_rates_configured: bool = False,
) -> AiExecutionDecision:
    if provider == "mock":
        return AiExecutionDecision(
            external_allowed=False,
            reason="local_provider",
            data_classification=data_classification,
            provider_region="local",
            pii_redaction_required=True,
            projected_cost_usd=0.0,
        )
    policy = db.scalar(
        select(AiDataPolicy).where(AiDataPolicy.tenant_id == tenant_id)
    )
    if policy is None or not policy.external_processing_enabled:
        return AiExecutionDecision(False, "external_processing_disabled", data_classification, None, True, projected_cost_usd)
    providers = set(json_value(policy.allowed_providers_json, []))
    regions = json_value(policy.provider_regions_json, {})
    region = str(regions.get(provider) or "") or None
    if provider not in providers:
        return AiExecutionDecision(False, "provider_not_allowed", data_classification, region, policy.pii_redaction_required, projected_cost_usd)
    if region is None:
        return AiExecutionDecision(False, "provider_region_not_configured", data_classification, None, policy.pii_redaction_required, projected_cost_usd)
    if not cost_rates_configured:
        return AiExecutionDecision(
            False,
            "cost_rates_not_configured",
            data_classification,
            region,
            policy.pii_redaction_required or contains_pii,
            projected_cost_usd,
        )
    if contains_pii and not policy.allow_reversible_redaction:
        return AiExecutionDecision(
            False,
            "reversible_pii_redaction_not_allowed",
            data_classification,
            region,
            True,
            projected_cost_usd,
        )
    if CLASSIFICATION_RANK[data_classification] > CLASSIFICATION_RANK[policy.maximum_external_classification]:
        return AiExecutionDecision(False, "data_classification_blocked", data_classification, region, policy.pii_redaction_required, projected_cost_usd)
    circuit = _circuit(db, tenant_id, provider, lock=True)
    now = utcnow()
    if circuit and circuit.state == "OPEN":
        if circuit.open_until and circuit.open_until <= now:
            circuit.state = "HALF_OPEN"
            circuit.probe_started_at = now
            circuit.revision += 1
        else:
            return AiExecutionDecision(False, "provider_circuit_open", data_classification, region, policy.pii_redaction_required, projected_cost_usd)
    elif circuit and circuit.state == "HALF_OPEN":
        probe_timeout = timedelta(seconds=circuit.cooldown_seconds)
        if (
            circuit.probe_started_at
            and circuit.probe_started_at + probe_timeout > now
        ):
            return AiExecutionDecision(
                False,
                "provider_half_open_probe_active",
                data_classification,
                region,
                policy.pii_redaction_required or contains_pii,
                projected_cost_usd,
            )
        circuit.probe_started_at = now
        circuit.revision += 1
    budget_statement = select(AiUsageBudget).where(
        AiUsageBudget.tenant_id == tenant_id
    )
    if db.get_bind().dialect.name == "postgresql":
        budget_statement = budget_statement.with_for_update()
    budget = db.scalar(budget_statement)
    if budget is None:
        return AiExecutionDecision(
            False,
            "usage_budget_not_configured",
            data_classification,
            region,
            policy.pii_redaction_required or contains_pii,
            projected_cost_usd,
        )
    if budget.hard_limit_enabled:
        totals = usage_totals(db, tenant_id, now)
        if totals["monthly_requests"] + 1 > budget.monthly_request_limit:
            return AiExecutionDecision(False, "monthly_request_budget_exceeded", data_classification, region, policy.pii_redaction_required, projected_cost_usd)
        if totals["daily_requests"] + 1 > budget.daily_request_limit:
            return AiExecutionDecision(False, "daily_request_budget_exceeded", data_classification, region, policy.pii_redaction_required, projected_cost_usd)
        if totals["monthly_cost_usd"] + projected_cost_usd > budget.monthly_cost_limit_usd:
            return AiExecutionDecision(False, "monthly_cost_budget_exceeded", data_classification, region, policy.pii_redaction_required, projected_cost_usd)
    return AiExecutionDecision(
        True,
        None,
        data_classification,
        region,
        policy.pii_redaction_required or contains_pii,
        projected_cost_usd,
    )


def record_provider_result(
    db: Session,
    *,
    tenant_id: str,
    provider: str,
    success: bool,
    failure_code: str | None = None,
) -> AiProviderCircuit | None:
    if provider == "mock":
        return None
    item = _circuit(db, tenant_id, provider, lock=True)
    if item is None:
        item = AiProviderCircuit(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            provider=provider,
            state="CLOSED",
        )
        db.add(item)
        db.flush()
    now = utcnow()
    if success:
        item.state = "CLOSED"
        item.consecutive_failures = 0
        item.last_success_at = now
        item.opened_at = None
        item.open_until = None
        item.last_failure_code = None
        item.probe_started_at = None
    else:
        item.consecutive_failures += 1
        item.last_failure_at = now
        item.last_failure_code = (failure_code or "provider_fallback")[:120]
        if item.consecutive_failures >= item.failure_threshold:
            item.state = "OPEN"
            item.opened_at = now
            item.open_until = now + timedelta(seconds=item.cooldown_seconds)
            item.probe_started_at = None
    item.revision += 1
    return item


def record_usage(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    operation: str,
    requested_provider: str,
    provider: str,
    model: str,
    provider_region: str | None,
    data_classification: str,
    pii_redacted: bool,
    input_text: str,
    output_text: str | None,
    estimated_cost_usd: float,
    latency_ms: int,
    outcome: str,
    fallback_reason: str | None,
    prompt_version_id: str | None,
    correlation_key: str | None = None,
) -> AiUsageLedger:
    item = AiUsageLedger(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        operation=operation,
        requested_provider=requested_provider,
        provider=provider,
        model=model,
        provider_region=provider_region,
        data_classification=data_classification,
        pii_redacted=pii_redacted,
        input_sha256=digest_text(input_text),
        output_sha256=digest_text(output_text) if output_text else None,
        input_tokens_estimated=estimate_tokens(input_text),
        output_tokens_estimated=estimate_tokens(output_text or "") if output_text else 0,
        estimated_cost_usd=max(0.0, estimated_cost_usd),
        latency_ms=max(0, latency_ms),
        outcome=outcome,
        fallback_reason=fallback_reason,
        prompt_version_id=prompt_version_id,
        correlation_sha256=digest_text(correlation_key) if correlation_key else None,
    )
    db.add(item)
    return item


def runtime_dashboard(db: Session, tenant_id: str) -> dict[str, Any]:
    policy = db.scalar(select(AiDataPolicy).where(AiDataPolicy.tenant_id == tenant_id))
    budget = db.scalar(select(AiUsageBudget).where(AiUsageBudget.tenant_id == tenant_id))
    totals = usage_totals(db, tenant_id)
    circuits = db.scalars(
        select(AiProviderCircuit).where(AiProviderCircuit.tenant_id == tenant_id)
    ).all()
    return {
        "policy_configured": policy is not None,
        "external_processing_enabled": bool(policy and policy.external_processing_enabled),
        "allowed_providers": json_value(policy.allowed_providers_json, []) if policy else [],
        "provider_regions": json_value(policy.provider_regions_json, {}) if policy else {},
        "maximum_external_classification": policy.maximum_external_classification if policy else "INTERNAL",
        "pii_redaction_required": True if policy is None else policy.pii_redaction_required,
        "data_policy": (
            {
                "id": policy.id,
                "revision": policy.revision,
                "external_processing_enabled": policy.external_processing_enabled,
                "allowed_providers": json_value(policy.allowed_providers_json, []),
                "provider_regions": json_value(policy.provider_regions_json, {}),
                "maximum_external_classification": policy.maximum_external_classification,
                "pii_redaction_required": policy.pii_redaction_required,
                "allow_reversible_redaction": policy.allow_reversible_redaction,
                "retention_days": policy.retention_days,
            }
            if policy
            else None
        ),
        "usage": totals,
        "budget": (
            {
                "monthly_request_limit": budget.monthly_request_limit,
                "monthly_cost_limit_usd": budget.monthly_cost_limit_usd,
                "daily_request_limit": budget.daily_request_limit,
                "warning_percent": budget.warning_percent,
                "hard_limit_enabled": budget.hard_limit_enabled,
                "revision": budget.revision,
            }
            if budget
            else None
        ),
        "circuits": [
            {
                "provider": item.provider,
                "state": item.state,
                "consecutive_failures": item.consecutive_failures,
                "failure_threshold": item.failure_threshold,
                "open_until": item.open_until,
                "last_failure_code": item.last_failure_code,
            }
            for item in circuits
        ],
    }
