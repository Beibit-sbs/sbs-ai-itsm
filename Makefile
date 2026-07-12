.PHONY: dev up down logs logs-backend logs-frontend ps health smoke test build clean prod-up prod-down prod-logs migrate backup restore env-check data-backup db-head db-upgrade db-current db-history

dev:
	docker compose up --build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

logs-frontend:
	docker compose logs -f frontend

ps:
	docker compose ps

health:
	@curl -fsS http://localhost:8000/api/v1/health && echo
	@curl -fsS http://localhost:8000/api/v1/health/liveness && echo
	@curl -sS http://localhost:8000/api/v1/health/readiness && echo

smoke:
	@set -e; \
	curl -fsS http://localhost:8000/api/v1/health > /dev/null; \
	curl -fsS http://localhost:5173/ > /dev/null; \
	code=$$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' -d '{"email":"smoke@example.com","password":"invalid"}'); \
	if [ "$$code" -ne 401 ] && [ "$$code" -ne 422 ]; then \
		echo "Login endpoint check failed: $$code"; \
		exit 1; \
	fi; \
	for route in tickets assets knowledge analytics notifications automation integrations; do \
		curl -fsS "http://localhost:5173/$$route" > /dev/null || exit 1; \
	done; \
	echo "Smoke checks passed"

test:
	cd backend && pytest
	cd frontend && npm run build

build:
	docker compose build

clean:
	docker compose down --remove-orphans

prod-up:
	docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

prod-down:
	docker compose -f docker-compose.prod.yml --env-file .env.production down

prod-logs:
	docker compose -f docker-compose.prod.yml --env-file .env.production logs -f

migrate:
	cd backend && alembic upgrade head

db-head:
	@if [ -x .venv/bin/python ]; then \
		cd backend && ../.venv/bin/python -m alembic heads; \
	else \
		docker compose exec backend python -m alembic heads; \
	fi

db-upgrade:
	@if [ -x .venv/bin/python ]; then \
		cd backend && ../.venv/bin/python -m alembic upgrade head; \
	else \
		docker compose exec backend python -m alembic upgrade head; \
	fi

db-current:
	@if [ -x .venv/bin/python ]; then \
		cd backend && ../.venv/bin/python -m alembic current; \
	else \
		docker compose exec backend python -m alembic current; \
	fi

db-history:
	@if [ -x .venv/bin/python ]; then \
		cd backend && ../.venv/bin/python -m alembic history; \
	else \
		docker compose exec backend python -m alembic history; \
	fi

backup:
	bash scripts/backup-db.sh

data-backup:
	bash scripts/backup-data.sh

restore:
	bash scripts/restore-db.sh

env-check:
	bash scripts/check-production-env.sh
