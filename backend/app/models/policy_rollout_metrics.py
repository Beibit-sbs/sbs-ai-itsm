"""Policy rollout metrics history model for time-series tracking."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.db.base import Base


class PolicyRolloutMetricsHistory(Base):
    """Historical metrics records for policy canary rollouts.
    
    Stores time-series metrics data collected during rollout monitoring.
    Enables trend analysis, alerting, and post-incident investigation.
    """
    
    __tablename__ = "policy_rollout_metrics_history"
    
    id: str = Column(String(36), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    
    # Reference to the rollout
    rollout_id: str = Column(String(36), ForeignKey("policy_canary_rollout.id"), nullable=False, index=True)
    
    # Metric collection timestamp
    collected_at: datetime = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # Metrics values (point-in-time snapshot)
    error_rate: float | None = Column(Float, nullable=True)  # E.g., 0.5 (0.5%)
    latency_p99_ms: float | None = Column(Float, nullable=True)  # E.g., 250.5
    throughput_eps: float | None = Column(Float, nullable=True)  # E.g., 1000.0 (events/second)
    
    # Additional metrics that may be collected
    cpu_percent: float | None = Column(Float, nullable=True)
    memory_percent: float | None = Column(Float, nullable=True)
    request_count: Integer | None = Column(Integer, nullable=True)
    
    # Metadata about this collection
    source: str | None = Column(String(50), nullable=True)  # E.g., 'prometheus', 'cloudwatch', 'simulated'
    collection_duration_ms: Integer | None = Column(Integer, nullable=True)  # How long collection took
    
    # Store raw response for debugging
    raw_data: dict | None = Column(JSON, nullable=True)
    
    # Audit trail
    created_at: datetime = Column(DateTime(timezone=True), nullable=False, default=datetime.now(UTC))
    
    # Indexes for efficient querying
    __table_args__ = (
        Index("ix_metrics_history_rollout_collected", "rollout_id", "collected_at"),
        Index("ix_metrics_history_collected_desc", "collected_at"),
    )
    
    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "rollout_id": self.rollout_id,
            "collected_at": self.collected_at,
            "error_rate": self.error_rate,
            "latency_p99_ms": self.latency_p99_ms,
            "throughput_eps": self.throughput_eps,
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "request_count": self.request_count,
            "source": self.source,
            "collection_duration_ms": self.collection_duration_ms,
        }


class PolicyRolloutMetricsSnapshot(Base):
    """Latest metrics snapshot for a rollout (for quick access).
    
    Denormalized table storing only the most recent metrics for fast queries.
    Updated on each polling cycle to provide quick access to current state.
    """
    
    __tablename__ = "policy_rollout_metrics_snapshot"
    
    rollout_id: str = Column(String(36), ForeignKey("policy_canary_rollout.id"), primary_key=True)
    
    # Latest metric values
    error_rate: float | None = Column(Float, nullable=True)
    latency_p99_ms: float | None = Column(Float, nullable=True)
    throughput_eps: float | None = Column(Float, nullable=True)
    cpu_percent: float | None = Column(Float, nullable=True)
    memory_percent: float | None = Column(Float, nullable=True)
    request_count: Integer | None = Column(Integer, nullable=True)
    
    # When this snapshot was taken
    snapshot_at: datetime = Column(DateTime(timezone=True), nullable=False)
    
    # Historical context
    error_rate_baseline: float | None = Column(Float, nullable=True)  # For trend comparison
    error_rate_previous: float | None = Column(Float, nullable=True)  # Previous poll value
    
    # Trend indicators
    error_rate_increasing: bool | None = Column(nullable=True)  # True if trending up
    error_rate_change_percent: float | None = Column(Float, nullable=True)  # % change from previous
    
    # Last update timestamp
    updated_at: datetime = Column(DateTime(timezone=True), nullable=False, default=datetime.now(UTC))
    
    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "rollout_id": self.rollout_id,
            "error_rate": self.error_rate,
            "latency_p99_ms": self.latency_p99_ms,
            "throughput_eps": self.throughput_eps,
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "request_count": self.request_count,
            "snapshot_at": self.snapshot_at,
            "error_rate_baseline": self.error_rate_baseline,
            "error_rate_previous": self.error_rate_previous,
            "error_rate_increasing": self.error_rate_increasing,
            "error_rate_change_percent": self.error_rate_change_percent,
        }
