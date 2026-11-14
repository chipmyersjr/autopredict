.DEFAULT_GOAL := build
ENV_FILE ?= .env
export ENV_FILE
COMPOSE = docker compose --env-file "$(ENV_FILE)"
RALPH_CONFIG ?= ralph/ingress-backend.json
RALPH_ARGS ?=
.PHONY: help build up setup db migrate seed dev down logs status ralph-preview ralph

help:
	@echo 'make build  Build containers, migrate/seed, and start the full stack'
	@echo 'make up     Alias for build'
	@echo 'make dev    Start previously built app containers without migrations/seeds'
	@echo 'make down   Stop all containers; preserve database data'
	@echo 'make logs   Follow backend, frontend, and database logs (Ctrl+C exits logs)'
	@echo 'make status Show container health'
	@echo 'Set ENV_FILE to use settings stored outside the project'
	@echo 'make ralph-preview  Show the configured task loop without running it'
	@echo 'make ralph          Execute tasks, verify, update the plan, and commit each task'

build:
	$(MAKE) setup
	$(COMPOSE) build backend frontend
	$(COMPOSE) stop backend frontend
	$(MAKE) db
	$(COMPOSE) run --rm --no-deps init
	$(COMPOSE) up -d --wait --wait-timeout 120 backend frontend
	@echo 'Frontend: http://127.0.0.1:5173 | API docs: http://127.0.0.1:8000/docs'
	@echo 'Running in the background. Use make logs or make down.'

up: build

setup:
	@command -v docker >/dev/null || { echo 'Docker Desktop is required. Install it and open it first.'; exit 1; }
	@docker compose version >/dev/null || { echo 'Docker Compose is required (included with Docker Desktop).'; exit 1; }
	@docker info >/dev/null 2>&1 || { echo 'Docker is unavailable. Open Docker Desktop and wait until it is running.'; exit 1; }
	@if [ "$(ENV_FILE)" = '.env' ]; then test -e .env || cp .env.example .env; fi
	@test -f "$(ENV_FILE)" && test -r "$(ENV_FILE)" || { echo 'ENV_FILE must point to an existing readable settings file.'; exit 1; }
	@test -e frontend/.env.local || cp frontend/.env.example frontend/.env.local

db: setup
	$(COMPOSE) up -d --wait --wait-timeout 60 db

migrate: db
	$(COMPOSE) run --rm --no-deps init alembic upgrade head

seed: db
	$(COMPOSE) run --rm --no-deps init /bin/sh -ec 'python -m app.seed && python -m app.seed_strategy && python -m app.seed_user'

dev: setup
	$(COMPOSE) up -d --wait --wait-timeout 120 backend frontend

down:
	$(COMPOSE) stop frontend backend db

logs:
	$(COMPOSE) logs -f backend frontend db

status:
	$(COMPOSE) ps

ralph-preview:
	python3 scripts/ralph.py preview --config "$(RALPH_CONFIG)" $(RALPH_ARGS)

ralph:
	python3 scripts/ralph.py run --config "$(RALPH_CONFIG)" --allow-plan-updates $(RALPH_ARGS)
