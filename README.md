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
