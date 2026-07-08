.PHONY: dev up down logs test build clean prod-up prod-down prod-logs migrate backup restore

dev:
	docker compose up --build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

test:
	cd backend && pytest
	cd frontend && npm run build

build:
	docker compose build

clean:
	docker compose down -v --remove-orphans

prod-up:
	docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

prod-down:
	docker compose -f docker-compose.prod.yml --env-file .env.production down

prod-logs:
	docker compose -f docker-compose.prod.yml --env-file .env.production logs -f

migrate:
	cd backend && alembic upgrade head

backup:
	docker compose exec -T postgres pg_dump -U $$POSTGRES_USER $$POSTGRES_DB > backup.sql

restore:
	docker compose exec -T postgres psql -U $$POSTGRES_USER $$POSTGRES_DB < backup.sql
