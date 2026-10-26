# Pharmacy System Management

Full spec: `docs/spec.md`. Read the sections a task touches before writing code.
The spec is the source of truth for tables, endpoints, rules and error codes.

## Stack
FastAPI, PostgreSQL 16 (one database per service), SQLAlchemy 2.0 (async, asyncpg),
Alembic, Pydantic v2, RabbitMQ (transactional outbox), Redis, Docker Compose,
Traefik v3.6. Python 3.12. Lint with ruff.

## Layout
- `shared/pharmacy_shared/` – config, db base + mixins, error codes and format,
  current user from Traefik headers, outbox, JSON logging, app factory.
- `services/<name>/<name>_service/` – `main.py`, `api/`, `services/` (business
  rules), `models/`, `schemas/`, `events/`; `migrations/` (Alembic); `tests/`.
- `traefik/`, `infra/postgres/init/`, `docs/`, `web/` (front end, not started).

| Service | Prefix | Owns |
| --- | --- | --- |
| auth | `/api/auth/v1` | Users, roles, permissions, sessions, PIN, audit log |
| branch | `/api/branch/v1` | Branches, branch settings, feature switches |
| catalog | `/api/catalog/v1` | Medicines, pack units, categories, brands, promotions, hampers, imports |
| inventory | `/api/inventory/v1` | Batches, stock per branch, movements, transfers, shrinkage, opening stock, recalls |
| stockcount | `/api/stockcount/v1` | Stock takes, count lines, double count, approval |
| prescription | `/api/prescription/v1` | Patients, doctors, prescriptions, Rx items, dispensing balance |
| controlled | `/api/controlled/v1` | Controlled-drug register (append-only, hash-chained), witness, discrepancies |
| sales | `/api/sales/v1` | POS, invoices, sale orders, suspend, templates, returns, commission; sale saga |
| customers | `/api/customers/v1` | Customers, customer groups, credit, payments, statements |
| purchasing | `/api/purchasing/v1` | Suppliers, supplier groups, purchase requests, POs, receiving, supplier payments and returns |
| reports | `/api/reports/v1` | Read models built from events; dashboard and all reports |
| notification | `/api/notifications/v1` | Telegram daily report, alerts |
| document | `/api/documents/v1` | Receipts, A4 invoices, labels, PO and register PDFs |
| ai | `/api/ai/v1` | DeepSeek features: import cleanup, ask your data, summaries, substitutes, Rx parsing |

## Open decisions
- File storage (Rx photos, PDFs): MinIO's free images were removed from Docker Hub
  in Sept 2026. Pick an S3-compatible store before S4 (SeaweedFS, Garage,
  Chainguard MinIO image, or cloud S3) and access it only through an S3 client
  (boto3/aioboto3), so the choice can change later.

## Rules (never break these)
- A service reads and writes only its own database. Other data: API call or events.
- Invoices, POs, payments, transfers, prescriptions: cancel with a reason, never delete.
- Medicines, customers, patients, doctors, suppliers, branches, staff: deactivate, never delete.
- Stock changes only through movements, always with branch_id and batch_id. FEFO on every sale.
- Controlled-drug register is append-only and hash-chained; corrections are new rows.
- Every POST that changes money or stock takes an `Idempotency-Key` header.
- Role, user and branch come from `pharmacy_shared.auth.current_user`, never from the body.
  Every query is filtered by the user's branches.
- SQL only through the ORM or bound parameters; no f-string SQL (ruff S608 fails CI).
- Input schemas use `extra="forbid"`. Errors use `AppError(ErrorCode.X, ...)`.
- Business logic lives in `services/`, not in routers. Every rule has a pytest test.
- Write the event to the outbox in the same transaction as the change.

## Commands
- `make env` then `make up` – start everything at http://localhost
- `make test` – starts the test Postgres + Redis (docker-compose.test.yml), then ruff + pytest everywhere
- `make owner` – create the first owner account; `make smoke` – end-to-end check through Traefik
  (asks for the 2FA code; optional S1 checks create and deactivate a test branch + cashier)
