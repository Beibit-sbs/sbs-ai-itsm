# PLATFORM-CORE-ASYNC-FOUNDATION-001 REPORT

## Scope
Инфраструктурная основа для перевода тяжёлых операций (AI, email, интеграции, импорты) с request-path на фоновое исполнение. Additive-only, backward compatible, без внешних зависимостей.

## What Was Added

### Backend
- Модель `JobRun` (`backend/app/models/job_run.py`) с полями: `id`, `task_name`, `status`, `tenant_id`, `actor_user_id`, `correlation_id`, `payload_json`, `result_json`, `error_message`, `attempts`, `max_attempts`, `queued_at`, `started_at`, `finished_at`, `duration_ms`, `created_at`, `updated_at`.
- Alembic revision `20261115_0009_job_runs` (guarded additive create).
- Service layer `app/services/jobs/`:
  - Task registry: `register_task`, `registered_task_names`, `registered_task`.
  - Execution: `create_job_run`, `execute_job`, `run_task` (inline execution в этом stage, worker в следующем).
  - Query: `list_jobs`, `get_job`, `job_summary`.
- Built-in tasks (`backend/app/services/jobs/tasks.py`): `system.echo`, `system.sleep`, `system.fail` — используются для тестов и smoke.
- REST-роут `app/api/v1/routes/jobs.py`:
  - `GET /jobs`
  - `GET /jobs/summary`
  - `GET /jobs/tasks`
  - `GET /jobs/{id}`
  - `POST /jobs/enqueue`
- Correlation ID middleware (`app/core/middleware.py`) + contextvar (`app/core/context.py`) — читает `X-Request-ID` или генерирует UUID; echo в response header.
- Регистрация модели, роутера, middleware, task registry в `models/__init__.py`, `api/v1/router.py`, `main.py`.

### Frontend
- Типы + API-клиент: `JobRun`, `JobRunSummary`, `fetchJobRuns`, `fetchJobSummary` в `frontend/src/api/client.ts`.
- Панели «Background Jobs» + «Recent Job Runs» на `/admin/system` с summary counters и таблицей последних 15 задач (task, status, attempts, duration, timestamp, correlation).

### RBAC
- Read (`GET /jobs*`): доступ через `admin.settings.read | admin.users.read | security.audit.read` (root — bypass).
- Enqueue (`POST /jobs/enqueue`): только `saas_root`.
- Tenant scoping для read: root видит все; остальные — только свои (`tenant_id == current_user.tenant_id`).

## Validation
| Проверка | Результат |
|---|---|
| Backend pytest (полный) | **162 passed, 4 warnings** (149 baseline + 13 новых `test_jobs.py`) |
| Backend pytest `tests/test_jobs.py` | 13 passed |
| Frontend `npx tsc -b --pretty false` | PASS |
| Frontend `npm run build` | PASS |
| `docker compose config` | PASS |
| `docker compose -f docker-compose.prod.yml config` | PASS |
| Alembic head | `20261115_0009` |
| Alembic applied to running DB | `20261115_0009` |
| Runtime API smoke | `system.echo` → success, `system.sleep` → success, `system.fail` → failed |
| Runtime summary | total=3, success=2, failed=1 (root); tenant-scoped 0 для admin@sbs.local (правильная изоляция) |
| Runtime RBAC | requester → 403 на GET и POST |
| Runtime correlation | Incoming header `live-corr-42` echoed back |
| Browser smoke `/admin/system` | Панель «Background Jobs» показывает Total 3 / Success 2 / Failed 1; таблица «Recent Job Runs» показывает 3 записи с correlation IDs |

## Security Notes
- Никаких секретов в payload/result хранения (клиент отвечает за то, что кладёт в payload).
- Correlation ID — public identifier, безопасен для логов.
- Tenant scoping не даёт leak jobs между тенантами.
- No new external dependency.

## Backward Compatibility
- Ни один существующий endpoint не изменён.
- Ни один существующий тест не сломан (149/149 pre-fix зелёные).
- Async worker не добавлен — только framework для будущего перевода. Все текущие sync-пути работают как раньше.

## Known Limitations
- В этом stage jobs выполняются inline (в request-процессе). Реальный async worker (arq/celery/nats) — следующий stage.
- Retry policy рудиментарная (`attempts`/`max_attempts` в схеме, но exponential backoff отсутствует).
- Нет dead-letter queue.
- Нет cancel-endpoint.
- Alembic status в `/health/deep` по-прежнему `unknown` в container runtime (документированный safe fallback).

## Next Stage
`PLATFORM-CORE-ASYNC-WORKER-002` (после следующего track): реальный worker service (arq или aiokafka), exponential backoff retry, dead-letter, cancel endpoint. Одновременно откроет `AI-REAL` для тяжёлых LLM-задач в фоне.
