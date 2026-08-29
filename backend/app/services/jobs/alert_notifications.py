"""
Stage 034: Alert notification system and real backend metrics collectors

Implements:
- Alert notification delivery (email, Slack, webhooks)
- Real Prometheus metrics collection
- Real CloudWatch metrics collection
- Alert escalation policies
- Notification history and audit
"""

import asyncio
import logging
import math
import re
import smtplib
import ssl
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from enum import Enum
from urllib.parse import urlsplit

import aiohttp
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ============================================================================
# NOTIFICATION CHANNELS
# ============================================================================


class NotificationChannelType(str, Enum):
    """Supported notification channels."""
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"
    SMS = "sms"
    PAGERDUTY = "pagerduty"


class AlertSeverity(str, Enum):
    """Alert severity levels for routing."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationDeliveryError(ValueError):
    """Safe-to-return notification configuration or request error."""


# ============================================================================
# NOTIFICATION SERVICE
# ============================================================================


class NotificationService:
    """Fail-closed notification delivery for explicitly configured channels."""

    _SLACK_HOSTS = {"hooks.slack.com", "hooks.slack-gov.com"}
    _EMAIL_ADDRESS = re.compile(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
    )
    
    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int = 25,
        smtp_from_address: str | None = None,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        smtp_starttls: bool = True,
        email_recipients: list[str] | None = None,
        slack_webhook_url: str | None = None,
        pagerduty_routing_key: str | None = None,
        webhook_url: str | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        if smtp_host is not None and not smtp_host.strip():
            raise ValueError("SMTP host cannot be blank")
        if not 1 <= smtp_port <= 65_535:
            raise ValueError("SMTP port must be between 1 and 65535")
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("Notification timeout must be between 1 and 30 seconds")
        if bool(smtp_username) != bool(smtp_password):
            raise ValueError("SMTP username and password must be configured together")

        self.smtp_host = smtp_host.strip() if smtp_host else None
        self.smtp_port = smtp_port
        self.smtp_from_address = self._validated_address(
            smtp_from_address,
            field_name="SMTP sender",
            required=False,
        )
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.smtp_starttls = smtp_starttls
        self.email_recipients = self._validated_recipients(email_recipients or [])
        self.slack_webhook_url = self._validated_https_destination(
            slack_webhook_url,
            channel="Slack",
            allowed_hosts=self._SLACK_HOSTS,
        )
        if pagerduty_routing_key and len(pagerduty_routing_key.strip()) < 20:
            raise ValueError("PagerDuty routing key is too short")
        self.pagerduty_routing_key = (
            pagerduty_routing_key.strip() if pagerduty_routing_key else None
        )
        self.webhook_url = self._validated_https_destination(
            webhook_url,
            channel="Webhook",
        )
        self.timeout = timeout_seconds

    @classmethod
    def _validated_address(
        cls,
        value: str | None,
        *,
        field_name: str,
        required: bool,
    ) -> str | None:
        normalized = value.strip() if value else ""
        if not normalized:
            if required:
                raise ValueError(f"{field_name} is required")
            return None
        parsed_name, parsed_address = parseaddr(normalized)
        if (
            parsed_name
            or parsed_address != normalized
            or not cls._EMAIL_ADDRESS.fullmatch(normalized)
            or len(normalized) > 254
        ):
            raise ValueError(f"{field_name} is invalid")
        return normalized

    @classmethod
    def _validated_recipients(cls, values: list[str]) -> list[str]:
        recipients = [
            cls._validated_address(
                value,
                field_name="Email recipient",
                required=True,
            )
            for value in values
        ]
        return list(dict.fromkeys(value for value in recipients if value is not None))

    @staticmethod
    def _validated_https_destination(
        value: str | None,
        *,
        channel: str,
        allowed_hosts: set[str] | None = None,
    ) -> str | None:
        if not value:
            return None
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in {None, 443}
            or (allowed_hosts is not None and hostname not in allowed_hosts)
        ):
            raise ValueError(f"{channel} destination is not an approved HTTPS URL")
        return value

    @staticmethod
    def _configured_destination(
        configured: str | None,
        requested: str | None,
        *,
        channel: str,
    ) -> str | None:
        if requested and requested != configured:
            raise NotificationDeliveryError(
                f"{channel} destination must be deployment-configured and cannot "
                "be selected by a request"
            )
        return configured

    async def send_notification(
        self,
        channel: NotificationChannelType,
        title: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.MEDIUM,
        recipients: list[str] | None = None,
        custom_url: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Send one bounded notification and report only confirmed delivery."""
        try:
            if not 1 <= len(title.strip()) <= 200:
                raise NotificationDeliveryError(
                    "Notification title must contain 1 to 200 characters"
                )
            if not 1 <= len(message.strip()) <= 2_000:
                raise NotificationDeliveryError(
                    "Notification message must contain 1 to 2000 characters"
                )
            if channel == NotificationChannelType.EMAIL:
                requested_recipients = (
                    self._validated_recipients(recipients)
                    if recipients is not None
                    else self.email_recipients
                )
                return await self._send_email(
                    title,
                    message,
                    requested_recipients,
                    severity,
                )
            if channel == NotificationChannelType.SLACK:
                return await self._send_slack(title, message, severity, custom_url, metadata)
            if channel == NotificationChannelType.WEBHOOK:
                return await self._send_webhook(title, message, severity, custom_url, metadata)
            if channel == NotificationChannelType.PAGERDUTY:
                return await self._send_pagerduty(title, message, severity)
            return {
                "channel": channel.value,
                "sent": False,
                "error": f"Unsupported channel: {channel}",
            }
        except Exception as e:
            logger.warning(
                "Notification delivery failed for channel=%s error_type=%s",
                channel.value,
                e.__class__.__name__,
            )
            return {
                "channel": channel.value,
                "sent": False,
                "error": (
                    str(e)
                    if isinstance(e, NotificationDeliveryError)
                    else f"{channel.value} delivery failed"
                ),
            }

    async def _send_email(
        self,
        title: str,
        message: str,
        recipients: list[str],
        severity: AlertSeverity,
    ) -> dict:
        """Send through an explicitly configured SMTP transport."""
        if not self.smtp_host or not self.smtp_from_address:
            return {
                "channel": "email",
                "sent": False,
                "error": "SMTP host and sender are not configured",
            }
        if not recipients:
            return {
                "channel": "email",
                "sent": False,
                "error": "Email recipients are not configured",
            }

        email = EmailMessage()
        email["From"] = self.smtp_from_address
        email["To"] = ", ".join(recipients)
        email["Subject"] = f"[{severity.value.upper()}] {title}"
        message_id = make_msgid(domain=self.smtp_from_address.rsplit("@", 1)[1])
        email["Message-ID"] = message_id
        email.set_content(message)

        def deliver() -> dict[str, tuple[int, bytes]]:
            with smtplib.SMTP(
                self.smtp_host,
                self.smtp_port,
                timeout=self.timeout,
            ) as client:
                client.ehlo()
                if self.smtp_starttls:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                if self.smtp_username and self.smtp_password:
                    client.login(self.smtp_username, self.smtp_password)
                return client.send_message(email)

        refused = await asyncio.to_thread(deliver)
        if refused:
            return {
                "channel": "email",
                "sent": False,
                "error": f"SMTP rejected {len(refused)} recipient(s)",
            }
        return {
            "channel": "email",
            "sent": True,
            "recipients": recipients,
            "accepted_recipients": len(recipients),
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "message_id": message_id,
            "error": None,
        }
    
    async def _send_slack(
        self,
        title: str,
        message: str,
        severity: AlertSeverity,
        webhook_url: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Send Slack notification."""
        url = self._configured_destination(
            self.slack_webhook_url,
            webhook_url,
            channel="Slack",
        )
        
        if not url:
            return {
                "channel": "slack",
                "sent": False,
                "error": "Slack webhook URL not configured",
            }
        
        # Color based on severity
        color_map = {
            AlertSeverity.CRITICAL: "FF0000",  # Red
            AlertSeverity.HIGH: "FF6600",      # Orange
            AlertSeverity.MEDIUM: "FFFF00",    # Yellow
            AlertSeverity.LOW: "00FF00",       # Green
            AlertSeverity.INFO: "0099FF",      # Blue
        }
        
        payload = {
            "attachments": [
                {
                    "title": title,
                    "text": message,
                    "color": color_map.get(severity, "FFFF00"),
                    "fields": [
                        {
                            "title": "Severity",
                            "value": severity.value.upper(),
                            "short": True,
                        },
                        {
                            "title": "Timestamp",
                            "value": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                            "short": True,
                        },
                    ],
                    "footer": "PLATFORM-CORE Alert",
                    "ts": int(datetime.now(UTC).timestamp()),
                }
            ]
        }
        
        if metadata:
            for key, value in list(metadata.items())[:20]:
                payload["attachments"][0]["fields"].append({
                    "title": str(key)[:100],
                    "value": str(value)[:500],
                    "short": True,
                })
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    allow_redirects=False,
                ) as response:
                    if response.status == 200:
                        return {
                            "channel": "slack",
                            "sent": True,
                            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                            "message_id": response.headers.get("x-slack-req-id"),
                            "error": None,
                        }
                    else:
                        return {
                            "channel": "slack",
                            "sent": False,
                            "error": f"HTTP {response.status}",
                        }
        except Exception as e:
            logger.warning(
                "Slack notification failed error_type=%s",
                e.__class__.__name__,
            )
            return {
                "channel": "slack",
                "sent": False,
                "error": "Slack delivery failed",
            }
    
    async def _send_webhook(
        self,
        title: str,
        message: str,
        severity: AlertSeverity,
        webhook_url: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Send only to the deployment-configured webhook destination."""
        url = self._configured_destination(
            self.webhook_url,
            webhook_url,
            channel="Webhook",
        )
        if not url:
            return {
                "channel": "webhook",
                "sent": False,
                "error": "Webhook URL not configured",
            }
        
        payload = {
            "alert_type": "metric_anomaly",
            "title": title,
            "message": message,
            "severity": severity.value,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "metadata": {
                str(key)[:100]: str(value)[:500]
                for key, value in list((metadata or {}).items())[:20]
            },
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    allow_redirects=False,
                ) as response:
                    if 200 <= response.status < 300:
                        return {
                            "channel": "webhook",
                            "sent": True,
                            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                            "message_id": response.headers.get("x-request-id"),
                            "error": None,
                        }
                    else:
                        return {
                            "channel": "webhook",
                            "sent": False,
                            "error": f"HTTP {response.status}",
                        }
        except Exception as e:
            logger.warning(
                "Webhook notification failed error_type=%s",
                e.__class__.__name__,
            )
            return {
                "channel": "webhook",
                "sent": False,
                "error": "Webhook delivery failed",
            }
    
    async def _send_pagerduty(
        self,
        title: str,
        message: str,
        severity: AlertSeverity,
    ) -> dict:
        """Send a PagerDuty Events API v2 trigger to its fixed service URL."""
        if not self.pagerduty_routing_key:
            return {
                "channel": "pagerduty",
                "sent": False,
                "error": "PagerDuty routing key not configured",
            }

        payload = {
            "routing_key": self.pagerduty_routing_key,
            "event_action": "trigger",
            "dedup_key": f"sbs-{uuid.uuid4()}",
            "payload": {
                "summary": title,
                "source": "sbs-ai-itsm",
                "severity": severity.value,
                "custom_details": {"message": message},
            },
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                allow_redirects=False,
            ) as response:
                if response.status != 202:
                    return {
                        "channel": "pagerduty",
                        "sent": False,
                        "error": f"HTTP {response.status}",
                    }
                response_payload = await response.json(content_type=None)
                if not isinstance(response_payload, dict):
                    return {
                        "channel": "pagerduty",
                        "sent": False,
                        "error": "PagerDuty returned an invalid response",
                    }
                dedup_key = response_payload.get("dedup_key")
                if not isinstance(dedup_key, str) or not dedup_key:
                    return {
                        "channel": "pagerduty",
                        "sent": False,
                        "error": "PagerDuty did not confirm a deduplication key",
                    }
                return {
                    "channel": "pagerduty",
                    "sent": True,
                    "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "message_id": dedup_key,
                    "error": None,
                }


# ============================================================================
# REAL PROMETHEUS COLLECTOR
# ============================================================================


class MetricsCollectionError(RuntimeError):
    """Raised when an external metrics source cannot produce trusted evidence."""


class PrometheusMetricsCollector:
    """Bounded, fail-closed Prometheus policy-rollout metrics collector."""

    _LABEL_VALUE = re.compile(r"[A-Za-z0-9_.:-]{1,100}")
    
    def __init__(
        self,
        prometheus_url: str = "http://localhost:9090",
        timeout_seconds: int = 10,
    ):
        """
        Initialize Prometheus collector.
        
        Args:
            prometheus_url: Prometheus server URL
            timeout_seconds: Query timeout
        """
        parsed = urlsplit(prometheus_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid Prometheus service URL")
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("Prometheus timeout must be between 1 and 30 seconds")
        self.prometheus_url = prometheus_url.rstrip("/")
        self.timeout = timeout_seconds
    
    async def collect_metrics(
        self,
        rollout_id: str,
        consumer_name: str,
        query_range_minutes: int = 5,
    ) -> dict[str, float | None]:
        """
        Query Prometheus for metrics.
        
        PromQL Queries:
        - error_rate: rate(http_requests_total{status=~"5.."}[5m])
        - latency_p99: histogram_quantile(0.99, http_request_duration_seconds_bucket)
        - throughput_eps: rate(http_requests_total[5m])
        """
        if not self._LABEL_VALUE.fullmatch(rollout_id):
            raise MetricsCollectionError("Invalid rollout label")
        if not self._LABEL_VALUE.fullmatch(consumer_name):
            raise MetricsCollectionError("Invalid consumer label")
        window = max(1, min(query_range_minutes, 60))
        labels = f'rollout_id="{rollout_id}",consumer="{consumer_name}"'
        total_rate = (
            "sum(rate(sbs_policy_rollout_events_total"
            f"{{{labels}}}[{window}m]))"
        )
        error_rate_query = (
            "100 * sum(rate(sbs_policy_rollout_events_total"
            f'{{{labels},outcome="error"}}[{window}m])) '
            f"/ clamp_min({total_rate}, 0.000001)"
        )
        latency_query = (
            "1000 * histogram_quantile(0.99, sum by (le) "
            "(rate(sbs_policy_rollout_duration_seconds_bucket"
            f"{{{labels}}}[{window}m])))"
        )

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                error_rate = await self._query_prometheus(
                    session,
                    error_rate_query,
                )
                latency = await self._query_prometheus(
                    session,
                    latency_query,
                )
                throughput = await self._query_prometheus(
                    session,
                    total_rate,
                )
        except MetricsCollectionError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise MetricsCollectionError(
                "Prometheus metrics are unavailable"
            ) from exc

        return {
            "error_rate": error_rate,
            "latency_p99_ms": latency,
            "throughput_eps": throughput,
        }
    
    async def _query_prometheus(
        self,
        session: aiohttp.ClientSession,
        query: str,
    ) -> float:
        """Execute PromQL query."""
        url = f"{self.prometheus_url}/api/v1/query"
        async with session.get(
            url,
            params={"query": query},
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise MetricsCollectionError(
                    f"Prometheus query failed with HTTP {response.status}"
                )
            data = await response.json(content_type=None)
        if not isinstance(data, dict) or data.get("status") != "success":
            raise MetricsCollectionError("Prometheus returned an invalid response")
        results = data.get("data", {}).get("result", [])
        if not isinstance(results, list) or len(results) != 1:
            raise MetricsCollectionError(
                "Prometheus query did not return exactly one aggregate"
            )
        value = results[0].get("value", [None, None])
        if not isinstance(value, list) or len(value) < 2:
            raise MetricsCollectionError("Prometheus metric value is missing")
        try:
            parsed = float(value[1])
        except (TypeError, ValueError) as exc:
            raise MetricsCollectionError("Prometheus metric value is invalid") from exc
        if not math.isfinite(parsed) or parsed < 0:
            raise MetricsCollectionError("Prometheus metric value is out of range")
        return parsed


# ============================================================================
# REAL CLOUDWATCH COLLECTOR
# ============================================================================


class CloudWatchMetricsCollector:
    """Real AWS CloudWatch metrics collector."""
    
    def __init__(
        self,
        region: str = "us-east-1",
        namespace: str = "PLATFORM-CORE",
        boto3_session=None,
    ):
        """
        Initialize CloudWatch collector.
        
        Args:
            region: AWS region
            namespace: CloudWatch namespace
            boto3_session: Optional boto3 session for testing
        """
        self.region = region
        self.namespace = namespace
        self.session = boto3_session
        self.cloudwatch = None
        self._initialize()
    
    def _initialize(self):
        """Initialize CloudWatch client (lazy)."""
        try:
            if self.session is None:
                import boto3
                self.cloudwatch = boto3.client("cloudwatch", region_name=self.region)
            else:
                self.cloudwatch = self.session.client("cloudwatch", region_name=self.region)
        except Exception as e:
            logger.warning(f"CloudWatch initialization: {e}")
    
    async def collect_metrics(
        self,
        rollout_id: str,
        consumer_name: str,
        minutes_back: int = 5,
    ) -> dict[str, float | None]:
        """
        Query CloudWatch for metrics.
        
        Metrics:
        - ErrorRate
        - LatencyP99Ms
        - ThroughputEPS
        """
        try:
            metrics = {}
            end_time = datetime.now(UTC)
            start_time = end_time - timedelta(minutes=minutes_back)
            
            # Error rate
            metrics["error_rate"] = await self._get_metric_statistics(
                "ErrorRate",
                rollout_id,
                consumer_name,
                start_time,
                end_time,
            )
            
            # Latency
            metrics["latency_p99_ms"] = await self._get_metric_statistics(
                "LatencyP99Ms",
                rollout_id,
                consumer_name,
                start_time,
                end_time,
            )
            
            # Throughput
            metrics["throughput_eps"] = await self._get_metric_statistics(
                "ThroughputEPS",
                rollout_id,
                consumer_name,
                start_time,
                end_time,
            )
            
            return metrics
        except Exception as e:
            logger.error(f"CloudWatch collection error: {e}")
            return {
                "error_rate": None,
                "latency_p99_ms": None,
                "throughput_eps": None,
            }
    
    async def _get_metric_statistics(
        self,
        metric_name: str,
        rollout_id: str,
        consumer_name: str,
        start_time: datetime,
        end_time: datetime,
        statistic: str = "Average",
    ) -> float | None:
        """Get metric statistics from CloudWatch."""
        try:
            if not self.cloudwatch:
                return None
            
            response = await asyncio.to_thread(
                self.cloudwatch.get_metric_statistics,
                Namespace=self.namespace,
                MetricName=metric_name,
                Dimensions=[
                    {"Name": "RolloutId", "Value": rollout_id},
                    {"Name": "Consumer", "Value": consumer_name},
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=[statistic],
            )
            
            datapoints = response.get("Datapoints", [])
            if datapoints:
                # Return most recent value
                latest = sorted(datapoints, key=lambda x: x["Timestamp"])[-1]
                return float(latest.get(statistic, 0))
            
            return None
        except Exception as e:
            logger.warning(f"CloudWatch metric query error: {e}")
            return None


# ============================================================================
# ALERT ROUTING
# ============================================================================


def determine_routing(
    severity: AlertSeverity,
    metric_type: str,
    rollout_status: str,
) -> dict:
    """
    Determine notification routing based on severity and context.
    
    Returns:
        {
            "channels": ["email", "slack", "pagerduty"],
            "escalation_minutes": 30,
            "on_call_required": True,
            "sla_minutes": 15,
        }
    """
    routing = {
        "channels": [],
        "escalation_minutes": 0,
        "on_call_required": False,
        "sla_minutes": None,
    }
    
    # Severity-based routing
    if severity == AlertSeverity.CRITICAL:
        routing["channels"] = ["slack", "pagerduty", "email"]
        routing["escalation_minutes"] = 5
        routing["on_call_required"] = True
        routing["sla_minutes"] = 5
    elif severity == AlertSeverity.HIGH:
        routing["channels"] = ["slack", "email"]
        routing["escalation_minutes"] = 15
        routing["on_call_required"] = True
        routing["sla_minutes"] = 15
    elif severity == AlertSeverity.MEDIUM:
        routing["channels"] = ["email", "slack"]
        routing["escalation_minutes"] = 30
        routing["on_call_required"] = False
        routing["sla_minutes"] = 30
    elif severity == AlertSeverity.LOW:
        routing["channels"] = ["email"]
        routing["escalation_minutes"] = 60
        routing["on_call_required"] = False
        routing["sla_minutes"] = 60
    else:  # INFO
        routing["channels"] = ["email"]
        routing["escalation_minutes"] = 120
        routing["on_call_required"] = False
        routing["sla_minutes"] = None
    
    # Rollout-specific routing
    if rollout_status == "production":
        routing["on_call_required"] = severity in [AlertSeverity.CRITICAL, AlertSeverity.HIGH]
    
    return routing


# ============================================================================
# ALERT EXECUTION
# ============================================================================


async def execute_alert(
    db: Session,
    alert_rule_id: str,
    rollout_id: str,
    title: str,
    message: str,
    severity: AlertSeverity,
    notification_service: NotificationService,
    metadata: dict | None = None,
) -> dict:
    """Route an alert and return confirmed channel-delivery evidence."""
    try:
        # Determine routing
        routing = determine_routing(severity, "metric_anomaly", "production")
        routed_channels = list(routing["channels"])
        if notification_service.webhook_url and "webhook" not in routed_channels:
            routed_channels.append("webhook")
        routing["channels"] = routed_channels
        
        # Send notifications
        notification_results = []
        for channel in routing["channels"]:
            try:
                result = await notification_service.send_notification(
                    channel=NotificationChannelType(channel),
                    title=title,
                    message=message,
                    severity=severity,
                    metadata=metadata,
                )
                notification_results.append(result)
            except Exception as e:
                logger.error(f"Notification failed for {channel}: {e}")
                notification_results.append({
                    "channel": channel,
                    "sent": False,
                    "error": str(e),
                })
        
        succeeded = sum(1 for r in notification_results if r.get("sent") is True)
        delivered_recipients = sum(
            int(result.get("accepted_recipients", 1))
            for result in notification_results
            if result.get("sent") is True
        )
        delivery_error = None
        if succeeded == 0:
            delivery_error = "No notification channel confirmed delivery"
        elif succeeded < len(notification_results):
            delivery_error = "One or more notification channels failed"
        
        return {
            "alert_id": f"alert-{uuid.uuid4()}",
            "rule_id": alert_rule_id,
            "sent_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "channels_attempted": len(routing["channels"]),
            "channels_succeeded": succeeded,
            "notification_results": notification_results,
            "total_recipients": delivered_recipients,
            "routing": routing,
            "error": delivery_error,
        }
    except Exception as e:
        logger.error(f"Alert execution error: {e}")
        return {
            "alert_id": None,
            "rule_id": alert_rule_id,
            "sent_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "channels_attempted": 0,
            "channels_succeeded": 0,
            "notification_results": [],
            "error": str(e),
        }
