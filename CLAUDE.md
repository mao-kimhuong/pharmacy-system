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
  (picks python3.13/3.12/python3 ≥ 3.12; recreates an older .venv)
- `make test-docker` – the same suite in a python:3.12 container (infra/test/Dockerfile, with Pango +
  Noto Khmer + psql), so label and init-script tests always run. Part of "done".
- `make owner` – create the first owner account; `make smoke` – end-to-end check through Traefik
  (asks for the 2FA code; optional S1 checks create and deactivate a test branch + cashier; optional
  S1b checks import the sample products (they stay), search, print labels, cashier 403s; optional
  S2 checks: supplier, PO + PDF, receive 2 lots per line, FEFO stock, pay to 0, cashier sees no cost;
  optional S3 checks: USD/KHR sale + receipt, FEFO split, last-unit race, credit, cancel, return)
- `make revision s=<service> m="message"` then `make migrate s=<service>`
- `python -m sales_service.cli recover` – finish sales/returns left half-way (also runs every minute)
- `make resync` – re-send branches, branch settings and products as events (needed once when a service starts
  listening after the data exists: RabbitMQ drops events for queues that did not exist yet)

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
- **DB / RabbitMQ connection (from S1b):** services get `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`
  and `RABBITMQ_HOST/USER/PASSWORD`; `pharmacy_shared.config` builds the URLs with escaping, so
  passwords may contain any character. `DATABASE_URL` / `RABBITMQ_URL` still override (tests).
  Never build a URL from a password by string interpolation. In `.env`, quote such passwords
  and write `$` as `$$`. The Postgres init script passes passwords as psql variables (`:'pw'`).
- **Products (catalog, from S1b):** medicines + pack units; exactly one base pack unit
  (qty_in_base 1, named like `base_unit`); quantities everywhere are in the base unit; barcodes
  unique across all pack units; controlled ⇒ Rx-only (DB check too); no cost in catalog.
  Search: `GET /api/catalog/v1/medicines/search?q=` (barcode → SKU → names, pg_trgm).
- **Catalog events:** `medicine.created|updated|activated|deactivated` carry the whole product
  (`medicine_id`, `version`, sku, names, generic, strength, form, category/brand refs, rx flag,
  schedule, storage, is_active, `pack_units[]` with id, name, qty_in_base, barcode, sell_price as a
  USD string, is_base, is_active). Pack unit changes send `medicine.updated`. Keep a local copy
  keyed by `medicine_id` and ignore payloads whose `version` is not newer (see
  `document_service/services/events.py`). Also `category.*` / `brand.*` ({id, name_en, name_km,
  is_active}); a rename does not resend medicines. User Log entries for medicines are one per
  change with flattened keys like `pack_units.box.sell_price` (feeds the Modification report).
- **Excel import/export:** `catalog_service/services/spreadsheet.py` – files are checked by content
  (real .xlsx, no macros, zip-bomb limits), read values only (openpyxl read_only + data_only,
  defusedxml); every export cell goes through `pharmacy_shared.spreadsheet.safe_cell`. Import is
  validate → `GET /imports/{id}` → commit (Idempotency-Key, one transaction, re-validated;
  `create_missing` for new categories/brands, `skip_invalid` skips whole SKUs).
- **Labels / PDFs (document, from S1b):** `POST /api/documents/v1/render` (`type: label`; layouts
  `shelf_50x30`, `barcode_40x25`, `a4_sheet`), permission `labels.print`. HTML → PDF with
  WeasyPrint (Pango/HarfBuzz shape Khmer); fonts Noto Sans + Noto Sans Khmer (`fonts-noto-core`
  in the image); Code128 via python-barcode SVG; text HTML-escaped; the URL fetcher only allows
  `data:`. Never ReportLab for Khmer. Locally `brew install pango` (else PDF tests skip).
  Receipts, invoices, PO and register PDFs (later sprints) should reuse this renderer.
- **Local copies (from S2):** `pharmacy_shared.copies` – `ProductCopyMixin` / `PackUnitCopyMixin`
  (tables `products`, `product_pack_units`) and `BranchCopyMixin` (`known_branches`) with
  `upsert_product` / `upsert_branch`; used by document, purchasing and inventory. Add a listener:
  routing keys in `services/events.py`, then `make resync` on existing stacks.
