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
    provider = _read("backend/app/services/ai/provider.py")
    service = _read("backend/app/services/ai/__init__.py")
    legacy = _read("backend/app/services/knowledge_ai.py")
    ai_routes = _read("backend/app/api/v1/routes/ai.py")
    admin_routes = _read("backend/app/api/v1/routes/admin.py")
    rag_routes = _read("backend/app/api/v1/routes/ai_retrieval.py")
    client = _read("frontend/src/api/client.ts")
    copilot = _read("frontend/src/pages/CopilotPage.tsx")
    translations = _read("frontend/src/i18n/catalog.ts")
    dashboard = _read("frontend/src/pages/DashboardPage.tsx")
    admin = _read("frontend/src/pages/AdminPage.tsx")
    admin_system = _read("frontend/src/pages/AdminSystemPage.tsx")
    rag_panel = _read("frontend/src/components/RagAssistantPanel.tsx")
    tests = _read("backend/tests/test_ai_provider.py")
    admin_tests = _read("backend/tests/test_admin_security.py")
    rag_tests = _read("backend/tests/test_ai_retrieval.py")
    controls = json.loads(
        _read("security/acceptance-catalog.json")
    )["controls"]

    finalize = _top_level_function(provider, "_finalize_from_json")
    status = _top_level_function(provider, "describe_provider_status")
    connection_test = _top_level_function(
        provider,
        "check_provider_configuration",
    )
    classify = _top_level_function(service, "classify_ticket_text")
    analyze = _top_level_function(service, "analyze_text_with_provider")

    _require(
        "provider=PROVIDER_MOCK" in finalize
        and 'model="keyword-rules-v1"' in finalize
        and "invalid_response_fallback" in finalize,
        "Invalid external output can still be labeled as provider success",
    )
    _require(
        "not _valid_classification_payload(parsed)" in finalize,
        "Incomplete external classification payload can still be accepted",
    )
    for marker in (
        "configured_provider=provider",
        "external_configured=ready",
        'execution_mode = "EXTERNAL_CONFIGURED"',
        'execution_mode = "LOCAL_SIMULATION"',
        'execution_mode = "FALLBACK_UNCONFIGURED"',
        'reason = "local_mock_simulation"',
    ):
        _require(marker in status, f"Provider status misses evidence marker: {marker}")
    _require(
        "success=False" in connection_test
        and "simulation=True" in connection_test
        and 'reason="local_mock_simulation"' in connection_test,
        "Mock provider test can still claim an external connection success",
    )
    _require(
        "result.provider != requested" in connection_test
        and 'reason="invalid_classification_response"' in connection_test,
        "External connection test can accept a fallback classification",
    )
    for marker in (
        '"requested_provider": provider_instance.name',
        '"provider": classification.provider',
        '"model": classification.model',
        '"provider_mock": classification.provider == PROVIDER_MOCK',
        '"fallback_used": classification.provider != provider_instance.name',
        '"execution_mode":',
    ):
        _require(marker in analyze, f"AI result evidence misses: {marker}")
    _require(
        '"SUCCESS"' in classify
        and '"BLOCKED"' in classify
        and '"FALLBACK"' in classify
        and 'failure_code=None if provider_success else "provider_fallback"'
        in classify,
        "AI usage ledger cannot distinguish fallback from success",
    )

    for marker in (
        '"requested_provider": "mock"',
        '"provider": "mock"',
        '"provider_mock": True',
        '"execution_mode": "LOCAL_SIMULATION"',
    ):
        _require(marker in legacy, f"Legacy local AI response misses: {marker}")

    for marker in (
        "configured_provider: str",
        "external_configured: bool",
        "execution_mode: str",
        "provider_mock: bool | None",
        "fallback_used: bool | None",
    ):
        _require(marker in ai_routes, f"AI API contract misses: {marker}")
    _require(
        "AiSuggestionResponse(**payload)" in ai_routes,
        "AI classify route no longer returns the governed evidence payload",
    )
    _require(
        "simulation: bool = False" in admin_routes
        and "simulation=result.simulation" in admin_routes,
        "Admin connection-test API hides local simulation evidence",
    )
    for marker in (
        "requested_provider: str",
        "provider_mock: bool",
        "fallback_used: bool",
        "execution_mode: str",
        "provider_mock = answer.provider == PROVIDER_MOCK",
        "fallback_used = answer.provider != requested_provider.name",
        "requested_provider=requested_provider.name",
        "provider_mock=provider_mock",
        "fallback_used=fallback_used",
        "execution_mode=execution_mode",
    ):
        _require(marker in rag_routes, f"RAG provider evidence misses: {marker}")

    for marker in (
        "requested_provider?: string | null",
        "provider_mock?: boolean | null",
        "fallback_used?: boolean | null",
        "simulation: boolean",
        "configured_provider: string",
        "external_configured: boolean",
        "execution_mode: string",
    ):
        _require(marker in client, f"Frontend AI contract misses: {marker}")
    _require(
        "Локальная AI-симуляция" in copilot
        and "result.provider_mock" in copilot
        and "result.fallback_used" in copilot
        and "result.requested_provider" in copilot
        and "Запрошенный provider" in copilot
        and "Режим выполнения" in copilot
        and "'Запрошенный provider': sourceMessage('Сұралған provider', 'Requested provider')"
        in translations
        and "'Режим выполнения': sourceMessage('Орындау режимі', 'Execution mode')"
        in translations
        and "AI live" not in copilot,
        "Copilot UI can still present local fallback as live AI",
    )
    _require(
        "aiTestResult.simulation" in admin
        and "Только локальная симуляция" in admin,
        "Administration UI hides mock connection-test simulation",
    )
    _require(
        "внешний provider не активирован" in admin
        and "Local AI simulation selected" in admin_system,
        "Administration save confirmation can still imply live mock AI",
    )
    _require(
        "aiConfigTestResult.simulation" in admin_system
        and "no external provider connection was tested" in admin_system
        and "External configured:" in admin_system,
        "System administration UI hides AI provider evidence mode",
    )
    _require(
        "answer.provider_mock" in rag_panel
        and "answer.fallback_used" in rag_panel
        and "answer.requested_provider" in rag_panel
        and "answer.execution_mode" in rag_panel
        and "Локальная AI-симуляция" in rag_panel,
        "RAG assistant hides requested/effective provider fallback evidence",
    )
    _require(
        "aiProviderQuery.data?.configured_provider" in dashboard
        and "aiProviderQuery.data?.active_provider" in dashboard
        and "aiProviderQuery.data?.execution_mode" in dashboard
        and "aiProviderQuery.data?.external_configured" in dashboard
        and "AI readiness" not in dashboard,
        "Dashboard can still present local AI simulation as provider readiness",
    )

    for regression in (
        "test_invalid_external_response_is_explicit_mock_fallback",
        "test_incomplete_external_object_is_explicit_mock_fallback",
        "test_mock_configuration_test_is_simulation_not_connection_success",
        "test_external_configuration_test_rejects_incomplete_payload",
        'assert info.ready is False',
        'assert payload["provider_mock"] is True',
        'assert payload["execution_mode"] == "LOCAL_SIMULATION"',
    ):
        _require(regression in tests, f"AI provider regression is missing: {regression}")
    for regression in (
        "test_ai_provider_config_test_endpoint_reports_mock_simulation",
        'assert payload["success"] is False',
        'assert payload["simulation"] is True',
        'assert payload["reason"] == "local_mock_simulation"',
    ):
        _require(
            regression in admin_tests,
            f"Admin AI provider regression is missing: {regression}",
        )
    for regression in (
        "test_rag_answer_contract_preserves_provider_fallback_evidence",
        'assert payload["requested_provider"] == "openai"',
        'assert payload["provider"] == "mock"',
        'assert payload["fallback_used"] is True',
    ):
        _require(
            regression in rag_tests,
            f"RAG AI provider regression is missing: {regression}",
        )

    control_ids = {str(item["id"]) for item in controls}
    _require(
        "SEC-AI-PROVIDER-EVIDENCE-INTEGRITY" in control_ids,
        "AI provider evidence release control is missing",
    )
    print(
        "AI provider evidence contract valid: mock execution and provider "
        "fallback remain explicit, external readiness is credential-bound, "
        "connection tests cannot promote simulation to success, and API/UI "
        "surfaces preserve requested/effective provider evidence."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"AI provider evidence contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
