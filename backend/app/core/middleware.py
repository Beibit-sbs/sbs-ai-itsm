from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.context import set_correlation_id


CORRELATION_ID_HEADER = "X-Request-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assigns a correlation id per request and echoes it back in the response header.

    The correlation id is stored in a contextvar so downstream code (e.g. job
    service, structured logs) can attach it to persisted records without
    needing to thread it through every function signature.
    """

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(CORRELATION_ID_HEADER)
        correlation_id = incoming.strip() if incoming else str(uuid.uuid4())
        token = None
        try:
            set_correlation_id(correlation_id)
            response = await call_next(request)
        finally:
            # Reset to None so leaks between requests are impossible.
            set_correlation_id(None)
            if token is not None:  # pragma: no cover - defensive placeholder
                pass
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
