from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.services.ai.pii import redact_pii, restore_pii
from app.services.ai.provider import (
    ClassificationResult,
    GeminiLLMProvider,
    MockLLMProvider,
    OpenAILLMProvider,
    _validated_https_provider_url,
    _clamp_priority,
    _finalize_from_json,
    _safe_parse_json_object,
    describe_provider_status,
    get_provider,
    check_provider_configuration,
)


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_pii_redaction_replaces_email_and_phone_and_iin() -> None:
    text = "Свяжитесь с ivan@example.com или +7 700 555 44 33. ИИН 123456789012. IP 192.168.1.10 карта 4111 1111 1111 1111."
    result = redact_pii(text)
    assert "ivan@example.com" not in result.text
    assert "192.168.1.10" not in result.text
    assert "123456789012" not in result.text
    assert "<EMAIL_" in result.text
    assert "<IP_" in result.text
    assert "<IIN_" in result.text
    # Cards go through card token since 16 digits satisfy CARD pattern first.
    assert any(tok.startswith("<EMAIL_") for tok in result.tokens)
    assert any(tok.startswith("<IP_") for tok in result.tokens)


def test_pii_restore_returns_original() -> None:
    original = "Пиши на ivan@example.com"
    redacted = redact_pii(original)
    assert redacted.text != original
    restored = restore_pii(redacted.text, redacted.tokens)
    assert restored == original


def test_clamp_priority_normalises_variants() -> None:
    assert _clamp_priority("HIGH") == "high"
    assert _clamp_priority("urgent") == "critical"
    assert _clamp_priority("p2") == "high"
    assert _clamp_priority(None) == "medium"
    assert _clamp_priority("whatever") == "medium"
    assert _clamp_priority("nonsense", fallback="low") == "low"


def test_safe_parse_json_object_handles_fenced_output() -> None:
    payload = "```json\n{\"category\": \"Test\", \"priority\": \"low\"}\n```"
    parsed = _safe_parse_json_object(payload)
    assert parsed is not None
    assert parsed["category"] == "Test"


def test_safe_parse_json_object_returns_none_for_garbage() -> None:
    assert _safe_parse_json_object("not json at all") is None


def test_invalid_external_response_is_explicit_mock_fallback() -> None:
    result = _finalize_from_json("openai", "gpt-test", None)

    assert result.provider == "mock"
    assert result.model == "keyword-rules-v1"
    assert result.rationale == "openai:invalid_response_fallback"


def test_incomplete_external_object_is_explicit_mock_fallback() -> None:
    result = _finalize_from_json(
        "gemini",
        "gemini-test",
        {"category": "Network", "unexpected": "not-a-contract"},
    )

    assert result.provider == "mock"
    assert result.model == "keyword-rules-v1"
    assert result.rationale == "gemini:invalid_response_fallback"


def test_mock_provider_returns_expected_category_for_network_keyword() -> None:
    provider = MockLLMProvider()
    result = asyncio.run(provider.classify_ticket("У меня не работает интернет и wifi"))
    assert isinstance(result, ClassificationResult)
    assert "Сеть" in result.category
    assert result.priority in {"low", "medium", "high", "critical"}
    assert 0.0 <= result.confidence <= 1.0
    assert result.provider == "mock"


def test_mock_provider_default_when_no_match(app) -> None:  # noqa: ARG001 - fixture ensures settings loaded
    provider = MockLLMProvider()
    result = asyncio.run(provider.classify_ticket("совершенно нейтральный текст"))
    assert result.category
    assert result.priority == "medium"


