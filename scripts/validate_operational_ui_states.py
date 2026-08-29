from __future__ import annotations

import ast
from pathlib import Path
import json
import re
import sys


ROOT = Path(__file__).resolve().parents[1]

TICKET_HISTORY_PRODUCERS = (
    "backend/app/api/v1/routes/tickets.py",
    "backend/app/services/ai_actions.py",
    "backend/app/services/automation.py",
    "backend/app/services/email_operations.py",
    "backend/app/services/event_operations.py",
    "backend/app/services/service_desk.py",
    "backend/app/services/ticket_lifecycle.py",
    "backend/app/services/workflow_engine.py",
)

TICKET_HISTORY_CATALOG_KEYS = {
    "notification_created": "ticket.history.event.notificationCreated",
    "created": "ticket.history.event.created",
    "created_on_behalf": "ticket.history.event.createdOnBehalf",
    "status_changed": "ticket.history.event.statusChanged",
    "updated": "ticket.history.event.updated",
    "assigned": "ticket.history.event.assigned",
    "comment_added": "ticket.history.event.commentAdded",
    "ticket_participant_added": "ticket.history.event.participantAdded",
    "ticket_participant_reactivated": "ticket.history.event.participantReactivated",
    "ticket_participant_removed": "ticket.history.event.participantRemoved",
    "duplicate_candidate_dismissed": "ticket.history.event.duplicateCandidateDismissed",
    "ticket_merged": "ticket.history.event.ticketMerged",
    "ticket_merge_received": "ticket.history.event.ticketMergeReceived",
    "ticket_split": "ticket.history.event.ticketSplit",
    "created_from_split": "ticket.history.event.createdFromSplit",
    "ai_guarded_action": "ticket.history.event.aiGuardedAction",
    "ai_guarded_action_rollback": "ticket.history.event.aiGuardedActionRollback",
    "automation_escalation": "ticket.history.event.automationEscalation",
    "runbook_attached": "ticket.history.event.runbookAttached",
    "automation_note": "ticket.history.event.automationNote",
    "automation_comment": "ticket.history.event.automationComment",
    "workflow_comment": "ticket.history.event.workflowComment",
    "workflow_field_update": "ticket.history.event.workflowFieldUpdate",
    "created_from_email": "ticket.history.event.createdFromEmail",
    "email_reply_added": "ticket.history.event.emailReplyAdded",
    "event_correlated": "ticket.history.event.eventCorrelated",
    "lifecycle_transition_rejected": "ticket.history.event.lifecycleTransitionRejected",
}


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _literal_strings(node: ast.AST | None) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _literal_strings(node.body) | _literal_strings(node.orelse)
    return set()


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _assigned_literals(scope: ast.AST, variable_name: str) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == variable_name
                for target in node.targets
            ):
                values.update(_literal_strings(node.value))
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == variable_name
        ):
            values.update(_literal_strings(node.value))
    return values


def _discover_ticket_history_events(path: str) -> set[str]:
    tree = ast.parse(_read(path), filename=path)
    result: set[str] = set()
    history_call_names = {"TicketHistory", "_write_history", "_ticket_history"}
    scopes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for scope in scopes:
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call) or _call_name(node) not in history_call_names:
                continue
            event_keyword = next(
                (keyword for keyword in node.keywords if keyword.arg == "event_type"),
                None,
            )
            if event_keyword is None:
                continue
            values = _literal_strings(event_keyword.value)
            if isinstance(event_keyword.value, ast.Name):
                values.update(_assigned_literals(scope, event_keyword.value.id))
            result.update(values)
    return result


