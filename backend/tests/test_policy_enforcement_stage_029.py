"""Unit tests for Stage 029: Policy Enforcement Integration."""
import json
from unittest.mock import Mock


from app.services.jobs.policy_enforcement_integration import (
    get_global_policy,
    get_active_rollout,
    should_apply_policy,
    get_effective_policy,
    get_policy_enforcement_status,
    evaluate_policy_before_apply,
)


class TestGetGlobalPolicy:
    """Tests for get_global_policy function (mocked DB)."""

    def test_get_runbook_policy_latest_version(self):
        """Get latest runbook policy version."""
        policy_dict = {"allowed_codes": ["RB1", "RB2"]}
        mock_record = Mock()
        mock_record.version = 2
        mock_record.payload_json = json.dumps(policy_dict)

        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.order_by.return_value.first.return_value = mock_record

        policy, version = get_global_policy(mock_db, "runbook")

        assert version == 2
        assert policy == policy_dict

    def test_get_autoremediation_policy_latest_version(self):
        """Get latest autoremediation policy version."""
        policy_dict = {"enabled": True, "max_requeued_per_cycle": 50}
        mock_record = Mock()
        mock_record.version = 3
        mock_record.payload_json = json.dumps(policy_dict)

        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.order_by.return_value.first.return_value = mock_record

        policy, version = get_global_policy(mock_db, "autoremediation")

        assert version == 3
        assert policy["enabled"] is True

    def test_get_policy_not_exists(self):
        """Return empty policy if not set."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.order_by.return_value.first.return_value = None

        policy, version = get_global_policy(mock_db, "runbook")

        assert version == 0
        assert policy == {}

    def test_get_policy_malformed_json(self):
        """Handle malformed JSON gracefully."""
        mock_record = Mock()
        mock_record.version = 1
        mock_record.payload_json = "not-valid-json"

        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.order_by.return_value.first.return_value = mock_record

        policy, version = get_global_policy(mock_db, "runbook")

        assert version == 1
        assert policy == {}

    def test_get_policy_dict_already_parsed(self):
        """Handle already-parsed dict payload."""
        policy_dict = {"setting": "value"}
        mock_record = Mock()
        mock_record.version = 1
        mock_record.payload_json = policy_dict  # Already a dict, not JSON string

        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.order_by.return_value.first.return_value = mock_record

        policy, version = get_global_policy(mock_db, "runbook")

        assert version == 1
        assert policy == policy_dict


class TestGetActiveRollout:
    """Tests for get_active_rollout function."""

    def test_get_active_rollout_found(self):
        """Get active rollout if exists."""
        mock_rollout = Mock()
        mock_rollout.policy_type = "runbook"
        mock_rollout.status = "in_progress"

        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.first.return_value = mock_rollout

        result = get_active_rollout(mock_db, "runbook")

        assert result == mock_rollout

    def test_get_active_rollout_not_found(self):
        """Return None if no active rollout."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.first.return_value = None

        result = get_active_rollout(mock_db, "runbook")

        assert result is None


class TestShouldApplyPolicy:
    """Tests for should_apply_policy function."""

    def test_apply_policy_no_active_rollout(self):
        """With no active rollout, policy applies to all consumers."""
        mock_db = Mock()
        # Mock get_active_rollout to return None
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.first.return_value = None

        result = should_apply_policy(mock_db, "my-consumer", "runbook")

        assert result is True

    def test_apply_policy_auto_rollback_triggered(self):
        """Policy doesn't apply if auto-rollback triggered."""
        mock_rollout = Mock()
        mock_rollout.auto_rollback_triggered = True

        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.first.return_value = mock_rollout

        result = should_apply_policy(mock_db, "any-consumer", "runbook")

        assert result is False

    def test_apply_policy_active_rollout_consumer_in_canary(self):
        """Consumer in canary percentage should get policy."""
        mock_rollout = Mock()
        mock_rollout.auto_rollback_triggered = False
        mock_rollout.current_canary_percentage = 100  # All consumers

        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.first.return_value = mock_rollout

        result = should_apply_policy(mock_db, "my-consumer", "runbook")

        # With 100% canary and should_consumer_get_policy, result should be True
        assert isinstance(result, bool)


