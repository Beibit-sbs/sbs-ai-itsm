from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "backend" / "app" / "api" / "v1" / "routes"
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "api_route", "websocket"}
PROTECTION_MARKERS = {
    "Depends(get_current_user)",
    "Depends(get_scim_connector)",
    "Depends(service_bearer)",
    "_require_monitoring_token(",
    "_event_source_credentials(",
    "verify_monitoring_request(",
    "secrets.compare_digest(",
    "decode_token(",
}
PUBLIC_ENDPOINTS = {
    ("auth.py", "sso_config"): "OIDC discovery metadata without secrets",
    ("auth.py", "sso_login"): "OIDC authorization redirect bootstrap",
    ("auth.py", "login"): "credential and MFA login entry point",
    ("auth.py", "verify_mfa_login"): "short-lived MFA challenge exchange",
    ("health.py", "health"): "shallow process health",
    ("health.py", "liveness"): "orchestrator liveness",
    ("health.py", "readiness"): "dependency readiness without secret detail",
}


def _route_decorators(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.Call]:
    routes: list[ast.Call] = []
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr in ROUTE_METHODS
        ):
            routes.append(decorator)
    return routes


def _route_label(decorator: ast.Call) -> str:
    method = (
        decorator.func.attr.upper()
        if isinstance(decorator.func, ast.Attribute)
        else "ROUTE"
    )
    path = "<dynamic>"
    if (
        decorator.args
        and isinstance(decorator.args[0], ast.Constant)
        and isinstance(decorator.args[0].value, str)
    ):
        path = decorator.args[0].value
    return f"{method} {path}"


def main() -> int:
    violations: list[str] = []
    discovered_public: set[tuple[str, str]] = set()
    endpoint_count = 0
    protected_count = 0
    for path in sorted(ROUTES.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = _route_decorators(node)
            if not decorators:
                continue
            endpoint_count += len(decorators)
            function_source = ast.get_source_segment(source, node) or ""
            key = (path.name, node.name)
            if any(marker in function_source for marker in PROTECTION_MARKERS):
                protected_count += len(decorators)
                continue
            if key in PUBLIC_ENDPOINTS:
                discovered_public.add(key)
                continue
            labels = ", ".join(_route_label(item) for item in decorators)
            violations.append(f"{path.name}:{node.lineno} {node.name} [{labels}]")

    missing_public = set(PUBLIC_ENDPOINTS) - discovered_public
    if missing_public:
        violations.extend(
            f"stale public allowlist entry: {filename}:{function_name}"
            for filename, function_name in sorted(missing_public)
        )
    if endpoint_count < 700:
        violations.append(
            f"route inventory unexpectedly shrank to {endpoint_count} endpoints"
        )
    if violations:
        print("Route authentication contract invalid:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1

    print(
        "Route authentication contract valid: "
        f"{endpoint_count} endpoints, {protected_count} protected, "
        f"{len(discovered_public)} governed public."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"Route authentication contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
