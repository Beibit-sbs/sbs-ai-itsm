from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.asset import Asset
from app.models.catalog_form import CatalogFormVersion
from app.models.external_system import ExternalSystem
from app.models.import_job import ImportJob
from app.models.integration_credential import IntegrationCredential
from app.models.integration_event_log import IntegrationEventLog
from app.models.integration_mapping import IntegrationMapping
from app.models.permission import Permission
from app.models.report_snapshot import ReportSnapshot
from app.models.role import Role
from app.models.saved_report import SavedReport
from app.models.sla import SlaPolicy
from app.models.service_catalog import (
    CatalogItem,
    CatalogService,
    ServiceCategory,
    ServiceOffering,
)
from app.models.system_setting import SystemSetting
from app.models.tenant import Tenant
from app.models.user import User
from app.models.webhook_endpoint import WebhookEndpoint
from app.models.ai_suggestion import AiSuggestion
from app.models.ticket import Ticket
from app.services.analytics import seed_reporting_demo_data
from app.services.asset_sla import seed_asset_sla_demo_data
from app.services.audit import log_audit
from app.services.automation import seed_workflow_automation_data
from app.services.catalog_forms import (
    canonical_json,
    default_attachment_rules,
    schema_hash,
)
from app.services.catalog_governance import (
    normalize_approval_policy,
    normalize_sla_policy,
)
from app.services.cmdb_bootstrap import ensure_standard_cmdb_model
from app.services.integrations.providers import create_integration_event
from app.services.knowledge_ai import seed_knowledge_ai_demo_data
from app.services.notifications import seed_demo_notifications, seed_notification_templates
from app.services.service_desk import (
    ensure_service_desk_reference_data,
    seed_service_desk_demo_data,
)


def _uuid() -> str:
    return str(uuid.uuid4())