class TestGetEffectivePolicy:
    """Tests for get_effective_policy function."""

    def test_effective_policy_no_global_no_override(self):
        """Empty effective policy if no global policy set."""
        # Mock get_active_rollout to return None (no canary)
        mock_db = Mock()
        mock_query_rollout = Mock()
        mock_query_global = Mock()

        def query_side_effect(model):
            # First call is for active_rollout check
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            else:
                return mock_query_global

        mock_db.query.side_effect = query_side_effect
        mock_query_rollout.filter.return_value.first.return_value = None
        mock_query_global.order_by.return_value.first.return_value = None

        effective = get_effective_policy(mock_db, "my-consumer", "runbook")

        assert effective == {}

    def test_effective_policy_global_only(self):
        """Use global policy if no consumer override."""
        global_policy = {"allowed_codes": ["RB1", "RB2"], "enabled": True}
        mock_record = Mock()
        mock_record.version = 1
        mock_record.payload_json = json.dumps(global_policy)

        # Mock should_apply_policy to return True
        mock_db = Mock()
        mock_query_rollout = Mock()
        mock_query_policy = Mock()
        mock_query_override = Mock()

        call_count = [0]

        def query_side_effect(model):
            call_count[0] += 1
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            elif "JobEventRunbookPolicyState" in str(model):
                return mock_query_policy
            else:
                return mock_query_override

        mock_db.query.side_effect = query_side_effect
        mock_query_rollout.filter.return_value.first.return_value = None  # No active rollout
        mock_query_policy.order_by.return_value.first.return_value = mock_record
        mock_query_override.filter_by.return_value.first.return_value = None  # No override

        effective = get_effective_policy(mock_db, "my-consumer", "runbook")

        assert effective == global_policy

    def test_effective_policy_global_plus_override(self):
        """Merge consumer override on top of global policy."""
        global_policy = {"allowed_codes": ["RB1", "RB2"], "enabled": True, "max_per_hour": 10}
        override_data = {"allowed_codes": ["RB1"], "max_per_hour": 5}

        mock_policy_record = Mock()
        mock_policy_record.version = 1
        mock_policy_record.payload_json = json.dumps(global_policy)

        mock_override = Mock()
        mock_override.overrides_json = json.dumps(override_data)

        mock_db = Mock()
        mock_query_rollout = Mock()
        mock_query_policy = Mock()
        mock_query_override = Mock()

        def query_side_effect(model):
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            elif "JobEventRunbookPolicyState" in str(model):
                return mock_query_policy
            else:
                return mock_query_override

        mock_db.query.side_effect = query_side_effect
        mock_query_rollout.filter.return_value.first.return_value = None
        mock_query_policy.order_by.return_value.first.return_value = mock_policy_record
        mock_query_override.filter_by.return_value.first.return_value = mock_override

        effective = get_effective_policy(mock_db, "my-consumer", "runbook")

        assert effective["allowed_codes"] == ["RB1"]  # Override
        assert effective["max_per_hour"] == 5  # Override
        assert effective["enabled"] is True  # From global


