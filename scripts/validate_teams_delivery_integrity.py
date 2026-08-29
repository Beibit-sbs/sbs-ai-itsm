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
    service = _read("backend/app/services/teams_collaboration.py")
    routes = _read("backend/app/api/v1/routes/teams_collaboration.py")
    model = _read("backend/app/models/teams_collaboration.py")
    client = _read("frontend/src/api/client.ts")
    page = _read("frontend/src/pages/TeamsCollaborationPage.tsx")
    tests = _read("backend/tests/test_teams_collaboration.py")
    migration = _read(
        "backend/migrations/versions/"
        "20260729_0072_reclassify_mock_teams_delivery.py"
    )
    controls = json.loads(
        _read("security/acceptance-catalog.json")
    )["controls"]

    queue = _top_level_function(service, "queue_teams_event")
    room = _top_level_function(service, "ensure_major_incident_room")
    transport = _top_level_function(service, "deliver_teams_payload")
    process = _top_level_function(service, "process_teams_delivery")
    cycle = _top_level_function(service, "run_teams_delivery_cycle")
    mock_guard = _top_level_function(routes, "_require_mock_teams_demo")
    dashboard = _top_level_function(routes, "teams_dashboard")
    test_route = _top_level_function(routes, "test_teams_connector")
    rotate = _top_level_function(routes, "rotate_teams_webhook")
    state = _top_level_function(routes, "change_teams_connector_state")

    _require(
        'connector.provider_type == "MOCK" and not runtime.demo_mode'
        in queue,
        "Production event queue can still target a mock Teams connector",
    )
    _require(
        'TeamsConnector.provider_type == "WORKFLOW_WEBHOOK"' in room
        and "get_settings().demo_mode" in room,
        "Production major-incident rooms can still select a mock connector",
    )
    _require(
        "Mock Teams connector is simulation-only" in transport
        and "return 200" not in transport
        and "mock:" not in transport,
        "Mock Teams transport can still fabricate HTTP success",
    )
    _require(
        'delivery.status = "SIMULATED"' in process
        and "delivery.attempts = 0" in process
        and "delivery.last_attempt_at = None" in process
        and "delivery.sent_at = None" in process
        and "delivery.provider_status_code = None" in process
        and "delivery.provider_reference = None" in process
        and "Mock Teams connectors are disabled outside demo mode" in process,
        "Mock Teams delivery is not explicit simulation or fail-closed",
    )
    _require(
        'elif row.status == "SIMULATED"' in cycle
        and '"simulated": simulated' in cycle,
        "Teams delivery cycle hides simulated outcomes",
    )
    _require(
        "not get_settings().demo_mode" in mock_guard
        and "HTTP_410_GONE" in mock_guard,
        "Mock Teams administration is not production-disabled",
    )
    _require(
        "active_production_connectors=active_production" in dashboard
        and "simulated_deliveries=int(" in dashboard
        and '"SIMULATED"' in dashboard
        and "mock_provider_enabled=runtime.demo_mode" in dashboard,
        "Teams dashboard presents simulation as production health",
    )
    _require(
        '"ok": False' in test_route
        and '"status": "SIMULATED"' in test_route
        and "teams.connector_test_simulated" in test_route
        and '"delivery_confirmed": False' in test_route,
        "Mock Teams connection test can still report real delivery",
    )
    _require(
        'item.provider_type != "WORKFLOW_WEBHOOK"' in rotate,
        "Mock connector can still accept a misleading webhook rotation",
    )
    _require(
        "_require_mock_teams_demo(item.provider_type)" in state,
        "Mock Teams activation is not production-disabled",
    )
    _require(
        "'SIMULATED'" in model
        and "ck_teams_deliveries_status" in model,
        "Teams delivery schema lacks an explicit simulation status",
    )

    for marker in (
        "active_production_connectors",
        "simulated_deliveries",
        "mock_provider_enabled",
    ):
        _require(marker in client, f"Teams client contract misses: {marker}")
    _require(
        "simulation only" in page
        and "Локальная симуляция" in page
        and "Webhook не вызывался" in page
        and "'SIMULATED'" in page,
        "Teams UI does not visibly separate simulation from sent delivery",
    )

    for marker in (
        'revision: str = "20260729_0072"',
        'down_revision: str | None = "20260729_0071"',
        "SET status = 'SIMULATED'",
        "attempts = 0",
        "last_attempt_at = NULL",
        "sent_at = NULL",
        "provider_status_code = NULL",
        "provider_reference = NULL",
        "SET success_count = 0",
        "last_success_at = NULL",
        "must not be restored as sent",
    ):
        _require(marker in migration, f"Teams evidence migration misses: {marker}")

    for regression in (
        "test_mock_delivery_is_simulated_without_transport_success",
        "test_mock_delivery_fails_closed_outside_demo_mode",
        'assert delivery.status == "SIMULATED"',
        "assert delivery.attempts == 0",
        "assert delivery.sent_at is None",
        'assert tested.json()["ok"] is False',
        'assert tested.json()["status"] == "SIMULATED"',
        'assert refreshed.json()["success_count"] == 0',
    ):
        _require(regression in tests, f"Teams regression is missing: {regression}")

    control_ids = {str(item["id"]) for item in controls}
    _require(
        "SEC-TEAMS-DELIVERY-INTEGRITY" in control_ids,
        "Teams delivery integrity release control is missing",
    )
    print(
        "Teams delivery contract valid: production-disabled mock connector, "
        "explicit simulation without HTTP/reference/timestamp/counters, "
        "workflow-only production routing, honest dashboard/UI semantics, "
        "and historical evidence invalidation."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(
            f"Teams delivery contract invalid: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
