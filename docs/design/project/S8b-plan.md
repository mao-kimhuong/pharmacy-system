# Sprint S8b: API gaps (plan, waiting for "go")

Based on CLAUDE.md, docs/spec.md and the current code (sales `sale_saga.py`, `cart.py`, `pricing.py`).

## 0. Ground rules applied
- Each service keeps its own DB. Cross-service checks go through `/internal/v1/...` with `InternalClient`.
- Inputs use `extra="forbid"`. Errors use `AppError(ErrorCode.X)`. Logic lives in `services/`, not routers.
- Every rule gets a pytest test.
- Money and stock writes take an `Idempotency-Key`, write a User Log entry and add an outbox event in the same transaction.
- Nothing is deleted. Cancels and blocks need a reason.
- Cost fields are dropped with `visibility.drop_fields` for users without `finance.cost_profit`.

## 1. Cart preview: one check engine for preview and posting
**Refactor first (no behaviour change):** move every pre-reservation rule out of `sale_saga._plan_lines`, `_price`, `_below_cost` and `cart.approve_discount` into `sales_service/services/checks.py`.
- `run_checks(session, actor, clients, cart, mode)` returns `CheckResult(lines, findings)`.
- `mode="collect"` is used by preview: it gathers every finding.
- `mode="raise"` is used by the saga: it raises the first blocking finding as the same `AppError` it raises today.
- The saga calls `run_checks(..., "raise")`. Existing saga tests must pass unchanged; this proves the refactor kept behaviour.

**Finding** = `{code, severity: "hard_stop" | "warning", line_no, message_en, message_km, details}`.
- Hard stops: RX_REQUIRED, PHARMACIST_REQUIRED, RX_EXPIRED, RX_QUANTITY_EXCEEDED, PRESCRIPTION_STATE, OUT_OF_STOCK, BATCH_EXPIRED, BATCH_BLOCKED, BELOW_COST (unless `sales.below_cost`), DISCOUNT_APPROVAL_REQUIRED, HAMPER_NOT_STOCKED, CREDIT_LIMIT_EXCEEDED, CONTROLLED_NOT_AVAILABLE.
- Warnings: ALLERGY_WARNING and DUPLICATE_THERAPY_WARNING. They become "resolved" when the line already carries `allergy_override_reason` / `acknowledge_warnings`. Near-expiry is info only.

**Read-only twins of the side-effecting calls**, with the same function body and a `dry_run` flag:
- prescription `POST /internal/v1/rx/check` uses the same code as `check-and-hold` with `hold=False`. No row locks, nothing held.
- inventory `POST /internal/v1/reservations/plan` uses the same FEFO allocator as `/reservations` with `write=False`: plain SELECT, no `FOR UPDATE`. It returns batches per line with expiry and cost_per_base, used for the BELOW_COST check.
- customers: `GET /internal/v1/customers/{id}/credit` returns balance and limit, for the CREDIT_LIMIT_EXCEEDED check.

**Endpoint `POST /api/sales/v1/carts/preview`** (`pos.sell`, branch check, no Idempotency-Key, no outbox).
- Request: `branch_id`, `customer_id?`, `lines[]` (LineIn as today), `payments?` (only to check credit).
- Response `CartPreviewOut`:
  - `lines[]`:
    - `line_no`, `name`, `pack_unit`, `qty`, `unit_price`;
    - `promotions[]` (`id`, `name_en`, `name_km`, `discount`), `promo_discount`, `manual_discount`, `net`;
    - `batches[]` (`lot`, `expiry`, `qty`; cost only with permission);
    - `warnings[]`, `hard_stops[]`.
  - Totals: `subtotal`, `discount`, `total`, `khr_per_usd`, `total_khr` (rounded to 100 riel with `money.py`), `rounding_khr`.
  - `can_post`: true when there are no hard stops and every warning is resolved.
- Rate limited like other POS reads.
- `POST /carts/price` stays as is (the web is not built yet). It is marked deprecated in OpenAPI.

**Promotion preview:** `POST /api/catalog/v1/promotions/preview` (`catalog.promotions`) takes a draft `PromotionCreate` and a sample cart. Catalog has no prices of its own, so it forwards to sales `POST /internal/v1/carts/preview` with `draft_promotion`. Sales runs the same `pricing.py` with the draft added to the active set (exclusive vs stackable rules unchanged). The response is the preview above plus `conflicts[]`: other promotions on the same items and which one wins.

**Tests:**
- Table-driven: for each code, the same cart gives the same code from preview and from `POST /invoices`.
- Preview writes nothing: row counts are the same before and after, and no `outbox`/`promotion_uses` rows.
- Preview with a warning plus its override → `can_post` true, and posting succeeds.
- KHR total matches `money.py`.
- Draft promotion conflicts.

