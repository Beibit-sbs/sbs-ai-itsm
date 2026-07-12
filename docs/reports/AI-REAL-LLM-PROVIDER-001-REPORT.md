# AI-REAL-LLM-PROVIDER-001 REPORT

## Scope
Первый настоящий LLM-слой поверх мок-классификатора. Абстракция «провайдер» с тремя реализациями (Mock / OpenAI / Gemini), PII-редактирование, безопасный fallback, admin-панель. Backward compatible: `/ai/analyze-ticket` работает как раньше; новый `/ai/classify` использует конфигурируемый провайдер и падает на mock, если ключ не задан.

## What Was Added

### Backend
- Провайдер-слой `app/services/ai/provider.py`:
  - `BaseLLMProvider` — абстрактный интерфейс `classify_ticket(text) -> ClassificationResult`.
  - `MockLLMProvider` — детерминированные keyword-rules RU-домен (сеть, принтер, доступы, почта, ИБ). Всегда готов, не требует ключа.
  - `OpenAILLMProvider` — вызов `POST {base_url}/chat/completions` с `response_format=json_object`. `Authorization: Bearer`.
  - `GeminiLLMProvider` — `POST /v1beta/models/{model}:generateContent?key=` с `responseMimeType=application/json` и `systemInstruction`.
  - Оба HTTP-провайдера используют `urllib.request` через `asyncio.to_thread` — **новых внешних зависимостей нет**.
  - `get_provider()` — фабрика; при отсутствии ключа или ошибке транспорта деградирует на `MockLLMProvider`.
  - `describe_provider_status()` — secrets-safe снапшот: active provider, model, api_key_configured (bool), pii_redaction_enabled, timeout, reason/fallback, supported providers. **Никаких значений ключей**.
- PII-редактирование `app/services/ai/pii.py`:
  - `redact_pii(text)` детектит email, phone (+7/интернационал), IIN Kazakhstan (12 цифр), IP, банковские карты (13–19 цифр).
  - Возвращает redacted text + token map.
  - `restore_pii(text, tokens)` — обратимо для восстановления оригиналов в текстовых полях ответа модели.
- Интеграционный оркестратор `app/services/ai/__init__.py`:
  - `classify_ticket_text(...)` — вызов провайдера с автоматическим PII-редактированием для non-mock провайдеров.
  - `analyze_text_with_provider(db, text, ticket_id=None)` — полный pipeline: провайдер → AiSuggestion в БД → обогащение related knowledge articles + similar tickets → same response shape что и `analyze_text_with_mock_ai`.
- Config-расширения `app/core/config.py`:
  - `ai_provider: str = "mock"`, `openai_api_key: str | None`, `openai_model: str = "gpt-4o-mini"`, `openai_base_url: str = "https://api.openai.com/v1"`.
  - `gemini_api_key: str | None`, `gemini_model: str = "gemini-2.0-flash-exp"`.
  - `ai_pii_redaction: bool = True`, `ai_request_timeout_seconds: float = 15.0`.
  - Все env-переменные читаются штатно pydantic-settings (UPPER_CASE имена).
- REST-endpoints в `app/api/v1/routes/ai.py`:
  - `POST /api/v1/ai/classify` — использует настроенного провайдера; требует `ai.use`.
  - `GET /api/v1/ai/provider-status` — только admin/security/root; никогда не возвращает значения ключей.
- Legacy `/api/v1/ai/analyze-ticket` оставлен без изменений (backward compat).

### Frontend
- Тип `AiProviderStatus` + функция `fetchAiProviderStatus` в `frontend/src/api/client.ts`.
- Карточка **AI Provider** на `/admin/system` показывает: активный провайдер, модель, ready-badge, api_key_configured (bool), pii redaction, timeout, supported providers, reason/fallback если fallback активен.

### Tests
- `backend/tests/test_ai_provider.py` — 15 тестов:
  - PII redact/restore для email/phone/IIN/IP/карт
  - `_clamp_priority` нормализует `HIGH → high`, `urgent → critical`, `p2 → high` и т.д.
  - `_safe_parse_json_object` — обработка fenced markdown и мусора
  - `MockLLMProvider` — правильная категория для «интернет и wifi», дефолт для нейтрального текста
  - Прямые инстанциации `OpenAILLMProvider` и `GeminiLLMProvider` (без сетевых вызовов)
  - `get_provider()` возвращает mock по умолчанию
  - `describe_provider_status()` возвращает mock defaults, без утечки полей
  - `GET /ai/provider-status` требует admin/security-роль (requester → 403)
  - Endpoint не содержит `sk-`, `openai_api_key` в ответе
  - `POST /ai/classify` создаёт AiSuggestion с `rationale=mock:*`, priority upper-case (LOW|MEDIUM|HIGH|CRITICAL), confidence 0–1

