"""Unit tests for Stage 032: Real Metrics Infrastructure."""
from datetime import UTC, datetime
from unittest.mock import Mock, patch


from app.services.jobs.metrics_infrastructure import (
    store_metrics_history,
    update_metrics_snapshot,
    get_metrics_history,
    get_metrics_snapshot,
    get_metrics_trend,
    clean_old_metrics,
    SimulatedMetricsCollector,
)


class TestStoreMetricsHistory:
    """Tests for store_metrics_history function."""

    def test_store_metrics_history_minimal(self):
        """Store metrics with minimal fields."""
        mock_db = Mock()
        
        with patch("app.services.jobs.metrics_infrastructure.PolicyRolloutMetricsHistory") as mock_model:
            with patch("app.services.jobs.metrics_infrastructure.datetime") as mock_datetime:
                mock_datetime.now.return_value = datetime.now(UTC)
                mock_instance = Mock()
                mock_model.return_value = mock_instance
                
                result = store_metrics_history(
                    mock_db,
                    rollout_id="crl-1",
                    error_rate=0.5,
                )
                
                mock_db.add.assert_called_once()
                mock_db.commit.assert_called_once()

    def test_store_metrics_history_full(self):
        """Store metrics with all fields."""
        mock_db = Mock()
        
        with patch("app.services.jobs.metrics_infrastructure.PolicyRolloutMetricsHistory") as mock_model:
            with patch("app.services.jobs.metrics_infrastructure.datetime") as mock_datetime:
                mock_datetime.now.return_value = datetime.now(UTC)
                mock_instance = Mock()
                mock_model.return_value = mock_instance
                
                result = store_metrics_history(
                    mock_db,
                    rollout_id="crl-1",
                    error_rate=0.5,
                    latency_p99_ms=250.0,
                    throughput_eps=1000.0,
                    cpu_percent=50.0,
                    memory_percent=60.0,
                    request_count=5000,
                    source="prometheus",
                    collection_duration_ms=150,
                    raw_data={"query": "test"},
                )
                
                mock_db.add.assert_called_once()
                mock_db.commit.assert_called_once()

    def test_store_metrics_history_with_source(self):
        """Store metrics with different source."""
        mock_db = Mock()
        
        with patch("app.services.jobs.metrics_infrastructure.PolicyRolloutMetricsHistory") as mock_model:
            with patch("app.services.jobs.metrics_infrastructure.datetime"):
                mock_instance = Mock()
                mock_model.return_value = mock_instance
                
                store_metrics_history(
                    mock_db,
                    rollout_id="crl-1",
                    error_rate=0.5,
                    source="cloudwatch",
                )
                
                # Verify source was set
                call_kwargs = mock_model.call_args[1]
                assert call_kwargs["source"] == "cloudwatch"


