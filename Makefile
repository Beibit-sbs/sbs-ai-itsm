.PHONY: dev up down logs test build clean

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
