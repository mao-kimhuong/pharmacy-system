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
- `traefik/`, `infra/postgres/init/`, `docs/`, `web/` (front end: React + Vite, see `web/README.md`).

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

## Decided
- File storage (Rx photos, later PDFs): SeaweedFS 4.51 (S3 API), decided in S4. Reached only
  through `pharmacy_shared.storage.Storage` (aioboto3), so cloud S3 is a settings change.

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
- `docker compose exec controlled python -m controlled_service.cli open-balances` – once after installing S5:
  controlled stock from before the register gets "opening" entries (`check` runs the 00:20 register check now)
- `docker compose exec auth python -m auth_service.cli reset-2fa --phone 012…` – last resort when an owner lost phone and
  backup codes (User Log + Telegram alert)
- `python -m sales_service.cli recover` – finish sales/returns left half-way (also runs every minute)
- `make resync` – re-send staff, branches, branch settings, products, customers, open POs and commission lines as events (needed
  once when a service starts listening after the data exists: RabbitMQ drops events for queues that did not exist yet)
- `make backfill` – rebuild the reports' read models by replaying every service's outbox (safe to repeat; `--rebuild` empties first)
- `make openapi` – every service's OpenAPI document to `openapi/*.json`
- `make api-types` (openapi → `web/src/api/gen`), `make web-dev` (Vite :5173, /api → http://localhost), `make web-test`
  (typecheck, lint, Vitest, build, bundle budget), `make web-e2e` (Playwright, `BASE_URL`), `make web-test-docker`
- Long runs on a Mac: `make test`, `test-docker`, `web-e2e` and `web-test-docker` run under `caffeinate -dims` (empty
  where caffeinate does not exist); run anything else long the same way (`caffeinate -dims …`). A sleeping Mac lets the
  Docker VM clock drift and every 2FA login then fails with INVALID_MFA_CODE. The e2e setup checks the stack's clock first
  (`web/e2e/lib/clock.ts`, > 15 s off → a clear error); resync with `docker run --rm --privileged alpine hwclock -s` or by
  restarting Docker Desktop, then run again.
- `make seed-demo` / `make bench-reports` – a year of demo data in the reports (APP_ENV=development, DEMO branches only) and
  the timing of every report (target < 2 s)
- `make seed-realistic` – a realistic Cambodian pharmacy for demos (APP_ENV=development only): 3 branches (PP1 Toul Kork,
  PP2 BKK1, SR1 Siem Reap), owner + 15 staff with PINs (owner/managers with 2FA), ~160 products, suppliers, customers,
  patients, doctors, stock by PO/receiving (SR1 by Initialize) and 90 days of trade, ALL through the services' APIs
  (`scripts/seed_realistic/`, run in a one-off sales container: login → /verify headers → the service, as Traefik does),
  then backfill + register check. Safe to repeat (seed-output/<project>/state.json; Idempotency-Keys are stable). Logins:
  `seed-output/<compose project>/logins.md` (git-ignored; one folder per stack). `make seed-reset` = down -v + up + seed. SEED_DAYS / SEED_MIN / SEED_MAX.
- **Dev clock (seed only):** `pharmacy_shared.clock` – `X-Dev-Clock: <ISO time>` + a valid `X-Service-Token` makes a request
  run at that time (`now()`, `today()`, server-default timestamps via a before-insert hook, forwarded on internal calls,
  `occurred_at` in User Log events). The middleware exists only when APP_ENV=development and ENVIRONMENT≠production
  (`shared/tests/test_dev_clock.py`); never rely on it in code.

## How things work (from S0)
- **Who is calling:** `user: CurrentUser = Depends(current_user)`; then `user.require_branch(branch_id)`.
  Traefik strips client-sent identity headers and sets them from `/api/auth/v1/verify`.
- **Web refresh cookie (auth):** a client that sends `X-Refresh-Cookie: 1` on `/login`, `/login/2fa` and `/refresh` gets the
  refresh token only as cookie `pharmacy_refresh` (httpOnly, Secure, SameSite=Strict, path `/api/auth/v1/refresh`, 7 days),
  never in the body; `/refresh` with no body reads the cookie; `/logout` clears it and ends the session by the token's `sid`.
  Other clients (smoke, scripts) keep the token in the body (`tests/test_refresh_cookie.py`).
- **2FA management (auth):** `services/two_factor.py`. Any user turns it on from the profile. `POST /me/2fa/disable` and
  `POST /2fa/backup-codes` need the password + a code or backup code, under login's lockout (wrong ones count, a locked
  account is refused; Traefik router `auth-mfa` has the login limit). Roles in `roles_requiring_2fa` get
  MFA_REQUIRED_FOR_ROLE (`/me` `mfa_required_for_role`) and take a new key in two steps: `POST /me/2fa/reset` (key waits in
  `totp_pending_secret_enc`, the old one keeps working) → `/me/2fa/reset/confirm` (10 new backup codes). `POST
  /users/{id}/2fa/reset`: owner only, `pin_token` (action `auth.mfa_reset`; PIN actions have no digits). Last resort on the
  server: `python -m auth_service.cli reset-2fa --phone …`. Off or reset: other sessions end (all of them for the owner's
  and the server's reset), User Log `user.2fa_disabled` / `user.2fa_reset`, same-named event → owner's Telegram (name and
  action only).
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
  protected one (everything else, via `auth-forward`). Auth adds public `login`, `login/2fa` and `refresh` (`shared/tests/test_traefik_routes.py`).
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
  reconcile. Riel is compared in riel: the part USD payments leave is due as riel at the invoice's rate, rounded to
  100 (an all-riel sale: total_khr); riel paid = due settles it exactly (2.70 USD → 11 100 riel even though 11 100 / 4100
  = 2.71), `payment_rounding_khr` keeps riel due − exact riel; non-cash riel above the due is refused, more cash riel gives
  change. Rules and examples: `sales_service/services/money.py` + `tests/test_money.py`.
- **Receipts (document, from S3):** `POST /api/documents/v1/render {"type": "receipt_80mm" |
  "invoice_a4", "invoice_id"}` (pos.sell or sales.view, own branches) from the copy of `invoice.*`
  events (waits up to 5 s → DOCUMENT_NOT_READY). 80 mm page cut to the content's length (laid out,
  measured, rendered again). Branch header/footer come from `branch.settings_updated` via sales.