PERMISSIONS = [
    ("tickets.read", "Read tickets", "tickets", "Read ticket records"),
    ("tickets.create", "Create tickets", "tickets", "Create new ticket records"),
    ("tickets.create.on_behalf", "Create tickets on behalf", "tickets", "Register a ticket for another tenant user with a mandatory audited reason"),
    ("tickets.update", "Update tickets", "tickets", "Update ticket details"),
    ("tickets.assign", "Assign tickets", "tickets", "Assign executors to tickets"),
    ("tickets.self_assign", "Take unassigned tickets", "tickets", "Assign an unassigned ticket to the current user"),
    ("tickets.scope.all", "Read all tenant tickets", "tickets", "Read every ticket in the current tenant"),
    ("tickets.scope.assigned", "Read assigned queue tickets", "tickets", "Read tickets assigned to the current user and unassigned queue tickets"),
    ("tickets.scope.requester", "Read requester tickets", "tickets", "Read tickets requested by the current user"),
    ("tickets.comment", "Comment tickets", "tickets", "Post comments to tickets"),
    ("tickets.close", "Close tickets", "tickets", "Resolve and close tickets"),
    ("tickets.bulk.execute", "Execute bounded ticket bulk actions", "tickets", "Preview and execute guarded bulk ticket changes"),
    ("tickets.participants.read", "Read ticket participants", "tickets", "Read participants and watcher notification preferences for visible tickets"),
    ("tickets.participants.manage", "Manage ticket participants", "tickets", "Add, update, and remove ticket participants and watchers"),
    ("tickets.watch", "Watch own tickets", "tickets", "Subscribe or unsubscribe the current user as a watcher on a visible ticket"),
    ("tickets.duplicates.read", "Read duplicate candidates", "tickets", "Review scored duplicate candidates for visible tenant tickets"),
    ("tickets.duplicates.manage", "Manage duplicate decisions", "tickets", "Dismiss duplicate candidates with immutable evidence"),
    ("tickets.merge", "Merge tickets", "tickets", "Soft-merge duplicate tickets with optimistic concurrency and audit evidence"),
    ("tickets.split", "Split tickets", "tickets", "Create a governed child ticket from a mixed-scope ticket"),
    ("major_incidents.read", "Read major incidents", "tickets", "Read the tenant major-incident command center and evidence"),
    ("major_incidents.manage", "Manage major incidents", "tickets", "Declare and operate major incidents, communications, actions, and PIR"),
    ("catalog.read", "Read service catalog", "catalog", "Browse published service catalog items"),
    ("catalog.manage", "Manage service catalog", "catalog", "Create and revise catalog taxonomy and items"),
    ("catalog.publish", "Publish service catalog", "catalog", "Approve, publish, and retire catalog items"),
    ("requests.read", "Read service requests", "requests", "Read service requests and their timelines"),
    ("requests.scope.all", "Read all tenant requests", "requests", "Read every service request in the current tenant"),
    ("requests.scope.requester", "Read requester service requests", "requests", "Read service requests submitted by the current user"),
    ("requests.create", "Create service requests", "requests", "Create requests from published catalog items"),
    ("requests.manage", "Manage service requests", "requests", "Manage service request lifecycles"),
    ("requests.approve", "Approve service requests", "requests", "Approve or reject service request items"),
    ("requests.fulfill", "Fulfill service requests", "requests", "Process service request fulfillment tasks"),
    ("requests.comment", "Comment service requests", "requests", "Post service request timeline comments"),
    ("assets.read", "Read assets", "assets", "Read assets inventory"),
    ("assets.create", "Create assets", "assets", "Create assets"),
    ("assets.update", "Update assets", "assets", "Update assets"),
    ("assets.assign", "Assign assets", "assets", "Assign assets to users"),
    ("assets.move", "Move assets", "assets", "Move assets between locations"),
    ("assets.verify", "Verify assets", "assets", "Verify asset location and inventory state"),
    ("assets.dispose", "Dispose assets", "assets", "Dispose assets with write-off reason"),
    ("assets.restore", "Restore assets", "assets", "Restore disposed assets"),
    ("assets.history.read", "Read asset history", "assets", "Read asset lifecycle history"),
    ("assets.import", "Import assets", "assets", "Upload and process asset import batches"),
    ("assets.import.preview", "Preview asset imports", "assets", "Generate import preview and validation"),
    ("assets.import.commit", "Commit asset imports", "assets", "Commit validated asset imports"),
    ("assets.import.read_batches", "Read import batches", "assets", "Read asset import batches and rows"),
    ("sam.read", "Read software assets", "software_assets", "Read software products, licenses, installations, compliance, and renewals"),
    ("sam.catalog.manage", "Manage software catalog", "software_assets", "Create and govern software catalog products and prohibited software policy"),
    ("sam.licenses.manage", "Manage software licenses", "software_assets", "Manage software entitlements, contracts, costs, expirations, and renewals"),
    ("sam.installations.manage", "Manage software installations", "software_assets", "Register and govern detected software installations and authorization state"),
    ("sam.reconcile", "Reconcile software compliance", "software_assets", "Run license compliance and expiration reconciliation"),
    ("changes.read", "Read changes", "changes", "Read change requests and lifecycle history"),
    ("changes.create", "Create changes", "changes", "Create change requests"),
    ("changes.update", "Update changes", "changes", "Update draft change assessments"),
    ("changes.submit", "Submit changes", "changes", "Submit changes for assessment and approval"),
    ("changes.approve", "Approve changes", "changes", "Approve or reject CAB decisions"),
    ("changes.schedule", "Schedule changes", "changes", "Schedule approved implementation windows"),
    ("changes.execute", "Execute changes", "changes", "Run and close change implementations"),
    ("problems.read", "Read problems", "problems", "Read problem records and Known Errors"),
    ("problems.create", "Create problems", "problems", "Create reactive and proactive problem records"),
    ("problems.update", "Update problems", "problems", "Update problem assessments and relationships"),
    ("problems.investigate", "Investigate problems", "problems", "Run root-cause investigations"),
    ("problems.publish_known_error", "Publish Known Errors", "problems", "Publish and retire KEDB workarounds"),
    ("problems.resolve", "Resolve problems", "problems", "Resolve, validate, close, and reopen problems"),
    ("sla.read", "Read SLA", "sla", "Read SLA policies and breaches"),
    ("sla.manage", "Manage SLA", "sla", "Manage SLA policies"),
    ("knowledge.read", "Read knowledge", "knowledge", "Read knowledge base"),
    ("knowledge.create", "Create knowledge", "knowledge", "Create knowledge articles"),
    ("knowledge.update", "Update knowledge", "knowledge", "Update knowledge articles"),
    ("knowledge.publish", "Publish knowledge", "knowledge", "Publish knowledge articles"),
    ("knowledge.archive", "Archive knowledge", "knowledge", "Archive knowledge articles"),
    ("knowledge.feedback", "Leave knowledge feedback", "knowledge", "Submit article feedback"),
    ("knowledge.create_from_ticket", "Create knowledge from ticket", "knowledge", "Generate article draft from ticket"),
    ("knowledge.usage.read", "Read knowledge usage", "knowledge", "Read knowledge usage logs"),
    ("knowledge.usage.write", "Write knowledge usage", "knowledge", "Write knowledge usage logs"),
    ("knowledge.attach.read", "Read ticket knowledge links", "knowledge", "Read knowledge links in tickets"),
    ("knowledge.attach", "Manage ticket knowledge links", "knowledge", "Create or remove knowledge links in tickets"),
    ("ai.use", "Use AI", "ai", "Use AI Copilot"),
    ("ai.view_suggestions", "View AI suggestions", "ai", "Read AI suggestions"),
    ("ai.accept_suggestion", "Accept AI suggestions", "ai", "Accept AI suggestion decisions"),
    ("ai.reject_suggestion", "Reject AI suggestions", "ai", "Reject AI suggestion decisions"),
    ("ai.rag.use", "Use grounded AI", "ai", "Ask the permission-aware grounded assistant"),
    ("ai.rag.read", "Read grounded AI status", "ai", "Read retrieval health and ingestion status"),
    ("ai.rag.manage", "Manage grounded AI index", "ai", "Synchronize the retrieval index"),
    ("ai.rag.audit", "Audit grounded AI", "ai", "Read redacted retrieval evidence logs"),
    ("ai.governance.read", "Read AI governance", "ai", "Read prompt, evaluation, and rollout governance"),
    ("ai.governance.manage", "Manage AI governance", "ai", "Create prompt versions and evaluation datasets"),
    ("ai.governance.evaluate", "Evaluate AI versions", "ai", "Run governed AI evaluation suites"),
    ("ai.governance.approve", "Approve AI versions", "ai", "Independently approve evaluated AI versions"),
    ("ai.governance.deploy", "Deploy AI versions", "ai", "Canary, activate, and roll back AI versions"),
    ("ai.governance.audit", "Audit AI governance", "ai", "Read immutable AI evaluation and rollout evidence"),
    ("ai.runtime.read", "Read AI runtime controls", "ai", "Read AI privacy, residency, budget, and circuit health"),
    ("ai.runtime.manage", "Manage AI runtime controls", "ai", "Manage AI data policy, budgets, and provider circuits"),
    ("ai.runtime.audit", "Audit AI runtime usage", "ai", "Read privacy-safe AI usage and cost evidence"),
    ("ai.actions.read", "Read guarded AI actions", "ai", "Read AI action policies, proposals, and execution state"),
    ("ai.actions.propose", "Propose guarded AI actions", "ai", "Create schema-validated AI action proposals"),
    ("ai.actions.approve", "Approve guarded AI actions", "ai", "Approve or reject AI action proposals"),
    ("ai.actions.execute", "Execute guarded AI actions", "ai", "Execute approved AI action proposals"),
    ("ai.actions.rollback", "Roll back guarded AI actions", "ai", "Roll back eligible guarded AI executions"),
    ("ai.actions.manage", "Manage guarded AI actions", "ai", "Manage tenant AI action policy and allowlist"),
    ("notifications.read", "Read notifications", "notifications", "Read notifications"),
    ("notifications.update", "Update notifications", "notifications", "Mark notifications read/unread"),
    ("notifications.manage", "Manage notifications", "notifications", "Manage notifications"),
    ("notifications.templates.read", "Read notification templates", "notifications", "Read notification templates"),
    ("notifications.templates.update", "Update notification templates", "notifications", "Update notification templates"),
    ("notifications.email_log.read", "Read email log", "notifications", "Read mock email log"),
    ("notifications.email_log.retry", "Retry email log", "notifications", "Retry failed email messages"),
    ("notifications.preferences.update", "Update notification preferences", "notifications", "Update own notification preferences"),
    ("email.channel.read", "Read email channels", "email", "Read tenant email channel configuration and health"),
    ("email.channel.manage", "Manage email channels", "email", "Configure, validate, activate, and revoke email channels"),
    ("email.inbound.read", "Read inbound email", "email", "Read inbound email intake and quarantine"),
    ("email.inbound.manage", "Manage inbound email", "email", "Synchronize and reprocess inbound email"),
    ("email.attachments.read", "Read email attachments", "email", "Read released email attachments and quarantine metadata"),
    ("email.attachments.manage", "Manage email attachments", "email", "Release or block quarantined email attachments"),
    ("email.delivery.read", "Read email delivery", "email", "Read outbound queue and provider delivery events"),
    ("email.delivery.manage", "Manage email delivery", "email", "Retry failed outbound email"),
    ("teams.connectors.read", "Read Teams connectors", "teams", "Read tenant Teams connector configuration and health"),
    ("teams.connectors.manage", "Manage Teams connectors", "teams", "Configure, test, activate, pause, and revoke Teams connectors"),
    ("teams.deliveries.read", "Read Teams deliveries", "teams", "Read Teams notification queue and delivery history"),
    ("teams.deliveries.manage", "Manage Teams deliveries", "teams", "Retry failed Teams notifications"),
    ("teams.collaboration.read", "Read Teams collaboration", "teams", "Read major incident Teams room state"),
    ("teams.collaboration.manage", "Manage Teams collaboration", "teams", "Open and close major incident Teams rooms"),
    ("monitoring.connectors.read", "Read monitoring connectors", "monitoring", "Read monitoring source configuration and health"),
    ("monitoring.connectors.manage", "Manage monitoring connectors", "monitoring", "Configure monitoring source authentication and intake controls"),
    ("monitoring.receipts.read", "Read monitoring receipts", "monitoring", "Read webhook intake, normalization, and dead-letter state"),
    ("monitoring.receipts.manage", "Manage monitoring receipts", "monitoring", "Reprocess monitoring webhook dead letters"),
    ("monitoring.events.read", "Read event operations", "monitoring", "Read normalized events, correlation groups, policies, suppressions, and responders"),
    ("monitoring.events.manage", "Manage event operations", "monitoring", "Acknowledge correlated events and evaluate escalations"),
    ("asset.discovery.read", "Read asset discovery", "assets", "Read discovery connectors, runs, health, and stale candidates"),
    ("asset.discovery.manage", "Manage asset discovery", "assets", "Configure, test, activate, pause, and revoke discovery connectors"),
    ("asset.discovery.run", "Run asset discovery", "assets", "Queue and recover asset discovery runs"),
    ("asset.discovery.review", "Review stale assets", "assets", "Dismiss or retire assets missing from complete discovery snapshots"),
    ("integration.platform.accounts.read", "Read service accounts", "integrations", "Read service-account scopes, restrictions, and usage"),
    ("integration.platform.accounts.manage", "Manage service accounts", "integrations", "Create, suspend, and revoke service accounts"),
    ("integration.platform.tokens.read", "Read API token metadata", "integrations", "Read token status and usage without secret material"),
    ("integration.platform.tokens.issue", "Issue API tokens", "integrations", "Issue and rotate scoped service-account tokens"),
    ("integration.platform.tokens.revoke", "Revoke API tokens", "integrations", "Revoke active service-account tokens"),
    ("integration.platform.webhooks.read", "Read outbound webhooks", "integrations", "Read webhook subscriptions and delivery state"),
    ("integration.platform.webhooks.manage", "Manage outbound webhooks", "integrations", "Configure, test, activate, pause, and revoke signed webhooks"),
    ("integration.platform.webhooks.replay", "Replay webhook deliveries", "integrations", "Replay failed and dead-letter webhook deliveries"),
    ("integration.platform.observability.read", "Read integration observability", "integrations", "Read API access logs, delivery health, and integration metrics"),
    ("workflows.read", "Read workflows", "automation", "Read workflow definitions, versions, and catalog"),
    ("workflows.design", "Design workflows", "automation", "Create workflows and edit draft versions"),
    ("workflows.publish", "Publish workflows", "automation", "Publish and rollback immutable workflow versions"),
    ("workflows.execute", "Execute workflows", "automation", "Simulate and start workflow executions"),
    ("workflows.executions.read", "Read workflow executions", "automation", "Read workflow execution state and tamper-evident history"),
    ("workflows.executions.manage", "Manage workflow executions", "automation", "Cancel and replay workflow executions"),
    ("workflows.approvals.read", "Read workflow approvals", "automation", "Read workflow approval tasks"),
    ("workflows.approvals.decide", "Decide workflow approvals", "automation", "Approve or reject workflow approval tasks for the assigned role"),
    ("workflows.approvals.override", "Override workflow approvals", "automation", "Decide workflow approvals assigned to another role"),
    ("workflows.reviews.read", "Read workflow reviews", "automation", "Read workflow publish-review evidence"),
    ("workflows.reviews.request", "Request workflow reviews", "automation", "Submit a valid workflow draft for four-eyes review"),
    ("workflows.reviews.decide", "Decide workflow reviews", "automation", "Approve or reject workflow drafts submitted by another author"),
    ("custom_fields.read", "Read custom fields", "configuration", "Read tenant field sets and immutable schema versions"),
    ("custom_fields.design", "Design custom fields", "configuration", "Create field sets and edit draft schemas"),
    ("custom_fields.publish", "Publish custom fields", "configuration", "Publish typed schema versions and approve breaking changes"),
    ("custom_fields.values.read", "Read custom-field values", "configuration", "Read custom-field values attached to ITSM records"),
    ("custom_fields.values.write", "Write custom-field values", "configuration", "Validate and save custom-field values on ITSM records"),
    ("custom_fields.sensitive.read", "Read sensitive custom fields", "configuration", "Decrypt sensitive custom-field values"),
    ("custom_fields.search", "Search custom fields", "configuration", "Search explicitly searchable custom-field values"),
    ("custom_fields.report", "Report on custom fields", "configuration", "Read explicitly reportable custom-field data"),
    ("configuration.packages.read", "Read configuration packages", "configuration", "Read package manifests, versions, comparisons, and integrity evidence"),
    ("configuration.packages.build", "Build configuration packages", "configuration", "Create packages and capture portable configuration versions"),
    ("configuration.packages.seal", "Seal configuration packages", "configuration", "Validate and cryptographically seal immutable package versions"),
    ("configuration.packages.export", "Export configuration packages", "configuration", "Export signed, secret-free configuration artifacts"),
    ("configuration.packages.import", "Import configuration packages", "configuration", "Verify and import signed configuration artifacts"),
    ("configuration.deployments.read", "Read configuration deployments", "configuration", "Read dry-run plans, approvals, results, and rollback evidence"),
    ("configuration.deployments.plan", "Plan configuration deployments", "configuration", "Create dependency-aware dry-run deployment plans"),
    ("configuration.deployments.approve", "Approve configuration deployments", "configuration", "Independently approve production configuration promotion"),
    ("configuration.deployments.apply", "Apply configuration deployments", "configuration", "Apply validated or approved configuration plans"),
    ("configuration.deployments.rollback", "Rollback configuration deployments", "configuration", "Restore or safely disable promoted configuration"),
    ("admin.users.read", "Read admin users", "admin", "Read users in admin console"),
    ("admin.users.create", "Create admin users", "admin", "Create users in admin console"),
    ("admin.users.update", "Update admin users", "admin", "Update users in admin console"),
    ("admin.roles.read", "Read roles", "admin", "Read role catalog"),
    ("admin.roles.manage", "Manage roles", "admin", "Manage roles"),
    ("admin.permissions.read", "Read permissions", "admin", "Read permissions catalog"),
    ("admin.settings.read", "Read settings", "admin", "Read system settings"),
    ("admin.settings.update", "Update settings", "admin", "Update non-sensitive settings"),
    ("admin.configuration.read", "Read configuration center", "admin", "Read typed configuration readiness and revision history"),
    ("admin.configuration.manage", "Manage configuration center", "admin", "Update validated tenant or global configuration"),
    ("admin.configuration.rollback", "Rollback configuration", "admin", "Restore a typed setting from audited revision evidence"),
    (
        "identity.provisioning.read",
        "Read identity provisioning",
        "identity",
        "Read SCIM connectors, identities, groups, events, and lifecycle status",
    ),
    (
        "identity.provisioning.manage",
        "Manage identity provisioning",
        "identity",
        "Manage connectors, mappings, retries, and joiner/mover/leaver controls",
    ),
    ("security.audit.read", "Read audit logs", "security", "Read audit events"),
    ("security.sessions.read", "Read sessions", "security", "Read session overview"),
    ("security.sessions.manage", "Manage sessions", "security", "Revoke active user sessions"),
    ("security.mfa.read", "Read MFA status", "security", "Read MFA enrollment and policy status"),
    ("security.mfa.manage", "Manage MFA", "security", "Reset MFA for users in the current scope"),
    ("security.login_events.read", "Read login events", "security", "Read login success/fail events"),
    ("analytics.read", "Read analytics", "analytics", "Read analytics and executive dashboards"),
    ("analytics.executive.read", "Read executive analytics", "analytics", "Read executive analytics dashboard"),
    ("analytics.tickets.read", "Read ticket analytics", "analytics", "Read ticket analytics"),
    ("analytics.sla.read", "Read SLA analytics", "analytics", "Read SLA analytics"),
    ("analytics.assets.read", "Read asset analytics", "analytics", "Read asset analytics"),
    ("analytics.knowledge.read", "Read knowledge analytics", "analytics", "Read knowledge analytics"),
    ("analytics.ai.read", "Read AI analytics", "analytics", "Read AI analytics"),
    ("analytics.security.read", "Read security analytics", "analytics", "Read security analytics"),
    ("analytics.automation.read", "Read automation analytics", "analytics", "Read automation analytics"),
    ("reports.read", "Read reports", "reports", "Read saved reports and snapshots"),
    ("reports.create", "Create reports", "reports", "Create saved reports and snapshots"),
    ("reports.run", "Run reports", "reports", "Generate report snapshots from saved reports"),
    ("reports.export", "Export reports", "reports", "Export analytics/report payloads"),
    ("integrations.read", "Read integrations", "integrations", "Read external systems and providers"),
    ("integrations.create", "Create integrations", "integrations", "Create external systems"),
    ("integrations.update", "Update integrations", "integrations", "Update and enable/disable external systems"),
    ("integrations.delete", "Delete integrations", "integrations", "Delete external integration entities"),
    ("integrations.manage", "Manage integrations", "integrations", "Legacy permission for integration management"),
    ("integrations.health_check", "Health check integrations", "integrations", "Run integration health checks"),
    ("integrations.test_connection", "Test integration connections", "integrations", "Run mock integration test connections"),
    ("integrations.export", "Export via integrations", "integrations", "Run integration export requests"),
    ("integrations.import", "Run integration imports", "integrations", "Legacy import permission alias"),
    ("integrations.import_jobs.read", "Read import jobs", "integrations", "Read integration import jobs"),
    ("integrations.import_jobs.run", "Run import jobs", "integrations", "Create and execute integration import jobs"),
    ("integrations.credentials.read", "Read credentials", "integrations", "Read integration credentials metadata"),
    ("integrations.credentials.manage", "Manage credentials", "integrations", "Create rotate and delete integration credentials"),
    ("integrations.webhooks.read", "Read integration webhooks", "integrations", "Read webhook endpoints"),
    ("integrations.webhooks.manage", "Manage integration webhooks", "integrations", "Create update and simulate webhooks"),
    ("integrations.events.read", "Read integration events", "integrations", "Read integration event logs"),
    ("integrations.events.retry", "Retry integration events", "integrations", "Retry failed integration events"),
    ("integrations.mappings.read", "Read integration mappings", "integrations", "Read integration mappings"),
    ("integrations.mappings.manage", "Manage integration mappings", "integrations", "Create and update integration mappings"),
    ("automation.rules.read", "Read automation rules", "automation", "Read workflow automation rules"),
    ("automation.rules.manage", "Manage automation rules", "automation", "Create and update workflow automation rules"),
    ("automation.rules.execute", "Execute automation rules", "automation", "Run manual and trigger-based automation"),
    ("automation.read", "Read automation", "automation", "Read automation module"),
    ("automation.create", "Create automation", "automation", "Create automation entities"),
    ("automation.update", "Update automation", "automation", "Update automation entities"),
    ("automation.delete", "Delete automation", "automation", "Delete automation entities"),
    ("automation.run", "Run automation", "automation", "Run automation rules and executions"),
    ("automation.dry_run", "Dry-run automation", "automation", "Run automation dry-runs without data changes"),
    ("automation.executions.retry", "Retry automation executions", "automation", "Retry failed automation executions"),
    ("automation.runbooks.create", "Create runbooks", "automation", "Create runbooks"),
    ("automation.runbooks.update", "Update runbooks", "automation", "Update runbooks"),
    ("automation.runbooks.run", "Run runbooks", "automation", "Execute runbooks"),
    ("automation.approvals.decide", "Decide approvals", "automation", "Approve or reject automation approvals"),
    ("automation.manage", "Manage automation", "automation", "Full automation management"),
    ("automation.runs.read", "Read automation runs", "automation", "Read automation execution runs"),
    ("automation.logs.read", "Read automation logs", "automation", "Read automation action logs"),
    ("automation.runbooks.read", "Read runbooks", "automation", "Read workflow runbooks"),
    ("automation.runbooks.manage", "Manage runbooks", "automation", "Create and update workflow runbooks"),
    ("automation.executions.read", "Read runbook executions", "automation", "Read runbook execution timeline"),
    ("automation.executions.manage", "Manage runbook executions", "automation", "Start and update runbook executions"),
    ("automation.approvals.read", "Read approval requests", "automation", "Read workflow approval requests"),
    ("automation.approvals.manage", "Manage approval requests", "automation", "Approve and reject workflow requests"),
    ("automation.suggestions.read", "Read automation suggestions", "automation", "Read runbook and automation suggestions"),
    ("search.use", "Use global search", "search", "Search only records already visible to the current user"),
    ("search.views.manage", "Manage saved search views", "search", "Create and manage personal saved search views"),
    ("search.views.share", "Share saved search views", "search", "Share saved search views with tenant roles"),
    ("tenant.read", "Read tenants", "tenant", "Read tenants"),
    ("tenant.manage", "Manage tenants", "tenant", "Manage tenants"),
    ("tenant.profile.read", "Read tenant profile", "tenant", "Read the current organization profile"),
    ("tenant.profile.manage", "Manage tenant profile", "tenant", "Update the current organization profile"),
    ("tenant.experience.read", "Read tenant experience", "tenant", "Read tenant branding, locale, timezone, and terminology"),
    ("tenant.experience.manage", "Manage tenant experience", "tenant", "Update validated tenant branding and localization"),
    ("tenant.experience.rollback", "Rollback tenant experience", "tenant", "Restore tenant experience from immutable revision evidence"),
    ("tenant.translations.read", "Read tenant translations", "tenant", "Read localized content lifecycle and integrity evidence"),
    ("tenant.translations.manage", "Manage tenant translations", "tenant", "Create, edit, and submit localized content drafts"),
    ("tenant.translations.publish", "Publish tenant translations", "tenant", "Review and publish localized content variants"),
    ("data.retention.read", "Read data governance", "data_governance", "Read retention policies, legal holds, deletion plans, and evidence"),
    ("data.retention.manage", "Manage retention policies", "data_governance", "Manage tenant retention policies within global minimums"),
    ("data.legal_hold.read", "Read legal holds", "data_governance", "Read tenant legal holds"),
    ("data.legal_hold.manage", "Manage legal holds", "data_governance", "Create and independently release legal holds"),
    ("data.deletion.request", "Request controlled deletion", "data_governance", "Preview and submit retention or tenant deletion plans"),
    ("data.deletion.approve", "Approve controlled deletion", "data_governance", "Independently approve or reject deletion plans"),
    ("data.deletion.execute", "Execute controlled deletion", "data_governance", "Execute an approved plan with exact confirmation"),
    ("data.export", "Export tenant data", "data_governance", "Export a secret-free tenant archive with integrity manifest"),
]


