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
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import json
import logging
import time
from typing import Awaitable, Callable, Dict, List, Set
import uuid
from datetime import datetime, UTC

from fastapi import WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.observability import metrics_registry
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

SUPPORTED_STREAM_TYPES = frozenset(
    {"summary", "metrics", "alerts", "comparison", "anomalies", "correlation"}
)


@dataclass(frozen=True)
class DashboardEvent:
    tenant_id: str
    stream_type: str
    data: dict
    timestamp: str


class RedisDashboardTransport:
    """Redis Pub/Sub transport and distributed stream lease for backend replicas."""

    def __init__(self, redis_url: str, channel: str = "sbs:dashboard:events") -> None:
        self.redis_url = redis_url
        self.channel = channel
        self.instance_id = str(uuid.uuid4())
        self.redis: Redis | None = None
        self.pubsub = None
        self.listener_task: asyncio.Task | None = None
        self.handler: Callable[[DashboardEvent], Awaitable[None]] | None = None
        self.running = False
        self.healthy = False

    async def start(self, handler: Callable[[DashboardEvent], Awaitable[None]]) -> None:
        if self.running:
            return
        self.handler = handler
        self.redis = Redis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
            health_check_interval=30,
        )
        await self.redis.ping()
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe(self.channel)
        self.running = True
        self.healthy = True
        metrics_registry.set_dashboard_transport_ready(True)
        self.listener_task = asyncio.create_task(self._listen(), name="dashboard-redis-pubsub")

    async def stop(self) -> None:
        self.running = False
        self.healthy = False
        metrics_registry.set_dashboard_transport_ready(False)
        if self.listener_task is not None:
            self.listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.listener_task
        self.listener_task = None
        await self._close_pubsub()
        if self.redis is not None:
            await self.redis.aclose()
        self.redis = None

    async def publish(self, event: DashboardEvent) -> None:
        if self.redis is None:
            raise RuntimeError("dashboard Redis transport is not started")
        payload = json.dumps(
            {
                "tenant_id": event.tenant_id,
                "stream_type": event.stream_type,
                "data": event.data,
                "timestamp": event.timestamp,
                "source_instance": self.instance_id,
            },
            separators=(",", ":"),
            default=str,
        )
        if len(payload.encode("utf-8")) > 1_000_000:
            raise ValueError("dashboard event exceeds 1 MB")
        await self.redis.publish(self.channel, payload)

    async def acquire_stream_lease(self, tenant_id: str, stream_type: str, ttl_seconds: int) -> bool:
        if self.redis is None:
            return False
        key = f"{self.channel}:lease:{tenant_id}:{stream_type}"
        return bool(await self.redis.set(key, self.instance_id, nx=True, ex=max(2, ttl_seconds)))

    async def consume_once(self, token_id: str, ttl_seconds: int) -> bool:
        if self.redis is None:
            return False
        key = f"{self.channel}:socket-token:{token_id}"
        return bool(await self.redis.set(key, self.instance_id, nx=True, ex=max(1, ttl_seconds)))

    async def _listen(self) -> None:
        retry_delay = 1.0
        while self.running:
            try:
                if self.pubsub is None:
                    if self.redis is None:
                        return
                    self.pubsub = self.redis.pubsub()
                    await self.pubsub.subscribe(self.channel)
                    self.healthy = True
                    metrics_registry.set_dashboard_transport_ready(True)
                    retry_delay = 1.0
                message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    await asyncio.sleep(0.05)
                    continue
                event = self._parse_event(message.get("data"))
                if event is not None and self.handler is not None:
                    await self.handler(event)
            except asyncio.CancelledError:
                raise
            except (RedisError, OSError, ValueError, TypeError) as exc:
                self.healthy = False
                metrics_registry.set_dashboard_transport_ready(False)
                logger.warning(
                    "dashboard_pubsub_listener_error",
                    extra={"error_type": exc.__class__.__name__, "retry_seconds": retry_delay},
                )
                await self._close_pubsub()
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)

    async def _close_pubsub(self) -> None:
        if self.pubsub is not None:
            with suppress(Exception):
                await self.pubsub.aclose()
        self.pubsub = None

    @staticmethod
    def _parse_event(raw: object) -> DashboardEvent | None:
        if not isinstance(raw, str):
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        tenant_id = str(payload.get("tenant_id") or "")
        stream_type = str(payload.get("stream_type") or "")
        data = payload.get("data")
        timestamp = str(payload.get("timestamp") or "")
        if not tenant_id or len(tenant_id) > 128 or stream_type not in SUPPORTED_STREAM_TYPES:
            return None
        if not isinstance(data, dict) or not timestamp:
            return None
        return DashboardEvent(tenant_id, stream_type, data, timestamp)


