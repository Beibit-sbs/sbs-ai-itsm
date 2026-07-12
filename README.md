# SBS AI ITSM

Интеллектуальная multi-tenant SaaS-платформа для управления ИТ-службой.

## FOUNDATION-001

Текущий репозиторий содержит запускаемую основу проекта:

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

## Быстрый запуск

```bash
cp .env.example .env
docker compose up --build
```

По умолчанию в `.env.example` включены режимы для локальной demo-разработки:

- `DEMO_MODE=true`
- `RUN_STARTUP_DDL=true`

После запуска:

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- OpenAPI: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health

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
- Бизнес-модули будут multi-tenant с обязательной backend-проверкой `tenant_id`.
- AI-функции позже подключаются через отдельный provider layer и не блокируют базовую работу ITSM.
- SaaS Root и администратор организации будут разделены permissions, а не только названиями ролей.

## Следующий этап

`FOUNDATION-002 — Tenant, User, Role and Permission Foundation`.

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
```

Operational runbooks:

- `docs/operations/DEPLOYMENT-RUNBOOK.md`
- `docs/operations/BACKUP-RESTORE-RUNBOOK.md`
- `docs/operations/INCIDENT-DIAGNOSTICS-RUNBOOK.md`
- `docs/operations/SECURITY-OPERATIONS-CHECKLIST.md`
