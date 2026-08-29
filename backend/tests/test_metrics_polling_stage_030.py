"""Unit tests for Stage 030: Scheduled Metrics Polling."""
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch


from app.services.jobs.metrics_polling import (
    poll_active_rollouts,
    get_rollout_polling_status,
    should_poll_now,
    estimate_next_poll_time,
)


class TestPollActiveRollouts:
    """Tests for poll_active_rollouts function."""

    def test_poll_active_rollouts_none_exist(self):
        """Return stats when no active rollouts."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = []

        stats = poll_active_rollouts(mock_db)

        assert stats["polled_count"] == 0
        assert stats["auto_rollback_count"] == 0
        assert stats["errors"] == []

    def test_poll_active_rollouts_safe_metrics(self):
        """Poll rollout with safe metrics (no auto-rollback)."""
        mock_rollout = Mock()
        mock_rollout.id = "crl-1"
        mock_rollout.error_rate_baseline = 0.5
        mock_rollout.error_rate_current = 0.48
        mock_rollout.updated_at = datetime.now(UTC)

        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = [mock_rollout]

        with patch("app.services.jobs.metrics_polling.check_auto_rollback_threshold") as mock_check:
            with patch("app.services.jobs.metrics_polling.log_audit"):
                mock_check.return_value = (False, None)  # Safe

                stats = poll_active_rollouts(mock_db)

                assert stats["polled_count"] == 1
                assert stats["auto_rollback_count"] == 0
                assert stats["errors"] == []
                mock_check.assert_called_once()

    def test_poll_active_rollouts_triggers_auto_rollback(self):
        """Poll triggers auto-rollback when metrics unsafe."""
        mock_rollout = Mock()
        mock_rollout.id = "crl-1"
        mock_rollout.error_rate_baseline = 0.5
        mock_rollout.error_rate_current = 0.9
        mock_rollout.updated_at = datetime.now(UTC)

        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = [mock_rollout]

        with patch("app.services.jobs.metrics_polling.check_auto_rollback_threshold") as mock_check:
            with patch("app.services.jobs.metrics_polling.log_audit"):
                mock_check.return_value = (True, "error_rate_threshold_exceeded: 75% > 50%")

                stats = poll_active_rollouts(mock_db)

                assert stats["polled_count"] == 1
                assert stats["auto_rollback_count"] == 1
                assert stats["errors"] == []
                # Verify auto_rollback_triggered set on rollout
                assert mock_rollout.auto_rollback_triggered is True

    def test_poll_active_rollouts_error_handling(self):
        """Handle errors gracefully during polling."""
        mock_rollout = Mock()
        mock_rollout.id = "crl-1"
        mock_rollout.error_rate_current = None

        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = [mock_rollout]

        stats = poll_active_rollouts(mock_db)

        assert stats["polled_count"] == 0
        assert stats["auto_rollback_count"] == 0
        assert stats["errors"] == ["Metrics evidence unavailable for crl-1"]


class TestGetRolloutPollingStatus:
    """Tests for get_rollout_polling_status function."""

    def test_get_polling_status_no_active_rollouts(self):
        """Return status when no active rollouts."""
        mock_db = Mock()
        mock_query_rollout = Mock()
        mock_query_audit = Mock()

        def query_side_effect(model):
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            else:
                return mock_query_audit

        mock_db.query.side_effect = query_side_effect
        mock_query_rollout.filter.return_value.all.return_value = []
        mock_query_audit.filter.return_value.order_by.return_value.first.return_value = None

        status = get_rollout_polling_status(mock_db)

        assert status["total_active"] == 0
        assert status["active_rollouts"] == []
        assert status["last_poll_at"] is None

    def test_get_polling_status_with_active_rollout(self):
        """Return status for active rollout."""
        now = datetime.now(UTC)
        started_at = now - timedelta(minutes=5)
        updated_at = now - timedelta(seconds=10)

        mock_rollout = Mock()
        mock_rollout.id = "crl-1"
        mock_rollout.policy_type = "runbook"
        mock_rollout.current_canary_percentage = 25
        mock_rollout.error_rate_baseline = 0.5
        mock_rollout.error_rate_current = 0.52
        mock_rollout.started_at = started_at
        mock_rollout.updated_at = updated_at

        mock_db = Mock()
        mock_query_rollout = Mock()
        mock_query_audit = Mock()

        def query_side_effect(model):
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            else:
                return mock_query_audit

        mock_db.query.side_effect = query_side_effect
        mock_query_rollout.filter.return_value.all.return_value = [mock_rollout]
        mock_query_audit.filter.return_value.order_by.return_value.first.return_value = None

        with patch("app.services.jobs.metrics_polling.datetime") as mock_datetime_module:
            mock_datetime_module.now.return_value = now
            mock_datetime_module.UTC = UTC

            status = get_rollout_polling_status(mock_db)

            assert status["total_active"] == 1
            assert len(status["active_rollouts"]) == 1

            rollout_status = status["active_rollouts"][0]
            assert rollout_status["rollout_id"] == "crl-1"
            assert rollout_status["policy_type"] == "runbook"
            assert rollout_status["current_canary_percentage"] == 25
            assert rollout_status["minutes_since_start"] == 5
            assert rollout_status["next_poll_in_seconds"] >= 0  # About 20 seconds remaining

    def test_get_polling_status_with_last_poll_time(self):
        """Include last poll time from audit log."""
        last_poll = datetime.now(UTC) - timedelta(minutes=2)

        mock_audit = Mock()
        mock_audit.created_at = last_poll

        mock_db = Mock()
        mock_query_rollout = Mock()
        mock_query_audit = Mock()

        def query_side_effect(model):
            if "PolicyCanaryRollout" in str(model):
                return mock_query_rollout
            else:
                return mock_query_audit

        mock_db.query.side_effect = query_side_effect
        mock_query_rollout.filter.return_value.all.return_value = []
        mock_query_audit.filter.return_value.order_by.return_value.first.return_value = mock_audit

        status = get_rollout_polling_status(mock_db)

        assert status["last_poll_at"] == last_poll


class TestShouldPollNow:
    """Tests for should_poll_now function."""

    def test_should_poll_never_polled_before(self):
        """Poll if never polled before."""
        result = should_poll_now(last_poll_at=None)

        assert result is True

    def test_should_poll_interval_not_reached(self):
        """Don't poll if interval not reached."""
        last_poll = datetime.now(UTC) - timedelta(seconds=5)

        result = should_poll_now(last_poll_at=last_poll, poll_interval_seconds=30)

        assert result is False

    def test_should_poll_interval_reached(self):
        """Poll if interval reached."""
        last_poll = datetime.now(UTC) - timedelta(seconds=35)

        result = should_poll_now(last_poll_at=last_poll, poll_interval_seconds=30)

        assert result is True

    def test_should_poll_exactly_at_interval(self):
        """Poll if exactly at interval."""
        last_poll = datetime.now(UTC) - timedelta(seconds=30)

        result = should_poll_now(last_poll_at=last_poll, poll_interval_seconds=30)

        assert result is True

    def test_should_poll_custom_interval(self):
        """Respect custom polling interval."""
        last_poll = datetime.now(UTC) - timedelta(seconds=50)

        # 60-second interval
        result = should_poll_now(last_poll_at=last_poll, poll_interval_seconds=60)

        assert result is False