- **Numbers (from S2):** `pharmacy_shared.numbering.next_number(session, DocSequence, branch_id,
  code, "PO")` → `PP1-PO-2026-000001`; counter row locked in the caller's transaction (no gaps,
  no duplicates; rollback frees it). Dates for business rules: `pharmacy_shared.clock.today()`
  (Asia/Phnom_Penh); tests monkeypatch it.
- **Purchasing (from S2):** PO draft → sent (status only) → partially_received → received;
  edit in draft only; cancel only if nothing received. Receive only a sent PO (Idempotency-Key):
  expiry < today → BATCH_EXPIRED, < 180 days → `short_expiry`; over-receipt needs `allow_over` +
  `purchasing.over_receive`. A receipt is the supplier's bill (`PP1-GRN-…`, due after payment
  terms); `goods.received` carries branch, supplier, lines (medicine, pack unit, qty_base, lot,
  expiry, cost_per_base NUMERIC(14,4), controlled flag). Supplier payments go to the branch's
  oldest open bills; above what is owed → SUPPLIER_OVERPAYMENT; cancel reverses allocations.
  The PO PDF: `POST /api/documents/v1/render {"type":"purchase_order"}` from the document
  service's copy of `purchase_order.*` events (waits up to 5 s, then DOCUMENT_NOT_READY).
- **Batches and movements (inventory, from S2):** a batch = medicine + lot + expiry + supplier +
  cost_per_base (same lot at another cost = another batch; FEFO treats them alike; unique index
  with NULLS NOT DISTINCT). `stock` is per (branch, batch) with CHECK on_hand ≥ reserved ≥ 0.
  Stock changes ONLY through `services/movements.apply_movement()` in the caller's transaction:
  it locks the stock row, writes a signed movement (`qty_after`) and emits `stock.changed`.
  `in`/`opening` movements are unique per source line (receipt line, stock-in line, opening line),
  so a re-delivered `goods.received` books nothing twice. FEFO order everywhere: expiry_date,
  received_at, id. Quick stock-in (no PO) and Initialize (validate → commit → branch locked; only
  the owner unlocks, with a reason) use the same expiry rules.
- **Cost visibility:** inventory cost (`cost_per_base`, `value`, `stock_value`) only with
  `finance.cost_profit`; purchasing prices (`unit_cost`, `line_total`, `total`, `paid`, `balance`)
  only with `purchasing.order` / `purchasing.pay` / `finance.cost_profit`. Routes build the full
  model and drop those keys with `pharmacy_shared.visibility.drop_fields` (absent, not null).
  Events between services always carry cost (reports need it).
- **Expiry job:** inventory background task at 00:05 Asia/Phnom_Penh (and once at start-up):
  active batches with expiry_date < today → `expired` (not sellable), `batch.expired` event,
  User Log entry by the system. `pg_try_advisory_xact_lock` = one replica at a time. Tests call
  `expire_batches(session, today)`; by hand: `python -m inventory_service.cli expire-batches
  [--dry-run [--today YYYY-MM-DD]]`. `EXPIRY_JOB_ENABLED=false` turns it off.
- **Models (from S3):** each service has its own declarative base, `<service>_service/models/base.py`
  (`Base = make_base()` from `pharmacy_shared.db`), so several services' models load in one
  process. New model files: `from .base import Base`.
- **Internal calls (from S3):** service-to-service endpoints live under `/internal/v1/...`
  (`create_service_app(..., internal_router=...)`); Traefik routes only `/api/...`, so they are
  reachable only on the Docker network (smoke checks the 404). Server side:
  `caller: InternalCaller = Depends(internal_caller)` – checks `X-Service-Token` against
  `SERVICE_TOKEN` (constant time, 401 otherwise) and gives the acting user/branch for the User
  Log. Client side: `pharmacy_shared.internal.InternalClient(url, "sales", token).post(path, body,
  actor=user, branch_id=..., idempotency_key=...)` – 2 s connect / 8 s read timeout, retries only
  connection errors, the other service's AppError comes back as the same AppError, unreachable →
  TEMPORARILY_UNAVAILABLE (503). Internal endpoints are idempotent by business ref (invoice id,
  return id), not by the middleware. Not rate-limited (the caller limits the real user).
  Production refuses to start if SERVICE_TOKEN is missing, a default or < 32 characters.
