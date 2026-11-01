# Sprint S8b: API gaps (plan, waiting for "go")

Based on CLAUDE.md, docs/spec.md and the code as of S8 (`cb8a03f`). The original plan with the
owner's four answers and the corrections found against the code (marked **[fixed]**).

## Found while building (S8b done)
- Sessions: `refresh_tokens` already had `ip`, `user_agent`, `created_at` (no migration); the access token gained a
  `sid` claim (its refresh family) so `current` can be marked and a revoked session's access token refused at once.
- The controlled register already had the entry type `supplier_return`: only the movement → entry mapping was added.
- A recall by a branch manager cannot use the batch status (batches are shared by all branches): the stock rows of
  their branches are blocked (`stock.recall_id`); the owner's recall also sets the batch status.
- Every supplier return creates a supplier credit; "refund" settles it with a refund receipt instead of applying it
  to bills (so the statement shows return and refund).
- The fake KHQR provider also has an owner-only `POST /payments/khqr/{id}/fake-pay` outside production, so the
  smoke and people trying the till can pay a QR through Traefik.
- Receipts and A4 invoices: the labels were mixed English · Khmer; now one language (`lang`, branch default km).

## Answers (owner)
1. KHQR: Bakong account settings per branch, defaulting to one shared account; accept USD and KHR.
2. Recall: owner for all branches; branch_manager for their own branches only.
3. Return on a paid bill: credit on the supplier's account by default; owner/manager may choose a
   cash refund, recorded as a supplier refund receipt.
4. Keep `POST /carts/price`, deprecated in OpenAPI; CLAUDE.md notes it is removed in S9.

## 0. Ground rules
Own DB per service (cross-service via `/internal/v1` + `InternalClient`); `extra="forbid"`;
`AppError(ErrorCode.X)`; logic in `services/`; a pytest per rule; money/stock writes:
Idempotency-Key + User Log + outbox event in one transaction; nothing deleted (cancel/block with a
reason); cost hidden with `drop_fields` without `finance.cost_profit`.

## 1. Cart preview: one check engine for preview and posting
- Refactor first, no behaviour change: the rules in `sale_saga._plan_lines`, `_price`,
  `_below_cost` and `cart.approve_discount` move to `sales_service/services/checks.py`:
  `run_checks(session, actor, clients, cart, mode)` → `CheckResult(lines, findings)`; `mode="collect"`
  (preview) gathers all, `mode="raise"` (saga) raises the first blocking one as today's AppError. All
  existing sales tests pass unchanged.
