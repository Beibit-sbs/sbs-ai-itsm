"""
Stage 035: Dashboard service for aggregating metrics, analysis, and alerts.

Functions:
- get_dashboard_summary() - Overall system health snapshot
- get_metrics_timeline() - Time-series metrics for charting
- get_active_alerts() - Current alerts with context
- get_rollout_comparison() - Compare multiple rollouts
- get_anomaly_timeline() - Anomaly events over time
"""

from datetime import datetime, timedelta, UTC
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from app.models.policy_rollout_metrics import (
    PolicyRolloutMetricsHistory,
    PolicyRolloutMetricsSnapshot,
)
from app.models.metrics_analysis import (
    PolicyMetricsAnomalyDetection,
    PolicyMetricsHealthAssessment,
)
from app.models.alert_notifications import (
    PolicyAlertHistory,
)
from app.models.policy_canary_rollout import PolicyCanaryRollout


def get_dashboard_summary(db: Session, tenant_id: str) -> dict:
    """Get overall dashboard health snapshot."""
    try:
        # Count active rollouts
        active_rollouts = db.query(PolicyCanaryRollout).filter(
            and_(
                PolicyCanaryRollout.tenant_id == tenant_id,
                PolicyCanaryRollout.status == "active",
            )
        ).count()

        # Get latest health assessments
        health_assessments = db.query(PolicyMetricsHealthAssessment).filter(
            PolicyMetricsHealthAssessment.tenant_id == tenant_id,
        ).order_by(
            desc(PolicyMetricsHealthAssessment.assessed_at)
        ).limit(10).all()

        # Calculate average health score
        health_scores = [h.health_score for h in health_assessments if h.health_score]
        avg_health = sum(health_scores) / len(health_scores) if health_scores else 0.0

        # Count active alerts
        active_alerts = db.query(PolicyAlertHistory).filter(
            and_(
                PolicyAlertHistory.tenant_id == tenant_id,
                PolicyAlertHistory.status == "active",
            )
        ).count()

        # Count critical alerts
        critical_alerts = db.query(PolicyAlertHistory).filter(
            and_(
                PolicyAlertHistory.tenant_id == tenant_id,
                PolicyAlertHistory.status == "active",
                PolicyAlertHistory.severity == "critical",
            )
        ).count()

        # Count anomalies
        recent_anomalies = db.query(PolicyMetricsAnomalyDetection).filter(
            and_(
                PolicyMetricsAnomalyDetection.tenant_id == tenant_id,
                PolicyMetricsAnomalyDetection.resolved_at.is_(None),
            )
        ).count()

        return {
            "timestamp": datetime.now(UTC).isoformat() + "Z",
            "active_rollouts": active_rollouts,
            "avg_health_score": avg_health,
            "health_status": "healthy" if avg_health >= 0.8 else "degraded" if avg_health >= 0.5 else "critical",
            "active_alerts": active_alerts,
            "critical_alerts": critical_alerts,
            "unresolved_anomalies": recent_anomalies,
            "system_status": "operational" if critical_alerts == 0 else "degraded" if critical_alerts < 5 else "critical",
        }
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }


def get_metrics_timeline(
    db: Session,
    tenant_id: str,
    rollout_id: str,
    minutes_back: int = 60,
    metric_type: str = "error_rate",
) -> dict:
    """Get time-series metrics for dashboard charting."""
    try:
        cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes_back)

        # Get history data
        history = db.query(PolicyRolloutMetricsHistory).filter(
            and_(
                PolicyRolloutMetricsHistory.rollout_id == rollout_id,
                PolicyRolloutMetricsHistory.tenant_id == tenant_id,
                PolicyRolloutMetricsHistory.collected_at >= cutoff_time,
            )
        ).order_by(PolicyRolloutMetricsHistory.collected_at).all()

        # Extract metric values
        timestamps = []
        values = []
        for record in history:
            timestamps.append(record.collected_at.isoformat() + "Z")
            if metric_type == "error_rate":
                values.append(record.error_rate or 0)
            elif metric_type == "latency_p99":
                values.append(record.latency_p99_ms or 0)
            elif metric_type == "throughput":
                values.append(record.throughput_eps or 0)
            elif metric_type == "cpu":
                values.append(record.cpu_percent or 0)
            elif metric_type == "memory":
                values.append(record.memory_percent or 0)

        # Calculate statistics
        if values:
            avg_value = sum(values) / len(values)
            min_value = min(values)
            max_value = max(values)
        else:
            avg_value = min_value = max_value = 0

        return {
            "rollout_id": rollout_id,
            "metric_type": metric_type,
            "time_window_minutes": minutes_back,
            "timestamps": timestamps,
            "values": values,
            "statistics": {
                "average": avg_value,
                "minimum": min_value,
                "maximum": max_value,
                "data_points": len(values),
            },
        }
    except Exception as e:
        return {
            "error": str(e),
            "rollout_id": rollout_id,
            "metric_type": metric_type,
        }


