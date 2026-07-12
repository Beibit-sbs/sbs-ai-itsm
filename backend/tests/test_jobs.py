from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth_headers(token: str, correlation_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if correlation_id is not None:
        headers["X-Request-ID"] = correlation_id
    return headers


def test_correlation_id_middleware_generates_header(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_correlation_id_middleware_echoes_incoming_header(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"X-Request-ID": "smoke-1234"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "smoke-1234"


def test_jobs_list_requires_authentication(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/jobs")
    assert response.status_code == 401


def test_jobs_list_denies_requester(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "requester@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/jobs", headers=_auth_headers(token))
    assert response.status_code == 403


def test_jobs_task_registry_exposes_builtins(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get("/api/v1/jobs/tasks", headers=_auth_headers(token))
    assert response.status_code == 200
    names = response.json()
    assert "system.echo" in names
    assert "system.sleep" in names
    assert "system.fail" in names


def test_enqueue_success_records_result_and_correlation(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token, correlation_id="test-corr-1"),
            json={"task_name": "system.echo", "payload": {"hello": "world"}},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["task_name"] == "system.echo"
    assert body["status"] == "success"
    assert body["result"] == {"echoed": {"hello": "world"}, "task_name": "system.echo", "attempt": 1}
    assert body["correlation_id"] == "test-corr-1"
    assert body["attempts"] == 1
    assert body["duration_ms"] is not None


def test_enqueue_failure_records_error_message(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.fail", "payload": {"reason": "boom"}},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"] is not None
    assert "boom" in body["error_message"]


def test_enqueue_unknown_task_returns_400(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "does.not.exist"},
        )
    assert response.status_code == 400


def test_non_root_cannot_enqueue(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.echo"},
        )
    assert response.status_code == 403


def test_admin_can_read_jobs(app) -> None:
    with TestClient(app) as client:
        root_token = _login(client, "root@sbs.local", "Root!2026")
        client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(root_token),
            json={"task_name": "system.echo", "payload": {}},
        )
        admin_token = _login(client, "admin@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/jobs?limit=5", headers=_auth_headers(admin_token))
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert all("task_name" in item and "status" in item for item in payload)


def test_job_summary_shape(app) -> None:
    with TestClient(app) as client:
        root_token = _login(client, "root@sbs.local", "Root!2026")
        client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(root_token),
            json={"task_name": "system.echo", "payload": {"a": 1}},
        )
        response = client.get("/api/v1/jobs/summary", headers=_auth_headers(root_token))
    assert response.status_code == 200
    data = response.json()
    for key in ("total", "queued", "running", "success", "failed"):
        assert key in data
    assert data["total"] >= 1
    assert data["success"] >= 1


def test_get_job_by_id_returns_detail(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        created = client.post(
            "/api/v1/jobs/enqueue",
            headers=_auth_headers(token),
            json={"task_name": "system.echo", "payload": {"k": "v"}},
        ).json()
        response = client.get(f"/api/v1/jobs/{created['id']}", headers=_auth_headers(token))
    assert response.status_code == 200
    detail = response.json()
    assert detail["id"] == created["id"]
    assert detail["result"] == {"echoed": {"k": "v"}, "task_name": "system.echo", "attempt": 1}


def test_get_job_unknown_id_returns_404(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000", headers=_auth_headers(token))
    assert response.status_code == 404
