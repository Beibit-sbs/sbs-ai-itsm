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


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _validate_guard_order(routes: str) -> int:
    tree = ast.parse(routes)
    guarded = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [
            (_call_name(child), child.lineno)
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
        ]
        legacy_lines = [
            line for name, line in calls if name == "_require_legacy_demo"
        ]
        if not legacy_lines:
            continue
        guarded += 1
        permission_lines = [
            line for name, line in calls if name == "require_permissions"
        ]
        _require(
            permission_lines and min(permission_lines) < min(legacy_lines),
            f"{node.name} exposes demo-mode state before authorization",
        )
    _require(guarded >= 19, "Legacy mutation guard coverage is incomplete")
    return guarded


def main() -> int:
    routes = _read("backend/app/api/v1/routes/integrations.py")
    providers = _read("backend/app/services/integrations/providers.py")
    service = _read("backend/app/services/integrations/__init__.py")
    client = _read("frontend/src/api/client.ts")
    page = _read("frontend/src/pages/IntegrationsPage.tsx")
    migration = _read(
        "backend/migrations/versions/"
        "20260729_0069_reclassify_legacy_integration_simulations.py"
    )
    tests = _read("backend/tests/test_integrations.py")
    controls = json.loads(
        _read("security/acceptance-catalog.json")
    )["controls"]

    guarded = _validate_guard_order(routes)
    _require(
        '@router.get("/runtime-capabilities")' in routes
        and '"production_control_plane_enabled": True' in routes
        and '"legacy_demo_enabled": get_settings().demo_mode' in routes,
        "The authenticated runtime capability boundary is missing",
    )
    _require(
        'status = "simulated" if simulated else "success"' in service
        and "if not simulated:" in service
        and "if simulated:\n        return event" in service
        and "simulated=True" in routes,
        "Webhook simulation can still mutate success evidence or trigger side effects",
    )
    _require(
        "provider_mode == \"production\"" in service
        and 'return "simulated"' in service
        and 'return "skipped"' in service
        and 'system.last_success_at = now' in service,
        "Provider evidence is not explicitly classified before success",
    )
    _require(
        'event.status = outcome if outcome != "skipped" else "failed"'
        in service
        and 'if outcome in {"success", "simulated"}:' in service
        and 'event.error_message = "Provider did not confirm external delivery"'
        in service,
        "Retry processing does not preserve the production/simulation boundary",
    )
    _require(
        "job.success_rows = success_rows" in service
        and "success_rows = 0" in service
        and "job.records_success = 0" in service
        and '"simulated_with_errors" if failed_rows else "simulated"'
        in service,
        "Legacy import preview can still claim imported records",
    )
    _require(
        '"exported": False' in providers
        and '"status": "simulated"' in providers
        and '"status": "success"' not in providers,
        "Legacy providers can still emit unconfirmed success",
    )
    _require(
        "export type IntegrationRuntimeCapabilities" in client
        and "fetchIntegrationRuntimeCapabilities" in client
        and "if (!legacyDemoEnabled) return available" in page
        and page.count(
            "enabled: Boolean(session?.access_token && legacyDemoEnabled &&"
        )
        >= 7
        and page.count("legacyDemoEnabled && activeTab ===") >= 8
        and page.count("throw new Error('Legacy demo action is unavailable')") >= 5
        and "const canRunAction = action === 'webhook' ? canManageWebhooks : canRunJobs"
        in page,
        "The production UI still exposes or queries legacy demo actions",
    )
    for status_name in (
        "simulated",
        "mock",
        "demo",
        "planned",
        "future",
        "logged_only",
        "mocked",
    ):
        _require(
            status_name in page.split("function statusBadge", 1)[1].split(
                "\n}",
                1,
            )[0],
            f"UI does not distinguish non-production status: {status_name}",
        )

    for marker in (
        'revision: str = "20260729_0069"',
        'down_revision: str | None = "20260729_0068"',
        "last_success_at = NULL",
        "SET status = 'simulated'",
        "success_rows = 0",
        "records_success = 0",
        "dry_run = TRUE",
        "success_count = 0",
        "Invalidated success evidence cannot be safely reconstructed",
    ):
        _require(marker in migration, f"Legacy evidence migration misses: {marker}")

    for regression in (
        'assert response.json()["status"] == "simulated"',
        'assert event.json()["status"] == "simulated"',
        'refreshed_webhook["success_count"] == webhook["success_count"]',
        'refreshed_webhook["last_received_at"]',
    ):
        _require(regression in tests, f"Integration regression is missing: {regression}")

    control_ids = {str(item["id"]) for item in controls}
    _require(
        "SEC-LEGACY-INTEGRATION-SIMULATION-BOUNDARY" in control_ids,
        "Legacy integration simulation release control is missing",
    )
    print(
        "Legacy integration boundary valid: "
        f"{guarded} authorized demo mutation paths, honest provider outcomes, "
        "side-effect-free webhook simulation, production-only UI control plane, "
        "and legacy evidence invalidation."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(
            f"Legacy integration boundary invalid: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
