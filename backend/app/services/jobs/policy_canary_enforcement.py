"""Policy canary rollout service for graduated rollout enforcement."""
import hashlib
import json
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.policy_canary_rollout import PolicyCanaryRollout
from app.models.consumer_policy_override import ConsumerPolicyOverride


def _consumer_hash(consumer_name: str) -> int:
    """Generate deterministic hash for consumer name for canary selection."""
    hash_obj = hashlib.sha256(consumer_name.encode())
    return int(hash_obj.hexdigest()[:8], 16)


def should_consumer_get_policy(consumer_name: str, canary_percentage: int) -> bool:
    """Determine if consumer is in canary rollout based on hash.
    
    Hash-based selection ensures same consumers always selected for a given canary %.
    Example: canary=5% selects consumers with hash % 100 < 5
    """
    if canary_percentage >= 100:
        return True
    if canary_percentage <= 0:
        return False
    
    consumer_hash = _consumer_hash(consumer_name)
    return (consumer_hash % 100) < canary_percentage


def merge_consumer_override(
    global_policy: dict[str, Any],
    override: ConsumerPolicyOverride | None,
) -> dict[str, Any]:
    """Merge consumer override with global policy (override takes precedence).
    
    Args:
        global_policy: The global policy payload
        override: Consumer-specific override (if any)
    
    Returns:
        Merged policy with overrides applied
    """
    if not override:
        return global_policy
    
    merged = dict(global_policy)
    try:
        overrides_json = json.loads(override.overrides_json) if isinstance(override.overrides_json, str) else override.overrides_json
        merged.update(overrides_json)
    except (json.JSONDecodeError, TypeError):
        # If override JSON is malformed, use global policy
        pass
    
    return merged


def get_effective_policy(
    db: Session,
    consumer_name: str,
    policy_type: str,
    global_policy: dict[str, Any],
) -> dict[str, Any]:
    """Get effective policy for consumer (global + any overrides).
    
    Args:
        db: Database session
        consumer_name: Consumer name
        policy_type: "runbook" or "autoremediation"
        global_policy: Global policy payload
    
    Returns:
        Effective policy (global + consumer overrides merged)
    """
    override = (
        db.query(ConsumerPolicyOverride)
        .filter_by(consumer_name=consumer_name, policy_type=policy_type)
        .first()
    )
    
    return merge_consumer_override(global_policy, override)


def create_canary_rollout(
    db: Session,
    approval_request_id: str,
    policy_type: str,
    canary_percentage: int,
    affected_consumers_count: int,
    metrics_baseline: dict[str, Any] | None = None,
) -> PolicyCanaryRollout:
    """Create a new canary rollout tracking record.
    
    Args:
        db: Database session
        approval_request_id: Reference to PolicyApprovalRequest
        policy_type: "runbook" or "autoremediation"
        canary_percentage: Initial canary percentage (5-100)
        affected_consumers_count: Number of consumers in canary
        metrics_baseline: Optional baseline metrics snapshot
    
    Returns:
        Created PolicyCanaryRollout record
    """
    rollout_id = f"crl-{secrets.token_hex(16)}"
    rollout = PolicyCanaryRollout(
        id=rollout_id,
        approval_request_id=approval_request_id,
        policy_type=policy_type,
        current_canary_percentage=canary_percentage,
        affected_consumers_count=affected_consumers_count,
        metrics_baseline_json=json.dumps(metrics_baseline) if metrics_baseline else None,
        error_rate_baseline=(
            float(metrics_baseline["error_rate"])
            if metrics_baseline and metrics_baseline.get("error_rate") is not None
            else None
        ),
        status="in_progress",
    )
    db.add(rollout)
    db.flush()  # Get the ID
    return rollout


def graduate_canary(
    db: Session,
    rollout_id: str,
    new_canary_percentage: int,
) -> PolicyCanaryRollout:
    """Graduate canary rollout to next percentage.
    
    Args:
        db: Database session
        rollout_id: PolicyCanaryRollout ID
        new_canary_percentage: New canary percentage (5-100)
    Returns:
        Updated PolicyCanaryRollout record
    
    Raises:
        ValueError: If new_canary_percentage <= current
    """
    rollout = db.query(PolicyCanaryRollout).filter_by(id=rollout_id).first()
    if not rollout:
        raise ValueError(f"Rollout {rollout_id} not found")
    
    if new_canary_percentage <= rollout.current_canary_percentage:
        raise ValueError(
            f"Cannot graduate to {new_canary_percentage}%; current is {rollout.current_canary_percentage}%"
        )
    
    rollout.current_canary_percentage = new_canary_percentage
    rollout.metrics_baseline_json = rollout.metrics_current_json
    rollout.error_rate_baseline = rollout.error_rate_current
    rollout.metrics_current_json = None
    rollout.error_rate_current = None
    
    return rollout


def complete_rollout(
    db: Session,
    rollout_id: str,
) -> PolicyCanaryRollout:
    """Mark rollout as completed (100% applied to all consumers).
    
    Args:
        db: Database session
        rollout_id: PolicyCanaryRollout ID
    
    Returns:
        Completed PolicyCanaryRollout record
    """
    rollout = db.query(PolicyCanaryRollout).filter_by(id=rollout_id).first()
    if not rollout:
        raise ValueError(f"Rollout {rollout_id} not found")
    
    rollout.status = "completed"
    rollout.completed_at = datetime.now(UTC)
    rollout.current_canary_percentage = 100
    
    return rollout


def auto_rollback_canary(
    db: Session,
    rollout_id: str,
    reason: str,
) -> PolicyCanaryRollout:
    """Auto-rollback canary if error threshold exceeded.
    
    Args:
        db: Database session
        rollout_id: PolicyCanaryRollout ID
        reason: Reason for auto-rollback (e.g., "error_rate_exceeded")
    
    Returns:
        Rolled-back PolicyCanaryRollout record
    """
    rollout = db.query(PolicyCanaryRollout).filter_by(id=rollout_id).first()
    if not rollout:
        raise ValueError(f"Rollout {rollout_id} not found")
    
    rollout.status = "rolled_back"
    rollout.completed_at = datetime.now(UTC)
    rollout.auto_rollback_triggered = True
    rollout.auto_rollback_reason = reason
    
    db.add(rollout)
    db.commit()
    db.refresh(rollout)
    return rollout


def get_rollout_for_approval(
    db: Session,
    approval_id: str,
) -> PolicyCanaryRollout | None:
    """Get most recent rollout for approval request.
    
    Args:
        db: Database session
        approval_id: PolicyApprovalRequest ID
    
    Returns:
        Most recent PolicyCanaryRollout or None
    """
    return (
        db.query(PolicyCanaryRollout)
        .filter_by(approval_request_id=approval_id)
        .order_by(PolicyCanaryRollout.started_at.desc())
        .first()
    )
