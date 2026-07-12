from fastapi import APIRouter
from app.api.v1.routes.automation import router as automation_router
from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.ai import router as ai_router
from app.api.v1.routes.assets import router as assets_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.integrations import router as integrations_router
from app.api.v1.routes.jobs import router as jobs_router
from app.api.v1.routes.knowledge import router as knowledge_router
from app.api.v1.routes.notifications import router as notifications_router
from app.api.v1.routes.analytics import router as analytics_router
from app.api.v1.routes.reports import router as reports_router
from app.api.v1.routes.security import router as security_router
from app.api.v1.routes.sla import router as sla_router
from app.api.v1.routes.tickets import router as tickets_router
from app.api.v1.routes.tenants import router as tenants_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(assets_router, tags=["assets"])
api_router.include_router(sla_router, tags=["sla"])
api_router.include_router(tickets_router, tags=["tickets"])
api_router.include_router(knowledge_router, tags=["knowledge"])
api_router.include_router(ai_router, tags=["ai"])
api_router.include_router(notifications_router, tags=["notifications"])
api_router.include_router(integrations_router, tags=["integrations"])
api_router.include_router(automation_router, tags=["automation"])
api_router.include_router(analytics_router, tags=["analytics"])
api_router.include_router(reports_router, tags=["reports"])
api_router.include_router(admin_router, tags=["admin"])
api_router.include_router(security_router, tags=["security"])
api_router.include_router(tenants_router, tags=["tenants"])
api_router.include_router(jobs_router, tags=["system"])
