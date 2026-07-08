from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.asset import Asset
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
from app.services.integrations.providers import create_integration_event
from app.services.knowledge_ai import seed_knowledge_ai_demo_data
from app.services.notifications import seed_demo_notifications, seed_notification_templates
from app.services.service_desk import seed_service_desk_demo_data


def _uuid() -> str:
    return str(uuid.uuid4())


PERMISSIONS = [
    ("tickets.read", "Read tickets", "tickets", "Read ticket records"),
    ("tickets.create", "Create tickets", "tickets", "Create new ticket records"),
    ("tickets.update", "Update tickets", "tickets", "Update ticket details"),
    ("tickets.assign", "Assign tickets", "tickets", "Assign executors to tickets"),
    ("tickets.comment", "Comment tickets", "tickets", "Post comments to tickets"),
    ("tickets.close", "Close tickets", "tickets", "Resolve and close tickets"),
    ("assets.read", "Read assets", "assets", "Read assets inventory"),
    ("assets.create", "Create assets", "assets", "Create assets"),
    ("assets.update", "Update assets", "assets", "Update assets"),
    ("assets.assign", "Assign assets", "assets", "Assign assets to users"),
    ("sla.read", "Read SLA", "sla", "Read SLA policies and breaches"),
    ("sla.manage", "Manage SLA", "sla", "Manage SLA policies"),
    ("knowledge.read", "Read knowledge", "knowledge", "Read knowledge base"),
    ("knowledge.create", "Create knowledge", "knowledge", "Create knowledge articles"),
    ("knowledge.update", "Update knowledge", "knowledge", "Update knowledge articles"),
    ("knowledge.publish", "Publish knowledge", "knowledge", "Publish knowledge articles"),
    ("ai.use", "Use AI", "ai", "Use AI Copilot"),
    ("ai.view_suggestions", "View AI suggestions", "ai", "Read AI suggestions"),
    ("notifications.read", "Read notifications", "notifications", "Read notifications"),
    ("notifications.manage", "Manage notifications", "notifications", "Manage notifications"),
    ("email_log.read", "Read email log", "notifications", "Read mock email log"),
    ("admin.users.read", "Read admin users", "admin", "Read users in admin console"),
    ("admin.users.create", "Create admin users", "admin", "Create users in admin console"),
    ("admin.users.update", "Update admin users", "admin", "Update users in admin console"),
    ("admin.roles.read", "Read roles", "admin", "Read role catalog"),
    ("admin.roles.manage", "Manage roles", "admin", "Manage roles"),
    ("admin.permissions.read", "Read permissions", "admin", "Read permissions catalog"),
    ("admin.settings.read", "Read settings", "admin", "Read system settings"),
    ("admin.settings.update", "Update settings", "admin", "Update non-sensitive settings"),
    ("security.audit.read", "Read audit logs", "security", "Read audit events"),
    ("security.sessions.read", "Read sessions", "security", "Read session overview"),
    ("security.login_events.read", "Read login events", "security", "Read login success/fail events"),
    ("analytics.read", "Read analytics", "analytics", "Read analytics and executive dashboards"),
    ("reports.read", "Read reports", "reports", "Read saved reports and snapshots"),
    ("reports.create", "Create reports", "reports", "Create saved reports and snapshots"),
    ("reports.export", "Export demo reports", "reports", "Request demo exports"),
    ("integrations.read", "Read integrations", "integrations", "Read external systems and providers"),
    ("integrations.manage", "Manage integrations", "integrations", "Create and update external systems"),
    ("integrations.health_check", "Health check integrations", "integrations", "Run integration health checks"),
    ("integrations.test_connection", "Test integration connections", "integrations", "Run mock integration test connections"),
    ("integrations.import", "Run integration imports", "integrations", "Run integration preview import jobs"),
    ("integrations.webhooks.read", "Read integration webhooks", "integrations", "Read webhook endpoints"),
    ("integrations.webhooks.manage", "Manage integration webhooks", "integrations", "Create update and simulate webhooks"),
    ("integrations.events.read", "Read integration events", "integrations", "Read integration event logs"),
    ("integrations.mappings.read", "Read integration mappings", "integrations", "Read integration mappings"),
    ("integrations.mappings.manage", "Manage integration mappings", "integrations", "Create and update integration mappings"),
    ("automation.rules.read", "Read automation rules", "automation", "Read workflow automation rules"),
    ("automation.rules.manage", "Manage automation rules", "automation", "Create and update workflow automation rules"),
    ("automation.rules.execute", "Execute automation rules", "automation", "Run manual and trigger-based automation"),
    ("automation.runs.read", "Read automation runs", "automation", "Read automation execution runs"),
    ("automation.logs.read", "Read automation logs", "automation", "Read automation action logs"),
    ("automation.runbooks.read", "Read runbooks", "automation", "Read workflow runbooks"),
    ("automation.runbooks.manage", "Manage runbooks", "automation", "Create and update workflow runbooks"),
    ("automation.executions.read", "Read runbook executions", "automation", "Read runbook execution timeline"),
    ("automation.executions.manage", "Manage runbook executions", "automation", "Start and update runbook executions"),
    ("automation.approvals.read", "Read approval requests", "automation", "Read workflow approval requests"),
    ("automation.approvals.manage", "Manage approval requests", "automation", "Approve and reject workflow requests"),
    ("automation.suggestions.read", "Read automation suggestions", "automation", "Read runbook and automation suggestions"),
    ("tenant.read", "Read tenants", "tenant", "Read tenants"),
    ("tenant.manage", "Manage tenants", "tenant", "Manage tenants"),
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
            "tickets.comment",
            "tickets.close",
            "assets.read",
            "assets.create",
            "assets.update",
            "assets.assign",
            "sla.read",
            "sla.manage",
            "knowledge.read",
            "knowledge.create",
            "knowledge.update",
            "knowledge.publish",
            "ai.use",
            "ai.view_suggestions",
            "notifications.read",
            "notifications.manage",
            "email_log.read",
            "admin.users.read",
            "admin.users.create",
            "admin.users.update",
            "admin.roles.read",
            "admin.roles.manage",
            "admin.permissions.read",
            "admin.settings.read",
            "admin.settings.update",
            "security.audit.read",
            "security.sessions.read",
            "security.login_events.read",
            "analytics.read",
            "reports.read",
            "reports.create",
            "reports.export",
            "integrations.read",
            "integrations.manage",
            "integrations.health_check",
            "integrations.test_connection",
            "integrations.import",
            "integrations.webhooks.read",
            "integrations.webhooks.manage",
            "integrations.events.read",
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
            "tickets.comment",
            "tickets.close",
            "assets.read",
            "assets.update",
            "sla.read",
            "knowledge.read",
            "ai.use",
            "ai.view_suggestions",
            "notifications.read",
            "analytics.read",
            "reports.read",
            "reports.create",
            "reports.export",
            "integrations.read",
            "integrations.manage",
            "integrations.health_check",
            "integrations.test_connection",
            "integrations.import",
            "integrations.webhooks.read",
            "integrations.webhooks.manage",
            "integrations.events.read",
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
            "tickets.comment",
            "notifications.read",
            "ai.view_suggestions",
            "knowledge.read",
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
        "permissions": ["tickets.read", "tickets.create", "knowledge.read", "notifications.read"],
    },
    "security_officer": {
        "name": "Security Officer",
        "scope": "tenant",
        "description": "Security analyst",
        "is_system": True,
        "permissions": [
            "security.audit.read",
            "security.sessions.read",
            "security.login_events.read",
            "tickets.read",
            "knowledge.read",
            "email_log.read",
            "notifications.read",
            "analytics.read",
            "reports.read",
            "integrations.read",
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
        "permissions": ["knowledge.read", "knowledge.create", "knowledge.update", "knowledge.publish", "notifications.read"],
    },
}


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
                    priority="critical",
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
                    priority="high",
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
                    priority="medium",
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
    db.commit()
