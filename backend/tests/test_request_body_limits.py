from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.middleware import RequestBodyLimitMiddleware


def _limited_app(max_bytes: int = 8) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=max_bytes)

    @app.post("/consume")
    async def consume(request: Request) -> dict[str, int]:
        return {"bytes": len(await request.body())}

    return app


def test_request_body_limit_accepts_bounded_payload() -> None:
    with TestClient(_limited_app()) as client:
        response = client.post("/consume", content=b"12345678")

    assert response.status_code == 200
    assert response.json() == {"bytes": 8}


def test_request_body_limit_rejects_declared_oversize() -> None:
    with TestClient(_limited_app()) as client:
        response = client.post("/consume", content=b"123456789")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_BODY_TOO_LARGE"


def test_request_body_limit_rejects_streamed_oversize_without_content_length() -> None:
    def stream():
        yield b"1234"
        yield b"56789"

    with TestClient(_limited_app()) as client:
        response = client.post("/consume", content=stream())

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_BODY_TOO_LARGE"


def test_capacity_settings_are_bounded() -> None:
    settings = Settings(
        _env_file=None,
        api_max_request_body_bytes=6_291_456,
        database_pool_size=10,
        database_max_overflow=5,
        database_pool_timeout_seconds=30,
        database_pool_recycle_seconds=1800,
    )

    assert settings.api_max_request_body_bytes == 6_291_456
    assert settings.database_pool_size + settings.database_max_overflow == 15
