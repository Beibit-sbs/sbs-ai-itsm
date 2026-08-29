from __future__ import annotations

import re
import secrets
import uuid

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import set_correlation_id


CORRELATION_ID_HEADER = "X-Request-ID"
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class MetricsTrustedHostMiddleware(TrustedHostMiddleware):
    """Keep the exact Host allowlist while permitting authenticated scrapes.

    DNS service discovery connects to replica IPs, so the HTTP Host value is an
    ephemeral container address. Only the exact metrics path may bypass the
    host check, and only with the same bearer token enforced by the endpoint.
    All user/API routes retain the strict TrustedHost boundary.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_hosts: list[str],
        metrics_path: str,
        metrics_auth_token: str | None,
        www_redirect: bool = False,
    ) -> None:
        super().__init__(
            app,
            allowed_hosts=allowed_hosts,
            www_redirect=www_redirect,
        )
        self.metrics_path = metrics_path
        self.metrics_auth_token = metrics_auth_token or ""

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] == "http"
            and scope.get("path") == self.metrics_path
            and self.metrics_auth_token
        ):
            authorization = Headers(scope=scope).get("authorization", "")
            scheme, _, provided = authorization.partition(" ")
            if scheme.lower() == "bearer" and secrets.compare_digest(
                provided.strip(),
                self.metrics_auth_token,
            ):
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Reject oversized bodies even when the reverse proxy is bypassed.

    Content-Length is checked before reading. Chunked/streamed bodies are counted
    while consumed, so omitting or forging Content-Length cannot evade the limit.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    @staticmethod
    async def _error(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "details": None,
                }
            },
        )
        await response(scope, receive, send)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                await self._error(
                    scope,
                    receive,
                    send,
                    status_code=400,
                    code="INVALID_CONTENT_LENGTH",
                    message="Content-Length must be a non-negative integer",
                )
                return
            if declared_length < 0:
                await self._error(
                    scope,
                    receive,
                    send,
                    status_code=400,
                    code="INVALID_CONTENT_LENGTH",
                    message="Content-Length must be a non-negative integer",
                )
                return
            if declared_length > self.max_bytes:
                await self._error(
                    scope,
                    receive,
                    send,
                    status_code=413,
                    code="REQUEST_BODY_TOO_LARGE",
                    message=f"Request body exceeds the {self.max_bytes}-byte limit",
                )
                return

        consumed = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await self._error(
                scope,
                receive,
                send,
                status_code=413,
                code="REQUEST_BODY_TOO_LARGE",
                message=f"Request body exceeds the {self.max_bytes}-byte limit",
            )


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assigns a correlation id per request and echoes it back in the response header.

    The correlation id is stored in a contextvar so downstream code (e.g. job
    service, structured logs) can attach it to persisted records without
    needing to thread it through every function signature.
    """

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(CORRELATION_ID_HEADER)
        candidate = incoming.strip() if incoming else ""
        correlation_id = candidate if _SAFE_CORRELATION_ID.fullmatch(candidate) else str(uuid.uuid4())
        try:
            set_correlation_id(correlation_id)
            response = await call_next(request)
        finally:
            # Reset to None so leaks between requests are impossible.
            set_correlation_id(None)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
