from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.services.admin_security import ensure_admin_security_schema
from app.services.asset_import import ensure_asset_import_schema
from app.services.asset_sla import ensure_asset_sla_schema
from app.services.reporting_schema import ensure_reporting_schema
from app.services.seed import seed_demo_data
from app.services.service_desk import ensure_service_desk_schema
import app.models  # noqa: F401

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_service_desk_schema(engine)
    ensure_asset_sla_schema(engine)
    ensure_asset_import_schema(engine)
    ensure_admin_security_schema(engine)
    ensure_reporting_schema(engine)
    db = SessionLocal()
    try:
        seed_demo_data(db)
    finally:
        db.close()
    yield


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
    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
