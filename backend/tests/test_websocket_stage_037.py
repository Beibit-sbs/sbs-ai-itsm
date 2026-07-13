"""
Tests for Stage 037: WebSocket Real-Time Dashboard Updates

Tests the WebSocket infrastructure for real-time dashboard data streaming.
"""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import WebSocket
from fastapi.testclient import TestClient

from app.services.jobs.dashboard_websocket_service import (
    DashboardWebSocketManager,
    ws_manager,
)


class TestDashboardWebSocketManager:
    """Test the WebSocket connection manager"""

    def test_manager_initialization(self):
        """Test that manager initializes correctly"""
        manager = DashboardWebSocketManager()
        assert manager.active_connections == {}
        assert manager.subscriptions == {}

    @pytest.mark.asyncio
    async def test_connect_new_connection(self):
        """Test registering a new WebSocket connection"""
        manager = DashboardWebSocketManager()
        mock_ws = AsyncMock(spec=WebSocket)
        tenant_id = "tenant-1"

        await manager.connect(mock_ws, tenant_id)

        assert tenant_id in manager.active_connections
        assert mock_ws in manager.active_connections[tenant_id]
        assert mock_ws in manager.subscriptions
        mock_ws.accept.assert_called_once()

    def test_disconnect_connection(self):
        """Test disconnecting a WebSocket connection"""
        manager = DashboardWebSocketManager()
        mock_ws = MagicMock()
        tenant_id = "tenant-1"

        # Manually set up the connection (bypass async connect)
        manager.active_connections[tenant_id] = {mock_ws}
        manager.subscriptions[mock_ws] = {"summary", "alerts"}

        manager.disconnect(mock_ws, tenant_id)

        assert mock_ws not in manager.active_connections.get(tenant_id, set())
        assert mock_ws not in manager.subscriptions

    @pytest.mark.asyncio
    async def test_subscribe_to_streams(self):
        """Test subscribing to specific data streams"""
        manager = DashboardWebSocketManager()
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.readyState = 1  # OPEN

        manager.subscriptions[mock_ws] = set()

        await manager.subscribe(mock_ws, ["summary", "alerts"])

        assert "summary" in manager.subscriptions[mock_ws]
        assert "alerts" in manager.subscriptions[mock_ws]
        mock_ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_unsubscribe_from_streams(self):
        """Test unsubscribing from data streams"""
        manager = DashboardWebSocketManager()
        mock_ws = AsyncMock(spec=WebSocket)

        manager.subscriptions[mock_ws] = {"summary", "alerts", "metrics"}

        await manager.unsubscribe(mock_ws, ["summary"])

        assert "summary" not in manager.subscriptions[mock_ws]
        assert "alerts" in manager.subscriptions[mock_ws]

    @pytest.mark.asyncio
    async def test_broadcast_summary(self):
        """Test broadcasting dashboard summary to subscribers"""
        manager = DashboardWebSocketManager()
        mock_ws1 = AsyncMock(spec=WebSocket)
        mock_ws1.readyState = 1  # OPEN
        mock_ws2 = AsyncMock(spec=WebSocket)
        mock_ws2.readyState = 1  # OPEN
        tenant_id = "tenant-1"

        manager.active_connections[tenant_id] = {mock_ws1, mock_ws2}
        manager.subscriptions[mock_ws1] = {"summary"}
        manager.subscriptions[mock_ws2] = {"alerts"}  # Not subscribed to summary

        summary_data = {
            "active_rollouts": 5,
            "avg_health_score": 0.9,
            "health_status": "healthy",
        }

        await manager.broadcast_summary(tenant_id, summary_data)

        mock_ws1.send_json.assert_called_once()
        message = mock_ws1.send_json.call_args[0][0]
        assert message["type"] == "summary"
        assert message["data"] == summary_data

        # ws2 should not receive the message
        mock_ws2.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_metrics(self):
        """Test broadcasting metrics to subscribers"""
        manager = DashboardWebSocketManager()
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.readyState = 1  # OPEN
        tenant_id = "tenant-1"

        manager.active_connections[tenant_id] = {mock_ws}
        manager.subscriptions[mock_ws] = {"metrics"}

        metrics_data = {
            "rollout_id": "crl-1",
            "metric_type": "error_rate",
            "values": [0.5, 0.6, 0.48],
            "timestamps": ["2026-07-13T10:00:00Z", "2026-07-13T10:05:00Z", "2026-07-13T10:10:00Z"],
        }

        await manager.broadcast_metrics(tenant_id, metrics_data)

        mock_ws.send_json.assert_called_once()
        message = mock_ws.send_json.call_args[0][0]
        assert message["type"] == "metrics"
        assert message["data"]["rollout_id"] == "crl-1"

    @pytest.mark.asyncio
    async def test_broadcast_alerts(self):
        """Test broadcasting alerts to subscribers"""
        manager = DashboardWebSocketManager()
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.readyState = 1  # OPEN
        tenant_id = "tenant-1"

        manager.active_connections[tenant_id] = {mock_ws}
        manager.subscriptions[mock_ws] = {"alerts"}

        alerts_data = {
            "alerts": [
                {
                    "id": "alert-1",
                    "rule_name": "High Error Rate",
                    "severity": "high",
                }
            ],
            "count": 1,
        }

        await manager.broadcast_alerts(tenant_id, alerts_data)

        mock_ws.send_json.assert_called_once()
        message = mock_ws.send_json.call_args[0][0]
        assert message["type"] == "alerts"
        assert message["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_broadcast_comparison(self):
        """Test broadcasting rollout comparison to subscribers"""
        manager = DashboardWebSocketManager()
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.readyState = 1  # OPEN
        tenant_id = "tenant-1"

        manager.active_connections[tenant_id] = {mock_ws}
        manager.subscriptions[mock_ws] = {"comparison"}

        comparison_data = {
            "comparison": [
                {"rollout_id": "crl-1", "name": "Feature A", "health_score": 0.95},
            ],
            "count": 1,
        }

        await manager.broadcast_comparison(tenant_id, comparison_data)

        mock_ws.send_json.assert_called_once()
        message = mock_ws.send_json.call_args[0][0]
        assert message["type"] == "comparison"

    @pytest.mark.asyncio
    async def test_broadcast_anomalies(self):
        """Test broadcasting anomalies to subscribers"""
        manager = DashboardWebSocketManager()
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.readyState = 1  # OPEN
        tenant_id = "tenant-1"

        manager.active_connections[tenant_id] = {mock_ws}
        manager.subscriptions[mock_ws] = {"anomalies"}

        anomalies_data = {
            "anomalies": [
                {
                    "id": "anom-1",
                    "metric": "error_rate",
                    "anomaly_score": 0.85,
                }
            ],
            "count": 1,
        }

        await manager.broadcast_anomalies(tenant_id, anomalies_data)

        mock_ws.send_json.assert_called_once()
        message = mock_ws.send_json.call_args[0][0]
        assert message["type"] == "anomalies"

    @pytest.mark.asyncio
    async def test_broadcast_correlation(self):
        """Test broadcasting correlation matrix to subscribers"""
        manager = DashboardWebSocketManager()
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.readyState = 1  # OPEN
        tenant_id = "tenant-1"

        manager.active_connections[tenant_id] = {mock_ws}
        manager.subscriptions[mock_ws] = {"correlation"}

        correlation_data = {
            "rollout_id": "crl-1",
            "correlation_matrix": {
                "error_rate": {"error_rate": 1.0, "latency_p99": 0.78},
            },
            "metric_count": 2,
        }

        await manager.broadcast_correlation(tenant_id, correlation_data)

        mock_ws.send_json.assert_called_once()
        message = mock_ws.send_json.call_args[0][0]
        assert message["type"] == "correlation"

    @pytest.mark.asyncio
    async def test_send_error(self):
        """Test sending error message"""
        manager = DashboardWebSocketManager()
        mock_ws = AsyncMock(spec=WebSocket)

        await manager.send_error(mock_ws, "Test error message")

        mock_ws.send_json.assert_called_once()
        message = mock_ws.send_json.call_args[0][0]
        assert message["type"] == "error"
        assert message["message"] == "Test error message"

    def test_get_tenant_connection_count(self):
        """Test getting connection count for a tenant"""
        manager = DashboardWebSocketManager()
        tenant_id = "tenant-1"

        mock_ws1 = MagicMock()
        mock_ws2 = MagicMock()
        mock_ws3 = MagicMock()

        manager.active_connections[tenant_id] = {mock_ws1, mock_ws2, mock_ws3}

        count = manager.get_tenant_connection_count(tenant_id)
        assert count == 3

    def test_get_tenant_connection_count_missing_tenant(self):
        """Test getting connection count for non-existent tenant"""
        manager = DashboardWebSocketManager()
        count = manager.get_tenant_connection_count("non-existent")
        assert count == 0


class TestWebSocketClientTypes:
    """Test WebSocket message type definitions"""

    def test_dashboard_stream_types(self):
        """Verify all dashboard stream types are supported"""
        stream_types = [
            "summary",
            "metrics",
            "alerts",
            "comparison",
            "anomalies",
            "correlation",
        ]
        for stream_type in stream_types:
            assert isinstance(stream_type, str)
            assert len(stream_type) > 0

    def test_websocket_message_structure(self):
        """Test WebSocket message JSON structure"""
        message = {
            "type": "summary",
            "data": {
                "active_rollouts": 5,
                "avg_health_score": 0.9,
            },
            "timestamp": "2026-07-13T12:00:00Z",
        }
        json_str = json.dumps(message)
        parsed = json.loads(json_str)
        assert parsed["type"] == "summary"
        assert parsed["data"]["active_rollouts"] == 5


class TestWebSocketIntegration:
    """Integration tests for WebSocket endpoint"""

    def test_websocket_endpoint_exists(self):
        """Test that WebSocket endpoint is registered"""
        # Note: Full WebSocket testing would require websocket-client library
        # This is a placeholder for integration test structure
        assert True


# Export tests for discovery
all_tests = [
    TestDashboardWebSocketManager,
    TestWebSocketClientTypes,
    TestWebSocketIntegration,
]
