"""
Unit tests for Stage 033: Advanced Metrics Analysis and Anomaly Detection

Test Categories:
1. Anomaly detection algorithms (zscore, iqr, mad)
2. Correlation analysis
3. Alert rule evaluation
4. Trend estimation
5. Anomaly scoring
6. Health assessment
"""

from unittest.mock import MagicMock

from app.services.jobs.metrics_analysis import (
    detect_anomalies,
    analyze_metric_correlation,
    AlertRule,
    estimate_metric_trend,
    get_anomaly_score,
    analyze_rollout_health,
)


# ============================================================================
# ANOMALY DETECTION TESTS
# ============================================================================


def test_detect_anomalies_zscore_basic():
    """Test Z-score anomaly detection with normal distribution."""
    values = [0.5] * 90 + [1.5, 2.0, 2.2, 1.8, 1.9]  # 90 normal + 5 anomalies
    result = detect_anomalies(values, method="zscore", zscore_threshold=2.5)
    
    assert result["method"] == "zscore"
    assert result["anomaly_count"] == 5
    assert result["total_count"] == 95
    assert result["normal_mean"] is not None
    assert len(result["anomaly_indices"]) == 5


def test_detect_anomalies_zscore_no_anomalies():
    """Test Z-score when all values are normal."""
    values = [0.5, 0.51, 0.49, 0.50, 0.52, 0.48]
    result = detect_anomalies(values, method="zscore", zscore_threshold=2.5)
    
    assert result["anomaly_count"] == 0
    assert result["total_count"] == 6


def test_detect_anomalies_iqr():
    """Test IQR anomaly detection."""
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100]  # 100 is outlier
    result = detect_anomalies(values, method="iqr", iqr_multiplier=1.5)
    
    assert result["method"] == "iqr"
    assert result["anomaly_count"] >= 1  # At least the 100


def test_detect_anomalies_mad():
    """Test MAD anomaly detection."""
    values = [0.5] * 50 + [10.0]  # One extreme outlier
    result = detect_anomalies(values, method="mad")
    
    assert result["method"] == "mad"
    assert result["anomaly_count"] >= 1


def test_detect_anomalies_empty():
    """Test with empty list."""
    result = detect_anomalies([], method="zscore")
    
    assert result["anomaly_count"] == 0
    assert result["total_count"] == 0
    assert result["normal_mean"] is None


def test_detect_anomalies_constant_values():
    """Test with constant values (zero deviation)."""
    values = [0.5] * 10
    result = detect_anomalies(values, method="zscore")
    
    assert result["anomaly_count"] == 0
    assert result["normal_std"] == 0.0


# ============================================================================
# CORRELATION ANALYSIS TESTS
# ============================================================================


def test_analyze_correlation_positive():
    """Test positive correlation detection."""
    metric_a = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    metric_b = [10, 12, 14, 16, 18, 20]  # Perfectly correlated
    
    result = analyze_metric_correlation(metric_a, metric_b)
    
    assert result["correlation"] is not None
    assert result["correlation"] > 0.9  # Strong positive
    assert result["correlation_strength"] == "strong"
    assert result["relationship"] == "positive"


def test_analyze_correlation_negative():
    """Test negative correlation detection."""
    metric_a = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    metric_b = [20, 18, 16, 14, 12, 10]  # Inverse relationship
    
    result = analyze_metric_correlation(metric_a, metric_b)
    
    assert result["correlation"] is not None
    assert result["correlation"] < -0.9  # Strong negative
    assert result["relationship"] == "negative"


def test_analyze_correlation_no_correlation():
    """Test no correlation detection."""
    metric_a = [0.5, 0.5, 0.5, 0.5, 0.5]
    metric_b = [1, 2, 3, 4, 5]
    
    result = analyze_metric_correlation(metric_a, metric_b)
    
    assert result["correlation"] is not None
    assert abs(result["correlation"]) < 0.3
    assert result["relationship"] == "none"