class DashboardWebSocketManager:
    """Manages WebSocket connections for real-time dashboard updates."""

    def __init__(self, *, max_connections_per_tenant: int = 200):
        # Active connections: tenant_id -> set of WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Connection subscriptions: track which data streams each connection wants
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
        # Broadcast queues for batching messages
        self.broadcast_queues: Dict[str, asyncio.Queue] = {}
        self.max_connections_per_tenant = max_connections_per_tenant
        self.transport: RedisDashboardTransport | None = None
        self._consumed_local_tokens: dict[str, float] = {}

    async def start_transport(self, transport: RedisDashboardTransport) -> None:
        self.transport = transport
        await transport.start(self._broadcast_event_local)

    async def stop_transport(self) -> None:
        if self.transport is not None:
            await self.transport.stop()
        self.transport = None

    def transport_ready(self) -> bool:
        return self.transport is None or self.transport.healthy

    async def connect(self, websocket: WebSocket, tenant_id: str) -> bool:
        """Register a new WebSocket connection."""
        if self.get_tenant_connection_count(tenant_id) >= self.max_connections_per_tenant:
            await websocket.close(code=1013, reason="Tenant WebSocket capacity reached")
            return False
        await websocket.accept()
        
        if tenant_id not in self.active_connections:
            self.active_connections[tenant_id] = set()
        
        self.active_connections[tenant_id].add(websocket)
        self.subscriptions[websocket] = set()
        metrics_registry.websocket_connected()
        
        logger.info(
            "websocket_connected",
            extra={
                "tenant_id": tenant_id,
                "tenant_connections": len(self.active_connections[tenant_id]),
            },
        )
        return True

    def disconnect(self, websocket: WebSocket, tenant_id: str):
        """Unregister a WebSocket connection."""
        was_connected = websocket in self.active_connections.get(tenant_id, set())
        if tenant_id in self.active_connections:
            self.active_connections[tenant_id].discard(websocket)
            
            if not self.active_connections[tenant_id]:
                del self.active_connections[tenant_id]
        
        self.subscriptions.pop(websocket, None)
        if was_connected:
            metrics_registry.websocket_disconnected()
            logger.info("websocket_disconnected", extra={"tenant_id": tenant_id})

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
            valid_streams = {item for item in stream_types if item in SUPPORTED_STREAM_TYPES}
            self.subscriptions[websocket].update(valid_streams)
            logger.info("websocket_subscribed", extra={"streams": sorted(valid_streams)})
            
            # Send confirmation
            await websocket.send_json({
                "type": "subscription_confirmed",
                "streams": sorted(self.subscriptions[websocket]),
                "timestamp": datetime.now(UTC).isoformat(),
            })

    async def unsubscribe(self, websocket: WebSocket, stream_types: List[str]):
        """Unsubscribe connection from specific data streams."""
        if websocket in self.subscriptions:
            valid_streams = {item for item in stream_types if item in SUPPORTED_STREAM_TYPES}
            self.subscriptions[websocket].difference_update(valid_streams)
            logger.info("websocket_unsubscribed", extra={"streams": sorted(valid_streams)})

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
        event = DashboardEvent(
            tenant_id=tenant_id,
            stream_type=stream_type,
            data=data,
            timestamp=datetime.now(UTC).isoformat(),
        )
        metrics_registry.dashboard_event_published()
        if self.transport is not None:
            try:
                await self.transport.publish(event)
                return
            except (RedisError, OSError, RuntimeError, ValueError):
                self.transport.healthy = False
                metrics_registry.set_dashboard_transport_ready(False)
                logger.exception("dashboard_pubsub_publish_failed", extra={"stream_type": stream_type})
        await self._broadcast_event_local(event)

    async def _broadcast_event_local(self, event: DashboardEvent) -> None:
        tenant_id = event.tenant_id
        stream_type = event.stream_type
        if tenant_id not in self.active_connections:
            return

        disconnected = set()
        for connection in self.active_connections[tenant_id]:
            if stream_type not in self.subscriptions.get(connection, set()):
                continue

            try:
                await connection.send_json({
                    "type": stream_type,
                    "data": event.data,
                    "timestamp": event.timestamp,
                })
            except Exception:
                logger.exception("websocket_broadcast_failed", extra={"stream_type": stream_type})
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
        except Exception:
            logger.exception("websocket_error_message_failed")

    async def acquire_stream_lease(self, tenant_id: str, stream_type: str, ttl_seconds: int) -> bool:
        if self.transport is None:
            return True
        try:
            return await self.transport.acquire_stream_lease(tenant_id, stream_type, ttl_seconds)
        except (RedisError, OSError):
            logger.exception("dashboard_stream_lease_failed", extra={"stream_type": stream_type})
            return False

    async def consume_socket_token(self, token_id: str, ttl_seconds: int) -> bool:
        if not token_id:
            return False
        if self.transport is not None:
            try:
                return await self.transport.consume_once(token_id, ttl_seconds)
            except (RedisError, OSError):
                logger.exception("websocket_token_consume_failed")
                return False

        now = time.monotonic()
        self._consumed_local_tokens = {
            item: expires_at for item, expires_at in self._consumed_local_tokens.items() if expires_at > now
        }
        if token_id in self._consumed_local_tokens:
            return False
        self._consumed_local_tokens[token_id] = now + max(1, ttl_seconds)
        return True

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
                    has_lease = await self.manager.acquire_stream_lease(
                        tenant_id,
                        stream_name,
                        max(2, interval_seconds),
                    )
                    if not has_lease:
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
        # Policy canary rollouts are platform policy records and currently do
        # not carry tenant_id. Tenant-owned health/alert data is scoped inside
        # dashboard_service.
        rollouts = (
            db.query(PolicyCanaryRollout.id)
            .filter(
                PolicyCanaryRollout.status.in_(("active", "in_progress")),
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
    connected = False
    try:
        connected = await ws_manager.connect(websocket, tenant_id)
        yield connected
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("websocket_unexpected_error", extra={"tenant_id": tenant_id})
    finally:
        if connected:
            ws_manager.disconnect(websocket, tenant_id)