def get_active_alerts(
    db: Session,
    tenant_id: str,
    severity_filter: str | None = None,
    limit: int = 50,
) -> dict:
    """Get current active alerts with context."""
    try:
        query = db.query(PolicyAlertHistory).filter(
            and_(
                PolicyAlertHistory.tenant_id == tenant_id,
                PolicyAlertHistory.status.in_(["active", "acknowledged"]),
            )
        )

        if severity_filter and severity_filter in ["critical", "high", "medium", "low"]:
            query = query.filter(PolicyAlertHistory.severity == severity_filter)

        alerts = query.order_by(
            desc(PolicyAlertHistory.triggered_at)
        ).limit(limit).all()

        alert_list = []
        for alert in alerts:
            duration = None
            if alert.resolved_at:
                duration = int((alert.resolved_at - alert.triggered_at).total_seconds())
            elif alert.triggered_at:
                duration = int((datetime.now(UTC) - alert.triggered_at).total_seconds())

            alert_list.append({
                "id": alert.id,
                "rule_id": alert.alert_rule_id,
                "rule_name": alert.rule_name,
                "rollout_id": alert.rollout_id,
                "metric": alert.metric,
                "current_value": alert.current_value,
                "threshold": alert.threshold,
                "operator": alert.operator,
                "severity": alert.severity,
                "status": alert.status,
                "triggered_at": alert.triggered_at.isoformat() + "Z" if alert.triggered_at else None,
                "acknowledged_at": alert.acknowledged_at.isoformat() + "Z" if alert.acknowledged_at else None,
                "duration_seconds": duration,
                "breach_count": alert.breach_count,
                "breach_percentage": alert.breach_percentage,
            })

        return {
            "alerts": alert_list,
            "count": len(alert_list),
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }
    except Exception as e:
        return {
            "error": str(e),
            "alerts": [],
            "count": 0,
        }


def get_rollout_comparison(
    db: Session,
    tenant_id: str,
    rollout_ids: list[str],
) -> dict:
    """Compare multiple rollouts side-by-side."""
    try:
        rollouts = []
        for rollout_id in rollout_ids[:10]:  # Limit to 10 comparisons
            # Get latest snapshot
            snapshot = db.query(PolicyRolloutMetricsSnapshot).filter(
                and_(
                    PolicyRolloutMetricsSnapshot.rollout_id == rollout_id,
                    PolicyRolloutMetricsSnapshot.tenant_id == tenant_id,
                )
            ).first()

            # Get latest health
            health = db.query(PolicyMetricsHealthAssessment).filter(
                and_(
                    PolicyMetricsHealthAssessment.rollout_id == rollout_id,
                    PolicyMetricsHealthAssessment.tenant_id == tenant_id,
                )
            ).order_by(desc(PolicyMetricsHealthAssessment.assessed_at)).first()

            # Get active alerts for rollout
            alert_count = db.query(PolicyAlertHistory).filter(
                and_(
                    PolicyAlertHistory.rollout_id == rollout_id,
                    PolicyAlertHistory.tenant_id == tenant_id,
                    PolicyAlertHistory.status == "active",
                )
            ).count()

            rollouts.append({
                "rollout_id": rollout_id,
                "error_rate": snapshot.error_rate if snapshot else None,
                "latency_p99_ms": snapshot.latency_p99_ms if snapshot else None,
                "throughput_eps": snapshot.throughput_eps if snapshot else None,
                "health_score": health.health_score if health else None,
                "health_status": health.status if health else None,
                "active_alerts": alert_count,
                "error_trend": snapshot.error_rate_increasing if snapshot else None,
            })

        return {
            "comparison": rollouts,
            "count": len(rollouts),
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }
    except Exception as e:
        return {
            "error": str(e),
            "comparison": [],
            "count": 0,
        }


