"""Policy enforcement integration - applies policies to consumers with canary + override support."""
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.job_event_runbook_policy_state import JobEventRunbookPolicyState
from app.models.job_event_autoremediation_policy_state import JobEventAutoremediationPolicyState
from app.models.policy_canary_rollout import PolicyCanaryRollout
from app.models.consumer_policy_override import ConsumerPolicyOverride
from app.services.jobs.policy_canary_enforcement import (
    should_consumer_get_policy,
    merge_consumer_override,
)


def get_global_policy(
    db: Session,
    policy_type: str,
) -> tuple[dict[str, Any], int]:
    """Get current global policy and its version.
    
    Args:
        db: Database session
        policy_type: "runbook" or "autoremediation"
    
    Returns:
        Tuple of (policy_dict, version_number)
    """
    if policy_type == "runbook":
        record = db.query(JobEventRunbookPolicyState).order_by(
            JobEventRunbookPolicyState.version.desc()
        ).first()
    else:  # autoremediation
        record = db.query(JobEventAutoremediationPolicyState).order_by(
            JobEventAutoremediationPolicyState.version.desc()
        ).first()
    
    if not record:
        return {}, 0
    
    try:
        policy = json.loads(record.payload_json) if isinstance(record.payload_json, str) else record.payload_json
    except (json.JSONDecodeError, TypeError):
        policy = {}
    
    return policy, record.version


def get_active_rollout(
    db: Session,
    policy_type: str,
) -> PolicyCanaryRollout | None:
    """Get active canary rollout for a policy type.
    
    Returns None if no active rollout exists.
    """
    rollout = db.query(PolicyCanaryRollout).filter(
        PolicyCanaryRollout.policy_type == policy_type,
        PolicyCanaryRollout.status == "in_progress",
        PolicyCanaryRollout.auto_rollback_triggered.is_(False),
    ).first()
    
    return rollout


def should_apply_policy(
    db: Session,
    consumer_name: str,
    policy_type: str,
) -> bool:
    """Determine if consumer should receive the policy.
    
    Checks:
    1. Is there an active canary rollout? If yes, check canary selection.
    2. If no active rollout, policy applies to all consumers.
    3. Respects auto-rollback status (no policy if auto-rolled-back).
    
    Args:
        db: Database session
        consumer_name: Consumer name
        policy_type: "runbook" or "autoremediation"
    
    Returns:
        True if consumer should apply policy
    """
    rollout = get_active_rollout(db, policy_type)
    
    if not rollout:
        # No canary rollout = policy applies to all consumers
        return True
    
    # Active canary rollout exists
    if rollout.auto_rollback_triggered:
        # Auto-rolled back = policy doesn't apply yet
        return False
    
    # Check if consumer is in the canary rollout
    return should_consumer_get_policy(consumer_name, rollout.current_canary_percentage)


def get_effective_policy(
    db: Session,
    consumer_name: str,
    policy_type: str,
) -> dict[str, Any]:
    """Get effective policy for a consumer.
    
    Combines:
    1. Global policy (base)
    2. Consumer override (merged on top)
    3. Respects canary selection
    
    Returns empty dict if consumer should not receive policy or policy not set.
    
    Args:
        db: Database session
        consumer_name: Consumer name
        policy_type: "runbook" or "autoremediation"
    
    Returns:
        Effective policy dict (may be empty)
    """
    # Check if consumer should get policy
    if not should_apply_policy(db, consumer_name, policy_type):
        return {}
    
    # Get global policy
    global_policy, _version = get_global_policy(db, policy_type)
    
    if not global_policy:
        return {}
    
    # Get consumer override (if any)
    override = db.query(ConsumerPolicyOverride).filter_by(
        consumer_name=consumer_name,
        policy_type=policy_type,
    ).first()
    
    # Merge override into global policy
    effective = merge_consumer_override(global_policy, override)
    
    return effective


