"""Unit tests for policy metrics monitoring and auto-rollback (Stage 028)."""


from app.services.jobs.policy_metrics_monitoring import (
    estimate_auto_rollback_confidence,
    check_auto_rollback_threshold,
)


def test_check_auto_rollback_threshold_within_limits():
    """Test threshold check passes when within limits."""
    should_rollback, reason = check_auto_rollback_threshold(
        baseline_error_rate=0.5,
        current_error_rate=0.6,  # 20% increase
        threshold_percent=50.0,
    )
    
    assert should_rollback is False
    assert reason is None


def test_check_auto_rollback_threshold_exceeds_limits():
    """Test threshold check triggers when exceeded."""
    should_rollback, reason = check_auto_rollback_threshold(
        baseline_error_rate=0.5,
        current_error_rate=0.85,  # 70% increase
        threshold_percent=50.0,
    )
    
    assert should_rollback is True
    assert "exceeded" in reason.lower()


def test_check_auto_rollback_threshold_with_zero_baseline():
    """Test threshold check with zero baseline."""
    # When baseline is 0, use absolute threshold of 1.0%
    should_rollback, reason = check_auto_rollback_threshold(
        baseline_error_rate=0.0,
        current_error_rate=0.5,
    )
    assert should_rollback is False  # 0.5% < 1.0%
    
    should_rollback, reason = check_auto_rollback_threshold(
        baseline_error_rate=0.0,
        current_error_rate=1.5,
    )
    assert should_rollback is True  # 1.5% > 1.0%


def test_check_auto_rollback_threshold_with_improvement():
    """Test threshold check allows improvement."""
    should_rollback, reason = check_auto_rollback_threshold(
        baseline_error_rate=1.0,
        current_error_rate=0.5,  # 50% improvement
        threshold_percent=50.0,
    )
    
    assert should_rollback is False  # Improvement is always safe


def test_check_auto_rollback_threshold_none_values():
    """Test threshold check with None values."""
    should_rollback, reason = check_auto_rollback_threshold(
        baseline_error_rate=None,
        current_error_rate=0.5,
    )
    
    assert should_rollback is False  # No data = safe
    assert reason is None


def test_estimate_auto_rollback_confidence_safe():
    """Test confidence scoring for safe metrics."""
    confidence = estimate_auto_rollback_confidence(
        baseline_error_rate=0.5,
        current_error_rate=0.48,  # Improvement
    )
    
    assert confidence == 0.0  # Definitely safe


def test_estimate_auto_rollback_confidence_unsafe():
    """Test confidence scoring for unsafe metrics."""
    confidence = estimate_auto_rollback_confidence(
        baseline_error_rate=0.5,
        current_error_rate=1.0,  # Doubling
    )
    
    assert confidence == 1.0  # Definitely rollback


def test_estimate_auto_rollback_confidence_borderline():
    """Test confidence scoring for borderline metrics."""
    confidence = estimate_auto_rollback_confidence(
        baseline_error_rate=0.5,
        current_error_rate=0.75,  # 50% increase
    )
    
    assert 0.4 < confidence < 0.6  # Borderline


def test_estimate_auto_rollback_confidence_no_change():
    """Test confidence with no change."""
    confidence = estimate_auto_rollback_confidence(
        baseline_error_rate=0.5,
        current_error_rate=0.5,
    )
    
    assert confidence == 0.0  # No change = safe


def test_estimate_auto_rollback_confidence_no_data():
    """Missing evidence is represented as maximum risk, never as safe."""
    confidence = estimate_auto_rollback_confidence(
        baseline_error_rate=None,
        current_error_rate=0.5,
    )
    
    assert confidence == 1.0
    
    confidence = estimate_auto_rollback_confidence(
        baseline_error_rate=0.5,
        current_error_rate=None,
    )
    
    assert confidence == 1.0


def test_estimate_auto_rollback_confidence_from_zero_baseline_small_rise():
    """Test confidence from zero baseline with small rise."""
    # Small rise from 0 to 0.5% = acceptable (< 1.0% absolute threshold)
    confidence = estimate_auto_rollback_confidence(
        baseline_error_rate=0.0,
        current_error_rate=0.5,
    )
    
    assert confidence == 0.0  # Safe (below 1.0% absolute threshold)


def test_estimate_auto_rollback_confidence_from_zero_baseline_spike():
    """Test confidence from zero baseline with spike."""
    # Spike from 0 to 2.5% = risky
    confidence = estimate_auto_rollback_confidence(
        baseline_error_rate=0.0,
        current_error_rate=2.5,
    )
    
    assert confidence == 1.0  # Definitely rollback


def test_estimate_auto_rollback_confidence_scales_linearly():
    """Test confidence increases linearly between 0% and 100% increase."""
    baseline = 1.0
    
    # 0% increase = 0.0 confidence
    conf_0 = estimate_auto_rollback_confidence(baseline, 1.0)
    assert conf_0 == 0.0
    
    # 25% increase = ~0.25 confidence
    conf_25 = estimate_auto_rollback_confidence(baseline, 1.25)
    assert 0.2 < conf_25 < 0.3
    
    # 50% increase = ~0.5 confidence
    conf_50 = estimate_auto_rollback_confidence(baseline, 1.5)
    assert 0.45 < conf_50 < 0.55
    
    # 100% increase = 1.0 confidence
    conf_100 = estimate_auto_rollback_confidence(baseline, 2.0)
    assert conf_100 == 1.0


def test_estimate_auto_rollback_confidence_improvement_always_safe():
    """Test improvement is always safe regardless of magnitude."""
    confidence = estimate_auto_rollback_confidence(
        baseline_error_rate=1.0,
        current_error_rate=0.1,  # 90% improvement
    )
    
    assert confidence == 0.0  # Definitely safe, even with large improvement


def test_threshold_check_at_exact_boundary():
    """Test threshold check at exact boundary."""
    # Exactly 50% increase with 50% threshold
    should_rollback, reason = check_auto_rollback_threshold(
        baseline_error_rate=1.0,
        current_error_rate=1.5,  # Exactly 50% increase
        threshold_percent=50.0,
    )
    
    # Should not rollback (boundary is >)
    assert should_rollback is False


def test_threshold_check_just_over_boundary():
    """Test threshold check just over boundary."""
    # 50.1% increase with 50% threshold
    should_rollback, reason = check_auto_rollback_threshold(
        baseline_error_rate=1.0,
        current_error_rate=1.501,  # Just over 50% increase
        threshold_percent=50.0,
    )
    
    assert should_rollback is True


def test_confidence_with_various_real_world_scenarios():
    """Test confidence calculation with realistic scenarios."""
    test_cases = [
        # API latency spike (baseline 100ms -> current 120ms)
        (100, 120, "latency", (0.1, 0.3)),
        
        # Error rate in normal operations (0.1% -> 0.12%)
        (0.1, 0.12, "error_rate", (0.1, 0.3)),
        
        # Cache hit rate degradation (99% -> 95%)
        (99, 95, "cache_hit_rate", None),  # Don't check this one
        
        # Throughput drop (1000 RPS -> 500 RPS baseline 1000)
        (1000, 500, "throughput", 0.0),  # Improvement is safe
    ]
    
    for baseline, current, metric_name, expected_range in test_cases:
        if expected_range is None:
            continue
        
        confidence = estimate_auto_rollback_confidence(
            baseline_error_rate=baseline,
            current_error_rate=current,
        )
        
        # For realistic scenarios, verify confidence is in expected range
        if isinstance(expected_range, tuple):
            assert expected_range[0] <= confidence <= expected_range[1]
        else:
            assert confidence == expected_range
