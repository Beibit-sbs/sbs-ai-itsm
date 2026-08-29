.PHONY: dev up down logs logs-backend logs-frontend logs-worker ps health smoke prod-smoke compose-check secrets-init prod-bootstrap test build clean prod-up prod-down prod-logs monitoring-logs migrate backup restore env-check data-backup db-head db-upgrade db-current db-history

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

logs-worker:
	docker compose logs -f worker

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

prod-smoke:
	python3 scripts/smoke-production.py --env-file .env.production

compose-check:
	docker compose -f docker-compose.prod.yml --env-file .env.production config --quiet

secrets-init:
	python3 scripts/init-production-secrets.py --directory secrets --with-bootstrap-password

prod-bootstrap:
	docker compose -f docker-compose.prod.yml -f docker-compose.bootstrap.yml --env-file .env.production up -d --build

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

monitoring-logs:
	docker compose -f docker-compose.prod.yml --env-file .env.production logs -f prometheus alertmanager grafana

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
