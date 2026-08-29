# SBS AI ITSM

Интеллектуальная multi-tenant SaaS-платформа для управления ИТ-службой.

## Платформа

Текущий репозиторий содержит полнофункциональную локальную ITSM-платформу:

- FastAPI backend;
- React + TypeScript frontend;
- PostgreSQL;
- Redis;
- Docker Compose;
- endpoint `/api/v1/health`;
- единый формат API-ошибок;
- базовый интерфейс Login и Dashboard;
- проверку доступности backend;
- backend tests и frontend production build.

Production-модули платформы:

- Service Desk и SLA;
- Asset Inventory / CMDB foundation;
- Change Management с CAB/ECAB, risk scoring и контролем окон;
- Problem Management с RCA, recurring-incident analytics и Known Error Database;
- Knowledge + AI Copilot;
- Workflow Automation, Integrations и Notifications;
- Analytics, Monitoring и tamper-evident Security Audit.

## Быстрый запуск

```bash
cp .env.example .env
docker compose up --build
```

По умолчанию в `.env.example` включены режимы для локальной demo-разработки:

- `DEMO_MODE=true`
- `SEED_DEMO_CATALOG=true`
- `RUN_STARTUP_DDL=true`

После запуска:

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- OpenAPI: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health

### Быстрый локальный запуск в Windows

При уже установленных зависимостях достаточно запустить:

```powershell
wscript.exe scripts\start-local-demo.vbs
```

Локальный frontend откроется на http://localhost:5173. Backend использует
постоянную SQLite-базу в `%LOCALAPPDATA%\Temp\sbs-ai-itsm-visible.db`, поэтому
данные не пропадают между перезапусками.

Демонстрационные учётные записи (только при `DEMO_MODE=true`):

| Роль | Логин | Пароль |
|---|---|---|
| Пользователь | `requester@sbs.local` | `Sbs!2026` |
| ИТ-менеджер | `manager@sbs.local` | `Sbs!2026` |
| Администратор организации | `admin@sbs.local` | `Sbs!2026` |
| SaaS Root | `root@sbs.local` | `Root!2026` |

В production эти учётные записи и demo-каталог должны быть отключены:
`DEMO_MODE=false`, `SEED_DEMO_CATALOG=false`.

## Локальная разработка backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp ../.env.example ../.env
uvicorn app.main:app --reload
```

Миграции (Alembic):

```bash
cd backend
alembic upgrade head
```

Тесты:

```bash
cd backend
pytest
```

## Локальная разработка frontend

```bash
cd frontend
npm install
npm run dev
```

Production build:

```bash
cd frontend
npm run build
```

## Архитектурные принципы

- API версионируется через `/api/v1`.
- Все настройки поступают через environment variables.
- Бизнес-модули multi-tenant с обязательной backend-проверкой `tenant_id`.
- AI-функции подключены через отдельный provider layer и не блокируют базовую работу ITSM.
- SaaS Root и администратор организации разделены permissions, а не только названиями ролей.

## Готовность и дальнейшие этапы

Функциональная готовность, локальные проверки и внешние блокеры запуска
фиксируются в отчётах `docs/reports/` и в execution ledger. Перенос на внешний
сервер выполняется после production runtime gate с PostgreSQL, Redis, worker,
MFA, TLS и реальными интеграционными секретами.

Главный план развития:
`docs/roadmap/PRODUCTION-ITSM-MASTER-ROADMAP.md`.

Текущий статус выполнения:
`docs/operations/WORLD-CLASS-EXECUTION-LEDGER.md`.

## Production запуск

Для production используется отдельный compose и env-шаблон:

```bash
cp .env.production.example .env.production
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Критичные параметры production:

- `DEMO_MODE=false` отключает demo-данные.
- `RUN_STARTUP_DDL=false` отключает runtime DDL на старте приложения.
- `JWT_SECRET_KEY` должен быть заменен на стойкий секрет.

Рекомендуемая последовательность деплоя:

1. Поднять Postgres/Redis.
2. Выполнить `alembic upgrade head`.
3. Запустить backend/frontend через `docker-compose.prod.yml`.

## Operations (Production-Ready)

Проверка production env (без вывода секретов):

```bash
bash scripts/check-production-env.sh
```

Бэкапы:

```bash
bash scripts/backup-db.sh
bash scripts/backup-data.sh
```

Restore (только с явным подтверждением):

```bash
CONFIRM_RESTORE=yes bash scripts/restore-db.sh backups/db/<file>.sql.gz
```

Alembic команды:

```bash
make db-head
make db-current
make db-upgrade
make db-history
```

Health/diagnostics:

```bash
make health
make smoke
make logs-backend
make logs-frontend
make logs-worker
```

Background jobs execution mode:

- `JOBS_EXECUTOR_MODE=redis` uses Redis queue + separate `worker` service (default in compose files).
- `JOBS_EXECUTOR_MODE=inline` executes jobs in backend process (useful for local test runs without worker).
- Queue name is controlled by `JOBS_QUEUE_NAME` (default `jobs:queue`).
- Dead-letter queue is controlled by `JOBS_DEAD_LETTER_QUEUE_NAME` (default `jobs:dead-letter`).
- Retry backoff is configured by `JOBS_RETRY_BASE_SECONDS` and `JOBS_RETRY_MAX_SECONDS`.
- Retries are scheduled via Redis sorted-set (`<queue>:scheduled`) and do not block worker loop with `sleep`.
- Dead-letter jobs can be replayed by SaaS root via `POST /api/v1/jobs/{job_id}/replay`.
- Redis enqueue path is transactional: API writes to `job_queue_outbox` in the same DB transaction; worker publishes pending outbox entries to Redis.

Operational runbooks:

- `docs/operations/DEPLOYMENT-RUNBOOK.md`
- `docs/operations/BACKUP-RESTORE-RUNBOOK.md`
- `docs/operations/INCIDENT-DIAGNOSTICS-RUNBOOK.md`
- `docs/operations/SECURITY-OPERATIONS-CHECKLIST.md`
- `docs/operations/CHANGE-MANAGEMENT-RUNBOOK.md`
- `docs/operations/AI-PROVIDER-CONFIGURATION.md`
- `docs/operations/ENTERPRISE-IDENTITY-RUNBOOK.md`

Latest administration delivery report:

- `docs/reports/ADMIN-CONTROL-PLANE-002-REPORT.md`
- `docs/reports/ADMIN-IDENTITY-ORGANIZATION-003-REPORT.md`
