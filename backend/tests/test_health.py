from fastapi.testclient import TestClient

from app.core.observability import MetricsRegistry


def test_health_endpoint(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "SBS AI ITSM"
    assert payload["version"] == "0.1.0"
    assert "timestamp" in payload


def test_liveness_endpoint(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/liveness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "alive"
    assert "timestamp" in payload


def test_readiness_endpoint_shape(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["ready"] is True
    assert "checks" in payload
    assert "postgres" in payload["checks"]
    assert "redis" in payload["checks"]
    assert "migrations" in payload["checks"]
    assert "runtime" in payload["checks"]
    assert "websocket_transport" in payload["checks"]
    assert payload["checks"]["migrations"] == "development_startup_ddl"


def test_database_readiness_reuses_one_pool_checkout(monkeypatch) -> None:
    from app.api.v1.routes import health as health_routes

    calls = {"connect": 0, "execute": 0}

    class Connection:
        def execute(self, _statement):
            calls["execute"] += 1

    class ConnectionContext:
        def __enter__(self):
            return Connection()

        def __exit__(self, *_args):
            return None

    class Engine:
        def connect(self):
            calls["connect"] += 1
            return ConnectionContext()

    monkeypatch.setattr(health_routes, "engine", Engine())
    monkeypatch.setattr(
        health_routes,
        "_probe_alembic",
        lambda _connection: {"status": "ok", "up_to_date": True},
    )

    postgres, alembic = health_routes._probe_database_checks()

    assert postgres == {"status": "ok"}
    assert alembic["up_to_date"] is True
    assert calls == {"connect": 1, "execute": 1}


def test_readiness_does_not_waive_outdated_migrations_outside_local_mode(
    app,
    monkeypatch,
) -> None:
    from app.api.v1.routes import health as health_routes

    monkeypatch.setattr(
        health_routes,
        "_collect_system_checks",
        lambda **_: {
            "postgres": {"status": "ok"},
            "redis": {"status": "ok"},
            "alembic": {"status": "ok", "up_to_date": False},
        },
    )
    monkeypatch.setattr(
        health_routes,
        "_development_startup_schema_is_ready",
        lambda: False,
    )
    monkeypatch.setattr(health_routes, "is_runtime_ready", lambda: True)
    monkeypatch.setattr(health_routes.ws_manager, "transport_ready", lambda: True)

    with TestClient(app) as client:
        response = client.get("/api/v1/health/readiness")

    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] == "out_of_date"


def test_metrics_endpoint_exposes_prometheus_format(app) -> None:
    with TestClient(app) as client:
        client.get("/api/v1/health")
        response = client.get("/api/v1/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "sbs_http_requests_total" in response.text
    assert "sbs_http_request_duration_seconds" in response.text
    assert "sbs_websocket_connections" in response.text
    assert "sbs_dashboard_transport_ready" in response.text
    assert "sbs_operational_snapshot_success" in response.text
    assert 'sbs_dependency_ready{dependency="postgres"} 1' in response.text
    assert 'sbs_auth_events_window{event="login_failed"}' in response.text
    assert 'sbs_attachment_scan_items{status="PENDING"}' in response.text
    assert "sbs_attachment_quarantine_oldest_age_seconds" in response.text


def test_http_latency_is_exported_as_a_histogram() -> None:
    registry = MetricsRegistry()
    registry.request_started()
    registry.request_finished("GET", "/tickets", 200, 0.075)

    rendered = registry.render_prometheus()

    assert "# TYPE sbs_http_request_duration_seconds histogram" in rendered
    assert (
        'sbs_http_request_duration_seconds_bucket{method="GET",'
        'path="/tickets",le="0.05"} 0'
    ) in rendered
    assert (
        'sbs_http_request_duration_seconds_bucket{method="GET",'
        'path="/tickets",le="0.1"} 1'
    ) in rendered
    assert (
        'sbs_http_request_duration_seconds_bucket{method="GET",'
        'path="/tickets",le="+Inf"} 1'
    ) in rendered


def test_metrics_endpoint_can_require_bearer_token(app, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.v1.routes.health.get_settings",
        lambda: type("Settings", (), {"metrics_auth_token": "metrics-secret-token"})(),
    )
    with TestClient(app) as client:
        denied = client.get("/api/v1/metrics")
        allowed = client.get(
            "/api/v1/metrics",
            headers={"Authorization": "Bearer metrics-secret-token"},
        )
    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_deep_health_requires_auth(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/deep")
    assert response.status_code == 401


def test_deep_health_does_not_expose_secrets(app) -> None:
    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "root@sbs.local", "password": "Root!2026"},
        )
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
        response = client.get(
            "/api/v1/health/deep",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = str(payload)
    assert "database_url" not in serialized.lower()
    assert "jwt_secret_key" not in serialized.lower()
    assert "password" not in serialized.lower()
    assert "checks" in payload
    assert "alembic" in payload["checks"]


def test_unknown_route_uses_unified_error_shape(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/unknown")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"
