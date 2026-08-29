from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def error_payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def _is_scim_request(request: Request) -> bool:
    return "/scim/v2" in request.url.path


def _scim_error_payload(
    status_code: int,
    message: str,
    *,
    scim_type: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "detail": message,
        "status": str(status_code),
    }
    if scim_type:
        payload["scimType"] = scim_type
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            message = str(exc.detail.get("message") or "Request failed")
            details = {key: value for key, value in exc.detail.items() if key != "message"}
        else:
            message = str(exc.detail)
            details = None
        if _is_scim_request(request):
            return JSONResponse(
                status_code=exc.status_code,
                content=_scim_error_payload(
                    exc.status_code,
                    message,
                    scim_type=(
                        str(details.get("scimType"))
                        if details and details.get("scimType")
                        else None
                    ),
                ),
                headers=exc.headers,
                media_type="application/scim+json",
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(
                error_payload(f"HTTP_{exc.status_code}", message, details)
            ),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if _is_scim_request(request):
            return JSONResponse(
                status_code=400,
                content=_scim_error_payload(
                    400,
                    "SCIM request validation failed",
                    scim_type="invalidValue",
                ),
                media_type="application/scim+json",
            )
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                error_payload(
                    "VALIDATION_ERROR", "Request validation failed", exc.errors()
                )
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, __: Exception) -> JSONResponse:
        if _is_scim_request(request):
            return JSONResponse(
                status_code=500,
                content=_scim_error_payload(
                    500,
                    "Internal provisioning error",
                ),
                media_type="application/scim+json",
            )
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "Internal server error"),
        )