- **FEFO reservations (inventory, from S3):** `POST /internal/v1/reservations` (one per invoice,
  idempotent): per line, active batches with expiry ≥ today (Phnom Penh), FEFO (expiry, received,
  id), split over batches, minus reserved and quarantined; stock rows `FOR UPDATE`, medicines in a
  fixed order (no deadlocks, no two tills on the last unit); OUT_OF_STOCK lists every short line.
  A pharmacist's batch override takes that batch (BATCH_EXPIRED / BATCH_BLOCKED / OUT_OF_STOCK).
  `/confirm` → `out` movements; `/release` and `/release-by-ref` → nothing sold; `/reverse` →
  `sale_cancel` movements into the same batches; `/returns` → `return` movements, optionally into
  `qty_quarantined` (on hand, never sold) until a pharmacist releases it (`POST
  /quarantine/release`, reason, User Log). `in/opening/out/sale_cancel/return` are unique per
  source ref.
- **Sale saga (sales, from S3):** `services/sale_saga.py`. 1 validate (active product, price from
  the local copy, pack units → base; controlled → CONTROLLED_NOT_AVAILABLE, Rx-only →
  RX_REQUIRED until S4/S5; payments settle), save `pending` (no number) → 2 reserve (undo:
  release by invoice) → 3 charge credit (undo: credit/reverse) → 4 confirm (undo: reverse) → 5 number
  `PP1-INV-2026-000123` (only completed sales get one: no gaps), batches per line, `invoice.created`,
  User Log. Failure: compensations in reverse (each registered before its step, idempotent,
  "nothing to undo" tolerated) → `failed` with code/reason; a compensation that cannot run →
  `needs_attention`, finished by the recovery task (every minute, advisory lock), which also
  finishes `cancelling` invoices and `needs_attention` returns. Same Idempotency-Key → same invoice
  (key stored on the invoice). Cancel (`sales.cancel`, reason): credit first, then stock; without
  `sales.cancel_any` only today's invoices; not after a return. Returns (`sales.return`): ≤ sold −
  returned, back to the last-used batch first or quarantine, opened packs only if the branch allows,
  credit sales refunded as a credit note; `PP1-RT-…`. Customers: append-only ledger (balance =
  sum), debts per credit invoice, payments oldest first, credit limits need `customers.credit_limit`.
- **KHR / USD (from S3):** prices and totals USD NUMERIC(14,2); per-branch rate (whole riel per
  USD, history with previous rate, who, when; `sales.exchange_rate`); each invoice stores its rate
  and the KHR total (rounded to 100 riel). Payments mix methods and currencies; riel in whole
  hundreds, converted at the invoice rate (half up, to the cent). Card/ABA/KHQR/credit may not
  overpay: change only from cash, given as USD, KHR or USD_KHR (default: dollars in USD, cents in
  riel), riel rounded to 100 half up; `change_rounding_khr` (exact − handed over) makes the drawer
  reconcile. Rules and examples: `sales_service/services/money.py` + `tests/test_money.py`.
- **Receipts (document, from S3):** `POST /api/documents/v1/render {"type": "receipt_80mm" |
  "invoice_a4", "invoice_id"}` (pos.sell or sales.view, own branches) from the copy of `invoice.*`
  events (waits up to 5 s → DOCUMENT_NOT_READY). 80 mm page cut to the content's length (laid out,
  measured, rendered again). Branch header/footer come from `branch.settings_updated` via sales.

## Definition of done
API matches the spec, migration included, tests pass (`make test` and `make test-docker`),
`docker compose up` works, permissions checked per role, audit log written.

## Progress (SDLC sprints, see docs/spec.md)
- [x] Project skeleton
- [x] S0 Setup – auth login + /verify, attach ForwardAuth, outbox relay, idempotency
- [x] S1a Settings – users, roles + permissions, 2FA, User Log, branches, branch settings, feature switches
- [x] S1b Settings – products, pack units, categories, brands, Excel import, labels
- [x] S2 Stock + buying – batches, stock, initialize, suppliers, PO, receiving, payments
- [x] S3 POS + sales – FEFO checkout, invoices, returns, customers, receipts
- [ ] S4 Prescriptions – patients, doctors, Rx, dispensing, allergy warnings, labels
- [ ] S5 Controlled + counts – register, PIN + witness, stock take, shrinkage
- [ ] S6 Branches – transfer requests, transfers, purchase requests, re-order
- [ ] S7 Sales extras – sale order, suspend, templates, promotions, hampers, commission
- [ ] S8 Reports – dashboard, all reports, Telegram 20:00
- [ ] S9 Hardening – performance, security, offline POS, UAT fixes; per-service tokens for
  internal calls (today one shared SERVICE_TOKEN: a service could call any other's /internal)
- [ ] S10 AI – DeepSeek phase A
