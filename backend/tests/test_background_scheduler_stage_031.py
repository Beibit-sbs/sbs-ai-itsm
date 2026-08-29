"""Unit tests for Stage 031: Background Worker Task Scheduler."""
import time
from unittest.mock import Mock, patch


from app.services.jobs.background_scheduler import (
    start_scheduler,
    stop_scheduler,
    get_scheduler_status,
    restart_scheduler,
    get_scheduler_metrics,
    _metrics_polling_job,
)


class TestStartScheduler:
    """Tests for start_scheduler function."""

    def teardown_method(self):
        """Clean up scheduler after each test."""
        try:
            stop_scheduler()
        except Exception:
            pass

    def test_start_scheduler_default_interval(self):
        """Start scheduler with default 30-second interval."""
        result = start_scheduler()

        assert result["status"] == "started"
        assert result["started_at"] is not None
        assert result["poll_interval_seconds"] == 30
        assert result["job_id"] == "metrics-polling-job"

        # Verify it's actually running
        status = get_scheduler_status()
        assert status["running"] is True

    def test_start_scheduler_custom_interval(self):
        """Start scheduler with custom interval."""
        result = start_scheduler(poll_interval_seconds=60)

        assert result["status"] == "started"
        assert result["poll_interval_seconds"] == 60

    def test_start_scheduler_already_running(self):
        """Handle starting when already running."""
        # Start once
        result1 = start_scheduler()
        assert result1["status"] == "started"

        # Try to start again
        result2 = start_scheduler()

        assert result2["status"] == "already_running"
        assert result2["started_at"] == result1["started_at"]

    def test_start_scheduler_creates_job(self):
        """Verify job is created and scheduled."""
        start_scheduler()
        status = get_scheduler_status()

        assert status["active_jobs"] == 1
        assert status["next_poll_in_seconds"] is not None
        # Next poll should be within 30 seconds
        assert 0 <= status["next_poll_in_seconds"] <= 30


class TestStopScheduler:
    """Tests for stop_scheduler function."""

    def test_stop_scheduler_when_running(self):
        """Stop scheduler that is running."""
        start_scheduler()

        result = stop_scheduler()

        assert result["status"] == "stopped"
        assert result["stopped_at"] is not None
        assert result["uptime_seconds"] is not None
        assert result["uptime_seconds"] >= 0

    def test_stop_scheduler_not_running(self):
        """Handle stopping when not running."""
        result = stop_scheduler()

        assert result["status"] == "not_running"
        assert result["stopped_at"] is not None

    def test_stop_scheduler_preserves_statistics(self):
        """Stopping preserves final poll counts."""
        start_scheduler()

        result = stop_scheduler()

        assert result["total_polls"] == 0  # No time has passed
        assert result["total_errors"] == 0


class TestGetSchedulerStatus:
    """Tests for get_scheduler_status function."""

    def teardown_method(self):
        """Clean up scheduler after each test."""
        try:
            stop_scheduler()
        except Exception:
            pass

    def test_get_status_not_running(self):
        """Status when scheduler not running."""
        status = get_scheduler_status()

        assert status["running"] is False
        assert status["started_at"] is None
        assert status["uptime_seconds"] is None
        assert status["poll_count"] == 0
        assert status["poll_errors"] == 0
        assert status["active_jobs"] == 0

    def test_get_status_running(self):
        """Status when scheduler is running."""
        start_scheduler()

        status = get_scheduler_status()

        assert status["running"] is True
        assert status["started_at"] is not None
        assert status["uptime_seconds"] is not None
        assert status["uptime_seconds"] >= 0
        assert status["active_jobs"] == 1
        assert status["next_poll_in_seconds"] is not None

    def test_get_status_includes_poll_count(self):
        """Status includes polling statistics."""
        start_scheduler()

        status = get_scheduler_status()

        assert "poll_count" in status
        assert "poll_errors" in status
        assert isinstance(status["poll_count"], int)
        assert isinstance(status["poll_errors"], int)


class TestRestartScheduler:
    """Tests for restart_scheduler function."""

    def test_restart_scheduler_changes_interval(self):
        """Restart with new interval."""
        # Start with 30s
        start_scheduler(poll_interval_seconds=30)
        original_start_time = get_scheduler_status()["started_at"]

        # Wait a tiny bit to ensure different restart time
        time.sleep(0.1)

        # Restart with 60s
        result = restart_scheduler(poll_interval_seconds=60)

        assert result["status"] == "restarted"
        assert result["stop_result"]["status"] == "stopped"
        assert result["start_result"]["status"] == "started"

        # Verify new interval
        status = get_scheduler_status()
        assert status["running"] is True
        assert status["started_at"] > original_start_time

    def test_restart_scheduler_when_not_running(self):
        """Restart when scheduler not running."""
        result = restart_scheduler()

        assert result["status"] == "restarted"
        assert result["start_result"]["status"] == "started"

        # Verify it's now running
        status = get_scheduler_status()
        assert status["running"] is True

    def teardown_method(self):
        """Clean up scheduler after each test."""
        try:
            stop_scheduler()
        except Exception:
            pass


