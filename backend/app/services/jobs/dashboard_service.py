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
from sqlalchemy import desc

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


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    rendered = value.isoformat()
    return rendered.replace("+00:00", "Z") if value.tzinfo else f"{rendered}Z"


def _tenant_scoped(query, column, tenant_id: str | None):
    """Apply tenant isolation while allowing the root-only global stream."""
    if tenant_id in (None, "global"):
        return query
    return query.filter(column == tenant_id)


def _elapsed_hours(started_at: datetime | None, ended_at: datetime | None = None) -> float:
    if started_at is None:
        return 0.0
    end = ended_at or datetime.now(UTC)
    if started_at.tzinfo is None and end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    elif started_at.tzinfo is not None and end.tzinfo is None:
        end = end.replace(tzinfo=started_at.tzinfo)
    return max(0.0, (end - started_at).total_seconds() / 3600)


def get_dashboard_summary(db: Session, tenant_id: str | None) -> dict:
    """Get overall dashboard health snapshot."""
    try:
        # Canary rollout records are platform policy records and do not carry
        # tenant_id. Tenant-owned health, anomaly, and alert records are
        # filtered below for organization sessions.
        active_rollout_records = (
            db.query(PolicyCanaryRollout)
            .filter(PolicyCanaryRollout.status.in_(("active", "in_progress")))
            .order_by(desc(PolicyCanaryRollout.started_at))
            .all()
        )
        active_rollout_ids = [item.id for item in active_rollout_records]

        health_query = _tenant_scoped(
            db.query(PolicyMetricsHealthAssessment),
            PolicyMetricsHealthAssessment.tenant_id,
            tenant_id,
        )
        health_assessments = (
            health_query.order_by(desc(PolicyMetricsHealthAssessment.assessed_at))
            .limit(10)
            .all()
        )

        # Calculate average health score
        health_scores = [h.health_score for h in health_assessments if h.health_score]
        avg_health = sum(health_scores) / len(health_scores) if health_scores else 0.0

        # Count active alerts
        active_alert_query = db.query(PolicyAlertHistory).filter(
            PolicyAlertHistory.status == "active"
        )
        active_alerts = _tenant_scoped(
            active_alert_query,
            PolicyAlertHistory.tenant_id,
            tenant_id,
        ).count()

        # Count critical alerts
        critical_alert_query = db.query(PolicyAlertHistory).filter(
            PolicyAlertHistory.status == "active",
            PolicyAlertHistory.severity == "critical",
        )
        critical_alerts = _tenant_scoped(
            critical_alert_query,
            PolicyAlertHistory.tenant_id,
            tenant_id,
        ).count()

        # Count anomalies
        anomaly_query = db.query(PolicyMetricsAnomalyDetection).filter(
            PolicyMetricsAnomalyDetection.resolved_at.is_(None)
        )
        recent_anomalies = _tenant_scoped(
            anomaly_query,
            PolicyMetricsAnomalyDetection.tenant_id,
            tenant_id,
        ).count()

        return {
            "timestamp": _timestamp(),
            "active_rollouts": len(active_rollout_ids),
            "active_rollout_ids": active_rollout_ids,
            "avg_health_score": avg_health,
            "health_status": (
                "unknown"
                if not health_scores
                else "healthy"
                if avg_health >= 0.8
                else "degraded"
                if avg_health >= 0.5
                else "critical"
            ),
            "active_alerts": active_alerts,
            "critical_alerts": critical_alerts,
            "unresolved_anomalies": recent_anomalies,
            "system_status": "operational" if critical_alerts == 0 else "degraded" if critical_alerts < 5 else "critical",
        }
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": _timestamp(),
            "active_rollouts": 0,
            "active_rollout_ids": [],
            "avg_health_score": 0.0,
            "health_status": "unknown",
            "active_alerts": 0,
            "critical_alerts": 0,
            "unresolved_anomalies": 0,
            "system_status": "unknown",
        }


def get_metrics_timeline(
    db: Session,
    tenant_id: str | None,
    rollout_id: str,
    minutes_back: int = 60,
    metric_type: str = "error_rate",
) -> dict:
    """Get time-series metrics for dashboard charting."""
    try:
        cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes_back)

        # Get history data
        history = (
            db.query(PolicyRolloutMetricsHistory)
            .filter(
                PolicyRolloutMetricsHistory.rollout_id == rollout_id,
                PolicyRolloutMetricsHistory.collected_at >= cutoff_time,
            )
            .order_by(PolicyRolloutMetricsHistory.collected_at)
            .all()
        )

        # Extract metric values
        timestamps = []
        values = []
        for record in history:
            timestamps.append(_isoformat(record.collected_at))
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
            "time_window_minutes": minutes_back,
            "timestamps": [],
            "values": [],
            "statistics": {
                "average": 0,
                "minimum": 0,
                "maximum": 0,
                "data_points": 0,
            },
        }


def get_active_alerts(
    db: Session,
    tenant_id: str | None,
    severity_filter: str | None = None,
    limit: int = 50,
) -> dict:
    """Get current active alerts with context."""
    try:
        query = db.query(PolicyAlertHistory).filter(
            PolicyAlertHistory.status.in_(["active", "acknowledged"])
        )
        query = _tenant_scoped(query, PolicyAlertHistory.tenant_id, tenant_id)

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
                "triggered_at": _isoformat(alert.triggered_at),
                "acknowledged_at": _isoformat(alert.acknowledged_at),
                "duration_seconds": duration,
                "breach_count": alert.breach_count,
                "breach_percentage": alert.breach_percentage,
            })

        return {
            "alerts": alert_list,
            "count": len(alert_list),
            "timestamp": _timestamp(),
        }
    except Exception as e:
        return {
            "error": str(e),
            "alerts": [],
            "count": 0,
            "timestamp": _timestamp(),
        }