def test_analyze_correlation_insufficient_data():
    """Test with insufficient data."""
    result = analyze_metric_correlation([1, 2], [3, 4], min_length=5)
    
    assert result["correlation"] is None
    assert result["correlation_strength"] == "insufficient_data"


# ============================================================================
# ALERT RULE TESTS
# ============================================================================


def test_alert_rule_greater_than():
    """Test alert rule with > operator."""
    rule = AlertRule("high_error", "error_rate", ">", 1.0)
    values = [0.5, 0.6, 1.2, 1.1, 0.7]
    
    result = rule.evaluate(values)
    
    assert result["rule_name"] == "high_error"
    assert result["breach_count"] == 2
    assert result["breach_percentage"] == 40.0


def test_alert_rule_duration_threshold():
    """Test alert rule duration requirement."""
    rule = AlertRule("sustained_high", "error_rate", ">", 1.0, duration_seconds=120)
    values = [1.2] * 5  # 5 breaches * 30s = 150s > 120s
    
    result = rule.evaluate(values)
    
    assert result["triggered"] is True
    assert result["meets_duration_threshold"] is True


def test_alert_rule_no_breaches():
    """Test alert rule with no violations."""
    rule = AlertRule("high_error", "error_rate", ">", 1.0)
    values = [0.5, 0.6, 0.7, 0.8]
    
    result = rule.evaluate(values)
    
    assert result["triggered"] is False
    assert result["breach_count"] == 0


def test_alert_rule_severity_critical():
    """Test severity calculation for critical breach."""
    rule = AlertRule("critical_error", "error_rate", ">", 1.0)
    values = [1.5] * 100  # 100% breach
    
    result = rule.evaluate(values)
    
    assert result["severity"] == "critical"
    assert result["breach_percentage"] == 100.0


# ============================================================================
# TREND ESTIMATION TESTS
# ============================================================================


def test_estimate_trend_increasing():
    """Test trend estimation with increasing values."""
    values = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    result = estimate_metric_trend(values, forecast_steps=3)
    
    assert result["trend_direction"] == "increasing"
    assert result["slope"] > 0
    assert len(result["forecast"]) == 3
    assert result["forecast"][0] < result["forecast"][1] < result["forecast"][2]


def test_estimate_trend_decreasing():
    """Test trend estimation with decreasing values."""
    values = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5]
    result = estimate_metric_trend(values, forecast_steps=3)
    
    assert result["trend_direction"] == "decreasing"
    assert result["slope"] < 0


def test_estimate_trend_flat():
    """Test trend estimation with constant values."""
    values = [0.5] * 10
    result = estimate_metric_trend(values)
    
    assert result["trend_direction"] == "flat"
    assert abs(result["slope"]) < 0.001


def test_estimate_trend_insufficient_data():
    """Test with insufficient data."""
    result = estimate_metric_trend([], forecast_steps=5)
    
    assert result["forecast"] == []
    assert result["trend_direction"] == "unknown"


# ============================================================================
# ANOMALY SCORE TESTS
# ============================================================================


def test_anomaly_score_normal():
    """Test anomaly score for normal metrics."""
    score = get_anomaly_score(
        error_rate=0.3,
        latency_p99_ms=200.0,
        throughput_eps=950.0,
        error_rate_baseline=0.5,
        latency_baseline=300.0,
        throughput_baseline=1000.0,
    )
    
    assert score["severity"] == "normal"
    assert score["anomaly_score"] < 0.2


def test_anomaly_score_critical():
    """Test anomaly score for critical metrics."""
    score = get_anomaly_score(
        error_rate=5.0,
        error_rate_baseline=0.5,
    )
    
    assert score["severity"] == "critical"
    assert score["anomaly_score"] >= 0.8


def test_anomaly_score_high_latency():
    """Test anomaly score for high latency."""
    score = get_anomaly_score(
        latency_p99_ms=1500.0,
        latency_baseline=500.0,
    )
    
    assert score["severity"] in ["significant", "high"]
    assert score["component_scores"].get("latency", 0) > 0.5