## Validation Summary
| Проверка | Результат |
|---|---|
| Backend pytest (полный) | **177 passed, 4 warnings** (162 baseline + 15 новых) |
| Backend pytest `tests/test_ai_provider.py` | 15 passed |
| Frontend `npx tsc -b --pretty false` | PASS |
| Frontend `npm run build` | PASS (~556 kB gzip 133 kB — только vite chunk-size warning) |
| `docker compose config` | PASS |
| `docker compose -f docker-compose.prod.yml config` | PASS |
| Runtime `GET /ai/provider-status` | 200, `active=mock`, `ready=true`, `api_key_configured=false`, `supported=[mock, openai, gemini]`, `reason=null` |
| Runtime `POST /ai/classify` (text «Не работает интернет и wifi ... email test@example.com») | 200, `category="Сеть и интернет"`, `priority=HIGH`, `confidence=72%`, `rationale=mock:keyword-rules-v1` |
| Runtime `/ai/provider-status` под requester | 403 |
| Runtime `/ai/classify` без токена | 401 |
| Browser smoke `/admin/system` | Карточка «AI Provider» рендерится: Active `mock`, Model `keyword-rules-v1`, Ready `true`, API key configured `false`, PII redaction `true`, Timeout `15 s`, Supported `mock, openai, gemini` |
| Secret-leak check | Регекс `/sk-|jwt_secret|"database_url"|change_me_before_production|password_hash/` не срабатывает в DOM |

## How to Enable Real Provider

Без изменения кода — только env-переменные в `.env.production` (или Docker Compose environment):

```
AI_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
AI_PII_REDACTION=true
```

или

```
AI_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash-exp
```

После рестарта backend `GET /ai/provider-status` вернёт `active_provider=openai|gemini`, `ready=true`, `api_key_configured=true`. `POST /ai/classify` начнёт делать реальные HTTP-вызовы. Ошибки транспорта/HTTP авто-падают на mock — endpoint никогда не 500-ит по вине провайдера.

## Security Notes
- Значения API-ключей никогда не сериализуются в ответ (`describe_provider_status` возвращает только `api_key_configured: bool`).
- Дефолт `AI_PII_REDACTION=true`: для non-mock провайдера входной текст маскируется (email → `<EMAIL_1>`, IIN → `<IIN_1>` и т.д.) до отправки в LLM. Токены восстанавливаются только в текстовых полях ответа модели.
- Никаких новых внешних зависимостей — контейнер образ не растёт, cost-of-supply-chain не увеличивается.
- Timeout по умолчанию 15 сек, любой HTTP-error переводит в mock fallback с логом `logger.warning`.

## Backward Compatibility
- Ни один существующий endpoint не сломан; `/ai/analyze-ticket` работает как раньше.
- Ни один существующий тест не сломан (162/162 baseline остались зелёными).
- Мок-логика сохранена: тесты `test_knowledge_ai.py::*` не тронуты.
- Если нет env-переменных провайдера — поведение системы идентично тому, что было до этого stage.

## Known Limitations
- LLM-запрос выполняется в handler-е (не через background job). При латентности 5-30 сек это блокирует HTTP-запрос. Следующий stage `PLATFORM-CORE-ASYNC-WORKER-002` переносит LLM в фоновую очередь через arq.
- RAG над Knowledge Base пока не реализован (только keyword-based related-articles). Следующий stage `AI-REAL-RAG-KNOWLEDGE-002` добавит pgvector и семантический поиск.
- Нет rate-limiting per tenant (по объёму LLM-запросов и токенов). Следующий stage `AI-REAL-GUARDRAILS-003`.
- Auto-classification при создании тикета не подключена (сохраняется как ручной вызов `/ai/classify`). Следующий stage `AI-REAL-AUTOCLASSIFY-004`.

## Next Stage
`PLATFORM-CORE-ASYNC-WORKER-002` — arq worker + переезд AI-классификации + отправки email + integration retries в фон. Даст видимый speed-up UI под нагрузкой + retry policy + dead-letter.
