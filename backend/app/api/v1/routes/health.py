from datetime import UTC, datetime
from pathlib import Path
import secrets

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.core.observability import is_runtime_ready, metrics_registry
from app.db.session import engine, get_db
from app.schemas.health import HealthResponse
from app.services.jobs.dashboard_websocket_service import ws_manager
from app.services.operational_metrics import render_operational_metrics
from app.services.rbac import has_permission, is_saas_root

_DEEP_HEALTH_ALLOWED_PERMISSIONS = (
    "admin.settings.read",
    "admin.users.read",
    "security.audit.read",
)

try:
    from redis import Redis
except Exception:  # pragma: no cover - defensive import fallback
    Redis = None

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        timestamp=datetime.now(UTC),
    )


def _probe_redis() -> dict[str, object]:
    if Redis is None:
        return {"status": "unknown", "error": "redis_client_unavailable"}
    settings = get_settings()
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        ping_ok = client.ping()
        return {"status": "ok" if ping_ok else "error"}
    except Exception as exc:  # pragma: no cover - depends on runtime infra
        return {"status": "error", "error": exc.__class__.__name__}


def _find_alembic_ini() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "alembic.ini"
        if candidate.exists():
            return candidate
    return None


def _probe_alembic(connection: Connection) -> dict[str, object]:
    ini_path = _find_alembic_ini()
    if ini_path is None:
        return {"status": "unknown", "current": None, "head": [], "up_to_date": None}

    try:
        config = Config(str(ini_path))
        script = ScriptDirectory.from_config(config)
        heads = sorted(list(script.get_heads()))
        context = MigrationContext.configure(connection)
        current_heads = sorted(context.get_current_heads())
        return {
            "status": "ok",
            "current": current_heads,
            "head": heads,
            "up_to_date": bool(current_heads) and set(current_heads) == set(heads),
        }
    except Exception as exc:  # pragma: no cover - depends on runtime infra
        return {
            "status": "error",
            "error": exc.__class__.__name__,
            "current": None,
            "head": [],
            "up_to_date": None,
        }


def _probe_database_checks() -> tuple[dict[str, object], dict[str, object]]:
    """Probe SQL reachability and migration state with one pool checkout.

    A dependency outage must not consume the database pool timeout twice just
    because readiness reports PostgreSQL and Alembic as separate checks.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            return {"status": "ok"}, _probe_alembic(connection)
    except Exception as exc:  # pragma: no cover - depends on runtime infra
        error = {"status": "error", "error": exc.__class__.__name__}
        return error, {
            **error,
            "current": None,
            "head": [],
            "up_to_date": None,
        }
def _redis_is_required() -> bool:
    settings = get_settings()
    return (
        settings.app_env.strip().lower() == "production"
        or settings.jobs_executor_mode == "redis"
        or settings.dashboard_realtime_transport == "redis"
    )


def _collect_system_checks(
    *,
    probe_optional_redis: bool = True,
) -> dict[str, dict[str, object]]:
    postgres_check, alembic_check = _probe_database_checks()
    redis_check = (
        _probe_redis()
        if probe_optional_redis or _redis_is_required()
        else {"status": "optional"}
    )
    return {
        "postgres": postgres_check,
        "redis": redis_check,
        "alembic": alembic_check,
    }


def _development_startup_schema_is_ready() -> bool:
    """Allow the explicit local SQLite/create_all mode without weakening production."""
    settings = get_settings()
    return (
        settings.app_env.strip().lower() != "production"
        and settings.run_startup_ddl
        and engine.dialect.name == "sqlite"
    )


@router.get("/health/liveness")
def liveness() -> dict[str, object]:
    return {
        "status": "alive",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/health/readiness")
def readiness() -> JSONResponse:
    checks = _collect_system_checks(probe_optional_redis=False)
    database_ok = checks["postgres"].get("status") == "ok"
    redis_ok = checks["redis"].get("status") in {"ok", "optional"}
    migrations_current = checks["alembic"].get("up_to_date") is True
    development_startup_schema = (
        not migrations_current and _development_startup_schema_is_ready()
    )
    migrations_ok = migrations_current or development_startup_schema
    runtime_ok = is_runtime_ready()
    websocket_ok = ws_manager.transport_ready()
    ready = database_ok and redis_ok and migrations_ok and runtime_ok and websocket_ok
    migration_status = (
        "ok"
        if migrations_current
        else "development_startup_ddl"
        if development_startup_schema
        else "out_of_date"
    )
    payload = {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "checks": {
            "postgres": checks["postgres"].get("status"),
            "redis": checks["redis"].get("status"),
            "migrations": migration_status,
            "runtime": "ready" if runtime_ok else "starting_or_draining",
            "websocket_transport": "ready" if websocket_ok else "not_ready",
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
    code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=payload)


@router.get("/metrics", include_in_schema=False)
def metrics(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    settings = get_settings()
    if settings.metrics_auth_token:
        provided = ""
        if authorization and authorization.startswith("Bearer "):
            provided = authorization.removeprefix("Bearer ").strip()
        if not secrets.compare_digest(provided, settings.metrics_auth_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid metrics token")
    return PlainTextResponse(
        metrics_registry.render_prometheus() + render_operational_metrics(db),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/health/deep")
def deep_health(current_user: AuthUserResponse = Depends(get_current_user)) -> dict[str, object]:
    if not is_saas_root(current_user) and not any(
        has_permission(current_user, perm) for perm in _DEEP_HEALTH_ALLOWED_PERMISSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing admin or security permission for deep diagnostics",
        )
    settings = get_settings()
    checks = _collect_system_checks()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "demo_mode": settings.demo_mode,
        "run_startup_ddl": settings.run_startup_ddl,
        "checks": checks,
        "timestamp": datetime.now(UTC).isoformat(),
    }
