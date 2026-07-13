"""
WebSocket service for real-time dashboard updates.

Provides server-sent data streams for:
- Dashboard summary (active rollouts, health score, alerts, anomalies)
- Metrics timelines (error rate, latency, throughput, cpu, memory)
- Active alerts (with real-time severity filtering)
- Rollout comparisons (up to 10 concurrent rollouts)
- Anomaly detection timeline (with resolution tracking)
- Metric correlation matrix (Pearson coefficients)

Uses FastAPI WebSocket for bidirectional communication with smart batching
to reduce message overhead.
"""

import asyncio
import logging
from typing import Callable, Dict, List, Set
from datetime import datetime, UTC
from contextlib import asynccontextmanager

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.services.jobs.dashboard_service import (
    get_dashboard_summary,
    get_metrics_timeline,
    get_active_alerts,
    get_rollout_comparison,
    get_anomaly_timeline,
    get_metric_correlation_matrix,
)
from app.db.session import SessionLocal
from app.models.policy_canary_rollout import PolicyCanaryRollout

logger = logging.getLogger(__name__)


class DashboardWebSocketManager:
    """Manages WebSocket connections for real-time dashboard updates."""

    def __init__(self):
        # Active connections: tenant_id -> set of WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Connection subscriptions: track which data streams each connection wants
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
        # Broadcast queues for batching messages
        self.broadcast_queues: Dict[str, asyncio.Queue] = {}

    async def connect(self, websocket: WebSocket, tenant_id: str):
        """Register a new WebSocket connection."""
        await websocket.accept()
        
        if tenant_id not in self.active_connections:
            self.active_connections[tenant_id] = set()
        
        self.active_connections[tenant_id].add(websocket)
        self.subscriptions[websocket] = set()
        
        logger.info(f"WebSocket connected for tenant {tenant_id}. "
                   f"Active connections: {len(self.active_connections[tenant_id])}")

    def disconnect(self, websocket: WebSocket, tenant_id: str):
        """Unregister a WebSocket connection."""
        if tenant_id in self.active_connections:
            self.active_connections[tenant_id].discard(websocket)
            
            if not self.active_connections[tenant_id]:
                del self.active_connections[tenant_id]
        
        self.subscriptions.pop(websocket, None)
        logger.info(f"WebSocket disconnected for tenant {tenant_id}")

    async def subscribe(self, websocket: WebSocket, stream_types: List[str]):
        """Subscribe connection to specific data streams.
        
        Args:
            websocket: WebSocket connection
            stream_types: List of stream types:
                - 'summary' (30s updates)
                - 'metrics' (30s updates)
                - 'alerts' (30s updates)
                - 'comparison' (60s updates)
                - 'anomalies' (60s updates)
                - 'correlation' (120s updates)
        """
        if websocket in self.subscriptions:
            self.subscriptions[websocket].update(stream_types)
            logger.info(f"WebSocket subscribed to: {stream_types}")
            
            # Send confirmation
            await websocket.send_json({
                "type": "subscription_confirmed",
                "streams": list(self.subscriptions[websocket]),
                "timestamp": datetime.now(UTC).isoformat(),
            })

    async def unsubscribe(self, websocket: WebSocket, stream_types: List[str]):
        """Unsubscribe connection from specific data streams."""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].difference_update(stream_types)
            logger.info(f"WebSocket unsubscribed from: {stream_types}")

    async def broadcast_summary(self, tenant_id: str, summary_data: dict):
        """Broadcast dashboard summary to all subscribers in tenant."""
        await self._broadcast_to_tenant(
            tenant_id,
            "summary",
            summary_data
        )

    async def broadcast_metrics(self, tenant_id: str, metrics_data: dict):
        """Broadcast metrics timeline to all subscribers in tenant."""
        await self._broadcast_to_tenant(
            tenant_id,
            "metrics",
            metrics_data
        )

    async def broadcast_alerts(self, tenant_id: str, alerts_data: dict):
        """Broadcast active alerts to all subscribers in tenant."""
        await self._broadcast_to_tenant(
            tenant_id,
            "alerts",
            alerts_data
        )

    async def broadcast_comparison(self, tenant_id: str, comparison_data: dict):
        """Broadcast rollout comparison to all subscribers in tenant."""
        await self._broadcast_to_tenant(
            tenant_id,
            "comparison",
            comparison_data
        )

    async def broadcast_anomalies(self, tenant_id: str, anomalies_data: dict):
        """Broadcast anomaly timeline to all subscribers in tenant."""
        await self._broadcast_to_tenant(
            tenant_id,
            "anomalies",
            anomalies_data
        )

    async def broadcast_correlation(self, tenant_id: str, correlation_data: dict):
        """Broadcast correlation matrix to all subscribers in tenant."""
        await self._broadcast_to_tenant(
            tenant_id,
            "correlation",
            correlation_data
        )

    async def _broadcast_to_tenant(self, tenant_id: str, stream_type: str, data: dict):
        """Internal method to broadcast to all interested connections in a tenant."""
        if tenant_id not in self.active_connections:
            return

        disconnected = set()
        for connection in self.active_connections[tenant_id]:
            if stream_type not in self.subscriptions.get(connection, set()):
                continue

            try:
                await connection.send_json({
                    "type": stream_type,
                    "data": data,
                    "timestamp": datetime.now(UTC).isoformat(),
                })
            except Exception as e:
                logger.error(f"Error broadcasting to WebSocket: {e}")
                disconnected.add(connection)

        # Clean up disconnected connections
        for connection in disconnected:
            self.active_connections[tenant_id].discard(connection)
            self.subscriptions.pop(connection, None)

    async def send_error(self, websocket: WebSocket, error_message: str):
        """Send error message to specific connection."""
        try:
            await websocket.send_json({
                "type": "error",
                "message": error_message,
                "timestamp": datetime.now(UTC).isoformat(),
            })
        except Exception as e:
            logger.error(f"Error sending error message: {e}")

    def get_tenant_connection_count(self, tenant_id: str) -> int:
        """Get number of active connections for a tenant."""
        return len(self.active_connections.get(tenant_id, set()))


