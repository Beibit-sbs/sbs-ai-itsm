from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import engine
from app.schemas.health import HealthResponse
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


def _probe_postgres() -> dict[str, object]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # pragma: no cover - depends on runtime infra
        return {"status": "error", "error": exc.__class__.__name__}


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


def _probe_alembic() -> dict[str, object]:
    ini_path = _find_alembic_ini()
    if ini_path is None:
        return {"status": "unknown", "current": None, "head": [], "up_to_date": None}

    try:
        config = Config(str(ini_path))
        script = ScriptDirectory.from_config(config)
        heads = sorted(list(script.get_heads()))
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current = context.get_current_revision()
        return {
            "status": "ok",
            "current": current,
            "head": heads,
            "up_to_date": bool(current and current in heads),
        }
    except Exception as exc:  # pragma: no cover - depends on runtime infra
        return {
            "status": "error",
            "error": exc.__class__.__name__,
            "current": None,
            "head": [],
            "up_to_date": None,
        }


def _collect_system_checks() -> dict[str, dict[str, object]]:
    return {
        "postgres": _probe_postgres(),
        "redis": _probe_redis(),
        "alembic": _probe_alembic(),
    }


@router.get("/health/liveness")
def liveness() -> dict[str, object]:
    return {
        "status": "alive",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/health/readiness")
def readiness() -> JSONResponse:
    checks = _collect_system_checks()
    postgres_ok = checks["postgres"].get("status") == "ok"
    redis_ok = checks["redis"].get("status") == "ok"
    ready = postgres_ok and redis_ok
    payload = {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "checks": {
            "postgres": checks["postgres"].get("status"),
            "redis": checks["redis"].get("status"),
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
    code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=payload)


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
