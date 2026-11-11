.DEFAULT_GOAL := build
.PHONY: help build up setup db migrate seed dev down logs status

help:
	@echo 'make build  Build containers, migrate/seed, and start the full stack'
	@echo 'make up     Alias for build'
	@echo 'make dev    Start previously built app containers without migrations/seeds'
	@echo 'make down   Stop all containers; preserve database data'
	@echo 'make logs   Follow backend, frontend, and database logs (Ctrl+C exits logs)'
	@echo 'make status Show container health'

build:
	$(MAKE) setup
	docker compose build backend frontend
	docker compose stop backend frontend
	$(MAKE) db
	docker compose run --rm --no-deps init
	docker compose up -d --wait --wait-timeout 120 backend frontend
	@echo 'Frontend: http://127.0.0.1:5173 | API docs: http://127.0.0.1:8000/docs'
	@echo 'Running in the background. Use make logs or make down.'

up: build

setup:
	@command -v docker >/dev/null || { echo 'Docker Desktop is required. Install it and open it first.'; exit 1; }
	@docker compose version >/dev/null || { echo 'Docker Compose is required (included with Docker Desktop).'; exit 1; }
	@docker info >/dev/null 2>&1 || { echo 'Docker is unavailable. Open Docker Desktop and wait until it is running.'; exit 1; }
	@test -e .env || cp .env.example .env
	@test -e frontend/.env.local || cp frontend/.env.example frontend/.env.local

db: setup
	docker compose up -d --wait --wait-timeout 60 db

migrate: db
	docker compose run --rm --no-deps init alembic upgrade head

seed: db
	docker compose run --rm --no-deps init /bin/sh -ec 'python -m app.seed && python -m app.seed_strategy && python -m app.seed_user'

dev: setup
	docker compose up -d --wait --wait-timeout 120 backend frontend

down:
	docker compose stop frontend backend db

logs:
	docker compose logs -f backend frontend db

status:
	docker compose ps
