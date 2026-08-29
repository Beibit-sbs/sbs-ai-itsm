from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _top_level_function(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                segment = ast.get_source_segment(source, node)
                _require(segment is not None, f"Cannot read function: {name}")
                return str(segment)
    raise ValueError(f"Top-level function is missing: {name}")


def main() -> int:
    service = _read("backend/app/services/automation.py")
    routes = _read("backend/app/api/v1/routes/automation.py")
    page = _read("frontend/src/pages/AutomationPage.tsx")
    migration = _read(
        "backend/migrations/versions/"
        "20260729_0070_reclassify_legacy_automation_evidence.py"
    )
    tests = _read("backend/tests/test_automation.py")
    controls = json.loads(
        _read("security/acceptance-catalog.json")
    )["controls"]

    conditions = _top_level_function(service, "evaluate_conditions")
    action = _top_level_function(service, "execute_action")
    execute = _top_level_function(service, "execute_rule")
    manual = _top_level_function(service, "run_manual_rule")
    runbook = _top_level_function(service, "run_runbook")
    retry = _top_level_function(service, "retry_execution")
    ticket_scope = _top_level_function(service, "_context_ticket")

    _require(
        "else:\n        return False" in conditions
        and "if not isinstance(conditions, list):\n        return False"
        in conditions
        and "results.append(False)" in conditions,
        "Malformed or incomplete automation conditions do not fail closed",
    )
    _require(
        "Ticket.tenant_id == tenant_id" in ticket_scope
        and "tenant_id=effective_tenant_id" in execute
        and '"tenant_scoped_ticket_required"' in action,
        "Automation ticket actions are not tenant scoped",
    )
    _require(
        'status="SIMULATED"' in action
        and "sent_at=None" in action
        and '"delivery_confirmed": False' in action
        and 'outcome(\n            "simulated"' in action
        and 'status="SENT"' not in action,
        "Mock automation email can still claim external delivery",
    )
    _require(
        '"exported": False' in action
        and '"action_not_implemented"' in action
        and '"safe no-op"' not in action
        and 'result["accepted"] = True' not in action,
        "Unimplemented or preview automation actions can still report success",
    )
    _require(
        'status_counts = {' in execute
        and 'run.status = "partial"' in execute
        and 'run.status = "simulated"' in execute
        and 'run.status = "skipped"' in execute
        and 'run.status = "success"' in execute
        and "Rule actions must contain only objects" in execute,
        "Automation run status is not derived from per-action evidence",
    )
    _require(
        "rule.tenant_id not in {None, current_user.tenant_id}" in manual
        and "runbook.tenant_id not in {None, current_user.tenant_id}"
        in runbook
        and "execution.tenant_id != current_user.tenant_id" in retry,
        "Manual, runbook, or retry service paths lack tenant isolation",
    )
    _require(
        '"manual_pending"' in runbook
        and '"completion_confirmed": False' in runbook
        and '"runbook_started"' in runbook,
        "Starting a manual runbook still fabricates completion",
    )
    for route_control in (
        "source_execution = db.scalar(",
        "Terminal runbook execution is immutable",
        "Runbook step exceeds the governed checklist",
        "All runbook checklist steps must be reached before completion",
        "Runbook has no executable checklist steps",
    ):
        _require(
            route_control in routes,
            f"Automation route integrity control is missing: {route_control}",
        )
    _require(
        routes.count("max_length=50") >= 2
        and routes.count("max_length=100") >= 2
        and "cooldown_minutes: int = Field" in routes,
        "Automation rule/runbook inputs are not bounded",
    )
    _require(
        "function statusBadge(status: string)" in page
        and "'badge-warning'" in page
        and "statusBadge(execution.status)" in page
        and "statusBadge(approval.status)" in page,
        "Automation UI does not distinguish non-success execution states",
    )

    for marker in (
        'revision: str = "20260729_0070"',
        'down_revision: str | None = "20260729_0069"',
        "provider = 'mock_automation'",
        "status = 'SIMULATED'",
        "accepted_at = NULL",
        "sent_at = NULL",
        "delivered_at = NULL",
        "SET status = 'manual_pending'",
        "SET status = 'partial'",
        "Invalidated delivery, action, and completion evidence is not restorable",
    ):
        _require(marker in migration, f"Automation evidence migration misses: {marker}")

    for regression in (
        "test_mock_email_is_simulated_and_never_marked_sent",
        "test_automation_action_cannot_mutate_cross_tenant_ticket",
        "test_manual_rule_execution_hides_cross_tenant_rule",
        "test_malformed_automation_conditions_fail_closed",
        "assert preview['sent_at'] is None",
        "assert run.json()['status'] == 'manual_pending'",
    ):
        _require(regression in tests, f"Automation regression is missing: {regression}")

    control_ids = {str(item["id"]) for item in controls}
    _require(
        "SEC-AUTOMATION-EXECUTION-INTEGRITY" in control_ids,
        "Automation execution integrity release control is missing",
    )
    print(
        "Automation execution contract valid: fail-closed conditions, "
        "tenant-scoped actions/runs/retries, evidence-derived statuses, "
        "non-delivery mock semantics, governed manual checklist completion, "
        "and historical evidence invalidation."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(
            f"Automation execution contract invalid: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