def get_rollout_comparison(
    db: Session,
    tenant_id: str | None,
    rollout_ids: list[str],
) -> dict:
    """Compare multiple rollouts side-by-side."""
    try:
        rollouts = []
        for rollout_id in rollout_ids[:10]:  # Limit to 10 comparisons
            rollout = db.get(PolicyCanaryRollout, rollout_id)
            if rollout is None:
                continue

            # Get latest snapshot
            snapshot = db.query(PolicyRolloutMetricsSnapshot).filter(
                PolicyRolloutMetricsSnapshot.rollout_id == rollout_id
            ).first()

            # Get latest health
            health_query = db.query(PolicyMetricsHealthAssessment).filter(
                PolicyMetricsHealthAssessment.rollout_id == rollout_id
            )
            health = (
                _tenant_scoped(
                    health_query,
                    PolicyMetricsHealthAssessment.tenant_id,
                    tenant_id,
                )
                .order_by(desc(PolicyMetricsHealthAssessment.assessed_at))
                .first()
            )

            # Get active alerts for rollout
            alert_query = db.query(PolicyAlertHistory).filter(
                PolicyAlertHistory.rollout_id == rollout_id,
                PolicyAlertHistory.status == "active",
            )
            alert_count = _tenant_scoped(
                alert_query,
                PolicyAlertHistory.tenant_id,
                tenant_id,
            ).count()

            anomaly_query = db.query(PolicyMetricsAnomalyDetection).filter(
                PolicyMetricsAnomalyDetection.rollout_id == rollout_id,
                PolicyMetricsAnomalyDetection.resolved_at.is_(None),
            )
            unresolved_anomalies = _tenant_scoped(
                anomaly_query,
                PolicyMetricsAnomalyDetection.tenant_id,
                tenant_id,
            ).count()

            rollouts.append({
                "rollout_id": rollout_id,
                "name": rollout.policy_type.replace("_", " ").title(),
                "status": rollout.status,
                "canary_percentage": float(rollout.current_canary_percentage),
                "error_rate": snapshot.error_rate if snapshot else None,
                "latency_p99_ms": snapshot.latency_p99_ms if snapshot else None,
                "throughput_eps": snapshot.throughput_eps if snapshot else None,
                "health_score": health.health_score if health else None,
                "health_status": health.status if health else None,
                "active_alerts": alert_count,
                "unresolved_anomalies": unresolved_anomalies,
                "duration_hours": _elapsed_hours(
                    rollout.started_at,
                    rollout.completed_at,
                ),
                "started_at": _isoformat(rollout.started_at),
                "error_trend": snapshot.error_rate_increasing if snapshot else None,
            })

        return {
            "comparison": rollouts,
            "count": len(rollouts),
            "timestamp": _timestamp(),
        }
    except Exception as e:
        return {
            "error": str(e),
            "comparison": [],
            "count": 0,
            "timestamp": _timestamp(),
        }


def get_anomaly_timeline(
    db: Session,
    tenant_id: str | None,
    rollout_id: str | None = None,
    minutes_back: int = 1440,  # 24 hours
) -> dict:
    """Get anomaly detection events over time."""
    try:
        cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes_back)

        query = db.query(PolicyMetricsAnomalyDetection).filter(
            PolicyMetricsAnomalyDetection.detected_at >= cutoff_time
        )
        query = _tenant_scoped(
            query,
            PolicyMetricsAnomalyDetection.tenant_id,
            tenant_id,
        )

        if rollout_id:
            query = query.filter(PolicyMetricsAnomalyDetection.rollout_id == rollout_id)

        anomalies = query.order_by(
            desc(PolicyMetricsAnomalyDetection.detected_at)
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
                "baseline": anomaly.baseline if anomaly.baseline is not None else 0.0,
                "deviation_percent": (
                    anomaly.deviation_percent
                    if anomaly.deviation_percent is not None
                    else 0.0
                ),
                "created_at": _isoformat(anomaly.detected_at),
                "acknowledged": anomaly.acknowledged,
                "resolved_at": _isoformat(anomaly.resolved_at),
            })

        return {
            "anomalies": timeline,
            "count": len(timeline),
            "time_window_minutes": minutes_back,
            "timestamp": _timestamp(),
        }
    except Exception as e:
        return {
            "error": str(e),
            "anomalies": [],
            "count": 0,
            "time_window_minutes": minutes_back,
            "timestamp": _timestamp(),
        }


def get_metric_correlation_matrix(
    db: Session,
    tenant_id: str | None,
    rollout_id: str,
    time_window_minutes: int = 60,
) -> dict:
    """Get correlation matrix between metrics."""
    try:
        cutoff_time = datetime.now(UTC) - timedelta(minutes=time_window_minutes)

        # Get all metrics for time window
        history = (
            db.query(PolicyRolloutMetricsHistory)
            .filter(
                PolicyRolloutMetricsHistory.rollout_id == rollout_id,
                PolicyRolloutMetricsHistory.collected_at >= cutoff_time,
            )
            .order_by(PolicyRolloutMetricsHistory.collected_at)
            .all()
        )

        if not history:
            return {
                "rollout_id": rollout_id,
                "correlation_matrix": {},
                "metric_count": 0,
                "time_window_minutes": time_window_minutes,
                "timestamp": _timestamp(),
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
            "timestamp": _timestamp(),
        }
    except Exception as e:
        return {
            "error": str(e),
            "rollout_id": rollout_id,
            "correlation_matrix": {},
            "metric_count": 0,
            "time_window_minutes": time_window_minutes,
            "timestamp": _timestamp(),
        }