# Global WebSocket manager instance
ws_manager = DashboardWebSocketManager()


class DashboardStreamBroadcaster:
    """Handles continuous streaming of dashboard data to WebSocket clients.
    
    Runs background tasks that poll dashboard service at regular intervals
    and broadcast updates to subscribed clients.
    """

    def __init__(
        self,
        db_session_factory: Callable[[], Session] = SessionLocal,
        manager: DashboardWebSocketManager = ws_manager,
        intervals: Dict[str, int] | None = None,
    ):
        self.db_session_factory = db_session_factory
        self.manager = manager
        self.is_running = False
        self.tasks: List[asyncio.Task] = []
        self.intervals = intervals or {
            "summary": 30,
            "metrics": 30,
            "alerts": 30,
            "comparison": 60,
            "anomalies": 60,
            "correlation": 120,
        }

    async def start(self):
        """Start background broadcast loops for all active tenant connections."""
        if self.is_running:
            return

        self.is_running = True
        self.tasks = [
            asyncio.create_task(
                self._run_stream_loop("summary", self.intervals["summary"], self._fetch_summary, self.manager.broadcast_summary)
            ),
            asyncio.create_task(
                self._run_stream_loop("metrics", self.intervals["metrics"], self._fetch_metrics, self.manager.broadcast_metrics)
            ),
            asyncio.create_task(
                self._run_stream_loop("alerts", self.intervals["alerts"], self._fetch_alerts, self.manager.broadcast_alerts)
            ),
            asyncio.create_task(
                self._run_stream_loop("comparison", self.intervals["comparison"], self._fetch_comparison, self.manager.broadcast_comparison)
            ),
            asyncio.create_task(
                self._run_stream_loop("anomalies", self.intervals["anomalies"], self._fetch_anomalies, self.manager.broadcast_anomalies)
            ),
            asyncio.create_task(
                self._run_stream_loop("correlation", self.intervals["correlation"], self._fetch_correlation, self.manager.broadcast_correlation)
            ),
        ]

        logger.info("Dashboard stream broadcaster started")

    async def stop(self):
        """Stop all background broadcast loops."""
        self.is_running = False

        for task in self.tasks:
            task.cancel()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

        self.tasks = []
        logger.info("Dashboard stream broadcaster stopped")

    async def _run_stream_loop(
        self,
        stream_name: str,
        interval_seconds: int,
        fetcher: Callable[[str], dict],
        broadcaster: Callable[[str, dict], asyncio.Future],
    ):
        while self.is_running:
            try:
                tenant_ids = list(self.manager.active_connections.keys())
                for tenant_id in tenant_ids:
                    if self.manager.get_tenant_connection_count(tenant_id) == 0:
                        continue
                    payload = fetcher(tenant_id)
                    await broadcaster(tenant_id, payload)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in %s broadcast loop: %s", stream_name, exc)

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

    def _get_active_rollout_ids(self, db: Session, tenant_id: str, limit: int = 10) -> List[str]:
        rollouts = (
            db.query(PolicyCanaryRollout.id)
            .filter(
                PolicyCanaryRollout.tenant_id == tenant_id,
                PolicyCanaryRollout.status == "active",
            )
            .limit(limit)
            .all()
        )
        return [row[0] for row in rollouts]

    def _fetch_summary(self, tenant_id: str) -> dict:
        with self.db_session_factory() as db:
            return get_dashboard_summary(db, tenant_id)

    def _fetch_metrics(self, tenant_id: str) -> dict:
        with self.db_session_factory() as db:
            rollout_ids = self._get_active_rollout_ids(db, tenant_id, limit=1)
            if not rollout_ids:
                return {
                    "rollout_id": None,
                    "metric_type": "error_rate",
                    "timestamps": [],
                    "values": [],
                    "data_points": 0,
                    "statistics": {},
                }
            return get_metrics_timeline(db, tenant_id, rollout_ids[0], minutes_back=60, metric_type="error_rate")

    def _fetch_alerts(self, tenant_id: str) -> dict:
        with self.db_session_factory() as db:
            return get_active_alerts(db, tenant_id, severity_filter=None, limit=50)

    def _fetch_comparison(self, tenant_id: str) -> dict:
        with self.db_session_factory() as db:
            rollout_ids = self._get_active_rollout_ids(db, tenant_id, limit=10)
            if not rollout_ids:
                return {"comparison": [], "count": 0}
            return get_rollout_comparison(db, tenant_id, rollout_ids)

    def _fetch_anomalies(self, tenant_id: str) -> dict:
        with self.db_session_factory() as db:
            return get_anomaly_timeline(db, tenant_id, rollout_id=None, minutes_back=1440)

    def _fetch_correlation(self, tenant_id: str) -> dict:
        with self.db_session_factory() as db:
            rollout_ids = self._get_active_rollout_ids(db, tenant_id, limit=1)
            if not rollout_ids:
                return {
                    "rollout_id": None,
                    "correlation_matrix": {},
                    "metric_count": 0,
                    "time_window_minutes": 60,
                }
            return get_metric_correlation_matrix(db, tenant_id, rollout_ids[0], time_window_minutes=60)


# Global broadcaster instance started/stopped by app lifecycle
dashboard_stream_broadcaster = DashboardStreamBroadcaster()


# Connection lifecycle management
@asynccontextmanager
async def managed_websocket(websocket: WebSocket, tenant_id: str):
    """Context manager for WebSocket lifecycle."""
    try:
        await ws_manager.connect(websocket, tenant_id)
        yield
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, tenant_id)
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket: {e}")
        ws_manager.disconnect(websocket, tenant_id)