class TestEstimateNextPollTime:
    """Tests for estimate_next_poll_time function."""

    def test_estimate_never_polled_before(self):
        """Estimate is now if never polled."""
        now = datetime.now(UTC)

        with patch("app.services.jobs.metrics_polling.datetime") as mock_datetime_module:
            mock_datetime_module.now.return_value = now
            mock_datetime_module.UTC = UTC

            estimated = estimate_next_poll_time(last_poll_at=None)

            assert estimated <= now + timedelta(seconds=1)  # Close to now

    def test_estimate_after_poll(self):
        """Estimate is last_poll + interval."""
        now = datetime.now(UTC)
        last_poll = now - timedelta(seconds=10)

        with patch("app.services.jobs.metrics_polling.datetime") as mock_datetime_module:
            mock_datetime_module.now.return_value = now
            mock_datetime_module.UTC = UTC

            estimated = estimate_next_poll_time(
                last_poll_at=last_poll,
                poll_interval_seconds=30,
            )

            # Should be last_poll + 30 = now + 20
            expected = last_poll + timedelta(seconds=30)
            assert abs((estimated - expected).total_seconds()) < 1  # Close to expected

    def test_estimate_overdue_poll(self):
        """Estimate is now if poll is overdue."""
        now = datetime.now(UTC)
        last_poll = now - timedelta(seconds=60)

        with patch("app.services.jobs.metrics_polling.datetime") as mock_datetime_module:
            mock_datetime_module.now.return_value = now
            mock_datetime_module.UTC = UTC

            estimated = estimate_next_poll_time(
                last_poll_at=last_poll,
                poll_interval_seconds=30,
            )

            # Should return now (not in past)
            assert estimated >= now

    def test_estimate_with_default_interval(self):
        """Use default 30-second interval if not specified."""
        now = datetime.now(UTC)
        last_poll = now - timedelta(seconds=10)

        with patch("app.services.jobs.metrics_polling.datetime") as mock_datetime_module:
            mock_datetime_module.now.return_value = now
            mock_datetime_module.UTC = UTC

            estimated = estimate_next_poll_time(last_poll_at=last_poll)

            # Should use default 30-second interval
            expected = last_poll + timedelta(seconds=30)
            assert abs((estimated - expected).total_seconds()) < 1