def test_openai_provider_direct_instantiation() -> None:
    provider = OpenAILLMProvider(
        api_key="sk-test-xyz",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        timeout=5.0,
    )
    assert provider.name == "openai"
    assert provider.model == "gpt-4o-mini"
    assert provider.has_api_key is True
    assert provider.is_mock is False


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1/chat/completions",
        "file:///etc/passwd",
        "https://user:password@api.openai.com/v1/chat/completions",
        "https://api.openai.com:8443/v1/chat/completions",
    ],
)
def test_ai_provider_rejects_nonstandard_or_credentialed_destinations(url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS endpoint"):
        _validated_https_provider_url(url)


def test_ai_provider_allows_https_destination_and_gemini_query_key() -> None:
    url = "https://generativelanguage.googleapis.com/v1/models/x?key=secret"
    assert _validated_https_provider_url(url) == url


def test_gemini_provider_direct_instantiation() -> None:
    provider = GeminiLLMProvider(api_key="test-gemini-key", model="gemini-2.0-flash-exp", timeout=5.0)
    assert provider.name == "gemini"
    assert provider.model == "gemini-2.0-flash-exp"
    assert provider.has_api_key is True
    assert provider.is_mock is False


def test_get_provider_returns_mock_by_default(app) -> None:  # noqa: ARG001
    provider = get_provider()
    assert isinstance(provider, MockLLMProvider)


def test_describe_provider_status_reports_mock_by_default(app) -> None:  # noqa: ARG001
    info = describe_provider_status()
    assert info.configured_provider == "mock"
    assert info.active_provider == "mock"
    assert info.ready is False
    assert info.external_configured is False
    assert info.execution_mode == "LOCAL_SIMULATION"
    assert info.api_key_configured is False
    assert info.reason == "local_mock_simulation"
    assert info.fallback_provider is None


def test_mock_configuration_test_is_simulation_not_connection_success() -> None:
    result = asyncio.run(
        check_provider_configuration(
            provider="mock",
            sample_text="network connection is unavailable",
        )
    )

    assert result.requested_provider == "mock"
    assert result.effective_provider == "mock"
    assert result.success is False
    assert result.simulation is True
    assert result.reason == "local_mock_simulation"


def test_external_configuration_test_rejects_incomplete_payload(monkeypatch) -> None:
    async def _incomplete_response(*args, **kwargs):  # noqa: ANN002, ANN003
        return 200, {
            "choices": [
                {
                    "message": {
                        "content": '{"category":"Network","unexpected":"value"}'
                    }
                }
            ]
        }

    monkeypatch.setattr(
        OpenAILLMProvider,
        "_http_post_json",
        _incomplete_response,
    )
    result = asyncio.run(
        check_provider_configuration(
            provider="openai",
            sample_text="network connection is unavailable",
            openai_api_key="sk-test-only",
        )
    )

    assert result.success is False
    assert result.simulation is False
    assert result.effective_provider == "mock"
    assert result.model == "keyword-rules-v1"
    assert result.reason == "invalid_classification_response"
    assert result.response_status == 200


def test_provider_status_endpoint_requires_authentication(app) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/ai/provider-status")
    assert response.status_code == 401


def test_provider_status_endpoint_allows_rag_entitled_requester(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "requester@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/ai/provider-status", headers=_headers(token))
    assert response.status_code == 200


def test_provider_status_endpoint_allows_ai_entitled_operator(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "agent.network@sbs.local", "Sbs!2026")
        response = client.get("/api/v1/ai/provider-status", headers=_headers(token))
    assert response.status_code == 200
    assert response.json()["execution_mode"] == "LOCAL_SIMULATION"


def test_provider_status_endpoint_returns_mock_defaults(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "root@sbs.local", "Root!2026")
        response = client.get("/api/v1/ai/provider-status", headers=_headers(token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured_provider"] == "mock"
    assert payload["active_provider"] == "mock"
    assert payload["ready"] is False
    assert payload["external_configured"] is False
    assert payload["execution_mode"] == "LOCAL_SIMULATION"
    assert payload["api_key_configured"] is False
    assert payload["reason"] == "local_mock_simulation"
    assert "mock" in payload["supported_providers"]
    assert "openai" in payload["supported_providers"]
    assert "gemini" in payload["supported_providers"]
    # Ensure no secret-like fields leak.
    serialized = str(payload).lower()
    assert "sk-" not in serialized
    assert "api_key" not in serialized or "api_key_configured" in serialized
    assert "openai_api_key" not in serialized


def test_classify_endpoint_creates_suggestion_with_mock(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "manager@sbs.local", "Sbs!2026")
        response = client.post(
            "/api/v1/ai/classify",
            headers=_headers(token),
            json={"input_text": "не работает интернет в офисе"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["recommended_priority"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert payload["recommended_category"]
    assert payload["confidence_value"] is not None
    assert payload["rationale"].startswith("mock:")
    assert payload["requested_provider"] == "mock"
    assert payload["provider"] == "mock"
    assert payload["model"] == "keyword-rules-v1"
    assert payload["provider_mock"] is True
    assert payload["fallback_used"] is False
    assert payload["execution_mode"] == "LOCAL_SIMULATION"


def test_classify_endpoint_requires_permission(app) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/classify",
            json={"input_text": "any"},
        )
    assert response.status_code == 401