- **Files (from S4):** `pharmacy_shared.storage.Storage` (S3 API, SeaweedFS in compose: internal network
  only, no host port, no Traefik route, private bucket `rx-files`, keys `S3_ACCESS_KEY` / `S3_SECRET_KEY`,
  production refuses defaults). Never a presigned or public link: the owning service streams the file
  after checking user, branch and permission and writes a User Log entry each time; headers: stored
  Content-Type, `Content-Disposition: inline` with a safe name, `X-Content-Type-Options: nosniff`,
  `Cache-Control: no-store`. Uploads go through `pharmacy_shared.uploads.check_upload` (JPEG/PNG/PDF by
  content, ≤ 10 MB, images re-encoded without EXIF, PDFs with JavaScript/launch/embedded files refused →
  FILE_REJECTED); random keys, original name only in the DB. Store down → TEMPORARILY_UNAVAILABLE.
- **Ingredients (catalog, from S4):** medicines carry `active_ingredients` (default: generic name split on
  "+") and `drug_classes` (e.g. penicillins), in medicine.* events and the Excel import (";"-separated).
- **Prescriptions (from S4):** patients (home branch + linked branches; another branch finds one only by
  exact phone via `POST /patients/link`, logged; every record view logged), allergies (ingredient or class,
  removed with a reason), doctors (licence unique), Rx `PP1-RX-…`: draft → active → partly / fully
  dispensed, expired (00:10 job + checked by date at dispense), cancelled (reason, not while held).
  `qty_base` is one fill; allowed in total = qty × (1 + repeats_allowed); one sale ≤ one fill.
  `rx_valid_days` (30) and `dispensing_label_size` (70x40 | 50x30 | 100x50 | a4_sheet) are branch settings.
  Prescription keeps copies of products (with ingredients/classes), branches, settings, customers.
