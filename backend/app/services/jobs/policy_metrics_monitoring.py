"""Metrics monitoring service for policy canary rollouts."""
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.policy_canary_rollout import PolicyCanaryRollout
from app.models.policy_approval_request import PolicyApprovalRequest


def _simulate_metrics() -> dict[str, float]:
    """Simulate metrics collection from infrastructure.
    
    In production, this would query Prometheus, CloudWatch, DataDog, etc.
    """
    return {
        "error_rate": 0.48,  # Baseline is 0.5%, current is 0.48%
        "latency_p99_ms": 155,
        "throughput_eps": 105,
    }


def update_rollout_metrics(
    db: Session,
    rollout_id: str,
    metrics: dict[str, Any] | None = None,
) -> PolicyCanaryRollout:
    """Update current metrics during canary rollout.
    
    Args:
        db: Database session
        rollout_id: PolicyCanaryRollout ID
        metrics: Current metrics dict (if None, simulate)
    
    Returns:
        Updated PolicyCanaryRollout record
    """
    rollout = db.query(PolicyCanaryRollout).filter_by(id=rollout_id).first()
    if not rollout:
        raise ValueError(f"Rollout {rollout_id} not found")
    
    if metrics is None:
        metrics = _simulate_metrics()
    
    rollout.metrics_current_json = json.dumps(metrics)
    rollout.error_rate_current = metrics.get("error_rate", 0.0)
    
    return rollout


def check_auto_rollback_threshold(
    baseline_error_rate: float | None,
    current_error_rate: float | None,
    threshold_percent: float = 50.0,  # 50% increase triggers rollback
) -> tuple[bool, str | None]:
    """Check if error rate exceeded threshold for auto-rollback.
    
    Args:
        baseline_error_rate: Baseline error rate (%) at rollout start
        current_error_rate: Current error rate (%) during rollout
        threshold_percent: Threshold as percentage increase (default 50%)
    
    Returns:
        Tuple of (should_rollback: bool, reason: str | None)
    """
    if baseline_error_rate is None or current_error_rate is None:
        return False, None
    
    if baseline_error_rate == 0:
        # Can't calculate percentage increase from 0; use absolute threshold
        if current_error_rate > 1.0:
            return True, f"error_rate_spike: {current_error_rate}% > 1.0% absolute threshold"
        return False, None
    
    percent_increase = ((current_error_rate - baseline_error_rate) / baseline_error_rate) * 100
    
    if percent_increase > threshold_percent:
        return True, f"error_rate_threshold_exceeded: {percent_increase:.1f}% > {threshold_percent}% threshold"
    
    return False, None


def evaluate_safe_to_graduate(
    rollout: PolicyCanaryRollout,
    threshold_percent: float = 50.0,
) -> tuple[bool, str]:
    """Evaluate if canary rollout is safe to graduate to next percentage.
    
    Args:
        rollout: PolicyCanaryRollout record with current metrics
        threshold_percent: Error rate threshold (default 50%)
    
    Returns:
        Tuple of (is_safe: bool, reason: str)
    """
    if rollout.auto_rollback_triggered:
        return False, f"already rolled back: {rollout.auto_rollback_reason}"
    
    if rollout.error_rate_baseline is None or rollout.error_rate_current is None:
        return False, "metrics not yet available (baseline or current is null)"
    
    should_rollback, reason = check_auto_rollback_threshold(
        rollout.error_rate_baseline,
        rollout.error_rate_current,
        threshold_percent,
    )
    
    if should_rollback:
        return False, f"error rate unsafe: {reason}"
    
    # Safe to graduate
    return True, "metrics stable, safe to graduate"


def estimate_auto_rollback_confidence(
    baseline_error_rate: float | None,
    current_error_rate: float | None,
) -> float:
    """Estimate confidence that rollout should auto-rollback (0.0-1.0).
    
    Args:
        baseline_error_rate: Baseline error rate (%)
        current_error_rate: Current error rate (%)
    
    Returns:
        Confidence score (0.0=definitely safe, 1.0=definitely rollback)
    """
    if baseline_error_rate is None or current_error_rate is None:
        return 0.0  # No data = safe
    
    if baseline_error_rate == 0:
        if current_error_rate > 2.0:
            return 1.0  # Spike = rollback
        if current_error_rate > 1.0:
            return 0.5  # Elevated = borderline
        return 0.0  # Normal = safe
    
    percent_increase = ((current_error_rate - baseline_error_rate) / baseline_error_rate) * 100
    
    if percent_increase < 0:
        return 0.0  # Improvement = definitely safe
    
    if percent_increase > 100:
        return 1.0  # Doubling = definitely rollback
    
    # Linear interpolation between 0% and 100% increase
    return min(1.0, percent_increase / 100.0)
