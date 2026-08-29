from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    access = _read("frontend/src/auth/accessControl.ts")
    guard = _read("frontend/src/auth/RequireAuth.tsx")
    shell = _read("frontend/src/components/AppShell.tsx")
    dashboard = _read("frontend/src/pages/DashboardPage.tsx")
    admin = _read("frontend/src/pages/AdminPage.tsx")
    admin_system = _read("frontend/src/pages/AdminSystemPage.tsx")
    copilot = _read("frontend/src/pages/CopilotPage.tsx")
    change_governance = _read("frontend/src/pages/ChangeGovernancePage.tsx")
    changes = _read("frontend/src/pages/ChangesPage.tsx")
    problems = _read("frontend/src/pages/ProblemsPage.tsx")
    releases = _read("frontend/src/pages/ReleasesPage.tsx")
    sla = _read("frontend/src/pages/SlaPage.tsx")
    events = _read("frontend/src/pages/EventOperationsPage.tsx")
    major_incidents = _read("frontend/src/pages/MajorIncidentsPage.tsx")
    tickets = _read("frontend/src/pages/TicketsPage.tsx")
    requests = _read("frontend/src/pages/RequestsPage.tsx")
    automation = _read("frontend/src/pages/AutomationPage.tsx")
    integrations = _read("frontend/src/pages/IntegrationsPage.tsx")
    analytics = _read("frontend/src/pages/AnalyticsPage.tsx")
    identity = _read("frontend/src/pages/IdentityProvisioningPage.tsx")
    notifications = _read("frontend/src/pages/NotificationsPage.tsx")
    email_log = _read("frontend/src/pages/EmailLogPage.tsx")
    configuration_center = _read(
        "frontend/src/components/ConfigurationCenterPanel.tsx"
    )
    ai_governance = _read("frontend/src/components/AiGovernancePanel.tsx")
    ai_routes = _read("backend/app/api/v1/routes/ai.py")
    ai_retrieval = _read("backend/app/services/ai_retrieval.py")
    asset_routes = _read("backend/app/api/v1/routes/assets.py")
    request_routes = _read("backend/app/api/v1/routes/requests.py")
    integration_routes = _read("backend/app/api/v1/routes/integrations.py")
    event_routes = _read("backend/app/api/v1/routes/event_operations.py")
    major_incident_routes = _read("backend/app/api/v1/routes/major_incidents.py")
    ticket_routes = _read("backend/app/api/v1/routes/tickets.py")
    rbac = _read("backend/app/services/rbac.py")
    seed = _read("backend/app/services/seed.py")
    ticket_tests = _read("backend/tests/test_tickets.py")
    asset_tests = _read("backend/tests/test_assets_inventory.py")
    request_tests = _read("backend/tests/test_request_fulfillment.py")
    event_tests = _read("backend/tests/test_event_operations.py")
    major_incident_tests = _read("backend/tests/test_major_incidents.py")
    admin_tests = _read("backend/tests/test_admin_security.py")
    controls = json.loads(
        _read("security/acceptance-catalog.json")
    )["controls"]

    route_permissions = {
        "/tickets": "tickets.read",
        "/major-incidents": "major_incidents.read",
        "/events": "monitoring.events.read",
        "/assets": "assets.read",
        "/sla": "sla.read",
        "/knowledge": "knowledge.read",
        "/notifications": "notifications.read",
        "/notifications/email-log": "notifications.email_log.read",
        "/analytics": "analytics.read",
        "/copilot": "ai.governance.read",
        "/admin/system": "admin.settings.read",
        "/identity-provisioning": "identity.provisioning.read",
        "/email-operations": "email.",
        "/teams-collaboration": "teams.",
        "/admin/custom-fields": "custom_fields.",
        "/admin/configuration-packages": "configuration.packages.",
    }
    for path, permission in route_permissions.items():
        _require(
            f"'{path}'" in access and f"'{permission}'" in access,
            f"Central route access registry misses {path} -> {permission}",
        )
    for marker in (
        "subject.role === 'saas_root'",
        "allPermissions?: readonly string[]",
        "required.every((permission) => permissions.has(permission))",
        "permissions.has(permission)",
        "permission.startsWith(prefix)",
        "ROUTE_ACCESS_REQUIREMENTS[normalizePath(pathname)]",
    ):
        _require(marker in access, f"Central permission evaluator misses: {marker}")

    _require(
        "canAccessPath(session.user, location.pathname)" in guard,
        "Authenticated direct routes are not checked by the central permission evaluator",
    )
    for marker in (
        'role="alert"',
        "Недостаточно прав",
        'to="/dashboard"',
        'to="/account"',
    ):
        _require(marker in guard, f"Accessible denied-state UI misses: {marker}")

    _require(
        "canAccessPath({ role, permissions: Array.from(permissions) }, item.to)"
        in shell,
        "Navigation does not use the same central route evaluator",
    )
    _require(
        "enabled: Boolean(session?.access_token && canReadNotifications)"
        in shell,
        "Navigation still performs an unauthorized notification request",
    )
    _require(
        "canAccessNavigationItem" not in shell,
        "Navigation retains a divergent local permission evaluator",
    )

    capability_queries = {
        "canReadTickets": "fetchTickets",
        "canReadAssets": "fetchAssets",
        "canReadSla": "fetchSlaOverview",
        "canReadKnowledge": "fetchKnowledgeArticles",
        "canReadNotifications": "fetchNotifications",
        "canReadEmailLog": "fetchEmailLog",
    }
    for capability, query in capability_queries.items():
        _require(
            f"&& {capability})" in dashboard and query in dashboard,
            f"Dashboard {query} request is not permission-gated by {capability}",
        )
    for marker in (
        "canReadOperationalData",
        "Рабочие данные пока недоступны",
        "canReadTickets && canReadKnowledge",
        "canUseAi && canReadTickets",
        "canReadKnowledge && canCreateKnowledgeFromTicket",
        "canReadNotifications || canReadEmailLog",
        "canReadTickets || canReadAssets",
    ):
        _require(marker in dashboard, f"Dashboard permission-aware rendering misses: {marker}")
    _require(
        "isAdminContext" not in dashboard,
        "Dashboard access still depends on hard-coded role names",
    )

    admin_capabilities = (
        "const canReadUsers = hasPermission('admin.users.read')",
        "const canCreateUsers = hasPermission('admin.users.create')",
        "const canManageUsers = hasPermission('admin.users.update')",
        "const canReadRoles = hasPermission('admin.roles.read')",
        "const canManageRoles = hasPermission('admin.roles.manage')",
        "const canReadPermissions = hasPermission('admin.permissions.read')",
        "const canReadAudit = hasPermission('security.audit.read')",
        "const canReadSettings = hasPermission('admin.settings.read')",
        "const canReadLoginEvents = hasPermission('security.login_events.read')",
        "const canReadSessions = hasPermission('security.sessions.read')",
        "const canManageSessions = hasPermission('security.sessions.manage')",
        "const canReadMfa = hasPermission('security.mfa.read')",
        "const canReadTenants = isRoot",
    )
    for marker in admin_capabilities:
        _require(marker in admin, f"Admin console capability is missing: {marker}")
    for marker in (
        "const availableTabs = useMemo(",
        "availableTabs.some((tab) => tab.key === linkedTab)",
        "availableTabs.map((tab)",
        "const canProvisionUsers = canCreateUsers && canReadRoles",
        "session?.access_token && canReadUsers",
        "session?.access_token && canReadRoles",
        "session?.access_token && canReadPermissions",
        "session?.access_token && canReadAudit",
        "session?.access_token && canReadSettings",
        "session?.access_token && canReadLoginEvents",
        "session?.access_token && canReadSessions",
        "canReadLoginEvents || canReadAudit",
        "canManageUsers || canManageSessions",
        "Каталог разрешений скрыт: требуется admin.permissions.read.",
    ):
        _require(marker in admin, f"Admin console permission boundary misses: {marker}")
    _require(
        "enabled: Boolean(session?.access_token)," not in admin,
        "Admin console still performs unconditional authenticated queries",
    )
    _require(
        "(session?.user.permissions ?? []).includes" not in admin,
        "Admin console retains divergent ad hoc permission checks",
    )

    process_capabilities = {
        "change governance": (
            change_governance,
            (
                "hasPermission('changes.create')",
                "hasPermission('changes.update')",
                "hasPermission('changes.schedule')",
                "hasPermission('changes.approve')",
                "hasPermission('changes.execute')",
            ),
        ),
        "release governance": (
            releases,
            (
                "hasPermission('changes.create')",
                "hasPermission('changes.update')",
                "hasPermission('changes.submit')",
                "hasPermission('changes.approve')",
                "hasPermission('changes.schedule')",
                "hasPermission('changes.execute')",
            ),
        ),
        "event operations": (
            events,
            (
                "hasPermission('monitoring.events.read')",
                "hasPermission('monitoring.events.manage')",
                "hasPermission('monitoring.connectors.read')",
                "hasPermission('monitoring.connectors.manage')",
                "hasPermission('monitoring.receipts.read')",
                "hasPermission('monitoring.receipts.manage')",
                "hasPermission('integrations.manage')",
                "scopeReady && canReadEvents",
                "scopeReady && canReadSources",
                "scopeReady && canReadReceipts",
            ),
        ),
        "ticket operations": (
            tickets,
            (
                "hasPermission('tickets.create')",
                "hasPermission('tickets.update')",
                "hasPermission('tickets.comment')",
                "hasPermission('tickets.assign')",
                "hasPermission('tickets.bulk.execute')",
                "hasPermission('assets.read')",
                "hasPermission('problems.read')",
                "hasPermission('ai.view_suggestions')",
                "hasPermission('knowledge.attach.read')",
                "hasPermission('knowledge.create_from_ticket')",
            ),
        ),
    }
    for surface, (source, markers) in process_capabilities.items():
        for marker in markers:
            _require(marker in source, f"{surface} permission boundary misses: {marker}")

    for surface, source in (
        ("change governance", change_governance),
        ("release governance", releases),
        ("event operations", events),
    ):
        _require(
            "['saas_root', 'organization_admin'" not in source,
            f"{surface} retains a hard-coded privileged-role array",
        )
    _require(
        "session?.user.permissions.includes('sla.manage')" in sla,
        "SLA management is not gated by sla.manage",
    )
    _require(
        "canCommentRequests" in requests
        and "session?.user.permissions.includes('requests.comment')" in requests,
        "Request comments are not gated by requests.comment",
    )
    for obsolete in (
        "canCreateTickets(",
        "canOperateTickets(",
        "canManageAssignments(",
        "canCreateArticleFromTicket(",
    ):
        _require(obsolete not in tickets, f"Ticket console retains role helper: {obsolete}")

    for marker in (
        "const canReadAiConfig = hasPermission('admin.settings.read')",
        "const canUpdateAiConfig = hasPermission('admin.settings.update')",
        "enabled: Boolean(session?.access_token) && canReadAiConfig",
        "{canUpdateAiConfig ? <div",
    ):
        _require(marker in admin_system, f"System diagnostics AI config misses: {marker}")
    for marker in (
        "const canAnalyze = hasPermission('ai.use')",
        "const canApplyTicketUpdate = hasPermission('tickets.update')",
        "enabled: Boolean(session?.access_token) && canReadTickets",
        "enabled: Boolean(session?.access_token) && canReadProviderStatus",
    ):
        _require(marker in copilot, f"Copilot permission boundary misses: {marker}")
    _require(
        "enabled: Boolean(token && canRead && policyId)" in ai_governance,
        "AI governance version query is not permission-gated",
    )
    for marker in ('"ai.use"', '"ai.rag.use"', '"ai.actions.read"'):
        _require(
            marker in ai_routes.split("_PROVIDER_STATUS_PERMS", 1)[1].split(")", 1)[0],
            f"AI provider status does not authorize entitled AI operators: {marker}",
        )
    _require(
        'return has_permission(current_user, "tickets.assign")' in ticket_routes,
        "Backend ticket queue management still depends on a hard-coded role name",
    )
    _require(
        "test_custom_role_ticket_assignment_scope_uses_effective_permissions"
        in ticket_tests,
        "Backend custom-role ticket assignment regression is missing",
    )
    for marker in (
        "tickets.scope.all",
        "tickets.scope.assigned",
        "tickets.scope.requester",
        "tickets.self_assign",
    ):
        _require(
            marker in seed and marker in tickets,
            f"Ticket scope permission is not wired end-to-end: {marker}",
        )
    _require(
        'for scope in ("all", "assigned", "requester")' in rbac
        and 'f"tickets.scope.{scope}"' in rbac
        and '"tickets.self_assign"' in rbac
        and "return rbac_can_read_ticket(current_user, ticket)" in ticket_routes,
        "Backend ticket scope evaluator is incomplete",
    )
    for marker in (
        "allPermissions: ['tickets.read']",
        "const canReadAllTickets",
        "const canReadAssignedTickets",
        "const canReadRequesterTickets",
        "const canSelfAssign",
        "restrictOperationsToAssigned",
    ):
        _require(marker in access or marker in tickets, f"Ticket UI scope misses: {marker}")
    for obsolete in (
        'current_user.role == "requester"',
        'current_user.role == "it_agent"',
    ):
        _require(
            obsolete not in ticket_routes and obsolete not in rbac,
            f"Backend ticket scope retains built-in role branch: {obsolete}",
        )
    _require(
        "test_custom_ticket_visibility_scopes_fail_closed_and_compose"
        in ticket_tests,
        "Backend custom-role visibility-scope regression is missing",
    )
    _require(
        '"tickets.read"' not in event_routes
        and '"tickets.update"' not in event_routes
        and event_routes.count('"monitoring.events.read"') >= 7
        and event_routes.count('"monitoring.events.manage"') >= 2,
        "Event Operations still inherits generic ticket authority",
    )
    for marker in (
        "hasPermission('major_incidents.read')",
        "hasPermission('major_incidents.manage')",
        "token && canRead",
        "showDeclare && canManage && canReadTicketCandidates",
        "{canManage ? (",
        "disabled={!canManage}",
    ):
        _require(
            marker in major_incidents,
            f"Major Incident permission boundary misses: {marker}",
        )
    _require(
        '"tickets.read"' not in major_incident_routes
        and '"tickets.update"' not in major_incident_routes
        and major_incident_routes.count('"major_incidents.read"') >= 10
        and major_incident_routes.count('"major_incidents.manage"') >= 6,
        "Major Incident API still inherits generic ticket authority",
    )
    _require(
        'login(client, "requester@sbs.local")' in event_tests
        and 'login(client, "requester@sbs.local")' in major_incident_tests
        and "assert denied.status_code == 403" in event_tests
        and "assert denied.status_code == 403" in major_incident_tests,
        "Requester denial regressions for operational event surfaces are missing",
    )
    for marker in (
        "token && showCreate && canCreate && canReadAssets",
        "{canReadAssets ? <label>Связанный актив",
    ):
        _require(
            marker in changes,
            f"Change create cross-module boundary misses: {marker}",
        )
    for marker in (
        "canAccessPath(session.user, '/tickets')",
        "token && showCreate && canCreate && canReadTicketCandidates",
        "token && showCreate && canCreate && canReadAssets",
        "token && showCreate && canCreate && canReadChanges",
        "{canReadTicketCandidates ? <label>Связанный инцидент",
        "{canReadAssets ? <label>Затронутый актив",
        "{canReadChanges ? <label>Corrective RFC",
    ):
        _require(
            marker in problems,
            f"Problem create cross-module boundary misses: {marker}",
        )
    _require(
        "return can_read_ticket(current_user, ticket)" in ai_routes
        and "return can_read_ticket(current_user, source)" in ai_retrieval,
        "AI ticket access is not using the central ticket visibility scope",
    )
    _require(
        'return has_permission(current_user, "assets.update")' in asset_routes
        and 'return has_permission(current_user, "assets.verify")' in asset_routes
        and "Only manager/admin/root" not in asset_routes
        and 'current_user.role == "requester"' not in asset_routes
        and "test_custom_asset_roles_use_effective_permissions" in asset_tests,
        "Asset operations still depend on built-in role names",
    )
    for marker in (
        "requests.scope.all",
        "requests.scope.requester",
    ):
        _require(
            marker in seed and marker in requests and marker in access,
            f"Request visibility scope is not wired end-to-end: {marker}",
        )
    _require(
        'for scope in ("all", "requester")' in request_routes
        and 'f"requests.scope.{scope}"' in request_routes
        and "ServiceRequest.id.is_(None)" in request_routes
        and 'current_user.role == "requester"' not in request_routes
        and "current_user.role in {" not in request_routes
        and "test_custom_request_visibility_scopes_fail_closed_and_compose"
        in request_tests,
        "Request visibility or approval authority still depends on built-in roles",
    )

    composite_console_boundaries = {
        "automation": (
            automation,
            (
                "const availableTabs = useMemo(",
                "token && canReadRules",
                "token && canReadRuns",
                "token && canReadRunbooks",
                "token && canReadExecutions",
                "token && canReadApprovals",
                "token && selectedRunId && canReadLogs",
                "{canManageRules ? <button",
                "{canManageExecutions ? <button",
                "{canDecideApprovals ? <button",
            ),
        ),
        "integrations": (
            integrations,
            (
                "const canAccessLegacy",
                "permission.startsWith('integration.platform.')",
                "permission.startsWith('integrations.')",
                "session?.access_token) && canAccessLegacy",
                "legacyDemoEnabled && canReadJobs",
                "legacyDemoEnabled && canReadEvents",
                "legacyDemoEnabled && canReadWebhooks",
                "legacyDemoEnabled && canReadMappings",
                "{canRunHealthCheck ? <button",
                "{canManageWebhooks ? <button",
            ),
        ),
        "analytics and reports": (
            analytics,
            (
                "const availableTabs = useMemo(",
                "has('analytics.executive.read')",
                "has('analytics.tickets.read')",
                "has('analytics.sla.read')",
                "has('analytics.assets.read')",
                "has('analytics.knowledge.read')",
                "has('analytics.ai.read')",
                "has('analytics.security.read')",
                "has('analytics.automation.read')",
                "has('reports.read')",
                "activeTab === 'reports'",
                "{canCreateReports ? <button",
                "{canExportReports ? <button",
            ),
        ),
        "identity provisioning": (
            identity,
            (
                "has('identity.provisioning.read')",
                "has('identity.provisioning.manage')",
                "has('admin.roles.read')",
                "has('admin.users.read')",
                "const canConfigureConnector = canManage && canReadRoles && canReadUsers",
                "token && scopedTenant && canRead",
                "token && canReadRoles",
                "token && canReadUsers",
            ),
        ),
        "notifications": (
            notifications,
            (
                "has('notifications.read')",
                "has('notifications.update')",
                "has('notifications.preferences.update')",
                "has('notifications.templates.read')",
                "has('notifications.templates.update')",
                "has('notifications.email_log.read')",
                "canReadTemplates) && activeTab === 'templates'",
                "{canUpdateNotifications ? <button",
                "disabled={!canUpdatePreferences || togglePreferenceMutation.isPending}",
            ),
        ),
    }
    for surface, (source, markers) in composite_console_boundaries.items():
        for marker in markers:
            _require(marker in source, f"{surface} boundary misses: {marker}")

    for marker in (
        "const canRead = isRoot || permissions.has('admin.configuration.read')",
        "enabled: Boolean(token && canRead)",
        "enabled: Boolean(token && canRead && historyKey)",
        "if (!canRead) return null",
    ):
        _require(
            marker in configuration_center,
            f"Configuration Center permission boundary misses: {marker}",
        )
    _require(
        "permissions.has('notifications.email_log.retry')" in email_log
        and "canRetryEmail && ['FAILED', 'BOUNCED'].includes(item.status)"
        in email_log,
        "Email-log retry is not gated by notifications.email_log.retry",
    )
    _require(
        'permission.startswith("integrations.")' in integration_routes,
        "Integration runtime capability discovery is not available to narrow "
        "integration roles",
    )
    for marker in (
        "'reports.read'",
        "'notifications.templates.read'",
        "'identity.provisioning.read'",
    ):
        _require(
            marker in access,
            f"Central route access registry misses composite-console marker: {marker}",
        )

    _require(
        "test_multiple_roles_produce_an_effective_permission_union" in admin_tests,
        "Backend regression for multi-role permission union is missing",
    )
    for marker in (
        "const permissionGuidance",
        "const [permissionSearch, setPermissionSearch]",
        "const rolePermissionWarnings = useMemo(",
        "const updatePermissionGroup",
        "replaceRolePermissionsMutation.isPending || rolePermissionWarnings.length > 0",
        "Object.entries(filteredPermissionsByModule)",
    ):
        _require(
            marker in admin,
            f"Safe role-permission editor misses: {marker}",
        )
    for marker in (
        "def _ensure_record_read_scopes",
        '"tickets.read" in codes and codes.isdisjoint(ticket_scopes)',
        '"requests.read" in codes and codes.isdisjoint(request_scopes)',
        "_ensure_record_read_scopes(list(permissions))",
    ):
        _require(
            marker in _read("backend/app/api/v1/routes/admin.py"),
            f"Backend role-scope dependency guard misses: {marker}",
        )
    _require(
        "test_service_request_read_requires_record_visibility_scope" in admin_tests
        and 'assert "visibility scope" in invalid.json()["error"]["message"]'
        in admin_tests,
        "Role visibility-scope dependency regressions are missing",
    )
    control_ids = {str(item["id"]) for item in controls}
    _require(
        "SEC-PERMISSION-AWARE-UI" in control_ids,
        "Permission-aware UI release control is missing",
    )

    print(
        "Permission-aware UI contract valid: custom and multi-role users share "
        "one central route evaluator across navigation and direct URLs; "
        "dashboard, administration, process consoles, system diagnostics, "
        "Copilot, and composite automation, integration, analytics, identity, "
        "notification, and configuration consoles are bounded by effective "
        "permissions."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Permission-aware UI contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