- **Dispensing (sales, from S4):** an Rx-only line needs `rx_item_id`, `is_pharmacist` and
  `pos.dispense_rx` (else RX_REQUIRED / PHARMACIST_REQUIRED). Saga step 1b `POST
  /internal/v1/rx/check-and-hold` (prescription; idempotent per invoice; rows locked): RX_EXPIRED,
  PRESCRIPTION_STATE, RX_QUANTITY_EXCEEDED, ALLERGY_WARNING (409; pass `allergy_override_reason`:
  pharmacist + `prescriptions.override_warning`), DUPLICATE_THERAPY_WARNING (409; pass
  `acknowledge_warnings`); messages in English and Khmer; the quantity is held; compensation
  `/rx/release`. The line stores Rx, patient, directions, warnings, override by / acknowledged by + at;
  User Log `dispensing.allergy_override` / `dispensing.warning_acknowledged`. Prescription follows
  invoice.created / cancelled / returned (absolute per line: sold − returned, 0 if cancelled; only newer
  invoice versions), so a return or cancel gives the quantity back. A retry after a warning needs a new
  Idempotency-Key (the failed sale is replayed for the old one).
- **Rx documents (document, from S4):** `POST /render {"type":"dispensing_label","invoice_id","line_no"?,
  "lang":"km"|"en","size"?}` (pos.dispense_rx or prescriptions.view; size from the invoice snapshot's
  branch setting) and `{"type":"rx_summary","patient_id"}` (prescriptions.view, logged), from copies of
  invoice.*, patient.*, prescription.* and user.* (pharmacist names; `python -m auth_service.cli
  republish` / `make resync` sends existing users). Receipts show the Rx number and lots on Rx lines.

- **PIN step-up (auth, from S5):** `POST /api/auth/v1/pin/verify {pin, action}` → one-time `pin_token`
  (2 min, Redis, only its hash stored, bound to person + action); `/pin/witness {witness_user_id, pin, action}`
  = a second person on the same device; `GET /pin/witnesses?branch_id=`. 5 wrong PINs → PIN_LOCKED 15 min
  (User Log `user.pin_locked`). Services consume tokens with `pharmacy_shared.pin.consume_pin / consume_witness`
  (auth `/internal/v1/pin-tokens/consume`, GETDEL): missing → PIN_REQUIRED (401) / WITNESS_REQUIRED (422);
  used, expired, wrong person or action → PIN_INVALID; witness = actor, other branch or no
  `controlled.witness` → WITNESS_INVALID; destroying controlled stock (register `destroy`, controlled
  shrinkage except lost/stolen) needs a branch_manager or owner witness (`roles=DESTRUCTION_WITNESS_ROLES`). Actions: controlled.dispense / adjust / destroy / resolve,
  stockcount.approve, inventory.shrinkage. Services never see a PIN.
- **Permission sync (from S5):** keys new to the DB go to the built-in roles whose defaults have them;
  `RENAMED` moves grants (`pos.dispense_controlled` → `controlled.dispense`); `DEFAULT_ADDITIONS` gives an
  existing key to a role once (table `applied_grants`).
- **Movements (from S5):** `meta` JSON (witness, Rx, patient, pharmacist, method…) travels in `stock.changed`
  (with `seq`, `occurred_at`); new types `shrinkage`, `count_adjust` (once per source). Reservation lines and
  returns pass `meta` for controlled sales.
- **Controlled register (from S5):** controlled service builds entries from `stock.changed` of controlled
  medicines (once per movement id): one hash chain per branch + medicine (`sha256(prev_hash + canonical JSON)`,
  UTC timestamps, advisory lock per chain), `balance_after`. DB trigger refuses UPDATE/DELETE/TRUNCATE
  (tests clean up with `SET LOCAL session_replication_role = replica`). `GET /register` (chain_valid),
  `/register/verify`, `POST /entries` (adjust/destroy: PIN + witness → inventory `/internal/v1/movements/controlled`,
  once per request), `/entries/correction` (new row, old one stays). Daily 00:20 (+ start-up, advisory lock):
  verify chains (`register.chain_broken`), register vs stock per batch (`register.discrepancy`; skipped while the
  register is behind = inventory's last seq > the watermark of seen movements; an open one clears itself when
  they agree again); resolve: `controlled.resolve`, PIN + witness, optional correction entry. PDF:
  `POST /api/documents/v1/render {"type":"controlled_register", branch_id, medicine_id?, date_from?, date_to?}`
  (document reads it over controlled `/internal/v1/register`).
- **Controlled sales (from S5):** line needs `rx_item_id`, `patient_id_document`, `is_pharmacist` +
  `controlled.dispense`; invoice `pin_token` (controlled.dispense) consumed in step 1. Controlled Rx valid
  `controlled_rx_valid_days` (7) by default and at most.
