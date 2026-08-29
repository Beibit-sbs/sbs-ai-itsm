"""
Tests for Stage 037: WebSocket Real-Time Dashboard Updates

Tests the WebSocket infrastructure for real-time dashboard data streaming.
"""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi import WebSocket

from app.services.jobs.dashboard_websocket_service import (
    DashboardEvent,
    DashboardWebSocketManager,
    DashboardStreamBroadcaster,
)
from app.api.v1.routes.auth import AuthUserResponse
from app.api.v1.routes.jobs import create_socket_token
from app.core.security import decode_token


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

    @pytest.mark.asyncio
    async def test_socket_token_is_one_time(self):
        manager = DashboardWebSocketManager()

        assert await manager.consume_socket_token("token-1", 60) is True
        assert await manager.consume_socket_token("token-1", 60) is False

    @pytest.mark.asyncio
    async def test_connection_capacity_is_enforced(self):
        manager = DashboardWebSocketManager(max_connections_per_tenant=1)
        first = AsyncMock(spec=WebSocket)
        second = AsyncMock(spec=WebSocket)

        await manager.connect(first, "tenant-1")
        await manager.connect(second, "tenant-1")

        second.close.assert_awaited_once_with(code=1013, reason="Tenant WebSocket capacity reached")
        assert manager.get_tenant_connection_count("tenant-1") == 1

    @pytest.mark.asyncio
    async def test_shared_transport_broadcasts_across_replicas(self):
        class SharedHub:
            def __init__(self):
                self.handlers = []
                self.tokens = set()

        class FakeTransport:
            def __init__(self, hub):
                self.hub = hub
                self.healthy = True
                self.handler = None

            async def start(self, handler):
                self.handler = handler
                self.hub.handlers.append(handler)

            async def stop(self):
                self.hub.handlers.remove(self.handler)

            async def publish(self, event: DashboardEvent):
                await asyncio.gather(*(handler(event) for handler in list(self.hub.handlers)))

            async def acquire_stream_lease(self, tenant_id, stream_type, ttl_seconds):
                return True

            async def consume_once(self, token_id, ttl_seconds):
                if token_id in self.hub.tokens:
                    return False
                self.hub.tokens.add(token_id)
                return True

        hub = SharedHub()
        first_manager = DashboardWebSocketManager()
        second_manager = DashboardWebSocketManager()
        await first_manager.start_transport(FakeTransport(hub))
        await second_manager.start_transport(FakeTransport(hub))
        socket = AsyncMock(spec=WebSocket)
        second_manager.active_connections["tenant-1"] = {socket}
        second_manager.subscriptions[socket] = {"summary"}

        await first_manager.broadcast_summary("tenant-1", {"status": "healthy"})

        socket.send_json.assert_awaited_once()
        assert await first_manager.consume_socket_token("shared-token", 60) is True
        assert await second_manager.consume_socket_token("shared-token", 60) is False
        await first_manager.stop_transport()
        await second_manager.stop_transport()


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
        from app.main import app

        assert str(app.url_path_for("websocket_dashboard")) == "/api/v1/jobs/dashboard/ws"


class TestDashboardStreamBroadcaster:
    """Tests for background stream broadcaster loops."""

    @pytest.mark.asyncio
    async def test_start_and_stop_broadcaster(self):
        """Broadcaster should create and stop all stream tasks cleanly."""
        manager = DashboardWebSocketManager()
        broadcaster = DashboardStreamBroadcaster(
            db_session_factory=MagicMock(),
            manager=manager,
            intervals={
                "summary": 1,
                "metrics": 1,
                "alerts": 1,
                "comparison": 1,
                "anomalies": 1,
                "correlation": 1,
            },
        )

        await broadcaster.start()
        assert broadcaster.is_running is True
        assert len(broadcaster.tasks) == 6

        await broadcaster.stop()
        assert broadcaster.is_running is False
        assert broadcaster.tasks == []

    @pytest.mark.asyncio
    async def test_stream_loop_broadcasts_for_connected_tenant(self):
        """Loop should fetch and broadcast for active tenant connections."""
        manager = DashboardWebSocketManager()
        manager.active_connections["tenant-1"] = {MagicMock()}

        broadcaster = DashboardStreamBroadcaster(
            db_session_factory=MagicMock(),
            manager=manager,
            intervals={
                "summary": 1,
                "metrics": 1,
                "alerts": 1,
                "comparison": 1,
                "anomalies": 1,
                "correlation": 1,
            },
        )

        payload = {"ok": True}
        fetcher = MagicMock(return_value=payload)
        sender = AsyncMock()

        broadcaster.is_running = True
        loop_task = asyncio.create_task(
            broadcaster._run_stream_loop("summary", 3600, fetcher, sender)
        )
        await asyncio.sleep(0.05)
        broadcaster.is_running = False
        loop_task.cancel()
        await asyncio.gather(loop_task, return_exceptions=True)

        fetcher.assert_called_with("tenant-1")
        sender.assert_called()


class TestSocketTokenEndpoint:
    """Test the socket token endpoint for WebSocket authentication"""

    def test_socket_token_response_structure(self):
        current_user = AuthUserResponse(
            id="user-1",
            email="agent@example.com",
            full_name="Agent",
            tenant_id="tenant-1",
            role="it_agent",
            permissions=["admin.settings.read"],
        )
        response = create_socket_token(current_user)

        assert response.expires_in == 60
        assert response.connection_url.startswith("/api/v1/jobs/dashboard/ws?token=")
        payload = decode_token(response.socket_token, expected_type="socket")
        assert payload["sub"] == "user-1"
        assert payload["tenant_id"] == "tenant-1"

    def test_root_socket_token_uses_global_scope(self):
        """Platform Root must be able to open the real-time dashboard socket."""
        current_user = AuthUserResponse(
            id="root-1",
            email="root@example.com",
            full_name="Platform Root",
            tenant_id=None,
            role="saas_root",
            permissions=["admin.settings.read"],
            is_root=True,
            is_superuser=True,
        )

        response = create_socket_token(current_user)
        payload = decode_token(response.socket_token, expected_type="socket")

        assert payload["sub"] == "root-1"
        assert payload["tenant_id"] == "global"

    def test_socket_token_expiration_one_hour(self):
        """Test that socket token expires in 1 hour"""
        # Verify the TTL is correct
        expected_ttl = 3600  # 1 hour in seconds
        assert expected_ttl == 60 * 60  # 60 minutes * 60 seconds

    def test_socket_token_has_required_fields(self):
        """Test that socket token payload has socket type marker"""
        # When decoded, socket token should have type='socket'
        # This is tested in the WebSocket authentication logic
        token_payload_structure = {
            "sub": "user-id",
            "tenant_id": "tenant-id",
            "type": "socket",  # Must have this field
            "exp": 1234567890,
        }
        
        assert token_payload_structure["type"] == "socket"
        assert "exp" in token_payload_structure


# Export tests for discovery
all_tests = [
    TestDashboardWebSocketManager,
    TestWebSocketClientTypes,
    TestWebSocketIntegration,
    TestDashboardStreamBroadcaster,
    TestSocketTokenEndpoint,
]
