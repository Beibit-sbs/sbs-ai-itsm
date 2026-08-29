"""Scheduled metrics polling for canary rollout monitoring."""
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.policy_canary_rollout import PolicyCanaryRollout
from app.models.audit_log import AuditLog
from app.services.jobs.policy_metrics_monitoring import (
    check_auto_rollback_threshold,
)
from app.services.audit import log_audit

logger = logging.getLogger("app.jobs.metrics_polling")


def poll_active_rollouts(db: Session) -> dict[str, Any]:
    """Poll metrics for all active canary rollouts.
    
    Returns dict with polling statistics:
    {
        "polled_count": int,  # Rollouts polled
        "auto_rollback_count": int,  # Auto-rollbacks triggered
        "errors": list[str],  # Any errors during polling
    }
    """
    stats = {
        "polled_count": 0,
        "auto_rollback_count": 0,
        "errors": [],
    }
    
    # Find all active, non-rolled-back rollouts
    active_rollouts = db.query(PolicyCanaryRollout).filter(
        PolicyCanaryRollout.status == "in_progress",
        PolicyCanaryRollout.auto_rollback_triggered.is_(False),
    ).all()
    
    logger.info(f"Polling metrics for {len(active_rollouts)} active rollouts")
    
    for rollout in active_rollouts:
        try:
            if rollout.error_rate_current is None:
                stats["errors"].append(
                    f"Metrics evidence unavailable for {rollout.id}"
                )
                continue

            metrics = {"error_rate": rollout.error_rate_current}
            stats["polled_count"] += 1
            
            # Check auto-rollback threshold
            if rollout.error_rate_baseline is not None:
                should_rollback, reason = check_auto_rollback_threshold(
                    rollout.error_rate_baseline,
                    metrics.get("error_rate"),
                    threshold_percent=50.0,
                )
                
                if should_rollback:
                    logger.warning(f"Auto-rollback triggered for {rollout.id}: {reason}")
                    rollout.auto_rollback_triggered = True
                    rollout.auto_rollback_reason = reason
                    stats["auto_rollback_count"] += 1
                    
                    # Log audit event
                    log_audit(
                        db,
                        action="policy.canary.auto_rollback_triggered",
                        entity_type="policy_canary_rollout",
                        entity_id=rollout.id,
                        actor_email="system@sbs.local",
                        tenant_id=None,
                        metadata={
                            "rollout_id": rollout.id,
                            "trigger_reason": reason,
                            "baseline_error_rate": rollout.error_rate_baseline,
                            "current_error_rate": metrics.get("error_rate"),
                        },
                    )
        
        except Exception as exc:
            error_msg = f"Error polling {rollout.id}: {str(exc)}"
            logger.error(error_msg)
            stats["errors"].append(error_msg)
    
    db.commit()
    return stats


def get_rollout_polling_status(db: Session) -> dict[str, Any]:
    """Get status of all active rollouts for polling.
    
    Returns dict with:
    {
        "active_rollouts": [
            {
                "rollout_id": str,
                "policy_type": str,
                "current_canary_percentage": int,
                "error_rate_baseline": float | None,
                "error_rate_current": float | None,
                "minutes_since_start": int,
                "next_poll_in_seconds": int,
            },
            ...
        ],
        "last_poll_at": datetime | None,
        "total_active": int,
    }
    """
    active_rollouts = db.query(PolicyCanaryRollout).filter(
        PolicyCanaryRollout.status == "in_progress",
        PolicyCanaryRollout.auto_rollback_triggered.is_(False),
    ).all()
    
    rollout_statuses = []
    for rollout in active_rollouts:
        # Estimate next poll (every 30 seconds by default)
        if rollout.updated_at:
            seconds_since_update = (datetime.now(UTC) - rollout.updated_at).total_seconds()
            next_poll_in = max(0, 30 - seconds_since_update)
        else:
            next_poll_in = 0
        
        minutes_since_start = 0
        if rollout.started_at:
            minutes_since_start = int(
                (datetime.now(UTC) - rollout.started_at).total_seconds() / 60
            )
        
        rollout_statuses.append({
            "rollout_id": rollout.id,
            "policy_type": rollout.policy_type,
            "current_canary_percentage": rollout.current_canary_percentage,
            "error_rate_baseline": rollout.error_rate_baseline,
            "error_rate_current": rollout.error_rate_current,
            "minutes_since_start": minutes_since_start,
            "next_poll_in_seconds": int(next_poll_in),
        })
    
    # Get last poll time from most recent audit log entry
    last_poll_entry = db.query(AuditLog).filter(
        AuditLog.action == "policy.canary.metrics_updated"
    ).order_by(AuditLog.created_at.desc()).first()
    
    last_poll_at = last_poll_entry.created_at if last_poll_entry else None
    
    return {
        "active_rollouts": rollout_statuses,
        "last_poll_at": last_poll_at,
        "total_active": len(rollout_statuses),
    }


def should_poll_now(
    last_poll_at: datetime | None,
    poll_interval_seconds: int = 30,
) -> bool:
    """Determine if polling should happen now.
    
    Args:
        last_poll_at: When polling last occurred
        poll_interval_seconds: Minimum interval between polls
    
    Returns:
        True if should poll now
    """
    if last_poll_at is None:
        return True  # Never polled, do it now
    
    elapsed = (datetime.now(UTC) - last_poll_at).total_seconds()
    return elapsed >= poll_interval_seconds


def estimate_next_poll_time(
    last_poll_at: datetime | None,
    poll_interval_seconds: int = 30,
) -> datetime:
    """Estimate when next poll should occur.
    
    Args:
        last_poll_at: When polling last occurred
        poll_interval_seconds: Interval between polls
    
    Returns:
        Datetime of estimated next poll
    """
    if last_poll_at is None:
        return datetime.now(UTC)
    
    next_poll = last_poll_at + timedelta(seconds=poll_interval_seconds)
    return max(next_poll, datetime.now(UTC))
