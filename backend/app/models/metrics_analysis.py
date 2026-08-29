"""
Stage 033: Database models for advanced metrics analysis.

Models:
- PolicyMetricsAlertRule - Alert rule definitions
- PolicyMetricsAnomalyDetection - Detected anomalies
- PolicyMetricsHealthAssessment - Rollout health snapshots
"""

from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class PolicyMetricsAlertRule(Base):
    """Alert rule for metric thresholds."""
    
    __tablename__ = "policy_metrics_alert_rules"
    
    id = Column(String, primary_key=True, index=True)
    rollout_id = Column(String, ForeignKey("policy_canary_rollouts.id"), nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    
    # Rule definition
    name = Column(String, nullable=False)  # "high_error_rate", etc.
    metric = Column(String, nullable=False)  # "error_rate", "latency_p99_ms"
    operator = Column(String, nullable=False)  # ">", "<", ">=", "<=", "==", "!="
    threshold = Column(Float, nullable=False)  # Threshold value
    duration_seconds = Column(Integer, default=60)  # Duration to trigger
    
    # Status
    enabled = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime, nullable=True)
    is_currently_triggered = Column(Boolean, default=False)
    
    # Metadata
    description = Column(String, nullable=True)
    severity_level = Column(String, default="medium")  # low, medium, high, critical
    notification_channels = Column(JSON, default={})  # {"email": ["admin@"], "slack": ["#alerts"]}
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    rollout = relationship("PolicyCanaryRollout")


class PolicyMetricsAnomalyDetection(Base):
    """Detected anomalies in metrics."""
    
    __tablename__ = "policy_metrics_anomaly_detection"
    
    id = Column(String, primary_key=True, index=True)
    rollout_id = Column(String, ForeignKey("policy_canary_rollouts.id"), nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    
    # Detection info
    metric = Column(String, nullable=False)  # "error_rate", "latency_p99_ms"
    detection_method = Column(String, nullable=False)  # "zscore", "iqr", "mad"
    anomaly_score = Column(Float, nullable=False)  # 0.0-1.0
    severity = Column(String, nullable=False)  # critical, high, medium, low, info
    
    # Anomaly details
    value = Column(Float, nullable=False)  # The anomalous value
    baseline = Column(Float, nullable=True)  # Expected/baseline value
    deviation_percent = Column(Float, nullable=True)  # % deviation from baseline
    anomaly_count = Column(Integer, nullable=True)  # How many anomalies detected
    total_count = Column(Integer, nullable=True)  # Total data points analyzed
    
    # Analysis metadata
    analysis_window_minutes = Column(Integer, default=30)
    raw_analysis = Column(JSON, nullable=True)  # Full analysis results
    
    # Status
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    
    detected_at = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True)


class PolicyMetricsHealthAssessment(Base):
    """Rollout health snapshots."""
    
    __tablename__ = "policy_metrics_health_assessment"
    
    id = Column(String, primary_key=True, index=True)
    rollout_id = Column(String, ForeignKey("policy_canary_rollouts.id"), nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    
    # Health scores
    health_score = Column(Float, nullable=False)  # 0.0-1.0
    status = Column(String, nullable=False)  # healthy, degraded, critical
    
    # Component health
    error_rate_health = Column(Float, nullable=True)  # 0.0-1.0
    latency_health = Column(Float, nullable=True)  # 0.0-1.0
    throughput_health = Column(Float, nullable=True)  # 0.0-1.0
    
    # Analysis
    summary = Column(String, nullable=True)
    primary_concern = Column(String, nullable=True)
    secondary_concerns = Column(JSON, default=[])  # List of strings
    recommendations = Column(JSON, default=[])  # List of strings
    
    # Metrics snapshot
    error_rate_current = Column(Float, nullable=True)
    latency_p99_current = Column(Float, nullable=True)
    throughput_current = Column(Float, nullable=True)
    
    # Analysis window
    analysis_window_minutes = Column(Integer, default=30)
    data_points_analyzed = Column(Integer, default=0)
    
    assessed_at = Column(DateTime, default=datetime.utcnow, index=True)


# Add relationships to PolicyCanaryRollout if needed
# These would be added in a migration or existing model updates