def get_policy_enforcement_status(
    db: Session,
    consumer_name: str,
    policy_type: str,
) -> dict[str, Any]:
    """Get comprehensive enforcement status for a consumer.
    
    Shows:
    - Whether policy applies to consumer
    - Active rollout info (if applicable)
    - Consumer override info (if applicable)
    - Reason for enforcement decision
    
    Args:
        db: Database session
        consumer_name: Consumer name
        policy_type: "runbook" or "autoremediation"
    
    Returns:
        Status dict with detailed information
    """
    global_policy, policy_version = get_global_policy(db, policy_type)
    rollout = get_active_rollout(db, policy_type)
    override = db.query(ConsumerPolicyOverride).filter_by(
        consumer_name=consumer_name,
        policy_type=policy_type,
    ).first()
    
    should_apply = should_apply_policy(db, consumer_name, policy_type)
    
    status = {
        "consumer_name": consumer_name,
        "policy_type": policy_type,
        "policy_applies": should_apply,
        "global_policy_version": policy_version,
        "global_policy_set": bool(global_policy),
        "active_rollout": None,
        "consumer_override": None,
        "enforcement_reason": "",
    }
    
    # Add rollout info
    if rollout:
        status["active_rollout"] = {
            "rollout_id": rollout.id,
            "current_canary_percentage": rollout.current_canary_percentage,
            "status": rollout.status,
            "auto_rollback_triggered": rollout.auto_rollback_triggered,
            "consumer_in_canary": should_consumer_get_policy(
                consumer_name,
                rollout.current_canary_percentage,
            ),
        }
        
        if rollout.auto_rollback_triggered:
            status["enforcement_reason"] = f"policy rolled back (auto-rollback_triggered: {rollout.auto_rollback_reason})"
        elif not status["active_rollout"]["consumer_in_canary"]:
            status["enforcement_reason"] = f"consumer not in canary ({rollout.current_canary_percentage}%)"
        else:
            status["enforcement_reason"] = f"consumer in active canary rollout ({rollout.current_canary_percentage}%)"
    else:
        if not global_policy:
            status["enforcement_reason"] = "no policy set globally"
        else:
            status["enforcement_reason"] = "no active rollout, applying to all consumers"
    
    # Add override info
    if override:
        status["consumer_override"] = {
            "override_id": override.id,
            "reason": override.reason,
            "created_by": override.created_by_email,
        }
    
    return status


def evaluate_policy_before_apply(
    db: Session,
    consumer_name: str,
    policy_type: str,
) -> dict[str, Any]:
    """Dry-run evaluation: what policy would apply if applied now?
    
    Used for testing/validation before actual application.
    
    Returns dict with:
    - will_apply: bool
    - effective_policy: dict (empty if won't apply)
    - enforcement_status: detailed status info
    - warnings: list of warning messages (e.g., "consumer override is stale")
    
    Args:
        db: Database session
        consumer_name: Consumer name
        policy_type: "runbook" or "autoremediation"
    
    Returns:
        Evaluation result dict
    """
    will_apply = should_apply_policy(db, consumer_name, policy_type)
    effective_policy = get_effective_policy(db, consumer_name, policy_type)
    status = get_policy_enforcement_status(db, consumer_name, policy_type)
    
    warnings = []
    
    # Check for stale overrides
    override = db.query(ConsumerPolicyOverride).filter_by(
        consumer_name=consumer_name,
        policy_type=policy_type,
    ).first()
    
    if override:
        global_policy, policy_version = get_global_policy(db, policy_type)
        if policy_version > override.policy_version:
            warnings.append(
                f"consumer override is outdated (override_version={override.policy_version}, global_version={policy_version})"
            )
    
    return {
        "consumer_name": consumer_name,
        "policy_type": policy_type,
        "will_apply": will_apply,
        "effective_policy": effective_policy,
        "enforcement_status": status,
        "warnings": warnings,
    }