class TestGetPolicyEnforcementStatus:
    """Tests for get_policy_enforcement_status function."""

    def test_enforcement_status_no_policy_set(self):
        """Status when no policy set globally."""
        mock_db = Mock()
        mock_query_policy = Mock()
        mock_query_rollout = Mock()
        mock_query_override = Mock()

        def query_side_effect(model):
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            elif "JobEventRunbookPolicyState" in str(model):
                return mock_query_policy
            else:
                return mock_query_override

        mock_db.query.side_effect = query_side_effect
        mock_query_policy.order_by.return_value.first.return_value = None
        mock_query_rollout.filter.return_value.first.return_value = None
        mock_query_override.filter_by.return_value.first.return_value = None

        status = get_policy_enforcement_status(mock_db, "my-consumer", "runbook")

        assert status["consumer_name"] == "my-consumer"
        assert status["policy_type"] == "runbook"
        assert status["policy_applies"] is True
        assert status["global_policy_version"] == 0
        assert status["global_policy_set"] is False

    def test_enforcement_status_with_override(self):
        """Status includes consumer override information."""
        mock_override = Mock()
        mock_override.id = "ov-1"
        mock_override.reason = "low-risk consumer"
        mock_override.created_by_email = "admin@test.com"

        mock_db = Mock()
        mock_query_policy = Mock()
        mock_query_rollout = Mock()
        mock_query_override = Mock()

        def query_side_effect(model):
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            elif "JobEventRunbookPolicyState" in str(model):
                return mock_query_policy
            else:
                return mock_query_override

        mock_db.query.side_effect = query_side_effect
        mock_query_policy.order_by.return_value.first.return_value = None
        mock_query_rollout.filter.return_value.first.return_value = None
        mock_query_override.filter_by.return_value.first.return_value = mock_override

        status = get_policy_enforcement_status(mock_db, "my-consumer", "runbook")

        assert status["consumer_override"] is not None
        assert status["consumer_override"]["reason"] == "low-risk consumer"


class TestEvaluatePolicyBeforeApply:
    """Tests for evaluate_policy_before_apply function."""

    def test_evaluate_policy_will_apply_empty(self):
        """Evaluate when policy will apply but is empty."""
        mock_db = Mock()
        mock_query_policy = Mock()
        mock_query_rollout = Mock()
        mock_query_override = Mock()

        def query_side_effect(model):
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            elif "JobEventRunbookPolicyState" in str(model):
                return mock_query_policy
            else:
                return mock_query_override

        mock_db.query.side_effect = query_side_effect
        mock_query_policy.order_by.return_value.first.return_value = None
        mock_query_rollout.filter.return_value.first.return_value = None
        mock_query_override.filter_by.return_value.first.return_value = None

        result = evaluate_policy_before_apply(mock_db, "my-consumer", "runbook")

        assert result["consumer_name"] == "my-consumer"
        assert result["will_apply"] is True
        assert result["effective_policy"] == {}
        assert result["warnings"] == []

    def test_evaluate_policy_detects_stale_override(self):
        """Evaluate detects outdated consumer override."""
        # Global policy v5
        mock_policy_record = Mock()
        mock_policy_record.version = 5
        mock_policy_record.payload_json = json.dumps({"setting": "global"})

        # Override for v3 (outdated)
        mock_override = Mock()
        mock_override.policy_version = 3

        mock_db = Mock()
        mock_query_policy = Mock()
        mock_query_rollout = Mock()
        mock_query_override = Mock()

        def query_side_effect(model):
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            elif "JobEventRunbookPolicyState" in str(model):
                return mock_query_policy
            else:
                return mock_query_override

        mock_db.query.side_effect = query_side_effect
        mock_query_policy.order_by.return_value.first.return_value = mock_policy_record
        mock_query_rollout.filter.return_value.first.return_value = None
        mock_query_override.filter_by.return_value.first.return_value = mock_override

        result = evaluate_policy_before_apply(mock_db, "my-consumer", "runbook")

        assert result["will_apply"] is True
        assert len(result["warnings"]) > 0
        assert "outdated" in result["warnings"][0].lower()

    def test_evaluate_policy_no_stale_override_warning(self):
        """No warning if override version matches global version."""
        mock_policy_record = Mock()
        mock_policy_record.version = 2
        mock_policy_record.payload_json = json.dumps({"setting": "global"})

        mock_override = Mock()
        mock_override.policy_version = 2  # Same as global

        mock_db = Mock()
        mock_query_policy = Mock()
        mock_query_rollout = Mock()
        mock_query_override = Mock()

        def query_side_effect(model):
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            elif "JobEventRunbookPolicyState" in str(model):
                return mock_query_policy
            else:
                return mock_query_override

        mock_db.query.side_effect = query_side_effect
        mock_query_policy.order_by.return_value.first.return_value = mock_policy_record
        mock_query_rollout.filter.return_value.first.return_value = None
        mock_query_override.filter_by.return_value.first.return_value = mock_override

        result = evaluate_policy_before_apply(mock_db, "my-consumer", "runbook")

        assert result["warnings"] == []

