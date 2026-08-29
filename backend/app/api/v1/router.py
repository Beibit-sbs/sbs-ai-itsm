from fastapi import APIRouter
from app.api.v1.routes.automation import router as automation_router
from app.api.v1.routes.workflow_engine import router as workflow_engine_router
from app.api.v1.routes.custom_fields import router as custom_fields_router
from app.api.v1.routes.configuration_packages import (
    router as configuration_packages_router,
)
from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.ai import router as ai_router
from app.api.v1.routes.ai_retrieval import router as ai_retrieval_router
from app.api.v1.routes.ai_governance import router as ai_governance_router
from app.api.v1.routes.ai_runtime_controls import router as ai_runtime_controls_router
from app.api.v1.routes.ai_actions import router as ai_actions_router
from app.api.v1.routes.configuration_center import router as configuration_center_router
from app.api.v1.routes.global_search import router as global_search_router
from app.api.v1.routes.tenant_experience import (
    router as tenant_experience_router,
)
from app.api.v1.routes.localized_content import (
    router as localized_content_router,
)
from app.api.v1.routes.assets import router as assets_router
from app.api.v1.routes.software_assets import router as software_assets_router
from app.api.v1.routes.changes import router as changes_router
from app.api.v1.routes.change_governance import router as change_governance_router
from app.api.v1.routes.releases import router as releases_router
from app.api.v1.routes.cmdb import router as cmdb_router
from app.api.v1.routes.cmdb_relationships import router as cmdb_relationships_router
from app.api.v1.routes.cmdb_reconciliation import router as cmdb_reconciliation_router
from app.api.v1.routes.cmdb_impact import router as cmdb_impact_router
from app.api.v1.routes.cmdb_quality import router as cmdb_quality_router
from app.api.v1.routes.asset_discovery import router as asset_discovery_router
from app.api.v1.routes.catalog import router as catalog_router
from app.api.v1.routes.catalog_forms import router as catalog_forms_router
from app.api.v1.routes.problems import router as problems_router
from app.api.v1.routes.problem_governance import router as problem_governance_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.integrations import router as integrations_router
from app.api.v1.routes.integration_platform import (
    router as integration_platform_router,
)
from app.api.v1.routes.jobs import router as jobs_router
from app.api.v1.routes.knowledge import router as knowledge_router
from app.api.v1.routes.monitoring import router as monitoring_router
from app.api.v1.routes.major_incidents import router as major_incidents_router
from app.api.v1.routes.event_operations import router as event_operations_router
from app.api.v1.routes.notifications import router as notifications_router
from app.api.v1.routes.analytics import router as analytics_router
from app.api.v1.routes.reports import router as reports_router
from app.api.v1.routes.requests import router as requests_router
from app.api.v1.routes.security import router as security_router
from app.api.v1.routes.sla import router as sla_router
from app.api.v1.routes.tickets import router as tickets_router
from app.api.v1.routes.tenants import router as tenants_router
from app.api.v1.routes.scim import router as scim_router
from app.api.v1.routes.identity_provisioning import (
    router as identity_provisioning_router,
)
from app.api.v1.routes.email_channels import (
    router as email_channels_router,
    webhook_router as email_webhook_router,
)
from app.api.v1.routes.teams_collaboration import (
    router as teams_collaboration_router,
)
from app.api.v1.routes.data_governance import router as data_governance_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(monitoring_router, tags=["monitoring"])
api_router.include_router(major_incidents_router, tags=["major-incidents"])
api_router.include_router(event_operations_router, tags=["event-operations"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(assets_router, tags=["assets"])
api_router.include_router(software_assets_router, tags=["software-assets"])
api_router.include_router(cmdb_router, tags=["cmdb"])
api_router.include_router(cmdb_relationships_router, tags=["cmdb"])
api_router.include_router(cmdb_reconciliation_router, tags=["cmdb"])
api_router.include_router(cmdb_impact_router, tags=["cmdb"])
api_router.include_router(cmdb_quality_router, tags=["cmdb"])
api_router.include_router(asset_discovery_router, tags=["asset-discovery"])
api_router.include_router(changes_router, tags=["changes"])
api_router.include_router(change_governance_router, tags=["change-governance"])
api_router.include_router(releases_router, tags=["releases"])
api_router.include_router(catalog_router, tags=["catalog"])
api_router.include_router(catalog_forms_router, tags=["catalog"])
api_router.include_router(requests_router, tags=["requests"])
api_router.include_router(problems_router, tags=["problems"])
api_router.include_router(problem_governance_router, tags=["problem-governance"])
api_router.include_router(sla_router, tags=["sla"])
api_router.include_router(tickets_router, tags=["tickets"])
api_router.include_router(knowledge_router, tags=["knowledge"])
api_router.include_router(ai_router, tags=["ai"])
api_router.include_router(ai_retrieval_router, tags=["ai-rag"])
api_router.include_router(ai_governance_router, tags=["ai-governance"])
api_router.include_router(ai_runtime_controls_router, tags=["ai-runtime-controls"])
api_router.include_router(ai_actions_router, tags=["ai-actions"])
api_router.include_router(configuration_center_router, tags=["configuration-center"])
api_router.include_router(global_search_router, tags=["global-search"])
api_router.include_router(tenant_experience_router, tags=["tenant-experience"])
api_router.include_router(localized_content_router, tags=["localized-content"])
api_router.include_router(notifications_router, tags=["notifications"])
api_router.include_router(integrations_router, tags=["integrations"])
api_router.include_router(
    integration_platform_router,
    tags=["integration-platform"],
)
api_router.include_router(automation_router, tags=["automation"])
api_router.include_router(workflow_engine_router, tags=["workflow-engine"])
api_router.include_router(custom_fields_router, tags=["custom-fields"])
api_router.include_router(
    configuration_packages_router,
    tags=["configuration-packages"],
)
api_router.include_router(analytics_router, tags=["analytics"])
api_router.include_router(reports_router, tags=["reports"])
api_router.include_router(admin_router, tags=["admin"])
api_router.include_router(security_router, tags=["security"])
api_router.include_router(tenants_router, tags=["tenants"])
api_router.include_router(jobs_router, tags=["system"])
api_router.include_router(scim_router, tags=["scim"])
api_router.include_router(
    identity_provisioning_router,
    tags=["identity-provisioning"],
)
api_router.include_router(email_channels_router, tags=["email"])
api_router.include_router(email_webhook_router, tags=["email"])
api_router.include_router(teams_collaboration_router, tags=["teams"])
api_router.include_router(data_governance_router, tags=["data-governance"])