## 2. OpenAPI quality
- `pharmacy_shared.errors`: add `ErrorOut {error: {code, message, details}}` (the format we already send) and a helper `errors(*codes)`. The helper builds the `responses=` dict, one entry per status, with `code` as an enum of exactly those codes.
- Every route declares its codes (`responses=errors(ErrorCode.NOT_FOUND, ...)`). Shared ones (401, 403 FORBIDDEN / MFA_SETUP_REQUIRED, 422 VALIDATION_ERROR, 429, 503) are added by `create_service_app` to every protected route.
- Reports and dashboard: one Pydantic `response_model` per endpoint (rows + totals + `cost_hidden` flag), 32 endpoints. Cost fields are `Optional` and absent when hidden.
- Remaining untyped `dict` responses in other services get models too.
- **Test** `shared/tests/test_openapi_quality.py`, run per service:
  - load the app;
  - fail if any 2xx response schema is missing or is `{type: object, additionalProperties: true}` without properties;
  - fail if any 4xx/5xx is missing `ErrorOut`;
  - fail if any code used in `raise AppError(ErrorCode.X)` in a route's module is missing from that route's enum (static check by AST, best effort).
- `openapi/*.json` regenerated with `make openapi` (new target).

## 3. KHQR (Bakong)
- `sales_service/services/khqr/`:
  - `Provider` protocol: `create(amount, currency, bill_no, expires_in) -> {qr_string, md5, expires_at}` and `status(md5) -> paid | pending | expired, paid_amount, bank_ref, paid_at`.
  - `FakeProvider`: deterministic QR, and `mark_paid()` for tests and dev; dev also gets `POST /internal/v1/khqr/fake/{id}/pay`.
  - `BakongProvider`: builds the EMV-KHQR string (merchant info tag 29/30, CRC16) and checks with the Bakong Open API `check_transaction_by_md5`. Selected by `KHQR_PROVIDER=fake|bakong`; production refuses `fake`.
