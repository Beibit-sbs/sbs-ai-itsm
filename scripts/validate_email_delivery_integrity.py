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


def _class(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            _require(segment is not None, f"Cannot read class: {name}")
            return str(segment)
    raise ValueError(f"Class is missing: {name}")


def main() -> int:
    operations = _read("backend/app/services/email_operations.py")
    provider = _read("backend/app/services/email_provider.py")
    routes = _read("backend/app/api/v1/routes/email_channels.py")
    model = _read("backend/app/models/email_channel.py")
    page = _read("frontend/src/pages/EmailOperationsPage.tsx")
    log_page = _read("frontend/src/pages/EmailLogPage.tsx")
    dashboard_page = _read("frontend/src/pages/DashboardPage.tsx")
    client = _read("frontend/src/api/client.ts")
    migration = _read(
        "backend/migrations/versions/"
        "20260729_0071_reclassify_mock_email_delivery.py"
    )
    tests = _read("backend/tests/test_email_channel.py")
    controls = json.loads(
        _read("security/acceptance-catalog.json")
    )["controls"]

    queue = _top_level_function(operations, "queue_email")
    process = _top_level_function(operations, "process_outbound_queue")
    retry = _top_level_function(operations, "schedule_email_retry")
    mock_provider = _class(provider, "MockEmailProvider")
    mock_guard = _top_level_function(routes, "_require_mock_email_demo")
    dashboard = _top_level_function(routes, "email_dashboard")
    test_connection = _top_level_function(
        routes,
        "test_email_channel_connection",
    )
    state_change = _top_level_function(
        routes,
        "change_email_channel_state",
    )
    synchronize = _top_level_function(routes, "synchronize_email_channel")

    _require(
        'status = "SIMULATED"' in queue
        and "Simulation only; no external email was sent" in queue
        and 'status = "SENT"' not in queue
        and "sent_at = now" not in queue
        and '"delivery_confirmed": False' in queue,
        "Queueing a mock email can still fabricate transport delivery",
    )
    _require(
        'item.status = "SIMULATED"' in process
        and 'result["simulated"] += 1' in process
        and "item.sent_at = None" in process
        and "item.provider_message_id = None" in process
        and "Mock email channels are disabled outside demo mode" in process,
        "Queued mock processing is not explicit simulation or fail-closed",
    )
    _require(
        '"SIMULATED"' in retry,
        "A simulated message can be retried as if it were a failed delivery",
    )
    _require(
        'status="SIMULATED"' in mock_provider
        and "sent_at=None" in mock_provider
        and 'status="SENT"' not in mock_provider,
        "The direct mock email provider can still create sent evidence",
    )
    _require(
        "not get_settings().demo_mode" in mock_guard
        and "HTTP_410_GONE" in mock_guard,
        "Mock email administration is not production-disabled",
    )
    _require(
        "active_production_channels=active_production" in dashboard
        and "simulated_outbound=count(" in dashboard
        and '"SIMULATED"' in dashboard
        and "mock_provider_enabled=settings.demo_mode" in dashboard,
        "Email dashboard still presents simulation as healthy production",
    )
    _require(
        '"ok": False' in test_connection
        and '"status": "SIMULATED"' in test_connection
        and "email_channel_connection_simulated" in test_connection,
        "Mock connection tests can still report real connectivity",
    )
    _require(
        "_require_mock_email_demo(item.provider_type)" in state_change
        and "item.last_success_at = None" in state_change,
        "Mock channel activation can still create production readiness evidence",
    )
    _require(
        'item.provider_type != "MICROSOFT_GRAPH"' in synchronize
        and "Inbound synchronization requires Microsoft Graph" in synchronize,
        "Mock inbound synchronization can still report a successful no-op",
    )
    _require(
        "'SIMULATED'" in model
        and "ck_email_delivery_event_type" in model,
        "Delivery event schema does not support explicit simulation",
    )

    for marker in (
        "active_production_channels",
        "simulated_outbound",
        "mock_provider_enabled",
        "'SIMULATED'",
    ):
        _require(marker in client, f"Email client contract misses: {marker}")
    _require(
        "simulation only" in page
        and "dashboard?.mock_provider_enabled" in page
        and "Внешняя отправка не выполнялась" in page
        and "SIMULATED" in log_page
        and "emailSimulated" in dashboard_page,
        "Email UI does not visibly distinguish simulation from delivery",
    )

    for marker in (
        'revision: str = "20260729_0071"',
        'down_revision: str | None = "20260729_0070"',
        "SET status = 'SIMULATED'",
        "provider_message_id = NULL",
        "accepted_at = NULL",
        "sent_at = NULL",
        "delivered_at = NULL",
        "SET event_type = 'SIMULATED'",
        "SET success_count = 0",
        "last_success_at = NULL",
        "Invalidated delivery evidence must never be recreated",
    ):
        _require(marker in migration, f"Email evidence migration misses: {marker}")

    for regression in (
        "test_admin_can_configure_explicitly_simulated_mock_channel",
        "test_mock_email_never_creates_transport_success",
        "test_existing_mock_channel_fails_closed_outside_demo_mode",
        'assert queued.json()["status"] == "SIMULATED"',
        "assert item.sent_at is None",
        "assert channel.success_count == 0",
    ):
        _require(regression in tests, f"Email regression is missing: {regression}")

    control_ids = {str(item["id"]) for item in controls}
    _require(
        "SEC-EMAIL-DELIVERY-INTEGRITY" in control_ids,
        "Email delivery integrity release control is missing",
    )
    print(
        "Email delivery contract valid: production-disabled mock transport, "
        "explicit simulation without delivery timestamps/counters, "
        "Graph-only synchronization, honest dashboard/UI semantics, "
        "and historical evidence invalidation."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(
            f"Email delivery contract invalid: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