ROLE_DEFS = {
    "saas_root": {
        "name": "SaaS Root",
        "scope": "global",
        "description": "Global root operator",
        "is_system": True,
        "permissions": [code for code, *_ in PERMISSIONS],
    },
    "organization_admin": {
        "name": "Organization Admin",
        "scope": "tenant",
        "description": "Organization administrator",
        "is_system": True,
        "permissions": [
            "tickets.read",
            "tickets.create",
            "tickets.update",
            "tickets.assign",
            "tickets.self_assign",
            "tickets.scope.all",
            "tickets.comment",
            "tickets.close",
            "major_incidents.read",
            "major_incidents.manage",
            "catalog.read",
            "catalog.manage",
            "catalog.publish",
            "requests.read",
            "requests.scope.all",
            "requests.create",
            "requests.manage",
            "requests.approve",
            "requests.fulfill",
            "requests.comment",
            "assets.read",
            "assets.create",
            "assets.update",
            "assets.assign",
            "assets.move",
            "assets.verify",
            "assets.dispose",
            "assets.restore",
            "assets.history.read",
            "assets.import",
            "assets.import.preview",
            "assets.import.commit",
            "assets.import.read_batches",
            "sam.read",
            "sam.catalog.manage",
            "sam.licenses.manage",
            "sam.installations.manage",
            "sam.reconcile",
            "changes.read",
            "changes.create",
            "changes.update",
            "changes.submit",
            "changes.approve",
            "changes.schedule",
            "changes.execute",
            "problems.read",
            "problems.create",
            "problems.update",
            "problems.investigate",
            "problems.publish_known_error",
            "problems.resolve",
            "sla.read",
            "sla.manage",
            "knowledge.read",
            "knowledge.create",
            "knowledge.update",
            "knowledge.publish",
            "knowledge.archive",
            "knowledge.feedback",
            "knowledge.create_from_ticket",
            "knowledge.usage.read",
            "knowledge.usage.write",
            "knowledge.attach.read",
            "knowledge.attach",
            "ai.use",
            "ai.view_suggestions",
            "ai.accept_suggestion",
            "ai.reject_suggestion",
            "ai.rag.use",
            "ai.rag.read",
            "ai.rag.manage",
            "ai.rag.audit",
            "ai.governance.read",
            "ai.governance.manage",
            "ai.governance.evaluate",
            "ai.governance.approve",
            "ai.governance.deploy",
            "ai.governance.audit",
            "ai.runtime.read",
            "ai.runtime.manage",
            "ai.runtime.audit",
            "ai.actions.read",
            "ai.actions.propose",
            "ai.actions.approve",
            "ai.actions.execute",
            "ai.actions.rollback",
            "ai.actions.manage",
            "notifications.read",
            "notifications.update",
            "notifications.manage",
            "notifications.templates.read",
            "notifications.templates.update",
            "notifications.email_log.read",
            "notifications.email_log.retry",
            "notifications.preferences.update",
            "email.channel.read",
            "email.channel.manage",
            "email.inbound.read",
            "email.inbound.manage",
            "email.attachments.read",
            "email.attachments.manage",
            "email.delivery.read",
            "email.delivery.manage",
            "teams.connectors.read",
            "teams.connectors.manage",
            "teams.deliveries.read",
            "teams.deliveries.manage",
            "teams.collaboration.read",
            "teams.collaboration.manage",
            "monitoring.connectors.read",
            "monitoring.connectors.manage",
            "monitoring.receipts.read",
            "monitoring.receipts.manage",
            "monitoring.events.read",
            "monitoring.events.manage",
            "asset.discovery.read",
            "asset.discovery.manage",
            "asset.discovery.run",
            "asset.discovery.review",
            "integration.platform.accounts.read",
            "integration.platform.accounts.manage",
            "integration.platform.tokens.read",
            "integration.platform.tokens.issue",
            "integration.platform.tokens.revoke",
            "integration.platform.webhooks.read",
            "integration.platform.webhooks.manage",
            "integration.platform.webhooks.replay",
            "integration.platform.observability.read",
            "workflows.read",
            "workflows.design",
            "workflows.publish",
            "workflows.execute",
            "workflows.executions.read",
            "workflows.executions.manage",
            "workflows.approvals.read",
            "workflows.approvals.decide",
            "workflows.approvals.override",
            "workflows.reviews.read",
            "workflows.reviews.request",
            "workflows.reviews.decide",
            "custom_fields.read",
            "custom_fields.design",
            "custom_fields.publish",
            "custom_fields.values.read",
            "custom_fields.values.write",
            "custom_fields.sensitive.read",
            "custom_fields.search",
            "custom_fields.report",
            "configuration.packages.read",
            "configuration.packages.build",
            "configuration.packages.seal",
            "configuration.packages.export",
            "configuration.packages.import",
            "configuration.deployments.read",
            "configuration.deployments.plan",
            "configuration.deployments.approve",
            "configuration.deployments.apply",
            "configuration.deployments.rollback",
            "admin.users.read",
            "admin.users.create",
            "admin.users.update",
            "admin.roles.read",
            "admin.roles.manage",
            "admin.permissions.read",
            "admin.settings.read",
            "admin.settings.update",
            "admin.configuration.read",
            "admin.configuration.manage",
            "admin.configuration.rollback",
            "identity.provisioning.read",
            "identity.provisioning.manage",
            "security.audit.read",
            "security.sessions.read",
            "security.sessions.manage",
            "security.mfa.read",
            "security.mfa.manage",
            "security.login_events.read",
            "analytics.read",
            "analytics.executive.read",
            "analytics.tickets.read",
            "analytics.sla.read",
            "analytics.assets.read",
            "analytics.knowledge.read",
            "analytics.ai.read",
            "analytics.security.read",
            "analytics.automation.read",
            "reports.read",
            "reports.create",
            "reports.run",
            "reports.export",
            "integrations.read",
            "integrations.create",
            "integrations.update",
            "integrations.delete",
            "integrations.manage",
            "integrations.health_check",
            "integrations.test_connection",
            "integrations.export",
            "integrations.import",
            "integrations.import_jobs.read",
            "integrations.import_jobs.run",
            "integrations.credentials.read",
            "integrations.credentials.manage",
            "integrations.webhooks.read",
            "integrations.webhooks.manage",
            "integrations.events.read",
            "integrations.events.retry",
            "integrations.mappings.read",
            "integrations.mappings.manage",
            "automation.rules.read",
            "automation.rules.manage",
            "automation.rules.execute",
            "automation.runs.read",
            "automation.logs.read",
            "automation.runbooks.read",
            "automation.runbooks.manage",
            "automation.executions.read",
            "automation.executions.manage",
            "automation.approvals.read",
            "automation.approvals.manage",
            "automation.suggestions.read",
            "tenant.profile.read",
            "tenant.profile.manage",
        ],
    },
    "it_manager": {
        "name": "IT Manager",
        "scope": "tenant",
        "description": "Operations manager",
        "is_system": True,
        "permissions": [
            "tickets.read",
            "tickets.create",
            "tickets.update",
            "tickets.assign",
            "tickets.self_assign",
            "tickets.scope.all",
            "tickets.comment",
            "tickets.close",
            "major_incidents.read",
            "major_incidents.manage",
            "catalog.read",
            "catalog.manage",
            "catalog.publish",
            "requests.read",
            "requests.scope.all",
            "requests.create",
            "requests.manage",
            "requests.approve",
            "requests.fulfill",
            "requests.comment",
            "assets.read",
            "assets.create",
            "assets.update",
            "assets.assign",
            "assets.move",
            "assets.verify",
            "assets.dispose",
            "assets.restore",
            "assets.history.read",
            "assets.verify",
            "assets.history.read",
            "assets.import",
            "assets.import.preview",
            "assets.import.commit",
            "assets.import.read_batches",
            "sam.read",
            "sam.catalog.manage",
            "sam.licenses.manage",
            "sam.installations.manage",
            "sam.reconcile",
            "changes.read",
            "changes.create",
            "changes.update",
            "changes.submit",
            "changes.approve",
            "changes.schedule",
            "changes.execute",
            "problems.read",
            "problems.create",
            "problems.update",
            "problems.investigate",
            "problems.publish_known_error",
            "problems.resolve",
            "sla.read",
            "knowledge.read",
            "knowledge.publish",
            "knowledge.archive",
            "knowledge.feedback",
            "knowledge.create_from_ticket",
            "knowledge.usage.read",
            "knowledge.usage.write",
            "knowledge.attach.read",
            "knowledge.attach",
            "ai.use",
            "ai.view_suggestions",
            "ai.accept_suggestion",
            "ai.reject_suggestion",
            "ai.rag.use",
            "ai.rag.read",
            "ai.rag.manage",
            "ai.rag.audit",
            "ai.governance.read",
            "ai.governance.manage",
            "ai.governance.evaluate",
            "ai.governance.approve",
            "ai.governance.deploy",
            "ai.governance.audit",
            "ai.runtime.read",
            "ai.runtime.manage",
            "ai.runtime.audit",
            "ai.actions.read",
            "ai.actions.propose",
            "ai.actions.approve",
            "ai.actions.execute",
            "ai.actions.rollback",
            "ai.actions.manage",
            "notifications.read",
            "notifications.update",
            "notifications.templates.read",
            "notifications.email_log.read",
            "notifications.preferences.update",
            "email.channel.read",
            "email.inbound.read",
            "email.inbound.manage",
            "email.attachments.read",
            "email.delivery.read",
            "teams.connectors.read",
            "teams.deliveries.read",
            "teams.deliveries.manage",
            "teams.collaboration.read",
            "teams.collaboration.manage",
            "monitoring.connectors.read",
            "monitoring.connectors.manage",
            "monitoring.receipts.read",
            "monitoring.receipts.manage",
            "monitoring.events.read",
            "monitoring.events.manage",
            "asset.discovery.read",
            "asset.discovery.manage",
            "asset.discovery.run",
            "asset.discovery.review",
            "integration.platform.accounts.read",
            "integration.platform.accounts.manage",
            "integration.platform.tokens.read",
            "integration.platform.tokens.issue",
            "integration.platform.tokens.revoke",
            "integration.platform.webhooks.read",
            "integration.platform.webhooks.manage",
            "integration.platform.webhooks.replay",
            "integration.platform.observability.read",
            "workflows.read",
            "workflows.design",
            "workflows.publish",
            "workflows.execute",
            "workflows.executions.read",
            "workflows.executions.manage",
            "workflows.approvals.read",
            "workflows.approvals.decide",
            "workflows.reviews.read",
            "workflows.reviews.request",
            "workflows.reviews.decide",
            "custom_fields.read",
            "custom_fields.design",
            "custom_fields.publish",
            "custom_fields.values.read",
            "custom_fields.values.write",
            "custom_fields.sensitive.read",
            "custom_fields.search",
            "custom_fields.report",
            "configuration.packages.read",
            "configuration.packages.build",
            "configuration.packages.seal",
            "configuration.packages.export",
            "configuration.packages.import",
            "configuration.deployments.read",
            "configuration.deployments.plan",
            "configuration.deployments.approve",
            "configuration.deployments.apply",
            "configuration.deployments.rollback",
            "admin.configuration.read",
            "analytics.read",
            "analytics.executive.read",
            "analytics.tickets.read",
            "analytics.sla.read",
            "analytics.assets.read",
            "analytics.knowledge.read",
            "analytics.ai.read",
            "analytics.security.read",
            "analytics.automation.read",
            "reports.read",
            "reports.create",
            "reports.run",
            "reports.export",
            "integrations.read",
            "integrations.create",
            "integrations.update",
            "integrations.manage",
            "integrations.health_check",
            "integrations.test_connection",
            "integrations.export",
            "integrations.import",
            "integrations.import_jobs.read",
            "integrations.import_jobs.run",
            "integrations.credentials.read",
            "integrations.credentials.manage",
            "integrations.webhooks.read",
            "integrations.webhooks.manage",
            "integrations.events.read",
            "integrations.events.retry",
            "integrations.mappings.read",
            "integrations.mappings.manage",
            "automation.rules.read",
            "automation.rules.manage",
            "automation.rules.execute",
            "automation.runs.read",
            "automation.logs.read",
            "automation.runbooks.read",
            "automation.runbooks.manage",
            "automation.executions.read",
            "automation.executions.manage",
            "automation.approvals.read",
            "automation.approvals.manage",
            "automation.suggestions.read",
        ],
    },
    "it_agent": {
        "name": "IT Agent",
        "scope": "tenant",
        "description": "Ticket executor",
        "is_system": True,
        "permissions": [
            "tickets.read",
            "tickets.update",
            "tickets.self_assign",
            "tickets.scope.assigned",
            "tickets.comment",
            "major_incidents.read",
            "major_incidents.manage",
            "catalog.read",
            "requests.read",
            "requests.scope.all",
            "requests.fulfill",
            "requests.comment",
            "assets.read",
            "assets.verify",
            "assets.import.preview",
            "assets.import.read_batches",
            "sam.read",
            "changes.read",
            "changes.create",
            "changes.update",
            "changes.submit",
            "changes.execute",
            "problems.read",
            "problems.create",
            "problems.update",
            "problems.investigate",
            "notifications.read",
            "notifications.update",
            "notifications.preferences.update",
            "email.inbound.read",
            "email.attachments.read",
            "teams.connectors.read",
            "teams.deliveries.read",
            "teams.collaboration.read",
            "monitoring.connectors.read",
            "monitoring.receipts.read",
            "monitoring.events.read",
            "monitoring.events.manage",
            "asset.discovery.read",
            "integration.platform.accounts.read",
            "integration.platform.webhooks.read",
            "integration.platform.observability.read",
            "workflows.read",
            "workflows.execute",
            "workflows.executions.read",
            "workflows.approvals.read",
            "workflows.approvals.decide",
            "workflows.reviews.read",
            "custom_fields.read",
            "custom_fields.values.read",
            "custom_fields.values.write",
            "custom_fields.search",
            "ai.actions.read",
            "ai.actions.propose",
            "ai.rag.use",
            "ai.rag.read",
            "ai.view_suggestions",
            "knowledge.feedback",
            "knowledge.read",
            "knowledge.usage.write",
            "knowledge.attach.read",
            "knowledge.attach",
            "ai.accept_suggestion",
            "ai.reject_suggestion",
            "automation.rules.read",
            "automation.runs.read",
            "automation.logs.read",
            "automation.runbooks.read",
            "automation.executions.read",
            "automation.executions.manage",
            "automation.approvals.read",
            "automation.suggestions.read",
        ],
    },
    "requester": {
        "name": "Requester",
        "scope": "tenant",
        "description": "Business requester",
        "is_system": True,
        "permissions": [
            "tickets.read",
            "tickets.create",
            "tickets.scope.requester",
            "tickets.comment",
            "catalog.read",
            "requests.read",
            "requests.scope.requester",
            "requests.create",
            "requests.comment",
            "knowledge.read",
            "knowledge.feedback",
            "ai.rag.use",
            "ai.rag.read",
            "notifications.read",
            "notifications.update",
            "notifications.preferences.update",
        ],
    },
    "security_officer": {
        "name": "Security Officer",
        "scope": "tenant",
        "description": "Security analyst",
        "is_system": True,
        "permissions": [
            "security.audit.read",
            "security.sessions.read",
            "security.sessions.manage",
            "security.mfa.read",
            "security.mfa.manage",
            "security.login_events.read",
            "identity.provisioning.read",
            "tickets.read",
            "tickets.scope.all",
            "major_incidents.read",
            "catalog.read",
            "requests.read",
            "requests.scope.all",
            "changes.read",
            "problems.read",
            "knowledge.read",
            "ai.rag.use",
            "ai.rag.read",
            "ai.rag.audit",
            "ai.governance.read",
            "ai.governance.audit",
            "ai.runtime.read",
            "ai.runtime.audit",
            "ai.actions.read",
            "notifications.read",
            "notifications.email_log.read",
            "email.channel.read",
            "email.inbound.read",
            "email.inbound.manage",
            "email.attachments.read",
            "email.attachments.manage",
            "email.delivery.read",
            "teams.connectors.read",
            "teams.connectors.manage",
            "teams.deliveries.read",
            "teams.deliveries.manage",
            "teams.collaboration.read",
            "teams.collaboration.manage",
            "monitoring.connectors.read",
            "monitoring.connectors.manage",
            "monitoring.receipts.read",
            "monitoring.receipts.manage",
            "monitoring.events.read",
            "asset.discovery.read",
            "integration.platform.accounts.read",
            "integration.platform.tokens.read",
            "integration.platform.webhooks.read",
            "integration.platform.observability.read",
            "workflows.read",
            "workflows.executions.read",
            "workflows.approvals.read",
            "workflows.reviews.read",
            "custom_fields.read",
            "custom_fields.values.read",
            "custom_fields.sensitive.read",
            "custom_fields.search",
            "custom_fields.report",
            "configuration.packages.read",
            "configuration.deployments.read",
            "admin.configuration.read",
            "analytics.read",
            "analytics.executive.read",
            "analytics.security.read",
            "reports.read",
            "integrations.read",
            "integrations.import_jobs.read",
            "integrations.credentials.read",
            "integrations.events.read",
            "integrations.webhooks.read",
            "integrations.mappings.read",
            "automation.rules.read",
            "automation.runs.read",
            "automation.logs.read",
            "automation.runbooks.read",
            "automation.executions.read",
            "automation.approvals.read",
            "automation.suggestions.read",
        ],
    },
    "knowledge_manager": {
        "name": "Knowledge Manager",
        "scope": "tenant",
        "description": "Knowledge owner",
        "is_system": True,
        "permissions": [
            "problems.read",
            "problems.publish_known_error",
            "knowledge.read",
            "knowledge.create",
            "knowledge.update",
            "knowledge.publish",
            "knowledge.archive",
            "knowledge.feedback",
            "knowledge.create_from_ticket",
            "knowledge.usage.read",
            "knowledge.usage.write",
            "knowledge.attach.read",
            "ai.rag.use",
            "ai.rag.read",
            "ai.rag.manage",
            "ai.governance.read",
            "ai.governance.manage",
            "ai.governance.evaluate",
            "ai.governance.approve",
            "ai.runtime.read",
            "ai.actions.read",
            "ai.actions.propose",
            "ai.view_suggestions",
            "notifications.read",
        ],
    },
}

