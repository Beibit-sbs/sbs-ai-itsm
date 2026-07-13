"""Real metrics infrastructure integration service layer."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models.policy_rollout_metrics import (
    PolicyRolloutMetricsHistory,
    PolicyRolloutMetricsSnapshot,
)
from app.services.audit import log_audit

logger = logging.getLogger("app.metrics_infrastructure")


def store_metrics_history(
    db: Session,
    rollout_id: str,
    error_rate: float | None = None,
    latency_p99_ms: float | None = None,
    throughput_eps: float | None = None,
    cpu_percent: float | None = None,
    memory_percent: float | None = None,
    request_count: int | None = None,
    source: str = "prometheus",
    collection_duration_ms: int | None = None,
    raw_data: dict | None = None,
) -> PolicyRolloutMetricsHistory:
    """Store metrics snapshot in historical table.
    
    Args:
        db: Database session
        rollout_id: Canary rollout ID
        error_rate: Current error rate (percent, e.g., 0.5)
        latency_p99_ms: P99 latency in milliseconds
        throughput_eps: Events per second
        cpu_percent: CPU utilization percent
        memory_percent: Memory utilization percent
        request_count: Total request count
        source: Metrics source ('prometheus', 'cloudwatch', 'simulated')
        collection_duration_ms: How long collection took
        raw_data: Raw metrics response (for debugging)
    
    Returns:
        Created history record
    """
    record = PolicyRolloutMetricsHistory(
        rollout_id=rollout_id,
        collected_at=datetime.now(UTC),
        error_rate=error_rate,
        latency_p99_ms=latency_p99_ms,
        throughput_eps=throughput_eps,
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        request_count=request_count,
        source=source,
        collection_duration_ms=collection_duration_ms,
        raw_data=raw_data,
    )
    
    db.add(record)
    db.commit()
    
    return record


def update_metrics_snapshot(
    db: Session,
    rollout_id: str,
    error_rate: float | None = None,
    latency_p99_ms: float | None = None,
    throughput_eps: float | None = None,
    cpu_percent: float | None = None,
    memory_percent: float | None = None,
    request_count: int | None = None,
    error_rate_baseline: float | None = None,
) -> PolicyRolloutMetricsSnapshot:
    """Update metrics snapshot (latest values for quick access).
    
    Denormalized table for fast queries without joins.
    Also calculates trends compared to previous snapshot.
    
    Args:
        db: Database session
        rollout_id: Canary rollout ID
        error_rate: Current error rate
        latency_p99_ms: P99 latency
        throughput_eps: Events per second
        cpu_percent: CPU utilization
        memory_percent: Memory utilization
        request_count: Request count
        error_rate_baseline: Baseline for comparison
    
    Returns:
        Updated snapshot record
    """
    # Get current snapshot to compare
    current = db.query(PolicyRolloutMetricsSnapshot).filter_by(rollout_id=rollout_id).first()
    
    error_rate_previous = None
    error_rate_increasing = None
    error_rate_change_percent = None
    
    if current and current.error_rate is not None and error_rate is not None:
        error_rate_previous = current.error_rate
        
        # Calculate trend
        if current.error_rate > 0:
            error_rate_change_percent = ((error_rate - current.error_rate) / current.error_rate) * 100
        else:
            # From zero baseline
            error_rate_change_percent = None if current.error_rate == 0 else 0.0
        
        error_rate_increasing = error_rate > current.error_rate
    
    if current:
        # Update existing
        current.error_rate = error_rate
        current.latency_p99_ms = latency_p99_ms
        current.throughput_eps = throughput_eps
        current.cpu_percent = cpu_percent
        current.memory_percent = memory_percent
        current.request_count = request_count
        current.snapshot_at = datetime.now(UTC)
        current.error_rate_baseline = error_rate_baseline
        current.error_rate_previous = error_rate_previous
        current.error_rate_increasing = error_rate_increasing
        current.error_rate_change_percent = error_rate_change_percent
        current.updated_at = datetime.now(UTC)
        record = current
    else:
        # Create new
        record = PolicyRolloutMetricsSnapshot(
            rollout_id=rollout_id,
            error_rate=error_rate,
            latency_p99_ms=latency_p99_ms,
            throughput_eps=throughput_eps,
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            request_count=request_count,
            snapshot_at=datetime.now(UTC),
            error_rate_baseline=error_rate_baseline,
            error_rate_previous=error_rate_previous,
            error_rate_increasing=error_rate_increasing,
            error_rate_change_percent=error_rate_change_percent,
        )
        db.add(record)
    
    db.commit()
    return record


def get_metrics_history(
    db: Session,
    rollout_id: str,
    limit: int = 100,
    minutes_back: int | None = None,
) -> list[PolicyRolloutMetricsHistory]:
    """Get historical metrics for a rollout.
    
    Args:
        db: Database session
        rollout_id: Canary rollout ID
        limit: Maximum number of records to return
        minutes_back: Optional time window (only return data from last N minutes)
    
    Returns:
        List of historical metrics records
    """
    query = db.query(PolicyRolloutMetricsHistory).filter_by(rollout_id=rollout_id)
    
    if minutes_back:
        cutoff = datetime.now(UTC) - timedelta(minutes=minutes_back)
        query = query.filter(PolicyRolloutMetricsHistory.collected_at >= cutoff)
    
    query = query.order_by(desc(PolicyRolloutMetricsHistory.collected_at))
    
    return query.limit(limit).all()


def get_metrics_snapshot(
    db: Session,
    rollout_id: str,
) -> PolicyRolloutMetricsSnapshot | None:
    """Get latest metrics snapshot for quick access.
    
    Args:
        db: Database session
        rollout_id: Canary rollout ID
    
    Returns:
        Latest snapshot or None if not found
    """
    return db.query(PolicyRolloutMetricsSnapshot).filter_by(rollout_id=rollout_id).first()


def get_metrics_trend(
    db: Session,
    rollout_id: str,
    minutes_back: int = 30,
) -> dict[str, Any]:
    """Analyze metrics trend over time window.
    
    Args:
        db: Database session
        rollout_id: Canary rollout ID
        minutes_back: Time window for analysis (default 30 minutes)
    
    Returns:
        Dictionary with trend analysis
    """
    history = get_metrics_history(db, rollout_id, limit=1000, minutes_back=minutes_back)
    
    if not history:
        return {
            "rollout_id": rollout_id,
            "data_points": 0,
            "error_rate_min": None,
            "error_rate_max": None,
            "error_rate_avg": None,
            "error_rate_trend": None,  # "up", "down", or "stable"
            "latency_min": None,
            "latency_max": None,
            "latency_avg": None,
        }
    
    error_rates = [h.error_rate for h in history if h.error_rate is not None]
    latencies = [h.latency_p99_ms for h in history if h.latency_p99_ms is not None]
    
    # Calculate trend: compare first half to second half
    trend = None
    if len(error_rates) > 2:
        mid = len(error_rates) // 2
        first_half_avg = sum(error_rates[:mid]) / len(error_rates[:mid]) if error_rates[:mid] else None
        second_half_avg = sum(error_rates[mid:]) / len(error_rates[mid:]) if error_rates[mid:] else None
        
        if first_half_avg and second_half_avg:
            if second_half_avg > first_half_avg * 1.1:  # >10% increase
                trend = "up"
            elif second_half_avg < first_half_avg * 0.9:  # >10% decrease
                trend = "down"
            else:
                trend = "stable"
    
    return {
        "rollout_id": rollout_id,
        "time_window_minutes": minutes_back,
        "data_points": len(history),
        "error_rate_min": min(error_rates) if error_rates else None,
        "error_rate_max": max(error_rates) if error_rates else None,
        "error_rate_avg": sum(error_rates) / len(error_rates) if error_rates else None,
        "error_rate_trend": trend,
        "latency_min": min(latencies) if latencies else None,
        "latency_max": max(latencies) if latencies else None,
        "latency_avg": sum(latencies) / len(latencies) if latencies else None,
    }


def clean_old_metrics(
    db: Session,
    days_to_keep: int = 30,
) -> int:
    """Clean up old metrics history records.
    
    Args:
        db: Database session
        days_to_keep: How many days of history to retain
    
    Returns:
        Number of records deleted
    """
    cutoff = datetime.now(UTC) - timedelta(days=days_to_keep)
    
    result = db.query(PolicyRolloutMetricsHistory).filter(
        PolicyRolloutMetricsHistory.created_at < cutoff
    ).delete()
    
    db.commit()
    
    return result


class MetricsCollectorInterface:
    """Interface for pluggable metrics collection backends."""
    
    async def collect_metrics(self, rollout_id: str, consumer_name: str) -> dict[str, float | None]:
        """Collect metrics for a rollout.
        
        Args:
            rollout_id: Canary rollout ID
            consumer_name: Consumer name
        
        Returns:
            Dict with metric values:
            {
                "error_rate": float,
                "latency_p99_ms": float,
                "throughput_eps": float,
            }
        """
        raise NotImplementedError


class PrometheusMetricsCollector(MetricsCollectorInterface):
    """Prometheus metrics collector backend."""
    
    def __init__(self, prometheus_url: str):
        self.prometheus_url = prometheus_url
    
    async def collect_metrics(self, rollout_id: str, consumer_name: str) -> dict[str, float | None]:
        """Collect metrics from Prometheus."""
        # TODO: Implement real Prometheus queries
        # For now, return simulated data (Stage 032+)
        return {
            "error_rate": 0.5,
            "latency_p99_ms": 250.0,
            "throughput_eps": 1000.0,
        }


class CloudWatchMetricsCollector(MetricsCollectorInterface):
    """CloudWatch metrics collector backend."""
    
    def __init__(self, region: str):
        self.region = region
    
    async def collect_metrics(self, rollout_id: str, consumer_name: str) -> dict[str, float | None]:
        """Collect metrics from CloudWatch."""
        # TODO: Implement real CloudWatch queries
        # For now, return simulated data (Stage 032+)
        return {
            "error_rate": 0.5,
            "latency_p99_ms": 250.0,
            "throughput_eps": 1000.0,
        }


class SimulatedMetricsCollector(MetricsCollectorInterface):
    """Simulated metrics collector for development/testing."""
    
    async def collect_metrics(self, rollout_id: str, consumer_name: str) -> dict[str, float | None]:
        """Return simulated metrics."""
        import random
        return {
            "error_rate": 0.5 + random.uniform(-0.1, 0.2),
            "latency_p99_ms": 250.0 + random.uniform(-50, 100),
            "throughput_eps": 1000.0 + random.uniform(-100, 200),
        }
