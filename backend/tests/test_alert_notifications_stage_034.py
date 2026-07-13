"""
Unit tests for Stage 034: Alert Notification Integration

Test Categories:
1. Notification service (email, Slack, webhooks)
2. Real Prometheus collector
3. Real CloudWatch collector
4. Alert routing
5. Alert execution
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import json

from app.services.jobs.alert_notifications import (
    NotificationService,
    NotificationChannelType,
    AlertSeverity,
    PrometheusMetricsCollector,
    CloudWatchMetricsCollector,
    determine_routing,
    execute_alert,
)


# ============================================================================
# NOTIFICATION SERVICE TESTS
# ============================================================================


@pytest.fixture
def notification_service():
    """Create notification service instance."""
    return NotificationService(
        smtp_host="localhost",
        smtp_port=25,
        slack_webhook_url="https://hooks.slack.com/services/TEST",
        timeout_seconds=5,
    )


@pytest.mark.asyncio
async def test_send_email_notification(notification_service):
    """Test email notification sending."""
    result = await notification_service.send_notification(
        channel=NotificationChannelType.EMAIL,
        title="High Error Rate",
        message="Error rate exceeded 1.0%",
        severity=AlertSeverity.HIGH,
        recipients=["admin@example.com"],
    )
    
    assert result["channel"] == "email"
    assert result["sent"] is True
    assert result["recipients"] == ["admin@example.com"]
    assert result["error"] is None
    assert "message_id" in result


@pytest.mark.asyncio
async def test_send_slack_notification(notification_service):
    """Test Slack notification sending."""
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response
        
        result = await notification_service.send_notification(
            channel=NotificationChannelType.SLACK,
            title="High Error Rate",
            message="Error rate exceeded 1.0%",
            severity=AlertSeverity.CRITICAL,
        )
        
        assert result["channel"] == "slack"
        assert result["sent"] is True
        assert result["error"] is None


@pytest.mark.asyncio
async def test_send_webhook_notification(notification_service):
    """Test webhook notification sending."""
    webhook_url = "https://example.com/webhook"
    
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response
        
        result = await notification_service.send_notification(
            channel=NotificationChannelType.WEBHOOK,
            title="Latency Alert",
            message="P99 latency > 500ms",
            severity=AlertSeverity.MEDIUM,
            custom_url=webhook_url,
        )
        
        assert result["channel"] == "webhook"
        assert result["sent"] is True


@pytest.mark.asyncio
async def test_send_pagerduty_notification(notification_service):
    """Test PagerDuty notification sending."""
    result = await notification_service.send_notification(
        channel=NotificationChannelType.PAGERDUTY,
        title="Critical System Error",
        message="System in degraded state",
        severity=AlertSeverity.CRITICAL,
        recipients=["on-call@example.com"],
    )
    
    assert result["channel"] == "pagerduty"
    assert result["sent"] is True


@pytest.mark.asyncio
async def test_notification_without_webhook_url(notification_service):
    """Test webhook notification without URL configured."""
    result = await notification_service.send_notification(
        channel=NotificationChannelType.WEBHOOK,
        title="Test",
        message="Test message",
        severity=AlertSeverity.LOW,
    )
    
    assert result["sent"] is False
    assert "not provided" in result["error"]


# ============================================================================
# PROMETHEUS COLLECTOR TESTS
# ============================================================================


@pytest.fixture
def prometheus_collector():
    """Create Prometheus collector instance."""
    return PrometheusMetricsCollector(
        prometheus_url="http://localhost:9090",
        timeout_seconds=5,
    )


@pytest.mark.asyncio
async def test_prometheus_collection_success(prometheus_collector):
    """Test successful Prometheus metrics collection."""
    with patch("aiohttp.ClientSession.get") as mock_get:
        # Mock successful response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "status": "success",
            "data": {
                "result": [
                    {"value": [1234567890, "0.005"]}  # 0.5%
                ]
            }
        })
        mock_get.return_value.__aenter__.return_value = mock_response
        
        metrics = await prometheus_collector.collect_metrics(
            "crl-123",
            "consumer-1",
        )
        
        assert metrics is not None
        assert metrics["error_rate"] is not None


@pytest.mark.asyncio
async def test_prometheus_empty_result(prometheus_collector):
    """Test Prometheus with empty results."""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "status": "success",
            "data": {"result": []}
        })
        mock_get.return_value.__aenter__.return_value = mock_response
        
        metrics = await prometheus_collector.collect_metrics(
            "crl-123",
            "consumer-1",
        )
        
        assert metrics["error_rate"] is None
        assert metrics["latency_p99_ms"] is None


@pytest.mark.asyncio
async def test_prometheus_http_error(prometheus_collector):
    """Test Prometheus collection with HTTP error."""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_get.return_value.__aenter__.return_value = mock_response
        
        metrics = await prometheus_collector.collect_metrics(
            "crl-123",
            "consumer-1",
        )
        
        assert metrics["error_rate"] is None
        assert metrics["latency_p99_ms"] is None


# ============================================================================
# CLOUDWATCH COLLECTOR TESTS
# ============================================================================


def test_cloudwatch_initialization():
    """Test CloudWatch collector initialization."""
    collector = CloudWatchMetricsCollector(
        region="us-east-1",
        namespace="PLATFORM-CORE",
    )
    
    assert collector.region == "us-east-1"
    assert collector.namespace == "PLATFORM-CORE"


@pytest.mark.asyncio
async def test_cloudwatch_collection_stub():
    """Test CloudWatch collection (stub implementation)."""
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_session.client.return_value = mock_client
    
    collector = CloudWatchMetricsCollector(
        region="us-east-1",
        boto3_session=mock_session,
    )
    
    # Mock get_metric_statistics
    mock_client.get_metric_statistics.return_value = {
        "Datapoints": [
            {
                "Timestamp": datetime.utcnow(),
                "Average": 0.5,
            }
        ]
    }
    
    metrics = await collector.collect_metrics(
        "crl-123",
        "consumer-1",
    )
    
    assert metrics is not None


# ============================================================================
# ALERT ROUTING TESTS
# ============================================================================


def test_route_critical_alert():
    """Test routing for critical alert."""
    routing = determine_routing(AlertSeverity.CRITICAL, "error_rate", "production")
    
    assert "slack" in routing["channels"]
    assert "pagerduty" in routing["channels"]
    assert routing["on_call_required"] is True
    assert routing["sla_minutes"] == 5
    assert routing["escalation_minutes"] == 5


def test_route_high_alert():
    """Test routing for high alert."""
    routing = determine_routing(AlertSeverity.HIGH, "latency", "production")
    
    assert routing["on_call_required"] is True
    assert routing["sla_minutes"] == 15
    assert routing["escalation_minutes"] == 15


def test_route_medium_alert():
    """Test routing for medium alert."""
    routing = determine_routing(AlertSeverity.MEDIUM, "throughput", "production")
    
    assert routing["on_call_required"] is False
    assert routing["sla_minutes"] == 30
    assert "email" in routing["channels"]


def test_route_low_alert():
    """Test routing for low alert."""
    routing = determine_routing(AlertSeverity.LOW, "cpu", "production")
    
    assert routing["on_call_required"] is False
    assert routing["sla_minutes"] == 60


def test_route_info_alert():
    """Test routing for info alert."""
    routing = determine_routing(AlertSeverity.INFO, "memory", "production")
    
    assert routing["on_call_required"] is False
    assert routing["sla_minutes"] is None


# ============================================================================
# ALERT EXECUTION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_execute_alert_successful(notification_service):
    """Test successful alert execution."""
    db = MagicMock()
    
    result = await execute_alert(
        db=db,
        alert_rule_id="rule-123",
        rollout_id="crl-456",
        title="Error Rate Alert",
        message="Error rate exceeded 1.0%",
        severity=AlertSeverity.HIGH,
        notification_service=notification_service,
        metadata={"current_value": 1.2, "threshold": 1.0},
    )
    
    assert result["alert_id"] is not None
    assert result["rule_id"] == "rule-123"
    assert result["channels_attempted"] > 0
    assert result["channels_succeeded"] > 0


@pytest.mark.asyncio
async def test_execute_alert_with_metadata(notification_service):
    """Test alert execution with custom metadata."""
    db = MagicMock()
    
    metadata = {
        "anomaly_score": 0.85,
        "correlation": 0.87,
        "trend": "increasing",
    }
    
    result = await execute_alert(
        db=db,
        alert_rule_id="rule-789",
        rollout_id="crl-999",
        title="Complex Alert",
        message="Multiple anomalies detected",
        severity=AlertSeverity.CRITICAL,
        notification_service=notification_service,
        metadata=metadata,
    )
    
    assert result["alert_id"] is not None
    assert result["sent_at"] is not None


# ============================================================================
# NOTIFICATION CHANNEL TYPE TESTS
# ============================================================================


def test_notification_channel_types():
    """Test all notification channel types."""
    assert NotificationChannelType.EMAIL.value == "email"
    assert NotificationChannelType.SLACK.value == "slack"
    assert NotificationChannelType.WEBHOOK.value == "webhook"
    assert NotificationChannelType.SMS.value == "sms"
    assert NotificationChannelType.PAGERDUTY.value == "pagerduty"


def test_alert_severity_levels():
    """Test all alert severity levels."""
    assert AlertSeverity.INFO.value == "info"
    assert AlertSeverity.LOW.value == "low"
    assert AlertSeverity.MEDIUM.value == "medium"
    assert AlertSeverity.HIGH.value == "high"
    assert AlertSeverity.CRITICAL.value == "critical"


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_multi_channel_alert_execution(notification_service):
    """Test alert execution with multiple notification channels."""
    db = MagicMock()
    
    result = await execute_alert(
        db=db,
        alert_rule_id="rule-multi",
        rollout_id="crl-multi",
        title="Multi-Channel Alert",
        message="Testing multiple channels",
        severity=AlertSeverity.CRITICAL,
        notification_service=notification_service,
    )
    
    # Critical should go to multiple channels
    assert result["channels_attempted"] >= 2


@pytest.mark.asyncio
async def test_alert_routing_and_execution():
    """Test complete alert routing and execution flow."""
    notification_service = NotificationService()
    db = MagicMock()
    
    # Determine routing
    routing = determine_routing(AlertSeverity.HIGH, "error_rate", "production")
    assert routing["on_call_required"] is True
    
    # Execute alert
    result = await execute_alert(
        db=db,
        alert_rule_id="rule-flow",
        rollout_id="crl-flow",
        title="High Error Rate",
        message="Error rate 1.5% (threshold: 1.0%)",
        severity=AlertSeverity.HIGH,
        notification_service=notification_service,
    )
    
    assert result["alert_id"] is not None
    assert result["channels_attempted"] > 0


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_notification_with_special_characters(notification_service):
    """Test notification with special characters in message."""
    result = await notification_service.send_notification(
        channel=NotificationChannelType.EMAIL,
        title="Alert: 🚨 Critical Error!",
        message="Error: $pecial ch@rs & <html>",
        severity=AlertSeverity.CRITICAL,
        recipients=["test@example.com"],
    )
    
    assert result["sent"] is True


@pytest.mark.asyncio
async def test_notification_with_empty_recipients(notification_service):
    """Test notification with empty recipients."""
    result = await notification_service.send_notification(
        channel=NotificationChannelType.EMAIL,
        title="Test",
        message="Test message",
        severity=AlertSeverity.LOW,
        recipients=[],
    )
    
    assert result["sent"] is True  # Email still sends


def test_routing_with_staging_rollout():
    """Test routing behavior for staging vs production."""
    prod_routing = determine_routing(AlertSeverity.HIGH, "error", "production")
    staging_routing = determine_routing(AlertSeverity.HIGH, "error", "staging")
    
    # Both should have similar structure
    assert "channels" in prod_routing
    assert "channels" in staging_routing


@pytest.mark.asyncio
async def test_prometheus_url_normalization(prometheus_collector):
    """Test Prometheus URL normalization (trailing slash)."""
    # Create with trailing slash
    collector = PrometheusMetricsCollector(
        prometheus_url="http://localhost:9090/",
    )
    
    assert collector.prometheus_url == "http://localhost:9090"


def test_cloudwatch_namespace_customization():
    """Test CloudWatch with custom namespace."""
    collector = CloudWatchMetricsCollector(
        region="us-west-2",
        namespace="CUSTOM-NAMESPACE",
    )
    
    assert collector.namespace == "CUSTOM-NAMESPACE"
    assert collector.region == "us-west-2"