for _search_role_code in (
    "organization_admin",
    "it_manager",
    "it_agent",
    "requester",
    "security_officer",
    "knowledge_manager",
):
    ROLE_DEFS[_search_role_code]["permissions"].extend(
        ["search.use", "search.views.manage"]
    )

for _search_sharing_role_code in (
    "organization_admin",
    "it_manager",
    "knowledge_manager",
):
    ROLE_DEFS[_search_sharing_role_code]["permissions"].append("search.views.share")

for _ticket_bulk_role_code in (
    "organization_admin",
    "it_manager",
    "it_agent",
):
    ROLE_DEFS[_ticket_bulk_role_code]["permissions"].append(
        "tickets.bulk.execute"
    )

for _ticket_participant_reader_role_code in (
    "organization_admin",
    "it_manager",
    "it_agent",
    "requester",
):
    ROLE_DEFS[_ticket_participant_reader_role_code]["permissions"].extend(
        ["tickets.participants.read", "tickets.watch"]
    )

for _ticket_participant_manager_role_code in (
    "organization_admin",
    "it_manager",
    "it_agent",
):
    ROLE_DEFS[_ticket_participant_manager_role_code]["permissions"].append(
        "tickets.participants.manage"
    )

for _ticket_on_behalf_role_code in (
    "organization_admin",
    "it_manager",
):
    ROLE_DEFS[_ticket_on_behalf_role_code]["permissions"].append(
        "tickets.create.on_behalf"
    )