- **Stock take (stockcount, from S5):** start = inventory snapshot (`/internal/v1/stock/snapshot`, scope full /
  category / location / controlled, under a short SHARE lock on movements → `as_of_seq`); blind counter view +
  barcode lookup; double count (controlled, or line value > `double_count_above_usd` 50) needs two people with
  the same number (recount otherwise; `round` keeps old counts); submit: expected = snapshot + movements after
  as_of_seq up to the moment the line was counted (DB clock); approve: PIN if a controlled line has a variance,
  owner only above `owner_approval_above_usd` (200) → `count.approved` → inventory `count_adjust` once per line.
- **Shrinkage + shelf locations (inventory, from S5):** `POST /shrinkages` (reasons expired / damaged / broken /
  lost_theft / recalled; controlled: PIN + witness + destruction method), above `shrinkage_approval_usd` (50)
  pending until someone else with `inventory.shrinkage_approve` approves; photo private in SeaweedFS
  (`inventory-files`), streamed + logged. `PUT /shelf-locations` (`inventory.locations`), code like "A3".

- **Scheduled jobs:** all in Asia/Phnom_Penh time (`clock.TIMEZONE`), each once at start-up too, one replica
  at a time (advisory lock): inventory expiry 00:05, prescription expiry 00:10, register check 00:20,
  re-order lists + alerts 00:30, sales: suspended carts expire 00:01, order reservations every 10 min, KHQR check 00:40; notification:
  stock digest 07:30, daily Telegram summary 20:00 (both also catch up at start-up), the sender every 10 s.
- **Transfers (inventory, from S6):** request (`transfers.request`, destination) → approve / reject
  (`transfers.approve`, source) → transfer `PP1-TR-…`: approved → picked → dispatched → received → closed, or
  cancelled (reason, only before dispatch, reservations released → TRANSFER_STATE after). Push without a
  request (`transfers.dispatch`, source). Pick = FEFO (reuses the reservation helpers) or chosen batches with a
  reason, and reserves the stock. Dispatch (Idempotency-Key) = `transfer_out` per pick → in transit (derived:
  dispatched picks, then open short/damaged differences; `GET /transfers/in-transit`). Receive (destination,
  Idempotency-Key) = `transfer_in` into the same batch (lot, expiry, supplier, cost kept), optional shelf
  location; short / damaged / extra → differences; resolve (`transfers.resolve`): write_off (posted shrinkage
  record with no movement; short on the source's books, damaged on the destination's), return_to_source
  (`transfer_in` at the source), accept extra (`adjust_in`), reject. Controlled lines: PIN + witness on dispatch
  and on receive (actions `transfers.dispatch` / `transfers.receive`), meta → register entries on both sides.
  `transfer_in/out` are once per source ref. Events `transfer.*` (full snapshot + version, cost per base) and
  `transfer_request.*`. `GET /transfers/by-number/{n}` (QR scan). Note PDF: `POST /api/documents/v1/render
  {"type":"transfer_note","transfer_id"}` (segno QR as SVG data URI).
- **Purchase requests (purchasing, from S6):** `PP1-PR-…`, submitted → approved / rejected / cancelled (reason);
  lines → ordered (PO) / transferring → fulfilled. To PO (`purchasing.order`): lines of several branches + one
  supplier → one draft PO per branch (S2 POs unchanged; same pack merged) + `po_groups` `PP1-PG-…`
  (`PurchaseOrder.group_id`, in purchase_order.* events); printout `{"type":"purchase_order_group","group_id"}`.
  Fill by transfer (`purchasing.request_approve`) → inventory `/internal/v1/transfers/from-purchase-request`
  (approved request + transfer, once per source_ref). Progress: receipts (oldest request first), PO cancel →
  approved again, `transfer.*` (absolute, newer versions only; fulfilled when all arrived or the transfer is
  closed). Re-order lists call `/internal/v1/purchase-requests` (once per source_ref).
- **Re-ordering (inventory, from S6):** `reorder_settings` (min, max, lead time, preferred supplier; bulk by
  category; `inventory.reorder_settings`). avg = net sales (out − sale_cancel − return) / `reorder_sales_days`
  (30); point = min or avg × (lead 7 + safety 3); available = sellable + in transit + open POs (copy of
  `purchase_order.*` → `open_po_lines`); target = max or avg × (lead + safety + days); rounded up to the biggest
  pack adding ≤ 25 %. Transfer suggestion: other branch with spare (above its max / 60 days of its sales) or
  near-expiry stock (within its `near_expiry_transfer_days` 90, more than it will sell in time, we sell faster).
  Lists (`POST /reorder-lists/run`, daily job) → purchase request or transfer requests in one step. Events
  `stock.low` and `batch.expiring` (branch `expiry_alert_days`) at most once a day (`alerts_sent`).
