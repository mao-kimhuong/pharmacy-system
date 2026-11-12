SERVICES := auth branch catalog inventory stockcount prescription controlled sales customers purchasing reports notification document ai

.PHONY: help env up down logs ps owner smoke payway-check test test-docker test-db test-db-down lint migrate revision resync backfill seed-demo bench-reports openapi api-types web-install web-dev web-test web-e2e web-test-docker

help:
	@echo "make env       copy .env.example to .env (first time)"
	@echo "make up        build and start everything"
	@echo "make down      stop everything"
	@echo "make logs s=sales   follow one service's logs"
	@echo "make owner     create the first owner account"
	@echo "make smoke     check login + protected routes through Traefik"
	@echo "make resync    re-send staff, branches, products, customers and open POs as events (after adding a listening service)"
	@echo "make test      lint + tests for all services (starts test databases)"
	@echo "make test-docker   the same, inside a python:3.12 container (no local Python needed)"
	@echo "make migrate s=auth             run alembic upgrade head in a service"
	@echo "make revision s=auth m='add users'   create a migration"
	@echo "make backfill  rebuild the reports' read models from every service's outbox (safe to repeat)"
	@echo "make seed-demo a year of demo data in the reports (APP_ENV=development, DEMO branches)"
	@echo "make bench-reports  time every report over the demo year"
	@echo "make openapi   write every service's OpenAPI document to openapi/*.json"
	@echo "make api-types openapi + the web app's typed clients (web/src/api/gen)"
	@echo "make web-dev   the web app on :5173 (Vite), /api proxied to http://localhost"
	@echo "make web-test  web: typecheck, lint, unit tests with coverage, build, bundle size"
	@echo "make web-e2e   web: Playwright against BASE_URL (default http://localhost)"
	@echo "make web-test-docker   make web-test inside a node container"

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
	docker compose exec purchasing python -m purchasing_service.cli republish
	docker compose exec sales python -m sales_service.cli republish

backfill:
	docker compose exec reports python -m reports_service.cli backfill

# PayWay settings + a check-transaction of a made-up tran_id (must answer 6 = not found); QR=1 also makes a
# 100 KHR sandbox QR. A one-off container: the running stack is not touched. Prints no secret.
payway-check:
	docker compose run --rm --no-deps --build sales python -m sales_service.cli payway-check $(if $(QR),--qr)

seed-demo:
	docker compose exec reports python -m reports_service.cli seed-demo

bench-reports:
	docker compose exec reports python -m reports_service.cli bench

openapi:
	.venv/bin/python scripts/openapi.py

test-db:
	docker compose -f docker-compose.test.yml up -d --wait

test-db-down:
	docker compose -f docker-compose.test.yml down

# Long runs keep a Mac awake: when it sleeps, the Docker VM clock drifts and every 2FA login
# then fails (INVALID_MFA_CODE). caffeinate only exists on macOS; elsewhere this is empty.
KEEP_AWAKE := $(shell command -v caffeinate >/dev/null 2>&1 && echo caffeinate -dims)

test: test-db
	$(KEEP_AWAKE) ./scripts/test-all.sh

# Same suite in a container (with Pango + Khmer font, so label tests run too).
test-docker: test-db
	$(KEEP_AWAKE) docker compose -f docker-compose.test.yml --profile runner run --rm --build tests

lint:
	ruff check .

migrate:
	docker compose exec $(s) alembic upgrade head

revision:
	docker compose exec $(s) alembic revision --autogenerate -m "$(m)"

# --- Web front end (web/). Needs Node 20+ (web/.nvmrc). ---
WEB_NODE ?= $(shell for n in $$HOME/.nvm/versions/node/v2[4-9]*/bin $$HOME/.nvm/versions/node/v2[0-3]*/bin; do [ -x $$n/node ] && echo $$n && break; done)
WEB_ENV = PATH="$(if $(WEB_NODE),$(WEB_NODE):)$$PATH"

web-install:
	cd web && $(WEB_ENV) npm ci --no-audit --no-fund

api-types: openapi
	cd web && $(WEB_ENV) npm run api-types

web-dev:
	cd web && $(WEB_ENV) npm run dev

web-test:
	cd web && $(WEB_ENV) npm run typecheck && $(WEB_ENV) npm run lint && $(WEB_ENV) npm test && $(WEB_ENV) npx vite build && $(WEB_ENV) npm run size

web-e2e:
	cd web && $(WEB_ENV) BASE_URL=$${BASE_URL:-http://localhost} $(KEEP_AWAKE) npx playwright test

web-test-docker:
	$(KEEP_AWAKE) docker run --rm -v "$(CURDIR)":/repo:ro -e CI=1 node:24-alpine sh -c "\
	  mkdir -p /x/web /x/docs && cp -r /repo/docs/design /x/docs/ && \
	  tar -C /repo/web --exclude=./node_modules --exclude=./dist --exclude=./coverage -cf - . | tar -C /x/web -xf - && \
	  cd /x/web && npm ci --no-audit --no-fund && npm run typecheck && npm run lint && npm test && npx vite build && npm run size"
