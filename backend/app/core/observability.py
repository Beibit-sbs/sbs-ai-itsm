from __future__ import annotations

from collections import defaultdict
import json
import logging
import re
import threading
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.context import get_correlation_id


_STANDARD_LOG_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}
_SENSITIVE_KEY_PARTS = ("authorization", "cookie", "credential", "password", "secret", "token", "api_key")
_URL_CREDENTIALS = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@\s]+)@")
_BEARER_TOKEN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/]+=*")


def _sanitize_text(value: str) -> str:
    value = _URL_CREDENTIALS.sub(r"\1<redacted>@", value)
    return _BEARER_TOKEN.sub(r"\1<redacted>", value)


def _sanitize_value(key: str, value: Any) -> Any:
    normalized_key = key.lower()
    if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return "<redacted>"
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, dict):
        return {str(item_key): _sanitize_value(str(item_key), item_value) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(key, item) for item in value]
    return value


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": _sanitize_text(str(getattr(record, "event", record.getMessage()))),
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id:
            payload["correlation_id"] = correlation_id
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update({str(key): _sanitize_value(str(key), value) for key, value in fields.items()})
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_KEYS or key in {"correlation_id", "event", "fields"}:
                continue
            payload[key] = _sanitize_value(key, value)
        if record.exc_info:
            payload["exception"] = _sanitize_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.name = "sbs-json"
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [existing for existing in root.handlers if existing.name != "sbs-json"]
    root.addHandler(handler)
    root.setLevel(level.upper())


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    logger.log(
        level,
        event,
        extra={
            "event": event,
            "correlation_id": get_correlation_id(),
            "fields": fields,
        },
    )


class MetricsRegistry:
    _DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self._duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self._duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)
        self._in_progress = 0
        self._websocket_connections = 0
        self._dashboard_events_total = 0
        self._dashboard_transport_ready = 1
        self._alertmanager_events: dict[str, int] = defaultdict(int)
        self.process_started_at = time.time()

    def request_started(self) -> None:
        with self._lock:
            self._in_progress += 1

    def request_finished(self, method: str, path: str, status_code: int, duration: float) -> None:
        key = (method, path)
        with self._lock:
            self._in_progress = max(0, self._in_progress - 1)
            self._requests[(method, path, status_code)] += 1
            self._duration_sum[key] += duration
            self._duration_count[key] += 1
            for boundary in self._DURATION_BUCKETS:
                if duration <= boundary:
                    self._duration_buckets[(method, path, boundary)] += 1

    def websocket_connected(self) -> None:
        with self._lock:
            self._websocket_connections += 1

    def websocket_disconnected(self) -> None:
        with self._lock:
            self._websocket_connections = max(0, self._websocket_connections - 1)

    def dashboard_event_published(self) -> None:
        with self._lock:
            self._dashboard_events_total += 1

    def set_dashboard_transport_ready(self, ready: bool) -> None:
        with self._lock:
            self._dashboard_transport_ready = int(ready)

    def alertmanager_event_received(self, alert_status: str) -> None:
        with self._lock:
            self._alertmanager_events[alert_status] += 1

    def render_prometheus(self) -> str:
        with self._lock:
            requests = dict(self._requests)
            duration_sum = dict(self._duration_sum)
            duration_count = dict(self._duration_count)
            duration_buckets = dict(self._duration_buckets)
            in_progress = self._in_progress
            websocket_connections = self._websocket_connections
            dashboard_events_total = self._dashboard_events_total
            dashboard_transport_ready = self._dashboard_transport_ready
            alertmanager_events = dict(self._alertmanager_events)

        lines = [
            "# HELP sbs_http_requests_total Total HTTP requests.",
            "# TYPE sbs_http_requests_total counter",
        ]
        for (method, path, status_code), value in sorted(requests.items()):
            lines.append(
                f'sbs_http_requests_total{{method="{_escape(method)}",path="{_escape(path)}",status="{status_code}"}} {value}'
            )
        lines.extend(
            [
                "# HELP sbs_http_request_duration_seconds Request duration in seconds.",
                "# TYPE sbs_http_request_duration_seconds histogram",
            ]
        )
        for (method, path), value in sorted(duration_sum.items()):
            labels = f'method="{_escape(method)}",path="{_escape(path)}"'
            for boundary in self._DURATION_BUCKETS:
                bucket_labels = f'{labels},le="{boundary:g}"'
                lines.append(
                    "sbs_http_request_duration_seconds_bucket"
                    f"{{{bucket_labels}}} "
                    f"{duration_buckets.get((method, path, boundary), 0)}"
                )
            lines.append(
                "sbs_http_request_duration_seconds_bucket"
                f'{{{labels},le="+Inf"}} {duration_count[(method, path)]}'
            )
            lines.append(f"sbs_http_request_duration_seconds_sum{{{labels}}} {value:.9f}")
            lines.append(
                f"sbs_http_request_duration_seconds_count{{{labels}}} {duration_count[(method, path)]}"
            )
        lines.extend(
            [
                "# HELP sbs_http_requests_in_progress Current in-progress HTTP requests.",
                "# TYPE sbs_http_requests_in_progress gauge",
                f"sbs_http_requests_in_progress {in_progress}",
                "# HELP sbs_process_start_time_seconds Process start time since Unix epoch.",
                "# TYPE sbs_process_start_time_seconds gauge",
                f"sbs_process_start_time_seconds {self.process_started_at:.3f}",
                "# HELP sbs_websocket_connections Current WebSocket connections.",
                "# TYPE sbs_websocket_connections gauge",
                f"sbs_websocket_connections {websocket_connections}",
                "# HELP sbs_dashboard_events_total Dashboard events published by this process.",
                "# TYPE sbs_dashboard_events_total counter",
                f"sbs_dashboard_events_total {dashboard_events_total}",
                "# HELP sbs_dashboard_transport_ready Dashboard Redis transport readiness.",
                "# TYPE sbs_dashboard_transport_ready gauge",
                f"sbs_dashboard_transport_ready {dashboard_transport_ready}",
                "# HELP sbs_alertmanager_events_total Alertmanager webhook events accepted.",
                "# TYPE sbs_alertmanager_events_total counter",
            ]
        )
        for alert_status, value in sorted(alertmanager_events.items()):
            lines.append(
                f'sbs_alertmanager_events_total{{status="{_escape(alert_status)}"}} {value}'
            )
        return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


metrics_registry = MetricsRegistry()
_runtime_ready = False
_runtime_lock = threading.Lock()


def set_runtime_ready(value: bool) -> None:
    global _runtime_ready
    with _runtime_lock:
        _runtime_ready = value


def is_runtime_ready() -> bool:
    with _runtime_lock:
        return _runtime_ready


class RequestTelemetryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger = logging.getLogger("app.http")
        started = time.perf_counter()
        metrics_registry.request_started()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - started
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or "__unmatched__"
            metrics_registry.request_finished(
                request.method,
                route_path,
                status_code,
                duration,
            )
            log_event(
                logger,
                logging.INFO if status_code < 500 else logging.ERROR,
                "http_request_completed",
                method=request.method,
                path=request.url.path[:2048],
                route=route_path,
                status_code=status_code,
                duration_ms=round(duration * 1000, 3),
                client_ip=request.client.host if request.client else None,
            )
