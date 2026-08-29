# Полный аудит готовности SBS AI ITSM

Дата аудита: 13 августа 2026 года  
Контур: локальная Windows-среда, frontend `127.0.0.1:5173`, backend `127.0.0.1:8000`  
Версия приложения: `0.1.0`

## Решение

- **Локальная демонстрация и UAT: GO.** Основные пользовательские, операторские, административные и root-сценарии работают; сервисы запущены и отвечают.
- **Публичный production на сервере: NO-GO до выполнения внешнего cutover-чеклиста.** Код и конфигурационные шаблоны проходят gate, но текущий локальный `.env.production` не является безопасной серверной конфигурацией и реальные провайдеры пока не настроены.
- Термин «готово» в этом отчёте не означает, что mock AI, mock email или mock Teams выполняют внешнюю доставку. Интерфейс и evidence-модель явно обозначают симуляцию и не выдают её за production-успех.

## Что проверено

Проверены все основные продуктовые области:

- аутентификация, сессии, MFA, OIDC, multi-role RBAC, tenant isolation и аудит;
- инциденты, массовые действия, комментарии, назначения и пользовательские области видимости;
- сервисный каталог, динамические формы, заявки, согласование, выполнение и timeline;
- изменения, календарь, CAB/governance, проблемы, KEDB, major incidents и релизы;
- активы, CMDB-классы и связи, импорт, discovery, reconciliation, impact и quality;
- SLA/OLA, уведомления, email operations, Teams collaboration и monitoring/event operations;
- база знаний, permission-aware RAG, AI governance, runtime controls и guarded actions;
- автоматизация, runbooks, workflow engine, approvals, scheduler, worker и WebSocket;
- аналитика, отчёты, глобальный поиск, custom fields, configuration packages;
- администрирование организаций, пользователей, ролей, прав, security и configuration center;
- русский, казахский и английский языки на входе и в общем интерфейсном слое.

## Live-проверка ролей и процессов

Через реальный браузер и локальный API выполнены следующие сценарии:

- вход requester, manager, admin и SaaS root;
- обход доступных маршрутов requester и всех 25 пунктов меню manager без необработанных route errors;
- создание инцидента `SD-1013`, самостоятельное назначение менеджером;
- создание сервисной заявки `REQ-20260813-ED578E1A` и задачи `RITM-20260813-2327CC3A`;
- назначение, запуск и завершение задачи; заявка перешла в `Completed`, timeline завершён;
- создание организации и пользователя, назначение нескольких ролей, проверка административных вкладок;
- проверка root-интерфейса настройки OpenAI/Gemini: provider, API key, model, base URL, test и save доступны; реальные ключи намеренно не вводились;
- публикация и отображение четырёх demo-услуг каталога;
- проверка каталога и заявок на русском, английском и казахском;
- после чистого перезапуска: backend health `200`, frontend `200`, HTTP 5xx `0`, traceback `0`, frontend console errors `0`, proxy errors `0`.

Временный пользователь, созданный при проверке администрирования, деактивирован.

## Исправленные дефекты высокой важности

- настроен стабильный Vite proxy и постоянная локальная SQLite-база;
- исправлена выдача административных прав и управление пользователями/ролями;
- добавлено идемпотентное заполнение демонстрационного каталога;
- менеджеру разрешено безопасное self-assignment по отдельному permission;
- ошибки API и JSON-поля с `datetime` переведены на безопасную сериализацию;
- исправлены миграции SQLite/Alembic и подтверждена единая голова `20260729_0072`;
- устранены сбои CMDB import/discovery/reconciliation и обязательных CI-атрибутов;
- исправлены Windows MAX_PATH для email attachments и видимость транзакционных email jobs;
- нормализованы timezone-сравнения SLA и change governance;
- исправлены SCIM event persistence, enterprise namespace parsing и пересчёт group-role mapping;
- исправлена агрегация MFA в Configuration Center;
- исправлено сохранение readiness snapshot в Go/No-Go решении релиза;
- улучшена диагностика циклов и secret-like полей workflow engine;
- статус AI provider открыт всем действительно entitled AI/RAG-операторам без раскрытия секретов;
- динамические поля заявок показывают понятные пользовательские подписи;
- добавлена рекурсивная локализация общего UI и устранены React key warnings;
- исключены ложные статусы доставки для mock email/Teams/AI;
- добавлен статический аудит всех интерактивных элементов интерфейса.

## Автоматические доказательства

- Backend: **83 тестовых модуля, 729 собранных сценариев**. Модули выполнены изолированными пакетами; найденные ошибки исправлялись и соответствующие полные модули запускались повторно до PASS.
- Release gate: **27/27 PASS**.
- Route authentication: **709 endpoint**, из них **702 protected** и **7 governed public**.
- OpenAPI: **591 path**.
- Alembic: одна голова `20260729_0072`.
- Frontend: TypeScript PASS; Vite 8.1.3 production build PASS; **140 modules transformed**.
- Accessibility baseline: **75 source files**, **16 dialogs**, 0 unnamed dialogs, 0 dialogs without focus management.
- Interactive controls: **651 buttons + 39 links**, inert controls не обнаружены.
- Observability: **7 SLO, 17 alerts, 17 panels**.
- `git diff --check`, Ruff и Python compileall: PASS.
- Docker Compose production и bootstrap configuration validation: PASS.

Машиночитаемое evidence: `docs/reports/PRODUCTION-READINESS-AUDIT-2026-08-13.json`  
Evidence SHA-256: `17a683fba3138f7f6083183f97fe6f76d49aa6a2739b109be823bbefa49d2107`

Поле `runtime_acceptance: NOT_EXECUTED` внутри JSON относится только к статическому M1-скрипту. Отдельная локальная browser/API acceptance выполнена вручную и описана выше; серверная acceptance ещё не выполнялась, потому что серверный контур и реальные credentials не предоставлены.

## Что обязательно сделать при переносе на сервер

1. Назначить реальный домен, TLS-сертификат, trusted hosts, CORS и frontend origin.
2. Сгенерировать новые production secrets; отключить demo mode, startup DDL и известные demo-пароли.
3. Поднять PostgreSQL, Redis, API, worker и scheduler через production Compose; применить миграции и проверить persistent volumes.
4. Настроить обязательный MFA для привилегированных ролей и, при необходимости, корпоративный OIDC/Entra ID.
5. Ввести реальные OpenAI или Gemini credentials через root-конфигурацию и выполнить connection test.
6. Настроить Microsoft Graph email, Teams webhooks, monitoring connectors и остальные требуемые внешние интеграции.
7. Выполнить server smoke, tenant-isolation acceptance, нагрузочный профиль, TLS/security scan и подтверждение backup/restore.
8. Деактивировать или сменить пароли всех демонстрационных учётных записей до допуска реальных пользователей.

До закрытия этих пунктов платформу можно использовать локально для демонстрации, настройки процессов, обучения и UAT, но нельзя публиковать в Интернет как production-систему с реальными пользовательскими данными.

## Известные не-блокирующие замечания

- Тестовый стек сообщает о будущей замене интеграции Starlette TestClient с `httpx` на `httpx2`; текущие тесты проходят.
- Git на Windows предупреждает о будущей нормализации LF/CRLF; `git diff --check` проходит, дефектов whitespace нет.
- Полная трёхъязычность реализована для входа, навигации и проверенных основных пользовательских потоков. Перед серверным запуском нужен финальный лингвистический просмотр всех редких административных экранов носителями русского и казахского языков.
