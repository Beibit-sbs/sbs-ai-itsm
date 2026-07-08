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


def test_unknown_route_uses_unified_error_shape(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/unknown")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"
