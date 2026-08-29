from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import (
    CorrelationIdMiddleware,
    MetricsTrustedHostMiddleware,
    RequestBodyLimitMiddleware,
)
from app.core.observability import (
    RequestTelemetryMiddleware,
    configure_logging,
    log_event,
    set_runtime_ready,
)
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.services.admin_security import ensure_admin_security_schema
from app.services.asset_import import ensure_asset_import_schema
from app.services.asset_sla import ensure_asset_sla_schema
from app.services.jobs import tasks as _job_tasks  # noqa: F401 - registers built-in tasks
from app.services.jobs.schema import ensure_jobs_schema
from app.services.jobs.policy_state import load_policy_into_settings
from app.services.jobs.runbook_policy_state import load_runbook_policy_into_settings
from app.services.jobs.dashboard_websocket_service import (
    RedisDashboardTransport,
    dashboard_stream_broadcaster,
    ws_manager,
)
from app.services.notifications_schema import ensure_notifications_schema
from app.services.reporting_schema import ensure_reporting_schema
from app.services.seed import seed_demo_data, seed_system_data
from app.services.service_desk import ensure_service_desk_schema
import app.models  # noqa: F401

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("app.lifecycle")


@asynccontextmanager
async def lifespan(_: FastAPI):
    set_runtime_ready(False)
    log_event(logger, logging.INFO, "application_starting", environment=settings.app_env)
    if settings.run_startup_ddl:
        Base.metadata.create_all(bind=engine)
        ensure_jobs_schema(engine)
        ensure_service_desk_schema(engine)
        ensure_asset_sla_schema(engine)
        ensure_asset_import_schema(engine)
        ensure_admin_security_schema(engine)
        ensure_reporting_schema(engine)
        ensure_notifications_schema(engine)
    db = SessionLocal()
    try:
        load_policy_into_settings(db, settings)
        load_runbook_policy_into_settings(db, settings)
        if settings.demo_mode:
            seed_demo_data(db)
        else:
            seed_system_data(db)
    finally:
        db.close()

    ws_manager.max_connections_per_tenant = settings.dashboard_ws_max_connections_per_tenant
    if settings.dashboard_realtime_transport == "redis":
        await ws_manager.start_transport(
            RedisDashboardTransport(settings.redis_url, settings.dashboard_pubsub_channel)
        )
    await dashboard_stream_broadcaster.start()
    set_runtime_ready(True)
    log_event(logger, logging.INFO, "application_ready", environment=settings.app_env)
    try:
        yield
    finally:
        set_runtime_ready(False)
        log_event(logger, logging.INFO, "application_draining", environment=settings.app_env)
        await dashboard_stream_broadcaster.stop()
        await ws_manager.stop_transport()
        log_event(logger, logging.INFO, "application_stopped", environment=settings.app_env)


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=settings.api_max_request_body_bytes,
    )
    application.add_middleware(
        MetricsTrustedHostMiddleware,
        allowed_hosts=settings.trusted_hosts,
        metrics_path=f"{settings.api_v1_prefix}/metrics",
        metrics_auth_token=settings.metrics_auth_token,
        www_redirect=False,
    )
    application.add_middleware(RequestTelemetryMiddleware)
    application.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