- Table `khqr_payments` (`branch_id`, `invoice_id?`, `cart_ref`, `amount`, `currency`, `md5`, `qr_string`, `status`, `expires_at`, `paid_at`, `bank_ref`, `created_by`).
- `POST /api/sales/v1/payments/khqr` (`pos.sell`, Idempotency-Key) returns `{id, qr_string, amount, currency, expires_at}`. The QR image is drawn by the web from the string, or optionally as an SVG via segno.
- `GET /api/sales/v1/payments/khqr/{id}` gets the status: it polls the provider (rate-limited, cached 2 s in Redis).
- When paid, `POST /invoices` accepts `payments[{method:"KHQR", khqr_id}]`. The saga checks status = paid and the amount, and links it once (unique `khqr_id` on payments). A background task polls pending rows every 5 s until they expire.
- Paid but the sale failed: the row is marked `needs_refund` and an alert goes out; no automatic refund.
- Tests: fake create → pending → paid → invoice posts. Wrong amount, expired, double use and provider down all return errors.
- **Needed for real Bakong:**
  - a Bakong account ID for each branch (or one per merchant), e.g. `pharmacy@aclb`, plus the merchant name and city as registered;
  - the merchant category code;
  - a Bakong Open API token (from api-bakong.nbc.gov.kh; it expires and must be renewed);
  - a choice between individual and merchant KHQR (merchant needs the acquiring bank's merchant ID);
  - whether to accept USD, KHR or both;
  - an outbound HTTPS allowance to the NBC API from the server.

## 4. Supplier returns and recalls
**Supplier return (purchasing + inventory + controlled):**
- Purchasing tables `supplier_returns` and lines (`PP1-SRN-…`): draft → submitted (stock out) → credited | cancelled (reason, only while draft). Lines name a batch and qty_base, and optionally a receipt line. Reason: damaged / expired / recalled / wrong_item / overstock.
- Submit (`purchasing.return`, Idempotency-Key):
  - inventory `/internal/v1/movements/supplier-return` writes `supplier_return` movements, one per line;
  - controlled lines need PIN + witness (action `purchasing.supplier_return`); the movement meta goes to the register as before;
  - a credit note is created against the supplier balance, so the oldest open bill drops. It shows in the statement and in Payables aging.
- Events `supplier_return.*`. The document type `supplier_return` is a PDF.

**Recall (inventory):**
- Tables `recalls` (`PP-RC-…`, medicine_id, lot numbers[], reason, source, started_by) and `recall_lines` (branch, batch, qty at start, action, status).
- `POST /api/inventory/v1/recalls` (`inventory.recall`, owner/manager, reason, Idempotency-Key):
  - every matching batch in every branch → `recalled` at once (not sellable; reservations refuse with BATCH_BLOCKED);
  - User Log entry, `batch.recalled` events, Telegram alert.
- `GET /recalls`, `GET /recalls/{id}`: stock per branch per batch, in transit, and on open transfers.
- Affected invoices: sales gets `/internal/v1/invoices/by-batches`, which returns invoice, date, customer and patient (patient only with `prescriptions.view`).
- Actions per line:
  - return to supplier, which creates the supplier return above from the recall;
  - or destroy, which reuses shrinkage reason `recalled` (controlled: PIN + manager/owner witness).
- `POST /recalls/{id}/close` once nothing is left. Lifting a recall (`/recalls/{id}/lift`, reason, owner) restores the old status.

## 5. Small additions
- **Register entry:** controlled `GET /api/controlled/v1/entries/{entry_id}` → entry, chain neighbours (prev/next id), `hash_valid`, witness, source movement and document ref.
- **Price history:** catalog keeps `pack_unit_price_history` (written in the same transaction as each sell_price change; back-filled once from the User Log). `GET /api/catalog/v1/medicines/{id}/price-history?pack_unit_id=&from=&to=`. Cost comes from inventory receipts and is merged in reports only, since catalog has no cost.
- **Exchange-rate history:** `GET /api/sales/v1/exchange-rates/{branch_id}/history?from=&to=` (paged, `RateOut` rows). The rows already exist; only the query and route are new.
- **Customer statement PDF:** document type `customer_statement` (`customer_id`, `date_from`, `date_to`, `lang`). Document reads customers `/internal/v1/customers/{id}/statement` and renders with WeasyPrint, Noto Khmer. Permission `customers.view` + branch.
- **lang on receipt and invoice:** `lang: "km" | "en"` on `InvoiceRender`. The default comes from branch setting `receipt_lang` (new, `km`). The templates get a small string table; numbers and SKUs are unchanged.
- **2FA backup codes:**
  - 10 codes of 10 characters from an unambiguous alphabet, stored as argon2 hashes (`mfa_backup_codes`: `user_id`, `hash`, `used_at`);
  - shown once by `/2fa/enable` and by `POST /api/auth/v1/2fa/backup-codes` (needs `password`; regenerating invalidates the old set);
  - `POST /login/2fa` accepts `backup_code`, which is consumed atomically;
  - User Log `user.backup_code_used` and `user.backup_codes_regenerated`; `/me` shows `backup_codes_left`;
  - same rate limit and lockout as TOTP.
- **Sessions:**
  - sessions are already the refresh-token rows; add `user_agent`, `ip`, `last_used_at`, `created_at` (migration);
  - `GET /api/auth/v1/me/sessions` (marks `current`) and `POST /api/auth/v1/me/sessions/{id}/revoke` (own sessions only; revoking current = logout);
  - User Log entry.
- Also documented: `details.locked_until` on the login lockout error (it is already sent; this adds it to the schema and a test).

## 6. Migrations
- sales: `khqr_payments`, `payments.khqr_id`.
- inventory: `recalls`, `recall_lines`, movement type `supplier_return`.
- purchasing: `supplier_returns`, lines, credit notes.
- catalog: `pack_unit_price_history`.
- auth: `mfa_backup_codes`, session columns.
- branch: setting `receipt_lang`.
- New permissions are added to `permissions.py` CATALOG and default grants: `purchasing.return`, `inventory.recall`, `sales.khqr`.

## 7. Done
- New tests in each service (listed above), plus `test_openapi_quality`.
- `scripts/smoke.py` adds an optional step S8b:
  - preview a cart with an Rx-only line as cashier → PHARMACIST_REQUIRED hard stop; as a pharmacist with Rx → can_post;
  - a fake KHQR payment → mark paid → invoice;
  - recall a lot → sale gets BATCH_BLOCKED;
  - a supplier return reduces the supplier balance;
  - a customer statement PDF in km and en;
  - backup code login;
  - list and revoke a session.
- `make test` and `make test-docker` pass; `openapi/*.json` regenerated.
- CLAUDE.md "How things work" gets S8b notes, and Progress adds "S8b API gaps".
- Commit `S8b: API gaps`, then stop with the verify steps.

## Open questions (answer with "go" or adjust)
1. KHQR: one Bakong account for all branches, or one per branch? Accept USD, KHR or both?
2. Recall: who may start one: owner only, or also managers for their own branches?
3. Supplier return of an already-paid bill: a credit note on the account (default), or a cash refund recorded as a supplier payment reversal?
4. Should `carts/price` be removed once the web uses `carts/preview`, or kept?