def get_anomaly_timeline(
    db: Session,
    tenant_id: str,
    rollout_id: str | None = None,
    minutes_back: int = 1440,  # 24 hours
) -> dict:
    """Get anomaly detection events over time."""
    try:
        cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes_back)

        query = db.query(PolicyMetricsAnomalyDetection).filter(
            and_(
                PolicyMetricsAnomalyDetection.tenant_id == tenant_id,
                PolicyMetricsAnomalyDetection.created_at >= cutoff_time,
            )
        )

        if rollout_id:
            query = query.filter(PolicyMetricsAnomalyDetection.rollout_id == rollout_id)

        anomalies = query.order_by(
            desc(PolicyMetricsAnomalyDetection.created_at)
        ).limit(100).all()

        timeline = []
        for anomaly in anomalies:
            timeline.append({
                "id": anomaly.id,
                "rollout_id": anomaly.rollout_id,
                "metric": anomaly.metric,
                "detection_method": anomaly.detection_method,
                "anomaly_score": anomaly.anomaly_score,
                "severity": anomaly.severity,
                "value": anomaly.value,
                "baseline": anomaly.baseline,
                "deviation_percent": anomaly.deviation_percent,
                "created_at": anomaly.created_at.isoformat() + "Z",
                "acknowledged": anomaly.acknowledged,
                "resolved_at": anomaly.resolved_at.isoformat() + "Z" if anomaly.resolved_at else None,
            })

        return {
            "anomalies": timeline,
            "count": len(timeline),
            "time_window_minutes": minutes_back,
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }
    except Exception as e:
        return {
            "error": str(e),
            "anomalies": [],
            "count": 0,
        }


def get_metric_correlation_matrix(
    db: Session,
    tenant_id: str,
    rollout_id: str,
    time_window_minutes: int = 60,
) -> dict:
    """Get correlation matrix between metrics."""
    try:
        cutoff_time = datetime.now(UTC) - timedelta(minutes=time_window_minutes)

        # Get all metrics for time window
        history = db.query(PolicyRolloutMetricsHistory).filter(
            and_(
                PolicyRolloutMetricsHistory.rollout_id == rollout_id,
                PolicyRolloutMetricsHistory.tenant_id == tenant_id,
                PolicyRolloutMetricsHistory.collected_at >= cutoff_time,
            )
        ).order_by(PolicyRolloutMetricsHistory.collected_at).all()

        if not history:
            return {
                "rollout_id": rollout_id,
                "correlation_matrix": {},
                "metric_count": 0,
            }

        # Extract metrics
        metrics = {
            "error_rate": [h.error_rate for h in history if h.error_rate is not None],
            "latency_p99": [h.latency_p99_ms for h in history if h.latency_p99_ms is not None],
            "throughput": [h.throughput_eps for h in history if h.throughput_eps is not None],
            "cpu": [h.cpu_percent for h in history if h.cpu_percent is not None],
            "memory": [h.memory_percent for h in history if h.memory_percent is not None],
        }

        # Simple correlation calculation (Pearson)
        def pearson_correlation(x: list[float], y: list[float]) -> float:
            if len(x) < 2 or len(y) < 2 or len(x) != len(y):
                return 0.0
            
            mean_x = sum(x) / len(x)
            mean_y = sum(y) / len(y)
            
            numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x)))
            denom_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
            denom_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5
            
            if denom_x == 0 or denom_y == 0:
                return 0.0
            
            return numerator / (denom_x * denom_y)

        # Build correlation matrix
        metric_names = [k for k, v in metrics.items() if v]
        correlation_matrix = {}

        for i, metric_a in enumerate(metric_names):
            correlation_matrix[metric_a] = {}
            for j, metric_b in enumerate(metric_names):
                if i == j:
                    correlation_matrix[metric_a][metric_b] = 1.0
                else:
                    corr = pearson_correlation(metrics[metric_a], metrics[metric_b])
                    correlation_matrix[metric_a][metric_b] = corr

        return {
            "rollout_id": rollout_id,
            "correlation_matrix": correlation_matrix,
            "metric_count": len(metric_names),
            "time_window_minutes": time_window_minutes,
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }
    except Exception as e:
        return {
            "error": str(e),
            "rollout_id": rollout_id,
            "correlation_matrix": {},
        }
