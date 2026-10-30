SERVICES := auth branch catalog inventory stockcount prescription controlled sales customers purchasing reports notification document ai

.PHONY: help env up down logs ps owner smoke test test-docker test-db test-db-down lint migrate revision resync

help:
	@echo "make env       copy .env.example to .env (first time)"
	@echo "make up        build and start everything"
	@echo "make down      stop everything"
	@echo "make logs s=sales   follow one service's logs"
	@echo "make owner     create the first owner account"
	@echo "make smoke     check login + protected routes through Traefik"
	@echo "make resync    re-send staff, branches, products and customers as events (after adding a listening service)"
	@echo "make test      lint + tests for all services (starts test databases)"
	@echo "make test-docker   the same, inside a python:3.12 container (no local Python needed)"
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

# Services that start listening late (new queue) missed earlier events: re-send them.
# Safe to repeat: consumers ignore what they already have.
resync:
	docker compose exec auth python -m auth_service.cli republish
	docker compose exec branch python -m branch_service.cli republish
	docker compose exec catalog python -m catalog_service.cli republish
	docker compose exec customers python -m customers_service.cli republish

test-db:
	docker compose -f docker-compose.test.yml up -d --wait

test-db-down:
	docker compose -f docker-compose.test.yml down

test: test-db
	./scripts/test-all.sh

# Same suite in a container (with Pango + Khmer font, so label tests run too).
test-docker: test-db
	docker compose -f docker-compose.test.yml --profile runner run --rm --build tests

lint:
	ruff check .

migrate:
	docker compose exec $(s) alembic upgrade head

revision:
	docker compose exec $(s) alembic revision --autogenerate -m "$(m)"