def test_anomaly_score_low_throughput():
    """Test anomaly score for low throughput."""
    score = get_anomaly_score(
        throughput_eps=250.0,
        throughput_baseline=1000.0,
    )
    
    assert score["severity"] in ["critical", "significant", "moderate"]
    assert score["component_scores"].get("throughput", 0) > 0.3


# ============================================================================
# HEALTH ASSESSMENT TESTS
# ============================================================================


def test_analyze_health_no_data():
    """Test health assessment with no metrics."""
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    
    result = analyze_rollout_health(db, "crl-123")
    
    assert result["status"] == "unknown"
    assert result["health_score"] == 0.5


def test_analyze_health_healthy():
    """Test health assessment for healthy rollout."""
    # Mock database
    db = MagicMock()
    mock_records = []
    for i in range(10):
        record = MagicMock()
        record.error_rate = 0.3
        record.latency_p99_ms = 150.0
        record.throughput_eps = 1000.0
        mock_records.append(record)
    
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_records
    
    result = analyze_rollout_health(db, "crl-123")
    
    assert result["status"] == "healthy"
    assert result["health_score"] > 0.8


def test_analyze_health_critical():
    """Test health assessment for critical rollout."""
    # Mock database
    db = MagicMock()
    mock_records = []
    for i in range(10):
        record = MagicMock()
        record.error_rate = 2.5
        record.latency_p99_ms = 1500.0
        record.throughput_eps = 50.0
        mock_records.append(record)
    
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_records
    
    result = analyze_rollout_health(db, "crl-123")
    
    assert result["status"] == "critical"
    assert result["health_score"] < 0.5


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


def test_full_analysis_workflow():
    """Test complete analysis workflow."""
    # Simulate metrics data
    values = [0.5, 0.51, 0.49, 0.52, 0.48, 1.5, 0.50, 0.49, 0.51]  # Contains one anomaly
    
    # Detect anomalies
    anomalies = detect_anomalies(values, method="zscore")
    assert anomalies["anomaly_count"] == 1
    
    # Estimate trend
    trend = estimate_metric_trend(values)
    assert trend["forecast"] is not None
    
    # Calculate anomaly score
    score = get_anomaly_score(error_rate=values[-1])
    assert score["anomaly_score"] >= 0


def test_alert_rule_with_trend():
    """Test alert rule combined with trend analysis."""
    values = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]  # Increasing trend
    
    # Detect breach
    rule = AlertRule("increasing_errors", "error_rate", ">", 0.95)
    alert = rule.evaluate(values)
    
    assert alert["triggered"] is True
    
    # Check trend
    trend = estimate_metric_trend(values)
    assert trend["trend_direction"] == "increasing"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


def test_detect_anomalies_single_value():
    """Test with single value."""
    result = detect_anomalies([0.5])
    
    assert result["total_count"] == 1
    assert result["anomaly_count"] == 0


def test_correlation_identical_metrics():
    """Test correlation of identical metrics."""
    values = [0.5, 0.6, 0.7, 0.8, 0.9]
    result = analyze_metric_correlation(values, values)
    
    assert result["correlation"] == 1.0
    assert result["correlation_strength"] == "strong"


def test_anomaly_score_no_baseline():
    """Test anomaly score calculation without baseline."""
    score = get_anomaly_score(error_rate=0.8)
    
    assert score["anomaly_score"] is not None
    assert score["severity"] in ["normal", "minor", "moderate"]


def test_trend_estimation_negative_values():
    """Test trend estimation with negative slope handling."""
    values = [100, 90, 80, 70, 60, 50]
    result = estimate_metric_trend(values)
    
    assert result["slope"] < 0
    assert result["trend_direction"] == "decreasing"
    for val in result["forecast"]:
        assert val < 50  # Forecasted values should continue decreasing