class TestUpdateMetricsSnapshot:
    """Tests for update_metrics_snapshot function."""

    def test_update_snapshot_create_new(self):
        """Create new snapshot if doesn't exist."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter_by.return_value.first.return_value = None
        
        with patch("app.services.jobs.metrics_infrastructure.PolicyRolloutMetricsSnapshot") as mock_model:
            with patch("app.services.jobs.metrics_infrastructure.datetime") as mock_datetime:
                mock_datetime.now.return_value = datetime.now(UTC)
                mock_instance = Mock()
                mock_model.return_value = mock_instance
                
                update_metrics_snapshot(
                    mock_db,
                    rollout_id="crl-1",
                    error_rate=0.5,
                    error_rate_baseline=0.4,
                )
                
                mock_db.add.assert_called_once()
                mock_db.commit.assert_called_once()

    def test_update_snapshot_existing(self):
        """Update existing snapshot."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        
        # Mock existing snapshot
        existing = Mock()
        existing.error_rate = 0.4
        existing.latency_p99_ms = 240.0
        mock_query.filter_by.return_value.first.return_value = existing
        
        with patch("app.services.jobs.metrics_infrastructure.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime.now(UTC)
            
            update_metrics_snapshot(
                mock_db,
                rollout_id="crl-1",
                error_rate=0.5,
            )
            
            # Verify update occurred
            assert existing.error_rate == 0.5
            mock_db.commit.assert_called_once()

    def test_update_snapshot_calculates_trend(self):
        """Calculate trend compared to previous."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        
        # Mock existing snapshot with previous value
        existing = Mock()
        existing.error_rate = 0.4  # Numeric value, not Mock
        existing.latency_p99_ms = 240.0
        existing.rollout_id = "crl-1"
        mock_query.filter_by.return_value.first.return_value = existing
        
        with patch("app.services.jobs.metrics_infrastructure.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime.now(UTC)
            
            update_metrics_snapshot(
                mock_db,
                rollout_id="crl-1",
                error_rate=0.5,  # Increased from 0.4
            )
            
            # Verify trend calculated
            assert existing.error_rate_increasing is True
            assert existing.error_rate_previous == 0.4
            # (0.5 - 0.4) / 0.4 * 100 = 25% (approximately, accounting for float precision)
            assert abs(existing.error_rate_change_percent - 25.0) < 0.001


class TestGetMetricsHistory:
    """Tests for get_metrics_history function."""

    def test_get_history_all_records(self):
        """Retrieve all history records."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        
        records = [Mock() for _ in range(5)]
        mock_query.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = records
        
        result = get_metrics_history(mock_db, "crl-1", limit=100)
        
        assert len(result) == 5

    def test_get_history_with_time_window(self):
        """Filter history by time window."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        
        mock_filter = Mock()
        mock_query.filter_by.return_value = mock_filter
        mock_filter.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        
        result = get_metrics_history(mock_db, "crl-1", minutes_back=30)
        
        # Verify time filter was applied
        mock_filter.filter.assert_called_once()

    def test_get_history_respects_limit(self):
        """Respect limit parameter."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = []
        
        get_metrics_history(mock_db, "crl-1", limit=50)
        
        # Verify limit was applied
        mock_query.filter_by.return_value.order_by.return_value.limit.assert_called_once_with(50)


class TestGetMetricsSnapshot:
    """Tests for get_metrics_snapshot function."""

    def test_get_snapshot_exists(self):
        """Retrieve existing snapshot."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        
        snapshot = Mock()
        snapshot.rollout_id = "crl-1"
        snapshot.error_rate = 0.5
        mock_query.filter_by.return_value.first.return_value = snapshot
        
        result = get_metrics_snapshot(mock_db, "crl-1")
        
        assert result.rollout_id == "crl-1"
        assert result.error_rate == 0.5

    def test_get_snapshot_not_found(self):
        """Handle missing snapshot."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter_by.return_value.first.return_value = None
        
        result = get_metrics_snapshot(mock_db, "crl-1")
        
        assert result is None


class TestGetMetricsTrend:
    """Tests for get_metrics_trend function."""

    def test_get_trend_no_data(self):
        """Handle no historical data."""
        mock_db = Mock()
        
        with patch("app.services.jobs.metrics_infrastructure.get_metrics_history") as mock_get_history:
            mock_get_history.return_value = []
            
            result = get_metrics_trend(mock_db, "crl-1")
            
            assert result["data_points"] == 0
            assert result["error_rate_min"] is None
            assert result["error_rate_trend"] is None

    def test_get_trend_with_data(self):
        """Calculate trend from history."""
        mock_db = Mock()
        
        # Create mock history with trend (increasing)
        records = []
        for i in range(10):
            record = Mock()
            record.error_rate = 0.4 + (i * 0.01)  # Increasing from 0.4 to 0.49
            record.latency_p99_ms = 200.0 + (i * 10)  # Increasing from 200 to 290
            records.append(record)
        
        with patch("app.services.jobs.metrics_infrastructure.get_metrics_history") as mock_get_history:
            mock_get_history.return_value = records
            
            result = get_metrics_trend(mock_db, "crl-1", minutes_back=30)
            
            assert result["data_points"] == 10
            assert result["error_rate_min"] == 0.4
            assert result["error_rate_max"] == 0.49
            assert result["error_rate_trend"] == "up"

    def test_get_trend_stable(self):
        """Detect stable trend."""
        mock_db = Mock()
        
        # Create mock history with stable values
        records = []
        for i in range(10):
            record = Mock()
            record.error_rate = 0.45  # Constant
            record.latency_p99_ms = 250.0  # Constant
            records.append(record)
        
        with patch("app.services.jobs.metrics_infrastructure.get_metrics_history") as mock_get_history:
            mock_get_history.return_value = records
            
            result = get_metrics_trend(mock_db, "crl-1")
            
            assert result["error_rate_trend"] == "stable"


class TestCleanOldMetrics:
    """Tests for clean_old_metrics function."""

    def test_clean_old_metrics(self):
        """Delete metrics older than retention period."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        
        mock_query.filter.return_value.delete.return_value = 100
        
        result = clean_old_metrics(mock_db, days_to_keep=30)
        
        assert result == 100
        mock_db.commit.assert_called_once()

    def test_clean_old_metrics_custom_retention(self):
        """Use custom retention period."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value.delete.return_value = 50
        
        result = clean_old_metrics(mock_db, days_to_keep=7)
        
        assert result == 50


class TestSimulatedMetricsCollector:
    """Tests for SimulatedMetricsCollector."""

    def test_collect_metrics_returns_dict(self):
        """Collector returns metrics dict."""
        collector = SimulatedMetricsCollector()
        
        import asyncio
        result = asyncio.run(collector.collect_metrics("crl-1", "consumer-1"))
        
        assert "error_rate" in result
        assert "latency_p99_ms" in result
        assert "throughput_eps" in result
        assert isinstance(result["error_rate"], float)
        assert isinstance(result["latency_p99_ms"], float)
        assert isinstance(result["throughput_eps"], float)

    def test_collect_metrics_variation(self):
        """Simulated metrics vary slightly."""
        collector = SimulatedMetricsCollector()
        
        import asyncio
        results = [
            asyncio.run(collector.collect_metrics("crl-1", "consumer-1"))
            for _ in range(5)
        ]
        
        # At least some variation in results
        error_rates = [r["error_rate"] for r in results]
        assert len(set(error_rates)) > 1  # Not all the same


class TestMetricsIntegration:
    """Integration tests for metrics infrastructure."""

    def test_full_metrics_lifecycle(self):
        """Complete store-retrieve-analyze lifecycle."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        
        # Store history
        with patch("app.services.jobs.metrics_infrastructure.PolicyRolloutMetricsHistory") as mock_history:
            with patch("app.services.jobs.metrics_infrastructure.datetime") as mock_datetime:
                mock_datetime.now.return_value = datetime.now(UTC)
                mock_instance = Mock()
                mock_history.return_value = mock_instance
                store_metrics_history(
                    mock_db,
                    rollout_id="crl-1",
                    error_rate=0.5,
                )
        
        # Update snapshot
        mock_query.filter_by.return_value.first.return_value = None
        with patch("app.services.jobs.metrics_infrastructure.PolicyRolloutMetricsSnapshot") as mock_snapshot:
            with patch("app.services.jobs.metrics_infrastructure.datetime") as mock_datetime:
                mock_datetime.now.return_value = datetime.now(UTC)
                mock_instance = Mock()
                mock_snapshot.return_value = mock_instance
                update_metrics_snapshot(
                    mock_db,
                    rollout_id="crl-1",
                    error_rate=0.5,
                )
        
        # Verify calls made
        assert mock_db.add.call_count >= 1
        assert mock_db.commit.call_count >= 2