ROLE_DEFS["it_agent"]["permissions"].extend(
    ["tickets.create", "tickets.create.on_behalf"]
)

for _ticket_duplicate_reader_role_code in (
    "organization_admin",
    "it_manager",
    "it_agent",
):
    ROLE_DEFS[_ticket_duplicate_reader_role_code]["permissions"].extend(
        ["tickets.duplicates.read", "tickets.duplicates.manage", "tickets.split"]
    )

for _ticket_merge_role_code in ("organization_admin", "it_manager"):
    ROLE_DEFS[_ticket_merge_role_code]["permissions"].append("tickets.merge")

for _tenant_experience_role_code in (
    "organization_admin",
    "it_manager",
    "it_agent",
    "requester",
    "security_officer",
    "knowledge_manager",
):
    ROLE_DEFS[_tenant_experience_role_code]["permissions"].append(
        "tenant.experience.read"
    )

ROLE_DEFS["organization_admin"]["permissions"].extend(
    [
        "tenant.experience.manage",
        "tenant.experience.rollback",
        "tenant.translations.read",
        "tenant.translations.manage",
        "tenant.translations.publish",
        "data.retention.read",
        "data.retention.manage",
        "data.legal_hold.read",
        "data.legal_hold.manage",
        "data.deletion.request",
        "data.deletion.approve",
        "data.deletion.execute",
        "data.export",
    ]
)

ROLE_DEFS["knowledge_manager"]["permissions"].extend(
    [
        "tenant.translations.read",
        "tenant.translations.manage",
        "tenant.translations.publish",
    ]
)

ROLE_DEFS["it_manager"]["permissions"].append("tenant.translations.read")
ROLE_DEFS["it_manager"]["permissions"].extend(
    ["data.retention.read", "data.legal_hold.read", "data.deletion.request"]
)
ROLE_DEFS["security_officer"]["permissions"].extend(
    [
        "data.retention.read",
        "data.legal_hold.read",
        "data.legal_hold.manage",
        "data.deletion.approve",
    ]
)


SETTING_DEFS = [
    ("password_min_length", "10", "Minimum password length", False),
    ("session_timeout_minutes", "60", "User session timeout in minutes", False),
    ("sla_warning_threshold", "30", "SLA warning threshold in minutes", False),
    ("ai_copilot_enabled", "true", "Enable AI Copilot features", False),
    ("email_notifications_enabled", "true", "Enable notification email logic", False),
    ("mock_email_provider_enabled", "true", "Use mock email provider", False),
    ("audit_retention_days", "180", "Audit retention period in days", False),
    ("knowledge_publication_required", "true", "Require explicit publication flow", False),
]


INTEGRATION_SYSTEM_DEFS = [
    ("zimbra_main", "Zimbra Mail Server", "zimbra", "https://mock-zimbra.sbs.local", "demo", True, "Primary mock mail platform."),
    ("ldap_main", "LDAP Directory", "ldap", "ldap://mock-ldap.sbs.local", "demo", True, "Mock campus directory."),
    ("ad_main", "Active Directory", "active_directory", "ldaps://mock-ad.sbs.local", "planned", False, "Planned Active Directory bridge."),
    ("smtp_main", "SMTP Gateway", "smtp", "smtp://mock-smtp.sbs.local", "demo", True, "Mock outbound messaging gateway."),
    ("platonus_main", "Platonus SIS", "platonus", "https://mock-platonus.sbs.local", "demo", True, "Mock academic information system."),
    ("moodle_main", "Moodle LMS", "moodle", "https://mock-moodle.sbs.local", "demo", True, "Mock learning management system."),
    ("telegram_bot", "Telegram Bot", "telegram", "https://mock-telegram.sbs.local", "planned", False, "Future Telegram messaging integration."),
    ("whatsapp_gateway", "WhatsApp Gateway", "whatsapp", "https://mock-whatsapp.sbs.local", "planned", False, "Future WhatsApp messaging integration."),
]


DEMO_CATALOG_DEFS = [
    {
        "category": ("ACCESS", "Доступ и учётные записи", "Корпоративный доступ, VPN и права пользователей", 10),
        "service": ("IDENTITY_ACCESS", "Управление доступом", "Запросы на подключение и изменение корпоративного доступа"),
        "offering": ("STANDARD_ACCESS", "Стандартное предоставление доступа", "Выполнение запроса группой Identity & Access", 480),
        "items": [
            {
                "code": "REMOTE_VPN_REQUEST",
                "name": "Доступ к корпоративному VPN",
                "short_description": "Подключение сотрудника к защищённому удалённому доступу.",
                "description": "Оформите запрос на временный или постоянный доступ к корпоративному VPN. Заявка проходит согласование и передаётся группе Identity & Access.",
                "support_group": "Identity & Access",
                "expected_delivery_minutes": 480,
                "approval_required": True,
                "risk_level": "MEDIUM",
                "form": {
                    "title": "Данные для подключения VPN",
                    "introduction": "Укажите требуемый срок доступа и рабочее обоснование.",
                    "sections": [{"id": "access", "title": "Параметры доступа", "description": "", "order": 10}],
                    "fields": [
                        {"key": "access_period", "label": "Срок доступа", "type": "select", "section_id": "access", "required": True, "help_text": "", "placeholder": "Выберите срок", "options": [{"value": "temporary", "label": "Временный"}, {"value": "permanent", "label": "Постоянный"}], "validations": {}},
                        {"key": "business_justification", "label": "Рабочее обоснование", "type": "textarea", "section_id": "access", "required": True, "help_text": "Опишите задачи, для которых необходим VPN.", "placeholder": "Например: удалённая работа с корпоративными системами", "options": [], "validations": {"min_length": 10, "max_length": 1000}},
                    ],
                },
            }
        ],
    },
    {
        "category": ("WORKPLACE", "Рабочее место", "Оборудование и программное обеспечение сотрудников", 20),
        "service": ("WORKPLACE_SUPPORT", "Поддержка рабочего места", "Подготовка оборудования и установка программного обеспечения"),
        "offering": ("STANDARD_WORKPLACE", "Стандартное рабочее место", "Обслуживание стандартного оборудования и ПО", 1440),
        "items": [
            {
                "code": "SOFTWARE_INSTALLATION_REQUEST",
                "name": "Установка программного обеспечения",
                "short_description": "Установка согласованного программного обеспечения на рабочее устройство.",
                "description": "Укажите программу и устройство. Service Desk проверит лицензию, совместимость и выполнит установку либо предложит разрешённую альтернативу.",
                "support_group": "Service Desk",
                "expected_delivery_minutes": 1440,
                "approval_required": False,
                "risk_level": "LOW",
                "form": {
                    "title": "Данные для установки ПО",
                    "introduction": "Укажите программу, устройство и рабочую необходимость.",
                    "sections": [{"id": "software", "title": "Программное обеспечение", "description": "", "order": 10}],
                    "fields": [
                        {"key": "software_name", "label": "Название программы", "type": "text", "section_id": "software", "required": True, "help_text": "", "placeholder": "Например: Adobe Acrobat Reader", "options": [], "validations": {"min_length": 2, "max_length": 200}},
                        {"key": "asset_tag", "label": "Инвентарный номер устройства", "type": "text", "section_id": "software", "required": False, "help_text": "Если номер неизвестен, оставьте поле пустым.", "placeholder": "AST-0001", "options": [], "validations": {"max_length": 100}},
                        {"key": "business_justification", "label": "Рабочее обоснование", "type": "textarea", "section_id": "software", "required": True, "help_text": "", "placeholder": "Для каких задач нужна программа", "options": [], "validations": {"min_length": 10, "max_length": 1000}},
                    ],
                },
            },
            {
                "code": "EMPLOYEE_LAPTOP_REQUEST",
                "name": "Ноутбук для сотрудника",
                "short_description": "Выдача нового или замена существующего рабочего ноутбука.",
                "description": "Запросите стандартный, мобильный или производительный ноутбук. Заявка требует согласования руководителя и проверки наличия оборудования.",
                "support_group": "Workplace Operations",
                "expected_delivery_minutes": 4320,
                "approval_required": True,
                "risk_level": "MEDIUM",
                "form": {
                    "title": "Параметры рабочего ноутбука",
                    "introduction": "Укажите сотрудника, профиль оборудования и причину выдачи.",
                    "sections": [{"id": "equipment", "title": "Оборудование", "description": "", "order": 10}],
                    "fields": [
                        {"key": "employee_email", "label": "Почта сотрудника", "type": "email", "section_id": "equipment", "required": True, "help_text": "", "placeholder": "employee@company.kz", "options": [], "validations": {}},
                        {"key": "equipment_profile", "label": "Профиль ноутбука", "type": "select", "section_id": "equipment", "required": True, "help_text": "", "placeholder": "Выберите профиль", "options": [{"value": "standard", "label": "Стандартный"}, {"value": "mobile", "label": "Мобильный"}, {"value": "power", "label": "Производительный"}], "validations": {}},
                        {"key": "business_justification", "label": "Причина выдачи", "type": "textarea", "section_id": "equipment", "required": True, "help_text": "", "placeholder": "Новый сотрудник, замена или изменение задач", "options": [], "validations": {"min_length": 10, "max_length": 1000}},
                    ],
                },
                "attachments": {"enabled": True, "required": False, "max_files": 3, "max_size_mb": 10, "allowed_extensions": ["pdf", "png", "jpg", "docx"]},
            },
        ],
    },
    {
        "category": ("COLLABORATION", "Почта и совместная работа", "Общие почтовые ресурсы и инструменты командной работы", 30),
        "service": ("MESSAGING", "Корпоративная почта", "Общие почтовые ящики, группы и списки рассылки"),
        "offering": ("STANDARD_MESSAGING", "Стандартные почтовые операции", "Настройка почтовых ресурсов в рабочее время", 1440),
        "items": [
            {
                "code": "SHARED_MAILBOX_REQUEST",
                "name": "Общий почтовый ящик",
                "short_description": "Создание общего почтового ящика для отдела или проекта.",
                "description": "Укажите желаемое имя, владельца и назначение общего почтового ящика. После согласования команда Messaging создаст ресурс и выдаст доступ.",
                "support_group": "Messaging",
                "expected_delivery_minutes": 1440,
                "approval_required": True,
                "risk_level": "LOW",
                "form": {
                    "title": "Параметры общего почтового ящика",
                    "introduction": "Укажите имя, ответственного владельца и назначение ресурса.",
                    "sections": [{"id": "mailbox", "title": "Почтовый ресурс", "description": "", "order": 10}],
                    "fields": [
                        {"key": "mailbox_name", "label": "Желаемое имя", "type": "text", "section_id": "mailbox", "required": True, "help_text": "", "placeholder": "project-team", "options": [], "validations": {"min_length": 3, "max_length": 100}},
                        {"key": "owner_email", "label": "Почта владельца", "type": "email", "section_id": "mailbox", "required": True, "help_text": "Владелец отвечает за состав участников.", "placeholder": "owner@company.kz", "options": [], "validations": {}},
                        {"key": "purpose", "label": "Назначение", "type": "textarea", "section_id": "mailbox", "required": True, "help_text": "", "placeholder": "Опишите отдел, проект или процесс", "options": [], "validations": {"min_length": 10, "max_length": 1000}},
                    ],
                },
            }
        ],
    },
]


