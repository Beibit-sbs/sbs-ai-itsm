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
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.jobs.alert_notifications import (
    NotificationService,
    NotificationChannelType,
    AlertSeverity,
    MetricsCollectionError,
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
        smtp_from_address="alerts@example.com",
        smtp_starttls=False,
        email_recipients=["admin@example.com"],
        slack_webhook_url="https://hooks.slack.com/services/TEST",
        pagerduty_routing_key="r" * 32,
        webhook_url="https://example.com/webhook",
        timeout_seconds=5,
    )


@pytest.mark.asyncio
async def test_send_email_notification(notification_service):
    """Test email notification sending."""
    with patch(
        "app.services.jobs.alert_notifications.smtplib.SMTP"
    ) as smtp:
        smtp.return_value.__enter__.return_value.send_message.return_value = {}
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
        mock_response.headers = {"x-slack-req-id": "slack-request-1"}
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
        mock_response.headers = {"x-request-id": "webhook-request-1"}
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
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 202
        mock_response.json = AsyncMock(
            return_value={"status": "success", "dedup_key": "pd-event-1"}
        )
        mock_post.return_value.__aenter__.return_value = mock_response
        result = await notification_service.send_notification(
            channel=NotificationChannelType.PAGERDUTY,
            title="Critical System Error",
            message="System in degraded state",
            severity=AlertSeverity.CRITICAL,
        )
    
    assert result["channel"] == "pagerduty"
    assert result["sent"] is True


@pytest.mark.asyncio
async def test_notification_without_webhook_url(notification_service):
    """Test webhook notification without URL configured."""
    unconfigured_service = NotificationService()
    result = await unconfigured_service.send_notification(
        channel=NotificationChannelType.WEBHOOK,
        title="Test",
        message="Test message",
        severity=AlertSeverity.LOW,
    )
    
    assert result["sent"] is False
    assert "not configured" in result["error"]


@pytest.mark.asyncio
async def test_request_cannot_override_configured_webhook(notification_service):
    """A caller cannot turn notification delivery into an SSRF primitive."""
    result = await notification_service.send_notification(
        channel=NotificationChannelType.WEBHOOK,
        title="Test",
        message="Test message",
        custom_url="https://attacker.example/webhook",
    )

    assert result["sent"] is False
    assert "deployment-configured" in result["error"]


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
    """Empty Prometheus evidence fails closed."""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "status": "success",
            "data": {"result": []}
        })
        mock_get.return_value.__aenter__.return_value = mock_response
        
        with pytest.raises(MetricsCollectionError):
            await prometheus_collector.collect_metrics(
                "crl-123",
                "consumer-1",
            )


@pytest.mark.asyncio
async def test_prometheus_http_error(prometheus_collector):
    """Prometheus HTTP failures cannot become nullable safe metrics."""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_get.return_value.__aenter__.return_value = mock_response
        
        with pytest.raises(MetricsCollectionError):
            await prometheus_collector.collect_metrics(
                "crl-123",
                "consumer-1",
            )


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
                "Timestamp": datetime.now(UTC),
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

    async def confirmed_delivery(*, channel, **_kwargs):
        return {
            "channel": channel.value,
            "sent": True,
            "message_id": f"{channel.value}-confirmed",
        }

    with patch.object(
        notification_service,
        "send_notification",
        new=AsyncMock(side_effect=confirmed_delivery),
    ):
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
    
    with patch.object(
        notification_service,
        "send_notification",
        new=AsyncMock(
            return_value={
                "channel": "configured",
                "sent": True,
                "message_id": "confirmed-1",
            }
        ),
    ):
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

    with patch.object(
        notification_service,
        "send_notification",
        new=AsyncMock(
            return_value={"channel": "configured", "sent": False, "error": "offline"}
        ),
    ):
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
    assert result["channels_succeeded"] == 0
    assert result["error"] == "No notification channel confirmed delivery"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_notification_with_special_characters(notification_service):
    """Test notification with special characters in message."""
    notification_service._send_email = AsyncMock(
        return_value={"channel": "email", "sent": True, "message_id": "smtp-confirmed"}
    )
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
    
    assert result["sent"] is False
    assert result["error"] == "Email recipients are not configured"


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
