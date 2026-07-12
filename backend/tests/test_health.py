from fastapi.testclient import TestClient


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
    assert response.status_code in {200, 503}
    payload = response.json()
    assert payload["status"] in {"ready", "not_ready"}
    assert isinstance(payload.get("ready"), bool)
    assert "checks" in payload
    assert "postgres" in payload["checks"]
    assert "redis" in payload["checks"]


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