def _seed_demo_catalog(
    db: Session,
    *,
    tenant: Tenant,
    owner: User,
    now: datetime,
) -> None:
    categories = {
        item.code: item
        for item in db.scalars(
            select(ServiceCategory).where(ServiceCategory.tenant_id == tenant.id)
        ).all()
    }
    services = {
        item.code: item
        for item in db.scalars(
            select(CatalogService).where(CatalogService.tenant_id == tenant.id)
        ).all()
    }
    offerings = {
        item.code: item
        for item in db.scalars(
            select(ServiceOffering).where(ServiceOffering.tenant_id == tenant.id)
        ).all()
    }
    items = {
        item.code: item
        for item in db.scalars(
            select(CatalogItem).where(CatalogItem.tenant_id == tenant.id)
        ).all()
    }

    for definition in DEMO_CATALOG_DEFS:
        category_code, category_name, category_description, sort_order = definition["category"]
        category = categories.get(category_code)
        if category is None:
            category = ServiceCategory(
                id=_uuid(),
                tenant_id=tenant.id,
                code=category_code,
                name=category_name,
                description=category_description,
                status="ACTIVE",
                sort_order=sort_order,
            )
            db.add(category)
            db.flush()
            categories[category_code] = category

        service_code, service_name, service_description = definition["service"]
        service = services.get(service_code)
        if service is None:
            service = CatalogService(
                id=_uuid(),
                tenant_id=tenant.id,
                category_id=category.id,
                code=service_code,
                name=service_name,
                description=service_description,
                owner_user_id=owner.id,
                support_group="Service Desk",
                status="ACTIVE",
            )
            db.add(service)
            db.flush()
            services[service_code] = service

        offering_code, offering_name, offering_description, fulfillment_minutes = definition["offering"]
        offering = offerings.get(offering_code)
        if offering is None:
            offering = ServiceOffering(
                id=_uuid(),
                tenant_id=tenant.id,
                service_id=service.id,
                code=offering_code,
                name=offering_name,
                description=offering_description,
                support_group="Service Desk",
                expected_fulfillment_minutes=fulfillment_minutes,
                status="ACTIVE",
            )
            db.add(offering)
            db.flush()
            offerings[offering_code] = offering

        for item_definition in definition["items"]:
            item = items.get(item_definition["code"])
            if item is None:
                delivery_minutes = item_definition["expected_delivery_minutes"]
                item = CatalogItem(
                    id=_uuid(),
                    tenant_id=tenant.id,
                    category_id=category.id,
                    service_id=service.id,
                    offering_id=offering.id,
                    code=item_definition["code"],
                    name=item_definition["name"],
                    short_description=item_definition["short_description"],
                    description=item_definition["description"],
                    lifecycle_status="PUBLISHED",
                    version=1,
                    owner_user_id=owner.id,
                    support_group=item_definition["support_group"],
                    expected_delivery_minutes=delivery_minutes,
                    approval_required=item_definition["approval_required"],
                    entitlement_rules_json="{}",
                    unit_cost_minor=0,
                    currency="KZT",
                    cost_type="NO_CHARGE",
                    risk_level=item_definition["risk_level"],
                    approval_policy_json=canonical_json(normalize_approval_policy({})),
                    sla_policy_json=canonical_json(
                        normalize_sla_policy({}, default_target_minutes=delivery_minutes)
                    ),
                    created_by_id=owner.id,
                    updated_by_id=owner.id,
                    published_at=now,
                )
                db.add(item)
                db.flush()
                items[item.code] = item

            published_form = db.scalar(
                select(CatalogFormVersion).where(
                    CatalogFormVersion.catalog_item_id == item.id,
                    CatalogFormVersion.status == "PUBLISHED",
                )
            )
            if published_form is None:
                form_schema = item_definition["form"]
                attachment_rules = item_definition.get(
                    "attachments", default_attachment_rules()
                )
                db.add(
                    CatalogFormVersion(
                        id=_uuid(),
                        tenant_id=tenant.id,
                        catalog_item_id=item.id,
                        version=1,
                        revision=1,
                        status="PUBLISHED",
                        schema_json=canonical_json(form_schema),
                        attachment_rules_json=canonical_json(attachment_rules),
                        schema_hash=schema_hash(form_schema, attachment_rules),
                        created_by_id=owner.id,
                        updated_by_id=owner.id,
                        published_by_id=owner.id,
                        published_at=now,
                    )
                )


def seed_system_data(db: Session) -> None:
    # Multiple API replicas can start at the same time after a deployment.
    # Serialize the idempotent system seed in PostgreSQL so concurrent
    # processes cannot race while creating shared roles and reference data.
    # The transaction-scoped lock is released by the existing commit/rollback.
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": 2_026_081_400_75},
        )

    settings = get_settings()
    now = datetime.now(UTC)

    # Ticket dictionaries are mandatory product reference data.  Keep them
    # available even when all demo fixtures are disabled in production.
    ensure_service_desk_reference_data(db)

    permission_map = {item.code: item for item in db.scalars(select(Permission)).all()}
    for code, name, module, description in PERMISSIONS:
        if code in permission_map:
            permission = permission_map[code]
            permission.name = name
            permission.module = module
            permission.description = description
        else:
            permission = Permission(id=_uuid(), code=code, name=name, module=module, description=description)
            db.add(permission)
            permission_map[code] = permission
    db.flush()

    root_role = db.scalar(select(Role).where(Role.tenant_id.is_(None), Role.code == "saas_root"))
    if root_role is None:
        root_role = Role(
            id=_uuid(),
            tenant_id=None,
            code="saas_root",
            name=ROLE_DEFS["saas_root"]["name"],
            scope=ROLE_DEFS["saas_root"]["scope"],
            description=ROLE_DEFS["saas_root"]["description"],
            is_system=True,
            created_at=now,
            updated_at=now,
        )
        db.add(root_role)
        db.flush()
    root_role.permissions = [permission_map[item] for item in ROLE_DEFS["saas_root"]["permissions"] if item in permission_map]
    root_role.updated_at = now

    # Production startup runs this seed without demo fixtures. Keep standard
    # tenant roles aligned with newly introduced product capabilities and add
    # roles missing from restored or upgraded organizations. A custom role that
    # deliberately uses a standard code remains operator-managed.
    tenant_roles = db.scalars(
        select(Role).where(Role.tenant_id.is_not(None))
    ).all()
    tenant_role_map = {(role.tenant_id, role.code): role for role in tenant_roles}
    tenant_role_definitions = {
        code: definition
        for code, definition in ROLE_DEFS.items()
        if definition["scope"] == "tenant"
    }
    for tenant in db.scalars(select(Tenant)).all():
        for code, definition in tenant_role_definitions.items():
            role = tenant_role_map.get((tenant.id, code))
            if role is None:
                role = Role(
                    id=_uuid(),
                    tenant_id=tenant.id,
                    code=code,
                    name=definition["name"],
                    scope=definition["scope"],
                    description=definition["description"],
                    is_system=True,
                    created_at=now,
                    updated_at=now,
                )
                db.add(role)
                tenant_role_map[(tenant.id, code)] = role
            elif not role.is_system:
                continue
            role.name = definition["name"]
            role.scope = definition["scope"]
            role.description = definition["description"]
            role.permissions = [
                permission_map[permission_code]
                for permission_code in definition["permissions"]
                if permission_code in permission_map
            ]
            role.updated_at = now

    root_user = db.scalar(select(User).where(User.is_root.is_(True)))
    if root_user is None:
        root_email = settings.bootstrap_root_email.strip().lower() if settings.bootstrap_root_email else None
        root_password = settings.bootstrap_root_password
        if not root_email or not root_password:
            raise RuntimeError(
                "No SaaS Root exists; configure BOOTSTRAP_ROOT_EMAIL and BOOTSTRAP_ROOT_PASSWORD for first deploy"
            )
        email_owner = db.scalar(select(User).where(User.email == root_email))
        if email_owner is not None:
            raise RuntimeError(
                "BOOTSTRAP_ROOT_EMAIL belongs to a non-root user; refusing automatic privilege escalation"
            )
    if root_user is None:
        root_user = User(
            id=_uuid(),
            tenant_id=None,
            role_id=root_role.id,
            email=root_email,
            full_name="SaaS Root",
            position="Platform",
            department="SaaS",
            phone=None,
            password_hash=hash_password(root_password),
            is_active=True,
            is_superuser=True,
            is_root=True,
            created_at=now,
            updated_at=now,
        )
        db.add(root_user)
        db.flush()
    else:
        root_user.tenant_id = None
        root_user.role_id = root_role.id
        root_user.full_name = "SaaS Root"
        root_user.is_active = True
        root_user.is_superuser = True
        root_user.is_root = True
        root_user.updated_at = now
    root_user.roles = [root_role]

    setting_map = {(item.tenant_id, item.key): item for item in db.scalars(select(SystemSetting)).all()}
    for key, value, description, is_sensitive in SETTING_DEFS:
        map_key = (None, key)
        setting = setting_map.get(map_key)
        if setting is None:
            setting = SystemSetting(
                id=_uuid(),
                tenant_id=None,
                key=key,
                value=value,
                description=description,
                is_sensitive=is_sensitive,
                updated_at=now,
            )
            db.add(setting)
        else:
            setting.description = description
            setting.is_sensitive = is_sensitive
            setting.updated_at = now

    for tenant in db.scalars(select(Tenant)).all():
        ensure_standard_cmdb_model(db, tenant.id, root_user.id)
    db.commit()