- **Promotions (catalog rules → sales, from S7):** catalog `promotions` (`catalog.promotions`): percent_off,
  amount_off, buy_x_get_y, bundle_price, qty_tiers, group_price; targets, window, days, branches, customer
  groups, max uses total / per customer, stackable, include_rx (Rx-only + controlled excluded otherwise);
  `promotion.*` events (whole rule + version). Sales copy + `promotion_uses` (held at save, released on fail,
  cancel, full return). Pricing engine `sales_service/services/pricing.py` (pure): best deal = each exclusive
  alone vs all stackable together, tie keeps the exclusive. Invoice lines store `promotion_ids`,
  `promo_discount`, `manual_discount`, `net`. Manual discount (`discount_pct` / `discount_amount`) capped per
  role by branch setting `max_discount_pct` (cashier 5, pharmacist 10, manager 20, owner none); above it
  `discount_approval_token` = `/pin/witness` (action `sales.discount`) of another user: manager or owner, and
  only the owner above a manager's own cap (DISCOUNT_APPROVAL_REQUIRED). After the reservation, net < batch
  cost → BELOW_COST unless `sales.below_cost` (owner by default).
- **Promotion rules (S7 + fixes):** empty `branch_ids` = every branch, owner only; others list their own branches and get
  BRANCH_FORBIDDEN on a promotion reaching other branches. `_bad` errors carry `details.field` + `details.reason` (the web
  app translates the reason; `web/src/api/fieldErrors.ts` puts any API error next to its field).
- **Hampers (from S7):** a catalog medicine with `kind="hamper"` + `hamper_components` (`catalog.hampers`,
  `/hampers`); Rx-only if a component is; no pack units added, components cannot be deactivated while used.
  No stock of its own: inventory expands a hamper line into its components (FEFO, all or nothing); POs,
  receiving, stock-in, transfers, counts, re-order refuse it (HAMPER_NOT_STOCKED). `GET
  /api/inventory/v1/hampers/{id}/availability` = lowest component. Invoice batches carry the component
  `medicine_id`; returns are whole hampers only (no part returns).