- `make revision s=<service> m="message"` then `make migrate s=<service>`

## How things work (from S0)
- **Who is calling:** `user: CurrentUser = Depends(current_user)`; then `user.require_branch(branch_id)`.
  Traefik strips client-sent identity headers and sets them from `/api/auth/v1/verify`.
- **Permissions (from S1a):** guard a route with `user: CurrentUser = Depends(requires("pos.sell"))`,
  or check inside with `user.require("sales.cancel")` / `user.has(...)`. Keys live in
  `services/auth/auth_service/permissions.py` (CATALOG + default role grants + MENU); add new
  keys there, they are synced to the DB at start-up. The owner has `*`. Dispensing Rx-only /
  controlled drugs needs the permission AND `user.is_pharmacist`.
- **2FA:** owner and branch manager must use an authenticator app. Their token only opens
  `/me`, `/2fa/setup`, `/2fa/enable`, `/logout` until 2FA is on (403 MFA_SETUP_REQUIRED).
- **User Log:** every change calls `record_audit(session, OutboxEvent, service=..., action=...,
  entity_type=..., entity_id=..., actor=user, branch_id=..., before=..., after=...)` in the same
  transaction (use `pharmacy_shared.audit.changes(before, after)` to keep only changed fields;
  never log secrets). The auth service consumes `audit.recorded` into `audit_logs`.
- **Listening to events:** `pharmacy_shared.consumer.EventConsumer` (queue `<service>.events`,
  duplicates skipped via a `processed_messages` table, failures → `<service>.events.dead`).
  Pass `consumer.run` in `background=` of `create_service_app`. Example: `services/auth/main.py`.
- **Branch list in other services:** keep a local copy from `branch.*` events
  (payload: branch_id, code, name_km, name_en, is_active), like auth's `known_branches`.
- **Feature switches:** `services/branch/branch_service/features.py`; GET /api/branch/v1/features.
- **Routes:** each service has a public Traefik router (health, docs, openapi.json) and a
  protected one (everything else, via `auth-forward`). Auth adds public `login` and `refresh`.
- **Money/stock writes:** add `_: str = Depends(require_idempotency_key)` to the route; the
  middleware replays the saved response for a retried key (24 h).
- **Events:** `add_event(session, OutboxEvent, "invoice.created", {...})` in the same
  transaction; the relay publishes to RabbitMQ exchange `pharmacy.events` (routing key =
  event type, message_id = outbox id, at-least-once: consumers must ignore seen ids).
- **Errors:** `raise AppError(ErrorCode.X, "message", status_code=...)`.
- **Tests:** real Postgres + Redis. See `services/auth/tests/conftest.py`: a fresh test
  database built with the service's own migrations, tables truncated per test.
- **Migrations:** containers run `alembic upgrade head` on start. New tables: change models,
  then `make revision s=<service> m="..."` and review the generated file.

## Definition of done
API matches the spec, migration included, tests pass (`make test`),
`docker compose up` works, permissions checked per role, audit log written.

## Progress (SDLC sprints, see docs/spec.md)
- [x] Project skeleton
- [x] S0 Setup – auth login + /verify, attach ForwardAuth, outbox relay, idempotency
- [x] S1a Settings – users, roles + permissions, 2FA, User Log, branches, branch settings, feature switches
- [ ] S1b Settings – products, pack units, categories, brands, Excel import, labels
- [ ] S2 Stock + buying – batches, stock, initialize, suppliers, PO, receiving, payments
- [ ] S3 POS + sales – FEFO checkout, invoices, returns, customers, receipts
- [ ] S4 Prescriptions – patients, doctors, Rx, dispensing, allergy warnings, labels
- [ ] S5 Controlled + counts – register, PIN + witness, stock take, shrinkage
- [ ] S6 Branches – transfer requests, transfers, purchase requests, re-order
- [ ] S7 Sales extras – sale order, suspend, templates, promotions, hampers, commission
- [ ] S8 Reports – dashboard, all reports, Telegram 20:00
- [ ] S9 Hardening – performance, security, offline POS, UAT fixes
- [ ] S10 AI – DeepSeek phase A