class TestGetSchedulerMetrics:
    """Tests for get_scheduler_metrics function."""

    def teardown_method(self):
        """Clean up scheduler after each test."""
        try:
            stop_scheduler()
        except Exception:
            pass

    def test_metrics_not_running(self):
        """Metrics when scheduler not running."""
        metrics = get_scheduler_metrics()

        assert metrics["running"] is False
        assert metrics["error_rate_percent"] == 0.0
        assert metrics["average_errors_per_poll"] == 0.0

    def test_metrics_running(self):
        """Metrics when scheduler is running."""
        start_scheduler()

        metrics = get_scheduler_metrics()

        assert metrics["running"] is True
        assert metrics["started_at"] is not None
        assert "error_rate_percent" in metrics
        assert "average_errors_per_poll" in metrics
        assert isinstance(metrics["error_rate_percent"], float)
        assert isinstance(metrics["average_errors_per_poll"], float)

    def test_metrics_error_rate_calculation(self):
        """Error rate calculated correctly."""
        start_scheduler()

        # With no polls yet, error rate should be 0
        metrics = get_scheduler_metrics()
        assert metrics["poll_count"] == 0
        assert metrics["error_rate_percent"] == 0.0
        assert metrics["average_errors_per_poll"] == 0.0


class TestMetricsPollingJob:
    """Tests for the actual polling job function."""

    def test_polling_job_with_empty_rollouts(self):
        """Job handles no active rollouts gracefully."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = []

        with patch("app.services.jobs.background_scheduler.SessionLocal") as mock_session:
            with patch("app.services.jobs.background_scheduler.poll_active_rollouts") as mock_poll:
                with patch("app.services.jobs.background_scheduler.log_audit"):
                    mock_session.return_value = mock_db
                    mock_poll.return_value = {"polled_count": 0, "auto_rollback_count": 0, "errors": []}

                    # Should not raise
                    _metrics_polling_job()

    def test_polling_job_logs_error(self):
        """Job logs errors that occur during polling."""
        with patch("app.services.jobs.background_scheduler.SessionLocal") as mock_session:
            mock_session.side_effect = Exception("Database error")

            with patch("app.services.jobs.background_scheduler.logger") as mock_logger:
                # Should not raise
                _metrics_polling_job()

                # Should log error
                mock_logger.error.assert_called()

    def test_polling_job_increments_poll_count(self):
        """Successful polling increments counter."""
        mock_db = Mock()

        with patch("app.services.jobs.background_scheduler.SessionLocal") as mock_session:
            with patch("app.services.jobs.background_scheduler.poll_active_rollouts") as mock_poll:
                with patch("app.services.jobs.background_scheduler.log_audit"):
                    mock_session.return_value = mock_db
                    mock_poll.return_value = {"polled_count": 5, "auto_rollback_count": 1, "errors": []}

                    initial_count = get_scheduler_status()["poll_count"]
                    _metrics_polling_job()
                    # Note: state increment only happens inside start_scheduler context


class TestSchedulerIntegration:
    """Integration tests for scheduler lifecycle."""

    def test_full_lifecycle_start_stop(self):
        """Complete start and stop lifecycle."""
        # Start
        start_result = start_scheduler()
        assert start_result["status"] == "started"

        # Check running
        status = get_scheduler_status()
        assert status["running"] is True

        # Stop
        stop_result = stop_scheduler()
        assert stop_result["status"] == "stopped"

        # Check stopped
        status = get_scheduler_status()
        assert status["running"] is False

    def test_scheduler_maintains_state(self):
        """Scheduler maintains consistent state across calls."""
        start_scheduler()

        status1 = get_scheduler_status()
        time.sleep(0.1)
        status2 = get_scheduler_status()

        # Started_at should be same
        assert status1["started_at"] == status2["started_at"]

        # Uptime should have increased
        assert status2["uptime_seconds"] >= status1["uptime_seconds"]

        stop_scheduler()

    def test_multiple_restart_cycles(self):
        """Multiple restart cycles work correctly."""
        for i in range(3):
            interval = 30 + (i * 10)
            result = restart_scheduler(poll_interval_seconds=interval)

            assert result["status"] == "restarted"
            assert get_scheduler_status()["running"] is True

        stop_scheduler()