def main() -> int:
    component = _read("frontend/src/components/QueryFailureNotice.tsx")
    translations = _read("frontend/src/i18n/catalog.ts")
    for marker in (
        'role="alert"',
        "failed.map(({ label }) => translate(label)).join(', ')",
        "void query.refetch()",
    ):
        _require(marker in component, f"Query failure notice misses: {marker}")
    _require(
        "Пустые значения не следует интерпретировать" in translations
        and "failure.detail" in component,
        "Query failure notice misses localized empty-state safety guidance",
    )

    shared_notice_surfaces = {
        "frontend/src/pages/IdentityProvisioningPage.tsx": 10,
        "frontend/src/pages/IntegrationsPage.tsx": 8,
        "frontend/src/pages/EmailOperationsPage.tsx": 8,
        "frontend/src/pages/TeamsCollaborationPage.tsx": 5,
        "frontend/src/pages/ConfigurationPackagesPage.tsx": 6,
        "frontend/src/pages/ReleasesPage.tsx": 8,
        "frontend/src/pages/ProblemGovernancePage.tsx": 7,
        "frontend/src/pages/ChangeGovernancePage.tsx": 11,
        "frontend/src/pages/MonitoringPage.tsx": 6,
        "frontend/src/pages/SlaPage.tsx": 8,
        "frontend/src/pages/AnalyticsPage.tsx": 11,
        "frontend/src/pages/AssetsPage.tsx": 13,
        "frontend/src/pages/CatalogPage.tsx": 7,
        "frontend/src/pages/CustomFieldsPage.tsx": 7,
        "frontend/src/pages/TicketsPage.tsx": 8,
        "frontend/src/pages/AdminSystemPage.tsx": 11,
        "frontend/src/components/WorkflowEnginePanel.tsx": 10,
        "frontend/src/components/IntegrationPlatformPanel.tsx": 9,
        "frontend/src/components/AssetDiscoveryPanel.tsx": 5,
        "frontend/src/components/AiGovernancePanel.tsx": 4,
        "frontend/src/components/CMDBQualityPanel.tsx": 4,
        "frontend/src/components/AiActionsPanel.tsx": 2,
        "frontend/src/components/CatalogFormDesigner.tsx": 2,
        "frontend/src/components/AiRuntimeControlsPanel.tsx": 1,
    }
    source_count = 0
    for path, expected_sources in shared_notice_surfaces.items():
        surface = _read(path)
        _require(
            "QueryFailureNotice" in surface,
            f"{path} does not expose query failure diagnostics",
        )
        actual_sources = surface.count("query:")
        _require(
            actual_sources >= expected_sources,
            f"{path} covers {actual_sources}/{expected_sources} query sources",
        )
        source_count += expected_sources

    dashboard = _read("frontend/src/pages/DashboardPage.tsx")
    _require(
        "const failedDashboardSources" in dashboard
        and "Значения помечены «—»" in dashboard
        and dashboard.count("queryValue(") >= 14,
        "Dashboard can still represent failed sources as valid zero metrics",
    )

    tickets = _read("frontend/src/pages/TicketsPage.tsx")
    for marker in (
        "const ticketHistoryMessage = (item: TicketHistory): ReactNode",
        "const ticketHistoryEventTypes = [",
        "const ticketHistoryEventLabelKeys: Record<TicketHistoryEventType, UiMessageKey>",
        "function TicketHistoryRawValue({ value }: { value: string })",
        "if (!isKnownTicketHistoryEvent(item.event_type))",
        "switch (eventType)",
        "item.field_name === 'status'",
        "statusLabel(item.old_value, translate)",
        "statusLabel(item.new_value, translate)",
        "if (fieldName === 'priority') return priorityLabel(value, translate)",
        "t('ticket.history.statusChanged', { oldStatus, newStatus })",
        "case 'comment_added':",
        "return withValue(eventLabel, item.new_value, 'comment')",
        "case 'event_correlated':",
        "return eventLabel",
        "<strong><TicketHistoryRawValue value={item.actor_name} /></strong>",
        "<p>{ticketHistoryMessage(item)}</p>",
    ):
        _require(marker in tickets, f"Ticket history localization misses: {marker}")

    whitelist_match = re.search(
        r"const ticketHistoryEventTypes = \[(.*?)\]\s+as const",
        tickets,
        flags=re.DOTALL,
    )
    _require(whitelist_match is not None, "Ticket history event whitelist is missing")
    frontend_events = set(re.findall(r"'([^']+)'", whitelist_match.group(1)))
    expected_events = set(TICKET_HISTORY_CATALOG_KEYS)
    _require(
        frontend_events == expected_events,
        "Ticket history frontend whitelist drifted: "
        f"missing={sorted(expected_events - frontend_events)}, "
        f"unexpected={sorted(frontend_events - expected_events)}",
    )

    backend_events: set[str] = set()
    for producer in TICKET_HISTORY_PRODUCERS:
        backend_events.update(_discover_ticket_history_events(producer))
    _require(
        backend_events == expected_events,
        "Ticket history producer whitelist drifted: "
        f"unmapped={sorted(backend_events - expected_events)}, "
        f"stale={sorted(expected_events - backend_events)}",
    )

    for event_type, catalog_key in TICKET_HISTORY_CATALOG_KEYS.items():
        _require(
            f"case '{event_type}'" in tickets,
            f"Ticket history renderer misses event_type={event_type}",
        )
        _require(
            f"{event_type}: '{catalog_key}'" in tickets,
            f"Ticket history label map misses event_type={event_type}",
        )
        _require(
            f"'{catalog_key}': message(" in translations,
            f"Ticket history catalog key is missing: {catalog_key}",
        )

    _require(
        "item.message" not in tickets
        and "translate(item.new_value" not in tickets
        and "translate(item.old_value" not in tickets
        and "t(item.new_value" not in tickets
        and "t(item.old_value" not in tickets,
        "Ticket history uses raw system messages or translates user-authored content",
    )
    for key in (
        "ticket.history.statusChanged",
        "ticket.history.statusChangedTo",
        "ticket.history.statusChangedGeneric",
        "ticket.history.event.unknown",
        "ticket.history.fieldPrefix",
        "ticket.history.previousValue",
        "ticket.history.newValue",
        "ticket.history.valueNotSet",
    ):
        _require(key in translations, f"Ticket history catalog key is missing: {key}")

    direct_pages = {
        "RequestsPage.tsx": (
            "!listQuery.isError && requests.length === 0",
            "void governanceQuery.refetch()",
        ),
        "ProblemsPage.tsx": (
            "!knownErrorsQuery.isError && !knownErrorsQuery.data?.items.length",
            "!listQuery.isError && !listQuery.data?.items.length",
            "void detailQuery.refetch()",
        ),
        "MajorIncidentsPage.tsx": (
            "!listQuery.isError && !listQuery.data?.length",
            "detailQuery.isError",
            "void summaryQuery.refetch()",
        ),
        "ChangesPage.tsx": (
            "!listQuery.isError && !listQuery.data?.items.length",
            "!detailQuery.isError",
        ),
        "CatalogPage.tsx": (
            "!itemsQuery.isError && visibleItems.length === 0",
        ),
        "EventOperationsPage.tsx": (
            "!groupsQuery.isError && !groupsQuery.data?.length",
            "!receiptsQuery.isError && !receiptsQuery.data?.length",
            "summaryQuery.isError ? '—'",
        ),
        "AutomationPage.tsx": (
            "const queryErrors = [",
            "!rulesQuery.isError &&",
            "!executionsQuery.isError &&",
            "!approvalsQuery.isError &&",
        ),
    }
    for filename, markers in direct_pages.items():
        page = _read(f"frontend/src/pages/{filename}")
        for marker in markers:
            _require(
                marker in page,
                f"{filename} does not distinguish error from empty state: {marker}",
            )

    controls = json.loads(_read("security/acceptance-catalog.json"))["controls"]
    control_ids = {str(item["id"]) for item in controls}
    _require(
        "UX-OPERATIONAL-UI-STATES" in control_ids,
        "Operational UI release control is missing",
    )

    print(
        "Operational UI state contract valid: "
        f"{len(shared_notice_surfaces)} composite surfaces and {source_count} query "
        "sources expose retryable diagnostics; primary queues do not mask API "
        "failures as empty data or zero metrics."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Operational UI state contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