- Finding = `{code, severity: hard_stop | warning | requirement, line_no, message_en, message_km, details}`.
  - Hard stops: RX_REQUIRED, PHARMACIST_REQUIRED, RX_EXPIRED, RX_QUANTITY_EXCEEDED, PRESCRIPTION_STATE,
    OUT_OF_STOCK, BATCH_EXPIRED, BATCH_BLOCKED, BELOW_COST (unless `sales.below_cost`),
    DISCOUNT_APPROVAL_REQUIRED, CREDIT_LIMIT_EXCEEDED, CUSTOMER_REQUIRED, EXCHANGE_RATE_MISSING,
    UNKNOWN_MEDICINE. **[fixed]** removed HAMPER_NOT_STOCKED (hampers are sellable; that code is only
    for POs, stock-in, transfers, counts) and CONTROLLED_NOT_AVAILABLE (no longer raised since S5);
    added CUSTOMER_REQUIRED, EXCHANGE_RATE_MISSING, UNKNOWN_MEDICINE (raised by today's saga).
  - **[fixed]** Requirements (new severity): a controlled line needs `patient_id_document` and the
    invoice a `pin_token` (controlled.dispense); a manual discount above the cap needs
    `discount_approval_token`. Preview reports them and never consumes a PIN or witness token
    (consuming is a side effect); `can_post` assumes they will be supplied.
  - Warnings: ALLERGY_WARNING, DUPLICATE_THERAPY_WARNING, resolved when the line carries
    `allergy_override_reason` (pharmacist + `prescriptions.override_warning`) / `acknowledge_warnings`.
    Near-expiry batch: info only.
- Read-only twins (same function body, a flag):
  - prescription `POST /internal/v1/rx/check` = `check-and-hold` with `hold=False` (no locks, nothing held);
  - inventory `POST /internal/v1/reservations/plan` = the `reserve()` allocator with `write=False`
    (`_fefo_rows(lock=False)`, hampers expanded, nothing written): batches per line with expiry and
    cost_per_base (for BELOW_COST);
  - customers `GET /internal/v1/customers/{id}/credit` → balance, limit, active (**[fixed]** new;
    today only `/credit/charge` checks it).
- `POST /api/sales/v1/carts/preview` (`pos.sell`, branch check, no Idempotency-Key, no outbox):
  request `branch_id`, `customer_id?`, `lines[]` (LineIn), `payments?`, `pin_token?` ignored.
  Response `CartPreviewOut`: `lines[]` (line_no, name, pack_unit, qty, unit_price, promotions[] (id,
  name_en, name_km, discount), promo_discount, manual_discount, net, batches[] (lot, expiry, qty;
  cost only with permission), warnings[], hard_stops[], requirements[]); subtotal, discount, total,
  khr_per_usd, total_khr (`money.round_riel`), rounding_khr; `can_post`.
- `POST /carts/price` kept, `deprecated=True`; CLAUDE.md: remove in S9.
- Promotion preview: catalog `POST /api/catalog/v1/promotions/preview` (`catalog.promotions`): draft
  `PromotionCreate` + sample cart → sales `POST /internal/v1/carts/preview` with `draft_promotion`
  (same `pricing.py`, draft added to the active set) → the preview plus `conflicts[]` (other
  promotions on the same items, which one wins).
- Tests: the same cart gives the same code from preview and `POST /invoices` (table-driven); preview
  writes nothing (row counts, no outbox / promotion_uses / holds / reservations); warning + override
  → can_post and posting succeeds; KHR total = money.py; draft promotion conflicts.

## 2. OpenAPI quality
- **[fixed]** The error body we send is flat: `{code, message, details}` (`errors.error_body`), not
  `{error: {...}}`. `ErrorOut` describes that shape; `errors(*codes)` builds `responses=` (one entry per
  status, `code` an enum of exactly those codes).
- Every route declares its codes; shared ones (401, 403 FORBIDDEN / MFA_SETUP_REQUIRED /
  BRANCH_FORBIDDEN, 422 VALIDATION_ERROR, 429 RATE_LIMITED, 503 TEMPORARILY_UNAVAILABLE) are added by
  `create_service_app` to every protected route.
- Reports: **[fixed]** 30 endpoints (28 reports + dashboard + catalog), generated from the registry:
  one response model per report (columns as typed rows, `summary`, `cost_hidden`); cost fields
  optional and absent when hidden. CSV/XLSX/PDF documented as alternative content types.
- Remaining `dict` responses in other services get models.
- `shared/tests/test_openapi_quality.py` runs per service app: no 2xx without a schema or with an
  untyped free-form object; every 4xx/5xx uses `ErrorOut`; AST check (best effort) that codes raised
  in a route's module are in its enum.
- `make openapi` (new target) regenerates `openapi/*.json` (**[fixed]** the folder exists with older
  files; they are refreshed for all 14 services).

## 3. KHQR (Bakong)
- `sales_service/services/khqr/`: `Provider` protocol (`create(amount, currency, bill_no, expires_in)
  → {qr_string, md5, expires_at}`, `status(md5) → paid|pending|expired, paid_amount, bank_ref, paid_at`);
  `FakeProvider` (deterministic, `mark_paid()`; dev/test `POST /internal/v1/khqr/fake/{id}/pay`);
  `BakongProvider` (EMV-KHQR string, tags 29/30, CRC16; Bakong Open API `check_transaction_by_md5`).
  `KHQR_PROVIDER=fake|bakong`; production refuses `fake`.
- **[fixed, answer 1]** Account settings per branch: branch setting `khqr` (account id, merchant name,
  city, merchant id, currencies) in the branch service, copied to sales via `branch.settings_updated`;
  empty → the shared account from sales settings (`KHQR_ACCOUNT_ID`, …). USD and KHR both accepted
  (KHR amounts in whole riel, rate = the branch rate at creation).
- Table `khqr_payments` (branch_id, invoice_id?, cart_ref, amount, currency, md5, qr_string, status
  pending|paid|expired|used|needs_refund, expires_at, paid_at, bank_ref, created_by).
- `POST /api/sales/v1/payments/khqr` (`pos.sell`, Idempotency-Key) → {id, qr_string, amount,
  currency, expires_at} (+ optional SVG via segno); `GET /payments/khqr/{id}` polls the provider
  (cached 2 s in Redis).
- `POST /invoices` accepts `payments[{method: "KHQR", khqr_id}]`: the saga checks paid + amount and
  links it once (**[fixed]** unique `khqr_id` on `invoice_payments`, the real table name). Background
  task polls pending rows every 5 s until they expire.
- Paid but the sale failed → `needs_refund` + Telegram alert (notification listens to
  `khqr.needs_refund`); no automatic refund.
- **[fixed]** No new permission `sales.khqr` (creating a QR is part of `pos.sell`).
- Tests: fake create → pending → paid → invoice; wrong amount, expired, used twice, provider down.
- Needed for real Bakong: account id(s), merchant name and city as registered, merchant category
  code, an Open API token (expires, renewed), individual vs merchant KHQR (merchant needs the
  acquiring bank's merchant id), outbound HTTPS to the NBC API.

## 4. Supplier returns and recalls
**Supplier return (purchasing + inventory + controlled):**
- `supplier_returns` + lines (`PP1-SRN-…`): draft → submitted (stock out) → credited | refunded, or
  cancelled (reason, only draft). Lines: batch, qty_base, optional receipt line; reason damaged /
  expired / recalled / wrong_item / overstock.
- Submit (`purchasing.return`, Idempotency-Key): inventory `/internal/v1/movements/supplier-return`
  → **[fixed]** new movement type `supplier_return` (added to `MOVEMENT_TYPES` and
  `ONCE_PER_SOURCE`); controlled lines need PIN + witness (action `purchasing.supplier_return`), and
  **[fixed]** the controlled service maps `supplier_return` → register entry type `return_to_supplier`
  (today's mapping in `controlled_service/services/events.py` would skip it).
- **[fixed, answer 3]** Money: by default a supplier credit (`supplier_credits`, allocated to the
  oldest open bills like a payment, so payables drop); owner/manager may choose `refund` instead → a
  supplier refund receipt (`supplier_refunds`: method, amount, reference), money in. Both in the
  statement, events `supplier_return.*` / `supplier_credit.*` / `supplier_refund.*`, and in the reports
  (payables aging, Transaction Payment, a new "Supplier returns" report).
- Document type `supplier_return` (PDF).

**Recall (inventory):**
- `recalls` (**[fixed]** number `RC-2026-000001` from one global counter: a recall spans branches,
  `next_number` needs a branch code) and `recall_lines` (branch, batch, qty at start, action, status).
- `POST /api/inventory/v1/recalls` (`inventory.recall`, reason, Idempotency-Key): **[fixed, answer 2]**
  owner → every matching batch in every branch; branch_manager → only batches in their branches.
  Matching batches → status `recalled` (already a batch status; reservations refuse with
  BATCH_BLOCKED). User Log, `batch.recalled` events, Telegram alert.
- `GET /recalls`, `GET /recalls/{id}`: stock per branch and batch, in transit, on open transfers.
- **[fixed]** Affected invoices: a public sales endpoint `GET /api/sales/v1/invoices/by-batches?batch_ids=`
  (`sales.view`, own branches; patient fields only with `prescriptions.view`), not an inventory call
  into sales: the web joins the two.
- Actions per line: return to supplier (creates the supplier return), or destroy (shrinkage reason
  `recalled`; controlled: PIN + manager/owner witness). `POST /recalls/{id}/close` when nothing is
  left; `POST /recalls/{id}/lift` (owner, reason) restores the previous status.

## 5. Small additions
- Register entry: controlled `GET /api/controlled/v1/entries/{entry_id}` → entry, prev/next ids,
  `hash_valid`, witness, source movement and document ref.
- Price history: catalog `pack_unit_price_history` (written in the same transaction as each
  sell_price change). **[fixed]** Back-filled once from the catalog's own outbox (`audit.recorded`
  rows with `pack_units.<name>.sell_price`, kept forever since S8), not from the User Log (that is the
  auth service's database). `GET /api/catalog/v1/medicines/{id}/price-history?pack_unit_id=&from=&to=`.
- Exchange-rate history: **[fixed]** `GET /api/sales/v1/exchange-rates/{branch_id}` already returns the
  history (newest first); it gains `from`, `to`, `page`, `size` instead of a new route.
- Customer statement PDF: document type `customer_statement` (customer_id, date_from, date_to, lang).
  **[fixed]** The statement already exists (`GET /api/customers/v1/customers/{id}/statement`); an
  internal twin `/internal/v1/customers/{id}/statement` reuses `payments.statement` for the document
  service. **[fixed]** Permission `contacts.customers` + branch (there is no `customers.view`).
- `lang: "km" | "en"` on receipt / A4 invoice; default from new branch setting `receipt_lang` (`km`),
  carried to sales by `branch.settings_updated` and into the invoice snapshot's branch block.
- 2FA backup codes: 10 codes × 10 characters (unambiguous alphabet), argon2 hashes
  (`mfa_backup_codes`: user_id, hash, used_at); shown once by `/2fa/enable` and by
  `POST /api/auth/v1/2fa/backup-codes` (password; regenerating invalidates the old set);
  `POST /login/2fa` accepts `backup_code` (consumed atomically); User Log `user.backup_code_used` /
  `user.backup_codes_regenerated`; `/me` shows `backup_codes_left`; same rate limit and lockout as TOTP.
- Sessions: **[fixed]** a session = a refresh-token family (`refresh_tokens.family_id`; each refresh
  rotates the row). Add `user_agent`, `ip`, `last_used_at`, `created_at` to `refresh_tokens`;
  `GET /api/auth/v1/me/sessions` (one row per active family, `current` marked) and
  `POST /me/sessions/{family_id}/revoke` (own only; current = logout); User Log.
- `details.locked_until` on the login lockout error documented in the schema, with a test.

## 6. Migrations
sales: `khqr_payments`, `invoice_payments.khqr_id` (unique), branch settings copy `khqr`,
`receipt_lang`. inventory: `recalls`, `recall_lines`, movement type `supplier_return`. purchasing:
`supplier_returns` + lines, `supplier_credits` (+ allocations), `supplier_refunds`. catalog:
`pack_unit_price_history`. auth: `mfa_backup_codes`, refresh-token columns. branch: settings
`receipt_lang`, `khqr`. controlled: entry type `return_to_supplier`. reports: supplier credits /
refunds / returns. Permissions: `purchasing.return`, `inventory.recall` (CATALOG + defaults:
owner; managers get both, recall limited to their branches by the rule above).

## 7. Done
New tests per service (above) + `test_openapi_quality`; smoke step S8b: cart preview with an
Rx-only line as cashier → PHARMACIST_REQUIRED, as a pharmacist with an Rx → can_post; fake KHQR →
paid → invoice; recall a lot → sale gets BATCH_BLOCKED; supplier return lowers the supplier balance;
customer statement PDF km + en; backup-code login; list and revoke a session. `make test`,
`make test-docker`, `make openapi`; CLAUDE.md S8b notes + "S8b API gaps" in Progress; commit
`S8b: API gaps`; stop with verify steps.
