from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import Settings
from app.core.middleware import MetricsTrustedHostMiddleware
from app.main import create_app


def test_application_installs_exact_trusted_host_boundary() -> None:
    application = create_app()
    middleware = next(
        item
        for item in application.user_middleware
        if item.cls is MetricsTrustedHostMiddleware
    )

    assert middleware.kwargs["allowed_hosts"] == Settings().trusted_hosts
    assert middleware.kwargs["metrics_path"] == "/api/v1/metrics"
    assert middleware.kwargs["www_redirect"] is False


def test_metrics_host_bypass_requires_exact_path_and_bearer_token() -> None:
    application = FastAPI()
    application.add_middleware(
        MetricsTrustedHostMiddleware,
        allowed_hosts=["itsm.example.com"],
        metrics_path="/api/v1/metrics",
        metrics_auth_token="metrics-test-token",
        www_redirect=False,
    )

    @application.get("/api/v1/metrics")
    def metrics() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(application)
    bad_host = {"Host": "172.20.0.5"}
    assert client.get("/api/v1/metrics", headers=bad_host).status_code == 400
    assert (
        client.get(
            "/api/v1/metrics",
            headers={**bad_host, "Authorization": "Bearer wrong"},
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/api/v1/metrics",
            headers={
                **bad_host,
                "Authorization": "Bearer metrics-test-token",
            },
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/v1/health",
            headers={
                **bad_host,
                "Authorization": "Bearer metrics-test-token",
            },
        ).status_code
        == 400
    )


def test_trusted_host_boundary_rejects_unlisted_hosts_without_redirect() -> None:
    application = FastAPI()
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["itsm.example.com"],
        www_redirect=False,
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(application)
    assert client.get("/health", headers={"Host": "itsm.example.com"}).status_code == 200
    response = client.get("/health", headers={"Host": "attacker.example"})
    assert response.status_code == 400
    assert "location" not in response.headers


def test_edge_trust_lists_are_normalized_and_deduplicated() -> None:
    settings = Settings(
        _env_file=None,
        trusted_hosts="ITSM.EXAMPLE.COM.,backend,backend",
        forwarded_allow_ips="172.30.250.10,172.30.250.10",
    )

    assert settings.trusted_hosts == ["itsm.example.com", "backend"]
    assert settings.forwarded_allow_ips == ["172.30.250.10"]
