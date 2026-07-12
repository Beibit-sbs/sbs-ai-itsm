"""LLM provider abstraction for SBS AI ITSM.

Design goals:
- Zero external SDK dependency (uses urllib + asyncio.to_thread for HTTP so we do
  not need to pin OpenAI/Google client versions in the container image).
- Safe by default: if no API key is configured, the mock provider is returned
  and everything continues to work as before.
- No secrets are exposed via any public function — only booleans about whether
  keys are configured.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("app.ai.provider")


PROVIDER_MOCK = "mock"
PROVIDER_OPENAI = "openai"
PROVIDER_GEMINI = "gemini"

_ALLOWED_PRIORITIES = {"low", "medium", "high", "critical"}


CLASSIFICATION_SYSTEM_PROMPT = (
    "You are an IT service desk triage assistant for the SBS AI ITSM platform. "
    "Given a user ticket description, return a strictly valid JSON object with "
    "the following keys: category (short label in Russian), priority (one of "
    "low|medium|high|critical), summary (one sentence in Russian), possible_cause "
    "(short text in Russian), suggested_solution (short text in Russian), "
    "confidence (float between 0 and 1). Do not include any additional keys, "
    "commentary or markdown. Prefer conservative priorities."
)


@dataclass(slots=True)
class ClassificationResult:
    category: str
    priority: str
    summary: str
    possible_cause: str
    suggested_solution: str
    confidence: float
    provider: str
    model: str
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProviderStatus:
    active_provider: str
    model: str
    ready: bool
    api_key_configured: bool
    pii_redaction_enabled: bool
    request_timeout_seconds: float
    reason: str | None = None
    fallback_provider: str | None = None
    supported_providers: list[str] = field(default_factory=list)


def _clamp_priority(value: str | None, fallback: str = "medium") -> str:
    if not value:
        return fallback
    normalized = value.strip().lower()
    if normalized in _ALLOWED_PRIORITIES:
        return normalized
    aliases = {
        "urgent": "critical",
        "p1": "critical",
        "p2": "high",
        "p3": "medium",
        "p4": "low",
        "normal": "medium",
    }
    return aliases.get(normalized, fallback)


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, number))


class BaseLLMProvider(ABC):
    """Abstract classifier interface."""

    name: str = "base"
    model: str = "n/a"
    is_mock: bool = False

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = float(timeout)

    @abstractmethod
    async def classify_ticket(self, text: str) -> ClassificationResult:
        raise NotImplementedError

    @property
    def is_ready(self) -> bool:
        return True

    @property
    def has_api_key(self) -> bool:
        return False


_MOCK_RULES: list[tuple[list[str], dict[str, Any]]] = [
    (
        ["не работает", "пропал", "отключ", "нет интернета", "vpn", "wifi", "wi-fi", "сеть"],
        {
            "category": "Сеть и интернет",
            "priority": "high",
            "summary": "Пользователь сообщает о проблеме с сетью или подключением.",
            "possible_cause": "Возможное отключение или сбой сетевого оборудования, VPN или DNS.",
            "suggested_solution": "Проверьте статус сетевого сегмента, VPN-туннели и локальный DNS.",
            "confidence": 0.72,
        },
    ),
    (
        ["принтер", "не печатает", "печать", "картридж", "мфу"],
        {
            "category": "Принтеры",
            "priority": "medium",
            "summary": "Проблема с печатью или устройством печати.",
            "possible_cause": "Замятие бумаги, отсутствие картриджа или ошибка драйвера принтера.",
            "suggested_solution": "Проверьте очередь печати, состояние картриджа и статус драйвера.",
            "confidence": 0.65,
        },
    ),
    (
        ["пароль", "доступ", "не могу войти", "заблокирован", "учетн", "учётн"],
        {
            "category": "Доступы и учётные записи",
            "priority": "high",
            "summary": "Проблема с доступом или учётной записью.",
            "possible_cause": "Истёк или заблокирован пароль, либо снят доступ к системе.",
            "suggested_solution": "Проверьте статус учётной записи в AD/IdP и при необходимости выполните сброс пароля.",
            "confidence": 0.7,
        },
    ),
    (
        ["почта", "email", "outlook", "не приходит", "писем"],
        {
            "category": "Корпоративная почта",
            "priority": "medium",
            "summary": "Проблема с корпоративной почтой.",
            "possible_cause": "Сбой почтового клиента, квота или блокировка ящика.",
            "suggested_solution": "Проверьте настройки клиента и статус ящика на почтовом сервере.",
            "confidence": 0.66,
        },
    ),
    (
        ["фишинг", "подозрительн", "вирус", "malware", "атака"],
        {
            "category": "Информационная безопасность",
            "priority": "critical",
            "summary": "Подозрение на инцидент информационной безопасности.",
            "possible_cause": "Возможная фишинговая рассылка или заражение устройства.",
            "suggested_solution": "Изолируйте устройство, зафиксируйте индикаторы и уведомите security officer.",
            "confidence": 0.82,
        },
    ),
]

_DEFAULT_MOCK = {
    "category": "Общие вопросы IT",
    "priority": "medium",
    "summary": "Требуется классификация специалистом первой линии.",
    "possible_cause": "Недостаточно данных в описании тикета.",
    "suggested_solution": "Запросите дополнительные детали у пользователя и продолжите триаж.",
    "confidence": 0.5,
}


class MockLLMProvider(BaseLLMProvider):
    """Deterministic keyword-based classifier used when no API key is configured."""

    name = PROVIDER_MOCK
    model = "keyword-rules-v1"
    is_mock = True

    async def classify_ticket(self, text: str) -> ClassificationResult:
        haystack = text.lower()
        for keywords, payload in _MOCK_RULES:
            if any(keyword in haystack for keyword in keywords):
                return ClassificationResult(
                    provider=self.name,
                    model=self.model,
                    rationale="mock:keyword_match",
                    category=str(payload["category"]),
                    priority=_clamp_priority(str(payload["priority"])),
                    summary=str(payload["summary"]),
                    possible_cause=str(payload["possible_cause"]),
                    suggested_solution=str(payload["suggested_solution"]),
                    confidence=_clamp_confidence(payload["confidence"]),
                )
        return ClassificationResult(
            provider=self.name,
            model=self.model,
            rationale="mock:default",
            category=str(_DEFAULT_MOCK["category"]),
            priority=_clamp_priority(str(_DEFAULT_MOCK["priority"])),
            summary=str(_DEFAULT_MOCK["summary"]),
            possible_cause=str(_DEFAULT_MOCK["possible_cause"]),
            suggested_solution=str(_DEFAULT_MOCK["suggested_solution"]),
            confidence=_clamp_confidence(_DEFAULT_MOCK["confidence"]),
        )


class _HTTPProviderMixin:
    """Shared HTTP helper — uses stdlib urllib inside asyncio.to_thread."""

    timeout: float

    async def _http_post_json(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[int, dict[str, Any]]:
        data = json.dumps(body).encode("utf-8")

        def _do_request() -> tuple[int, dict[str, Any]]:
            request = urllib.request.Request(url, method="POST", data=data)
            for key, value in headers.items():
                request.add_header(key, value)
            request.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    return response.getcode(), payload
            except urllib.error.HTTPError as exc:
                try:
                    payload = json.loads(exc.read().decode("utf-8"))
                except Exception:  # pragma: no cover - defensive
                    payload = {"error": {"message": exc.reason}}
                return exc.code, payload

        return await asyncio.to_thread(_do_request)


def _safe_parse_json_object(raw: str) -> dict[str, Any] | None:
    """Extract JSON object from possibly-noisy model output."""

    if not raw:
        return None
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json\n"):
            stripped = stripped[5:]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _finalize_from_json(
    provider: str,
    model: str,
    parsed: dict[str, Any] | None,
) -> ClassificationResult:
    if not parsed:
        return ClassificationResult(
            provider=provider,
            model=model,
            rationale=f"{provider}:invalid_response_fallback",
            category=str(_DEFAULT_MOCK["category"]),
            priority=_clamp_priority(str(_DEFAULT_MOCK["priority"])),
            summary=str(_DEFAULT_MOCK["summary"]),
            possible_cause=str(_DEFAULT_MOCK["possible_cause"]),
            suggested_solution=str(_DEFAULT_MOCK["suggested_solution"]),
            confidence=_clamp_confidence(_DEFAULT_MOCK["confidence"]),
        )
    return ClassificationResult(
        provider=provider,
        model=model,
        rationale=f"{provider}:classified",
        category=str(parsed.get("category") or _DEFAULT_MOCK["category"])[:200],
        priority=_clamp_priority(str(parsed.get("priority") or "medium")),
        summary=str(parsed.get("summary") or _DEFAULT_MOCK["summary"])[:800],
        possible_cause=str(parsed.get("possible_cause") or _DEFAULT_MOCK["possible_cause"])[:800],
        suggested_solution=str(parsed.get("suggested_solution") or _DEFAULT_MOCK["suggested_solution"])[:1200],
        confidence=_clamp_confidence(parsed.get("confidence")),
    )


class OpenAILLMProvider(_HTTPProviderMixin, BaseLLMProvider):
    """OpenAI-compatible chat completions provider (also works with OpenAI-compatible gateways)."""

    name = PROVIDER_OPENAI
    is_mock = False

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 15.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._api_key = api_key
        self.model = model
        self._base_url = base_url.rstrip("/")

    @property
    def has_api_key(self) -> bool:
        return bool(self._api_key)

    async def classify_ticket(self, text: str) -> ClassificationResult:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 500,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            status, payload = await self._http_post_json(
                f"{self._base_url}/chat/completions", body, headers
            )
        except Exception as exc:  # pragma: no cover - depends on network
            logger.warning("openai_provider_transport_error", extra={"error": exc.__class__.__name__})
            return await MockLLMProvider(self.timeout).classify_ticket(text)

        if status >= 400:
            logger.warning("openai_provider_http_error", extra={"status": status})
            return await MockLLMProvider(self.timeout).classify_ticket(text)

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.warning("openai_provider_shape_error")
            return await MockLLMProvider(self.timeout).classify_ticket(text)
        parsed = _safe_parse_json_object(str(content))
        return _finalize_from_json(self.name, self.model, parsed)


class GeminiLLMProvider(_HTTPProviderMixin, BaseLLMProvider):
    """Google Generative Language API provider (Gemini)."""

    name = PROVIDER_GEMINI
    is_mock = False
    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str, model: str, timeout: float = 15.0) -> None:
        super().__init__(timeout=timeout)
        self._api_key = api_key
        self.model = model

    @property
    def has_api_key(self) -> bool:
        return bool(self._api_key)

    async def classify_ticket(self, text: str) -> ClassificationResult:
        body = {
            "systemInstruction": {"role": "user", "parts": [{"text": CLASSIFICATION_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 500,
                "responseMimeType": "application/json",
            },
        }
        url = f"{self._BASE_URL}/models/{self.model}:generateContent?key={self._api_key}"
        try:
            status, payload = await self._http_post_json(url, body, {})
        except Exception as exc:  # pragma: no cover - depends on network
            logger.warning("gemini_provider_transport_error", extra={"error": exc.__class__.__name__})
            return await MockLLMProvider(self.timeout).classify_ticket(text)

        if status >= 400:
            logger.warning("gemini_provider_http_error", extra={"status": status})
            return await MockLLMProvider(self.timeout).classify_ticket(text)

        try:
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            logger.warning("gemini_provider_shape_error")
            return await MockLLMProvider(self.timeout).classify_ticket(text)
        parsed = _safe_parse_json_object(str(content))
        return _finalize_from_json(self.name, self.model, parsed)


def get_provider() -> BaseLLMProvider:
    """Resolve the configured provider or fall back to mock."""

    settings = get_settings()
    timeout = max(1.0, float(settings.ai_request_timeout_seconds))
    provider = (settings.ai_provider or PROVIDER_MOCK).strip().lower()

    if provider == PROVIDER_OPENAI and settings.openai_api_key:
        return OpenAILLMProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            timeout=timeout,
        )
    if provider == PROVIDER_GEMINI and settings.gemini_api_key:
        return GeminiLLMProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout=timeout,
        )
    return MockLLMProvider(timeout=timeout)


def describe_provider_status() -> ProviderStatus:
    """Return a secrets-safe description of the active AI provider."""

    settings = get_settings()
    timeout = max(1.0, float(settings.ai_request_timeout_seconds))
    provider = (settings.ai_provider or PROVIDER_MOCK).strip().lower()

    reason: str | None = None
    fallback: str | None = None
    active = provider
    api_key_configured = False
    model = "n/a"
    ready = False

    if provider == PROVIDER_OPENAI:
        api_key_configured = bool(settings.openai_api_key)
        model = settings.openai_model
        if api_key_configured:
            ready = True
        else:
            reason = "openai_api_key_missing"
            fallback = PROVIDER_MOCK
            active = PROVIDER_MOCK
            # Mock provider is always operational, so effective readiness is True.
            ready = True
    elif provider == PROVIDER_GEMINI:
        api_key_configured = bool(settings.gemini_api_key)
        model = settings.gemini_model
        if api_key_configured:
            ready = True
        else:
            reason = "gemini_api_key_missing"
            fallback = PROVIDER_MOCK
            active = PROVIDER_MOCK
            ready = True
    elif provider == PROVIDER_MOCK:
        model = "keyword-rules-v1"
        ready = True
    else:
        reason = "unknown_provider"
        fallback = PROVIDER_MOCK
        active = PROVIDER_MOCK
        model = "keyword-rules-v1"
        ready = True

    return ProviderStatus(
        active_provider=active,
        model=model,
        ready=ready,
        api_key_configured=api_key_configured,
        pii_redaction_enabled=bool(settings.ai_pii_redaction),
        request_timeout_seconds=timeout,
        reason=reason,
        fallback_provider=fallback,
        supported_providers=[PROVIDER_MOCK, PROVIDER_OPENAI, PROVIDER_GEMINI],
    )


__all__ = [
    "BaseLLMProvider",
    "ClassificationResult",
    "GeminiLLMProvider",
    "MockLLMProvider",
    "OpenAILLMProvider",
    "PROVIDER_GEMINI",
    "PROVIDER_MOCK",
    "PROVIDER_OPENAI",
    "ProviderStatus",
    "describe_provider_status",
    "get_provider",
]