def seed_demo_data(db: Session) -> None:
    settings = get_settings()

    tenant = db.scalar(select(Tenant).where(Tenant.slug == "demo-tenant"))
    now = datetime.now(UTC)
    if tenant is None:
        tenant = Tenant(
            id=_uuid(),
            name="Demo Tenant",
            slug="demo-tenant",
            status="active",
            description="Demo organization for FOUNDATION-002",
            updated_at=now,
        )
        db.add(tenant)
        db.flush()

    other_tenant = db.scalar(select(Tenant).where(Tenant.slug == "demo-tenant-2"))
    if other_tenant is None:
        other_tenant = Tenant(
            id=_uuid(),
            name="Demo Tenant 2",
            slug="demo-tenant-2",
            status="active",
            description="Secondary tenant for isolation checks",
            updated_at=now,
        )
        db.add(other_tenant)
        db.flush()

    permission_map = {item.code: item for item in db.scalars(select(Permission)).all()}
    for code, name, module, description in PERMISSIONS:
        if code in permission_map:
            item = permission_map[code]
            item.name = name
            item.module = module
            item.description = description
            continue
        item = Permission(id=_uuid(), code=code, name=name, module=module, description=description)
        db.add(item)
        permission_map[code] = item
    db.flush()

    role_map: dict[tuple[str | None, str], Role] = {}
    for role in db.scalars(select(Role)).all():
        role_map[(role.tenant_id, role.code if getattr(role, "code", None) else role.name)] = role

    def ensure_role(tenant_id: str | None, code: str) -> Role:
        key = (tenant_id, code)
        if key in role_map:
            role = role_map[key]
        else:
            definition = ROLE_DEFS[code]
            role = Role(
                id=_uuid(),
                tenant_id=tenant_id,
                code=code,
                name=definition["name"],
                scope=definition["scope"],
                description=definition["description"],
                is_system=definition["is_system"],
                created_at=now,
                updated_at=now,
            )
            db.add(role)
            db.flush()
            role_map[key] = role
        definition = ROLE_DEFS[code]
        role.name = definition["name"]
        role.scope = definition["scope"]
        role.description = definition["description"]
        role.is_system = definition["is_system"]
        role.permissions = [permission_map[item] for item in definition["permissions"] if item in permission_map]
        return role

    root_role = ensure_role(None, "saas_root")
    org_admin_role = ensure_role(tenant.id, "organization_admin")
    it_manager_role = ensure_role(tenant.id, "it_manager")
    it_agent_role = ensure_role(tenant.id, "it_agent")
    requester_role = ensure_role(tenant.id, "requester")
    security_officer_role = ensure_role(tenant.id, "security_officer")
    knowledge_manager_role = ensure_role(tenant.id, "knowledge_manager")
    ensure_role(other_tenant.id, "organization_admin")

    user_defs = [
        ("saas.root@sbs.local", "SaaS Root", None, root_role, True, True, "Platform", "SaaS", "+70000000001"),
        (settings.demo_root_email, "SaaS Root", None, root_role, True, True, "Platform", "SaaS", "+70000000011"),
        (settings.demo_admin_email, "Demo Tenant Admin", tenant.id, org_admin_role, False, False, "Org Admin", "Operations", "+70000000012"),
        ("manager@sbs.local", "IT Manager", tenant.id, it_manager_role, False, False, "IT Manager", "IT", "+70000000013"),
        ("agent.network@sbs.local", "Network Agent", tenant.id, it_agent_role, False, False, "Network Engineer", "IT", "+70000000014"),
        ("agent.support@sbs.local", "Support Agent", tenant.id, it_agent_role, False, False, "Support Engineer", "IT", "+70000000015"),
        ("security@sbs.local", "Security Officer", tenant.id, security_officer_role, False, False, "Security Officer", "Security", "+70000000016"),
        ("knowledge@sbs.local", "Knowledge Manager", tenant.id, knowledge_manager_role, False, False, "Knowledge Manager", "ITSM", "+70000000017"),
        ("requester@sbs.local", "Business Requester", tenant.id, requester_role, False, False, "Specialist", "Business", "+70000000018"),
        ("other.admin@sbs.local", "Other Tenant Admin", other_tenant.id, ensure_role(other_tenant.id, "organization_admin"), False, False, "Org Admin", "Operations", "+70000000019"),
    ]

    user_map = {item.email: item for item in db.scalars(select(User)).all()}
    for email, full_name, tenant_id, role, is_root, is_superuser, position, department, phone in user_defs:
        user = user_map.get(email)
        if user is None:
            user = User(
                id=_uuid(),
                tenant_id=tenant_id,
                role_id=role.id,
                email=email,
                full_name=full_name,
                position=position,
                department=department,
                phone=phone,
                password_hash=hash_password(settings.demo_root_password if email == settings.demo_root_email else "Sbs!2026"),
                is_active=True,
                is_superuser=is_superuser,
                is_root=is_root,
                created_at=now,
                updated_at=now,
            )
            db.add(user)
            db.flush()
            user_map[email] = user
        else:
            user.tenant_id = tenant_id
            user.role_id = role.id
            user.full_name = full_name
            user.position = position
            user.department = department
            user.phone = phone
            user.is_active = True
            user.is_superuser = is_superuser
            user.is_root = is_root
            if email in {settings.demo_root_email, "saas.root@sbs.local"}:
                user.password_hash = hash_password(settings.demo_root_password if email == settings.demo_root_email else "Sbs!2026")
            elif email == settings.demo_admin_email:
                user.password_hash = hash_password(settings.demo_admin_password)
            else:
                user.password_hash = hash_password("Sbs!2026")
            user.updated_at = now
        user.roles = [role]

    setting_map = {(item.tenant_id, item.key): item for item in db.scalars(select(SystemSetting)).all()}
    for key, value, description, is_sensitive in SETTING_DEFS:
        for tenant_id in (None, tenant.id):
            map_key = (tenant_id, key)
            setting = setting_map.get(map_key)
            if setting is None:
                setting = SystemSetting(
                    id=_uuid(),
                    tenant_id=tenant_id,
                    key=key,
                    value=value,
                    description=description,
                    is_sensitive=is_sensitive,
                    updated_at=now,
                )
                db.add(setting)
                setting_map[map_key] = setting
            else:
                setting.value = value
                setting.description = description
                setting.is_sensitive = is_sensitive
                setting.updated_at = now

    external_system_map = {item.code: item for item in db.scalars(select(ExternalSystem)).all()}
    for code, name, system_type, base_url, status_value, is_enabled, description in INTEGRATION_SYSTEM_DEFS:
        system = external_system_map.get(code)
        if system is None:
            system = ExternalSystem(
                id=_uuid(),
                tenant_id=tenant.id,
                code=code,
                name=name,
                system_type=system_type,
                base_url=base_url,
                status=status_value,
                is_enabled=is_enabled,
                last_health_status="ok" if is_enabled and status_value == "demo" else "planned",
                last_health_checked_at=now if is_enabled else None,
                description=description,
                created_at=now,
                updated_at=now,
            )
            db.add(system)
            db.flush()
            external_system_map[code] = system
        else:
            system.name = name
            system.system_type = system_type
            system.base_url = base_url
            system.status = status_value
            system.is_enabled = is_enabled
            system.last_health_status = "ok" if is_enabled and status_value == "demo" else (system.last_health_status or "planned")
            system.last_health_checked_at = now if is_enabled else system.last_health_checked_at
            system.description = description
            system.updated_at = now

    credential_map = {(item.external_system_id, item.username): item for item in db.scalars(select(IntegrationCredential)).all()}
    for system in external_system_map.values():
        username = f"svc_{system.code}"
        key = (system.id, username)
        if key in credential_map:
            credential = credential_map[key]
            credential.auth_type = "basic" if system.system_type in {"ldap", "active_directory", "smtp"} else "token"
            credential.secret_ref = f"mock://vault/{system.code}"
            credential.is_active = system.is_enabled
            credential.last_rotated_at = now
            credential.updated_at = now
            continue
        db.add(
            IntegrationCredential(
                id=_uuid(),
                tenant_id=tenant.id,
                external_system_id=system.id,
                auth_type="basic" if system.system_type in {"ldap", "active_directory", "smtp"} else "token",
                username=username,
                secret_ref=f"mock://vault/{system.code}",
                is_active=system.is_enabled,
                last_rotated_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    webhook_defs = [
        ("LDAP Sync Preview", "/hooks/ldap-sync-preview", "ldap"),
        ("Zimbra Mailbox Alert", "/hooks/zimbra-mailbox-alert", "zimbra"),
        ("Platonus User Sync", "/hooks/platonus-user-sync", "platonus"),
        ("Moodle Course Update", "/hooks/moodle-course-update", "moodle"),
        ("Custom Incident Webhook", "/hooks/custom-incident", "custom_api"),
    ]
    webhook_map = {(item.tenant_id, item.path): item for item in db.scalars(select(WebhookEndpoint)).all()}
    for name, path, target_system in webhook_defs:
        key = (tenant.id, path)
        if key in webhook_map:
            endpoint = webhook_map[key]
            endpoint.name = name
            endpoint.target_system = target_system
            endpoint.is_active = True
            endpoint.secret_ref = f"mock://hooks/{target_system}"
            endpoint.updated_at = now
            continue
        db.add(
            WebhookEndpoint(
                id=_uuid(),
                tenant_id=tenant.id,
                name=name,
                path=path,
                target_system=target_system,
                is_active=True,
                secret_ref=f"mock://hooks/{target_system}",
                created_at=now,
                updated_at=now,
            )
        )

    mapping_defs = [
        (external_system_map["ldap_main"].id, "directory_user", "itsm_user", {"email": "email", "department": "department"}),
        (external_system_map["zimbra_main"].id, "mailbox_alert", "ticket", {"subject": "title", "body": "description"}),
        (external_system_map["platonus_main"].id, "academic_user", "itsm_user_preview", {"email": "email", "group": "department"}),
        (external_system_map["moodle_main"].id, "lms_user", "itsm_user_preview", {"email": "email", "courses": "tags"}),
        (external_system_map["smtp_main"].id, "notification_event", "integration_event", {"status": "status", "to": "recipient"}),
        (external_system_map["whatsapp_gateway"].id, "message_event", "notification", {"phone": "recipient", "text": "message"}),
    ]
    mapping_map = {(item.external_system_id, item.source_entity, item.target_entity): item for item in db.scalars(select(IntegrationMapping)).all()}
    for external_system_id, source_entity, target_entity, mapping_payload in mapping_defs:
        key = (external_system_id, source_entity, target_entity)
        if key in mapping_map:
            mapping = mapping_map[key]
            mapping.mapping_json = json.dumps(mapping_payload, ensure_ascii=False)
            mapping.is_active = True
            mapping.updated_at = now
            continue
        db.add(
            IntegrationMapping(
                id=_uuid(),
                tenant_id=tenant.id,
                external_system_id=external_system_id,
                source_entity=source_entity,
                target_entity=target_entity,
                mapping_json=json.dumps(mapping_payload, ensure_ascii=False),
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )

    if int(db.scalar(select(func.count(ImportJob.id))) or 0) < 5:
        for external_system_id, job_type, total, success, failed, status_value, error_message in [
            (external_system_map["ldap_main"].id, "ldap_users_preview", 5, 5, 0, "completed", None),
            (external_system_map["zimbra_main"].id, "zimbra_mailboxes_preview", 4, 4, 0, "completed", None),
            (external_system_map["platonus_main"].id, "platonus_users_preview", 4, 4, 0, "completed", None),
            (external_system_map["moodle_main"].id, "moodle_users_preview", 3, 3, 0, "completed", None),
            (external_system_map["smtp_main"].id, "smtp_notifications_preview", 2, 2, 0, "running", None),
        ]:
            db.add(
                ImportJob(
                    id=_uuid(),
                    tenant_id=tenant.id,
                    external_system_id=external_system_id,
                    job_type=job_type,
                    status=status_value,
                    records_total=total,
                    records_success=success,
                    records_failed=failed,
                    started_at=now,
                    finished_at=None if status_value == "running" else now,
                    error_message=error_message,
                    created_at=now,
                )
            )

    if int(db.scalar(select(func.count(IntegrationEventLog.id))) or 0) < 20:
        for direction, event_type, status_value, code in [
            ("outbound", "health_check", "ok", "zimbra_main"),
            ("outbound", "health_check", "ok", "ldap_main"),
            ("outbound", "health_check", "ok", "platonus_main"),
            ("outbound", "health_check", "ok", "moodle_main"),
            ("outbound", "test_connection", "ok", "smtp_main"),
            ("inbound", "mock_ldap_pull_users", "completed", "ldap_main"),
            ("inbound", "mock_zimbra_pull_mailboxes", "completed", "zimbra_main"),
            ("inbound", "mock_platonus_pull_users", "completed", "platonus_main"),
            ("inbound", "mock_moodle_pull_users", "completed", "moodle_main"),
            ("inbound", "webhook_simulation", "accepted", None),
            ("outbound", "send_notification", "logged_only", "smtp_main"),
            ("outbound", "push_ticket", "mocked", "zimbra_main"),
            ("inbound", "users_preview", "completed", "ldap_main"),
            ("inbound", "groups_preview", "completed", "platonus_main"),
            ("inbound", "courses_preview", "completed", "moodle_main"),
            ("inbound", "mailbox_health_preview", "completed", "zimbra_main"),
            ("outbound", "health_check", "degraded", "smtp_main"),
            ("outbound", "health_check", "failed", "whatsapp_gateway"),
            ("inbound", "custom_api_sync", "error", None),
            ("outbound", "test_connection", "planned", "ad_main"),
        ]:
            system = external_system_map.get(code) if code else None
            create_integration_event(
                db,
                tenant_id=tenant.id,
                external_system_id=system.id if system else None,
                direction=direction,
                event_type=event_type,
                status=status_value,
                request_summary={"system_code": code} if code else {"system_code": "custom"},
                response_summary={"status": status_value, "message": f"Demo integration event for {event_type}."},
                error_message="Mock integration failure." if status_value in {"error", "failed"} else None,
            )

    if db.execute(select(Asset.id)).first() is None and tenant is not None:
        db.add_all(
            [
                Asset(
                    id=_uuid(),
                    tenant_id=tenant.id,
                    asset_tag="AST-2001",
                    name="ThinkPad T14 Gen 4",
                    asset_type="Laptop",
                    type="Laptop",
                    serial_number="LTP-7F4A-2039",
                    inventory_number="INV-2001",
                    manufacturer="Lenovo",
                    model="ThinkPad T14 Gen 4",
                    status="in_use",
                    owner_name="Ирина Соколова",
                    assigned_to_name="Ирина Соколова",
                    assigned_to_email="irina.sokolova@sbs.local",
                    department="Учебный центр",
                    location="Moscow / HQ / Floor 4",
                    purchase_date=datetime(2024, 2, 14, tzinfo=UTC),
                    warranty_until=None,
                    condition="good",
                    description="Основной рабочий ноутбук для сотрудника поддержки.",
                ),
                Asset(
                    id=_uuid(),
                    tenant_id=tenant.id,
                    asset_tag="AST-2002",
                    name="Cisco SG350",
                    asset_type="Network Switch",
                    type="Network Switch",
                    serial_number="CSW-8821-11",
                    inventory_number="INV-2002",
                    manufacturer="Cisco",
                    model="SG350",
                    status="in_stock",
                    owner_name="Warehouse",
                    assigned_to_name="Warehouse",
                    assigned_to_email=None,
                    department="Operations",
                    location="Moscow / Storage",
                    purchase_date=None,
                    warranty_until=None,
                    condition="good",
                    description="Запасной коммутатор для сервисного склада.",
                ),
                Asset(
                    id=_uuid(),
                    tenant_id=tenant.id,
                    asset_tag="AST-2003",
                    name="HP EliteDisplay E243",
                    asset_type="Monitor",
                    type="Monitor",
                    serial_number="MON-243-7781",
                    inventory_number="INV-2003",
                    manufacturer="HP",
                    model="EliteDisplay E243",
                    status="in_repair",
                    owner_name="Service Desk",
                    assigned_to_name="Service Desk",
                    assigned_to_email=None,
                    department="Support",
                    location="Moscow / Vendor Repair",
                    purchase_date=None,
                    warranty_until=None,
                    condition="needs_service",
                    description="Монитор отправлен на диагностику по заявке инвентаризации.",
                ),
            ]
        )

    if db.execute(select(SlaPolicy.id)).first() is None and tenant is not None:
        db.add_all(
            [
                SlaPolicy(
                    id=_uuid(),
                    tenant_id=tenant.id,
                    name="Critical Incident SLA",
                    priority="CRITICAL",
                    target_response_minutes=15,
                    target_resolution_minutes=120,
                    response_minutes=15,
                    resolution_minutes=120,
                    is_active=True,
                    status="active",
                    breach_count=1,
                    description="Высший приоритет для остановки бизнеса и критических инцидентов.",
                ),
                SlaPolicy(
                    id=_uuid(),
                    tenant_id=tenant.id,
                    name="High Priority SLA",
                    priority="HIGH",
                    target_response_minutes=30,
                    target_resolution_minutes=240,
                    response_minutes=30,
                    resolution_minutes=240,
                    is_active=True,
                    status="active",
                    breach_count=0,
                    description="Для значимых инцидентов с заметным влиянием на пользователей.",
                ),
                SlaPolicy(
                    id=_uuid(),
                    tenant_id=tenant.id,
                    name="Standard Service Request SLA",
                    priority="MEDIUM",
                    target_response_minutes=60,
                    target_resolution_minutes=1440,
                    response_minutes=60,
                    resolution_minutes=1440,
                    is_active=True,
                    status="active",
                    breach_count=2,
                    description="Обычные сервисные запросы и операционные задачи.",
                ),
            ]
        )

    if settings.seed_demo_catalog:
        catalog_owner = (
            user_map.get("manager@sbs.local") or user_map[settings.demo_admin_email]
        )
        _seed_demo_catalog(db, tenant=tenant, owner=catalog_owner, now=now)
    seed_service_desk_demo_data(db)
    seed_asset_sla_demo_data(db)
    seed_knowledge_ai_demo_data(db)
    seed_notification_templates(db)
    seed_demo_notifications(db)
    seed_workflow_automation_data(db, tenant.id, settings.demo_admin_email)

    ai_suggestion_count = int(db.scalar(select(func.count(AiSuggestion.id))) or 0)
    if ai_suggestion_count == 0:
        demo_tickets = db.scalars(select(Ticket).order_by(Ticket.created_at.asc()).limit(6)).all()
        confidence_cycle = ["high", "medium", "high", "low", "medium", "high"]
        for index, ticket in enumerate(demo_tickets):
            db.add(
                AiSuggestion(
                    id=_uuid(),
                    ticket_id=ticket.id,
                    input_text=ticket.description or ticket.title,
                    recommended_category=ticket.category,
                    recommended_priority=ticket.priority,
                    recommended_asset_type="Laptop" if "WORKSTATION" in ticket.category or "MAIL" in ticket.category else "Network",
                    recommended_article_id=None,
                    summary=f"AI demo summary for {ticket.ticket_number}",
                    possible_cause="Demo analytics seed cause.",
                    suggested_solution="Demo analytics seed solution.",
                    recommended_assignee=ticket.assignee_name or "Service Desk Lead",
                    confidence=confidence_cycle[index % len(confidence_cycle)],
                    created_at=now,
                )
            )

    seed_reporting_demo_data(db, tenant.id, settings.demo_admin_email)
    seed_reporting_demo_data(db, None, settings.demo_root_email)

    audit_count = int(db.scalar(select(func.count(AuditLog.id))) or 0)
    if audit_count == 0:
        actor = user_map.get(settings.demo_admin_email)
        for index in range(30):
            log_audit(
                db,
                action="security.demo_event" if index % 5 == 0 else "admin.demo_event",
                entity_type="seed",
                entity_id=str(index + 1),
                actor_user=actor,
                metadata={"index": index + 1},
            )

    if db.scalar(select(func.count(SavedReport.id))) == 0:
        seed_reporting_demo_data(db, tenant.id, settings.demo_admin_email)
    if db.scalar(select(func.count(ReportSnapshot.id))) == 0:
        seed_reporting_demo_data(db, None, settings.demo_root_email)
    ensure_standard_cmdb_model(
        db,
        tenant.id,
        user_map.get(settings.demo_admin_email).id
        if user_map.get(settings.demo_admin_email)
        else None,
    )
    ensure_standard_cmdb_model(
        db,
        other_tenant.id,
        user_map.get(settings.demo_root_email).id
        if user_map.get(settings.demo_root_email)
        else None,
    )
    db.commit()