- **Suspend / templates / sale orders (sales, from S7):** `/carts/suspend` → `PP1-SP-…` (no reservation),
  `/carts/{id}/resume` re-prices + checks stock (`changes[]`), job expires yesterday's. `/sale-templates`
  (+ `/load`). Sale orders `PP1-SO-…`: quote → `/confirm` (ordered; optional FEFO reservation `ref_type
  sale_order`, 1–14 days, and a deposit = customers `deposits`, KHR at the branch rate) → `/invoice` (lines of
  the order, normal saga; the order's reservation is split onto the invoice via inventory `/reservations/{id}/
  split`; payment method `deposit`) → partly_fulfilled / fulfilled; cancel / close release the reservation and
  settle the deposit per branch setting `order_deposit_on_cancel` (keep_as_credit | refund | forfeit; forfeit
  only manager / owner). Invoice cancel gives the qty and deposit back to the order. PDF `{"type":
  "sale_order","sale_order_id"}`.
- **Commission (sales, from S7):** rules (`commission.manage`) % of net or USD per base unit; scope medicine >
  category > brand > all, a staff override first; earned by the user who completed the sale on the line's
  USD net; returns / cancels → negative lines. Periods per branch + month open → closed → paid; locked
  periods get nothing new (reversals go to the next open period). `/commission/report` (+ `/{staff_id}`
  drill-down): `commission.view_own` = self only, `commission.manage` = the branch.

- **Outbox replay (from S8):** outbox rows are never deleted (the relay only sets `published_at`).
  `create_service_app` adds `GET /internal/v1/outbox?after_seq=&limit=` to every service with an outbox (service
  token, only the callers in `OUTBOX_REPLAY_CALLERS`, default `reports`; never routed by Traefik).
- **Reports (from S8):** read models built ONLY from events (`reports_service/services/events.py`): idempotent upserts by
  source id, versioned snapshots ignore older versions, same handlers for live events and the backfill (same message id =
  outbox id, so they never double count). Days in Asia/Phnom_Penh: a sale on the day it completed; a cancel removes it
  from that day; a return counts on its own day. KHR = each invoice's own KHR total. `sales_daily` rollup rebuilt per
  branch + day after each invoice event. Reports registry `services/reports.py` (`@report(key, title, *permissions)`,
  "a|b" = either); every report: `GET /api/reports/v1/<key>` with date_from/date_to/branch/staff/category/supplier/
  customer/medicine, `?format=csv|xlsx|pdf` (10 a minute per user, User Log `report.exported`, ≤ 100 000 rows, PDF ≤ 5 000
  via document `/internal/v1/render/table`, else EXPORT_TOO_LARGE). Columns marked `secret` ("cost": finance.cost_profit;
  "purchase": purchasing.order/pay/finance.cost_profit) are dropped from columns, rows AND summary before any format
  (`common.drop_hidden`). Branch scope: the user's branches, owner all, another branch → BRANCH_FORBIDDEN. Dashboard
  `GET /dashboard` (today / yesterday / same weekday last week). Rx report needs prescriptions.view and has no patient.
  Re-order stays in inventory. New events for it: `commission.recorded`, `commission_period.updated`, `shrinkage.*`,
  `count.submitted` (+ lines on approved), `user.pin_locked`, `register.discrepancy_resolved`; goods.received has
  `total` + `due_on`; credit/payment/deposit events carry `occurred_at`; invoice returns carry `created_at`.
- **Telegram (notification, from S8):** chats per branch + "owner" (`PUT /chats/{target}`, `notifications.manage`;
  managers only their branches), `messages` outbox with a unique `dedupe_key` (a job run twice adds nothing; a sent summary
  is never changed), status queued → sent | failed | skipped (no token / no chat), backoff 30 s × 2ⁿ ≤ 1 h, Telegram's
  429 retry_after, 8 tries; other 4xx fail at once. Texts only from allow-listed fields (`services/texts.py`): never
  patient, Rx, doctor or customer data; cost and profit only in the owner's chat. Alerts at once: register discrepancy /
  chain broken, account or PIN lockout, below-cost sale, large manual discount (alert settings, 20 % / 10 USD); low stock
  and near expiry in the 07:30 digest. `POST /test` (503 TELEGRAM_NOT_CONFIGURED without a token).

- **Cart preview (sales, from S8b):** `services/checks.py` is step 1 of the saga: `run_checks(mode="raise")` (the
  saga; raises the first problem, consumes the PIN / approval tokens) and `mode="collect"` (the preview; every finding,
  nothing consumed). `POST /carts/preview` then asks read-only twins: prescription `/internal/v1/rx/check` (same code as
  check-and-hold, `hold=False`), inventory `/internal/v1/reservations/plan` (same allocator, `write=False`, no locks;
  → BELOW_COST from the batches' cost), customers `GET /internal/v1/customers/{id}/credit`. Findings: hard_stop /
  requirement (PIN, patient ID document, discount approval: reported, never consumed) / warning (resolved by the
  override) / info (NEAR_EXPIRY), English + Khmer; `can_post`. Writes nothing. `POST /carts/price` is deprecated
  (remove in S9). Catalog `POST /promotions/preview` sends a draft promotion to sales `/internal/v1/carts/preview`
  (same pricing) → the preview + `conflicts`.
- **OpenAPI errors (from S8b):** every 4xx/5xx is `ErrorOut` (`{code, message, details}`) with the exact codes per status:
  found by `pharmacy_shared.openapi_errors` (AST of the endpoint and what it calls, by name, in its package and in
  pharmacy_shared: `AppError(ErrorCode.X, …, status_code=N)` and helpers called the same way), plus
  `openapi_extra=errors(...)` for codes passed through from other services (`SALE_PASSTHROUGH`), plus the shared
  401/403/422/429/503 on protected routes. `shared/tests/test_openapi_quality.py` fails on untyped 2xx, non-ErrorOut
  errors, or a code raised in an endpoint but not listed. Reports: one model per report, rows typed from its `Col(...)`
  list. `make openapi` writes `openapi/*.json` (git-ignored).
- **KHQR (sales, from S8b):** `POST /payments/khqr` (pos.sell, Idempotency-Key) → EMV-KHQR string (tag 29 individual /
  30 merchant, CRC16) of the branch's Bakong account (branch setting `khqr`) or the shared one (`KHQR_*`); USD or KHR
  (whole hundreds). `GET /payments/khqr/{id}` asks the provider (2 s Redis cache); a task polls pending ones every 5 s.
  A sale pays with `{method: "KHQR", khqr_id, amount, currency}`: paid, same branch / amount / currency, unused
  (`invoice_payments.khqr_id` unique, row locked) → `used`. A failed or cancelled sale → `needs_refund` +
  `khqr.needs_refund` (Telegram alert); refunds by hand. `KHQR_PROVIDER=fake|bakong` (production refuses fake; fake:
  `/internal/v1/khqr/fake/{id}/pay`, and `POST /payments/khqr/{id}/fake-pay` for the owner outside production).
- **ABA PayWay (KHQR, after S8b):** `KHQR_PROVIDER=payway` – `sales_service/services/payway.py` (QR API, check-transaction-2,
  close-transaction, refund; HMAC-SHA512 hashes; refund `merchant_auth` RSA PKCS#1 v1.5 in 117-byte chunks with ABA's public
  key; `status.code` compared as text, "0" = "00"; a base URL with a path is cut before "/api/"). Settings PAYWAY_BASE_URL,
  PAYWAY_MERCHANT_ID, PAYWAY_API_KEY (ABA's "Public Key" = the HMAC secret), PAYWAY_CALLBACK_URL; the RSA files are compose
  secrets (`/run/secrets/payway_rsa_*.pem`, host files named by PAYWAY_RSA_*_KEY_SOURCE, default `infra/payway/not-set.pem`
  so `up` works without them); the private key is mounted but never read. Start-up names a missing setting, never a value.
  Never print, log or commit their values (`scripts/payway_setup.py` moves them from a credentials file into .env/secrets
  without printing). Public callback `POST /payments/payway/callback` (router `sales-payway-callback`) only triggers a
  check. Paid = status 0 AND amount + currency match, else `review`; cancel `POST /payments/khqr/{id}/cancel`; late payment
  on an expired/cancelled QR → `needs_refund`. Refunds: `khqr_refunds` once per payment + source (failed sale, invoice
  cancel, return `refund_method: "khqr"`, late payment, review) → `POST /payments/khqr/refunds/{id}/refund` (`sales.khqr_refund`
  = owner + branch manager, own branch, PIN action `sales.khqr_refund`, never automatic; a lost answer stays `requested`
  and the next try asks PayWay first; Bakong: `by_hand`). Daily check 00:40 → `khqr_reconcile_issues` + Telegram.
  Web: Sales → KHQR Refunds (`/sales/khqr-refunds`), the invoice offers a due refund. `make payway-check [QR=1]` (QR=1:
  sandbox only, a 100 KHR QR); `python -m sales_service.cli khqr-reconcile [--date]`. Riel is compared in riel
  (money.settle): what USD payments leave is due as riel at the invoice's rate, rounded to 100 (all-riel = total_khr);
  riel = due settles exactly and `payment_rounding_khr` keeps the difference; a riel KHQR/ABA/card may not exceed it.
- **Supplier returns (purchasing, from S8b):** `PP1-SRN-…` draft → credited | refunded, or cancelled (only a draft,
  reason); `purchasing.return`. Submit (Idempotency-Key): inventory `/internal/v1/movements/supplier-return` (movement
  type `supplier_return`, once per line, the batch must be the supplier's; controlled: PIN + witness, action
  `purchasing.supplier_return`, register entry `supplier_return`); value = the batches' cost. Every return is a
  `supplier_credit`: settle `credit` applies it to the branch's open bills (oldest first) and what is left to the next
  bills received; settle `refund` (owner / branch manager) records a supplier refund `PP1-SRF-…` (money in). Statement
  shows `return` / `refund`. Events `supplier_return.*`, `supplier_credit.updated` (allocations), `supplier_refund.created`.
  PDF `{"type":"supplier_return"}` (values only with purchase-price permissions).
- **Recalls (inventory, from S8b):** `RC-2026-…` (one counter), `inventory.recall`: the owner recalls lots everywhere
  (batch status `recalled` + stock rows blocked), a branch manager in their branches (stock rows only, `stock.recall_id`).
  Blocked stock is never reserved, picked or counted as sellable (override → BATCH_BLOCKED). `batch.recalled` per branch
  (Telegram). Per line: return (a draft supplier return, once) or destroy (shrinkage `recalled`). Close when nothing is
  on hand; lift (owner, reason) restores. Affected sales: `GET /api/sales/v1/invoices/by-batches` (patient only with
  prescriptions.view).
- **Small S8b additions:** controlled `GET /entries/{id}` (neighbours, hash_valid, corrections); catalog
  `pack_unit_price_history` (before-flush listener: every path; `GET /medicines/{id}/price-history`; `python -m
  catalog_service.cli price-history` fills it once from the outbox); `GET /exchange-rates/{branch}` takes from / to /
  page / size; document `customer_statement` (customers `/internal/v1/customers/{id}/statement`) and receipts / A4 in
  `lang` km | en (branch setting `receipt_lang`, default km); auth 2FA backup codes (10, argon2, used once, `/2fa/enable`
  shows them, `POST /2fa/backup-codes` with the password regenerates, `/login/2fa` takes `backup_code`, `/me`
  `backup_codes_left`) and sessions (= refresh-token families; the access token carries `sid`; `GET /me/sessions`,
  `POST /me/sessions/{id}/revoke` ends it at once via `auth:revoked_sid:{sid}`).

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
- [x] S4 Prescriptions – patients, doctors, Rx, dispensing, allergy warnings, labels
- [x] S5 Controlled + counts – register, PIN + witness, stock take, shrinkage
- [x] S6 Branches – transfer requests, transfers, purchase requests, re-order
- [x] S7 Sales extras – sale order, suspend, templates, promotions, hampers, commission
- [x] S8 Reports – dashboard, all reports, Telegram 20:00
- [x] S8b API gaps – cart preview, OpenAPI error schemas, KHQR, supplier returns, recalls, small additions
- [ ] S9 Hardening – performance, security, offline POS, UAT fixes; per-service tokens for
  internal calls (today one shared SERVICE_TOKEN: a service could call any other's /internal);
  SeaweedFS: lock down its IAM gRPC port and use a non-admin S3 identity per service; register table owned by a
  NOLOGIN role (today: trigger + REVOKE on the service user, which still owns the table)
  Traefik's Docker provider restricted to this compose project (constraint on the `com.docker.compose.project`
  label) so other stacks' containers never leak into routing (in S8 a second stack on the same host was load-balanced
  into; check the constraint really filters – on the throwaway stack a Label constraint alone did not); remove the
  deprecated `POST /api/sales/v1/carts/price` (replaced by `/carts/preview` in S8b); the intermittent "rejected SSL
  upgrade" test DB errors (seen in catalog and sales tests): set `ssl=disable` explicitly for local and test DB
  connections (SSL stays configurable for production) and make the test DB fixture retry its first connect.
- [ ] S10 AI – DeepSeek phase A

Front end (`web/`, plan: `docs/plans/frontend-plan.md`, design handoff: `docs/design/`, how it works: `web/README.md`).
Decided: F-sprints hide designed details the API lacks (choice A alternative); refresh token in the httpOnly cookie
(B); offline POS needs S9 backend work first (C); e2e against `BASE_URL` (D); openapi-typescript + openapi-fetch (E);
dev-only `/dev/design` (F). The `web` service is Traefik `PathPrefix(/)` priority 1 (static nginx, its own CSP).
POS (`web/src/features/pos`): the cart holds only choices; prices, totals and checks come from `/carts/preview`
(debounced). `can_post` ignores unresolved *requirements* (PIN, patient ID, approval), so Pay also waits for those.
Rx warnings come back under one code for the cart: actions follow `details.warnings[].kind` (allergy → override
reason, duplicate_therapy → acknowledge). The checkout Idempotency-Key follows the exact request body (a retry
replays; any change makes a new key). The scan box frees itself on Enter (scanners send the next code at once).
- [x] F0 Design system + app shell + auth + shared states
- [x] F1 POS – all 9 flows on `/carts/preview`, POS lite, POS back office
- [x] F2 Prescriptions + controlled drugs
- [x] F3 Warehouse + stock (incl. mobile stock count)
- [x] F4 Purchase + transfer (incl. mobile receiving)
- [x] F5 Contacts
- [x] F6 Dashboard + reports
- [x] F7 User management + settings
- [ ] F8 Print layouts, offline POS sync, polish, accessibility pass
