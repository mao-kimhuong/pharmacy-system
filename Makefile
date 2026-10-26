SERVICES := auth branch catalog inventory stockcount prescription controlled sales customers purchasing reports notification document ai

.PHONY: help env up down logs ps owner smoke test test-db test-db-down lint migrate revision

help:
	@echo "make env       copy .env.example to .env (first time)"
	@echo "make up        build and start everything"
	@echo "make down      stop everything"
	@echo "make logs s=sales   follow one service's logs"
	@echo "make owner     create the first owner account"
	@echo "make smoke     check login + protected routes through Traefik"
	@echo "make test      lint + tests for all services (starts test databases)"
	@echo "make migrate s=auth             run alembic upgrade head in a service"
	@echo "make revision s=auth m='add users'   create a migration"

env:
	@test -f .env || cp .env.example .env && echo ".env ready - change the passwords"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f $(s)

ps:
	docker compose ps

owner:
	docker compose exec auth python -m auth_service.cli create-owner

smoke:
	python3 scripts/smoke.py

test-db:
	docker compose -f docker-compose.test.yml up -d --wait

test-db-down:
	docker compose -f docker-compose.test.yml down

test: test-db
	./scripts/test-all.sh

lint:
	ruff check .

migrate:
	docker compose exec $(s) alembic upgrade head

revision:
	docker compose exec $(s) alembic revision --autogenerate -m "$(m)"
