"""
Stage 034: Database models for alert notifications and history.

Models:
- PolicyAlertNotification - Alert notification records
- PolicyAlertHistory - Alert execution history
- PolicyNotificationPreference - User notification preferences
"""

from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, JSON, ForeignKey, Text

from app.db.base import Base


class PolicyAlertNotification(Base):
    """Alert notification records."""
    
    __tablename__ = "policy_alert_notifications"
    
    id = Column(String, primary_key=True, index=True)
    alert_rule_id = Column(String, ForeignKey("policy_metrics_alert_rules.id"), nullable=False, index=True)
    rollout_id = Column(String, ForeignKey("policy_canary_rollouts.id"), nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    
    # Notification details
    channel = Column(String, nullable=False)  # email, slack, webhook, pagerduty
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String, nullable=False)  # critical, high, medium, low, info
    
    # Delivery status
    sent = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)
    message_id = Column(String, nullable=True)
    error = Column(String, nullable=True)
    
    # Recipients
    recipients = Column(JSON, default=[])  # List of email/user ids
    
    # Metadata
    alert_metadata = Column(JSON, nullable=True)
    routing_decision = Column(JSON, nullable=True)  # Routing info
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(String, nullable=True)


class PolicyAlertHistory(Base):
    """Historical record of alerts."""
    
    __tablename__ = "policy_alert_history"
    
    id = Column(String, primary_key=True, index=True)
    alert_rule_id = Column(String, ForeignKey("policy_metrics_alert_rules.id"), nullable=False, index=True)
    rollout_id = Column(String, ForeignKey("policy_canary_rollouts.id"), nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    
    # Alert trigger details
    rule_name = Column(String, nullable=False)
    metric = Column(String, nullable=False)
    threshold = Column(Float, nullable=False)
    current_value = Column(Float, nullable=False)
    operator = Column(String, nullable=False)  # >, <, >=, <=, ==
    
    # Severity
    severity = Column(String, nullable=False)
    anomaly_score = Column(Float, nullable=True)
    
    # Status
    status = Column(String, default="active")  # active, acknowledged, resolved, escalated
    
    # Timing
    triggered_at = Column(DateTime, default=datetime.utcnow, index=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    
    # Notifications
    notifications_sent = Column(Integer, default=0)
    notification_channels = Column(JSON, default=[])
    
    # Context
    breach_count = Column(Integer, default=1)
    breach_percentage = Column(Float, nullable=True)
    
    # Notes
    notes = Column(Text, nullable=True)
    root_cause = Column(Text, nullable=True)
    
    # Audit trail
    created_by = Column(String, nullable=True)
    modified_by = Column(String, nullable=True)
    modified_at = Column(DateTime, nullable=True)


class PolicyNotificationPreference(Base):
    """User notification preferences."""
    
    __tablename__ = "policy_notification_preferences"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    
    # Email preferences
    email_enabled = Column(Boolean, default=True)
    email_address = Column(String, nullable=True)
    email_critical = Column(Boolean, default=True)
    email_high = Column(Boolean, default=True)
    email_medium = Column(Boolean, default=False)
    email_low = Column(Boolean, default=False)
    
    # Slack preferences
    slack_enabled = Column(Boolean, default=False)
    slack_user_id = Column(String, nullable=True)
    slack_critical = Column(Boolean, default=True)
    slack_high = Column(Boolean, default=True)
    slack_medium = Column(Boolean, default=False)
    slack_low = Column(Boolean, default=False)
    
    # Webhook preferences
    webhook_enabled = Column(Boolean, default=False)
    webhook_url = Column(String, nullable=True)
    webhook_critical = Column(Boolean, default=True)
    webhook_high = Column(Boolean, default=True)
    webhook_medium = Column(Boolean, default=False)
    webhook_low = Column(Boolean, default=False)
    
    # Quiet hours
    quiet_hours_enabled = Column(Boolean, default=False)
    quiet_hours_start = Column(String, nullable=True)  # HH:MM
    quiet_hours_end = Column(String, nullable=True)    # HH:MM
    quiet_hours_timezone = Column(String, default="UTC")
    
    # Escalation
    escalation_enabled = Column(Boolean, default=False)
    escalation_after_minutes = Column(Integer, default=30)
    escalation_recipients = Column(JSON, default=[])
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
