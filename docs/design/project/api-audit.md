# UI ↔ API audit (updated 31/10/2026)

Source: 14 OpenAPI specs in uploads/ (280 endpoints, health/whoami excluded).

## What changed
1. **Every API tag now names the real endpoint** from the specs (service names `inventory`, `prescription`, `purchasing`, `customers`, `stockcount`, `branch`, `notifications`, `documents`). Cart checks use `POST /api/sales/v1/carts/price` with `override_reason`, `allergy_override_reason`, `acknowledge_warnings`. Controlled sale and discount approval use `pin/verify` and `pin/witness` tokens on `POST /api/sales/v1/invoices`. All prints use `POST /api/documents/v1/render`.
2. **Witness sign-off queue removed** (old 12m and the "Witness sign-offs" menu item). Witnessing stays on the same device: witness dialog with a second user + PIN → `POST /api/auth/v1/pin/witness`.
3. **2FA**: "Trust this device" removed from 15c and 15i. Backup codes kept (setup step 3, "Use a backup code instead") and tagged API pending.
4. **Account locked (15f)** reads `error.details.locked_until` (UTC) and shows it in Asia/Phnom_Penh with a countdown.
5. **New screens** in `API Coverage Screens.dc.html`:
   - 18a Categories & brands: catalog categories/brands CRUD + activate/deactivate
   - 18b Re-order settings: reorder-settings GET/PUT/bulk, reorder-lists/run
   - 18c Notification settings + daily summary preview: notifications settings GET/PUT, daily-summary/run
   - 18d Inventory movements: inventory movements
   - 18e Opening-stock upload: opening-balances template/upload/list/detail, initialize-locks + unlock
   - 18f Receipts + supplier payments: purchasing receipts, supplier-payments list/detail/cancel, supplier statement
   - 18g Customer payments: customer-payments list/create/cancel, customers/{id}/unpaid
   - 18h Controlled register correction: pin/witnesses, pin/verify, pin/witness, controlled entries/correction
6. **10 reports added** to Reports.dc.html (13g–13p) using the report template, and to the menu: Sales Summary, Profit, Sale Cancellations, Discounts, Slow-moving Stock, ABC Analysis, Purchase By Supplier, Top Customers, Stock Count Variances, Transfers In Transit.
7. Menu additions (App Shell): Stock → Movements, Re-order settings · Warehouse → Categories & brands · Purchase → Receipts · Contacts → Customer Payment · Report → Profit, ABC Analysis (+29 more) · Settings → Notifications.

## API pending (backend will add; design kept, tag shows "⚠ API pending")
| # | Screen | Endpoint the screen expects (suggested) |
|---|---|---|
| 1 | POS 3l, POS Lite 4d · KHQR | `POST /api/sales/v1/payments/khqr` → `{id, qr_payload, amount_khr, expires_at}` · `GET /api/sales/v1/payments/khqr/{id}/status` → `{status: waiting/paid/expired, paid_at, bank_ref}` |
| 2 | 12h · Promotion preview | `POST /api/catalog/v1/promotions/preview` (unsaved PromotionCreate + sample cart) → priced lines, conflicts |
| 3 | 12n · Price history | `GET /api/catalog/v1/medicines/{medicine_id}/price-history` → `[{from, pack_unit_id, cost, sell, reason, changed_by}]` |
| 4 | 7b · Register entry detail | `GET /api/controlled/v1/entries/{entry_id}` → EntryOut + witness, hash, prev_hash |
| 5 | 8g · Recall | `GET/POST /api/inventory/v1/recalls`, `GET …/{recall_id}` (batches, stock by branch, customers who bought, quarantine action) |
| 6 | 10d · Supplier return | `POST /api/purchasing/v1/supplier-returns`, `GET …` (lines from batches, reason, credit note) |
| 7 | 17h · Customer statement PDF | `customer_statement` type on `POST /api/documents/v1/render` (data from `GET /api/customers/v1/customers/{id}/statement`) |
| 8 | 14i · Active sessions | `GET /api/auth/v1/me/sessions`, `POST …/sessions/{id}/revoke` |
| 9 | 14f · Exchange-rate history | `GET /api/sales/v1/exchange-rates/{branch_id}/history?months=12` (RateOut has only current + previous) |
| 10 | 15c, 15d, 15i · 2FA backup codes | `GET /api/auth/v1/2fa/backup-codes` (shown once at setup) + `backup_code` accepted by `POST /api/auth/v1/login/2fa` |

To confirm with backend (not new endpoints):
- `details.locked_until` on the login lockout error is used by 15f but isn't documented in auth.json.
- Error codes used in the UI (OUT_OF_STOCK, CREDIT_LIMIT_EXCEEDED, RX_REQUIRED, PHARMACIST_REQUIRED, RX_QUANTITY_EXCEEDED, DISCOUNT_APPROVAL_REQUIRED, BELOW_COST, HAMPER_NOT_STOCKED, PERIOD_LOCKED, DUPLICATE_PHONE, PIN_LOCKED, INVALID_MFA_CODE) aren't documented in the specs; only SUPPLIER_OVERPAYMENT is.
- `POST carts/price` (PricedLineOut) returns no warnings or failure codes, so POS hard stops and warnings (3f–3h, 3o) only surface after `POST invoices`. Pre-payment warnings need fields on PricedLineOut (e.g. `warnings[]`, `blocking_code`).
- PricedCart has no `total_khr`; promotion names need a lookup by `promotion_ids`.
- `receipt_80mm` / `invoice_a4` render has no `lang`; 17a/17b show KM and EN receipts.
- Barcode label size in the API is 40×25 mm; 17c shows 38×25 mm.
- Dashboard and report responses are untyped in the specs, so tile/column fields can't be checked.

## Endpoints still without a dedicated screen
These are covered as buttons or actions on existing screens and need no new design:
- **Create/edit/activate** for users, roles, branches, customers, customer groups, suppliers, supplier groups, patients, doctors, allergies, medicines, pack units, promotions, sale templates. They are opened from the list screens (14a, 14b, 14e, 10a–d, 12l, 6a–6d, 9a–9c, 12h, 12a).
- Lists and lifecycle actions: PO list/detail/update/cancel (12j), PR create/list/cancel (10a), transfer-requests list/approve/reject/cancel (11a), transfer detail/cancel (11a–d), shrinkages list/reject/photo (11e), stockcount list/detail/submit/cancel (8c–8i), sale-orders list/create/confirm/close (12c), invoice returns list (12e).
- `POST /api/auth/v1/refresh`, `POST /api/auth/v1/logout` (session handling, user menu).
- `DELETE /api/auth/v1/users/{id}/pin` (Reset PIN in 14a).
- `POST /api/inventory/v1/transfers` (direct push without a request), `GET …/transfers/in-transit` (covered by report 13p), `PUT …/shelf-locations` (edit in 8f).
- `GET /api/catalog/v1/medicines/export.xlsx`, `GET …/imports` + `template.xlsx`, `GET …/hampers` (export/template buttons on 9a, 9e, 9d).
- `POST /api/sales/v1/commission/periods/{branch}/{month}/close`, `…/rules/{id}/deactivate`, `GET …/commission/report/{staff_id}` (12g, 14d).
- `PATCH`/`activate` prescriptions, attachment download (6f).
- `GET /api/reports/v1/catalog`: lists the reports available to the user (menu source).
- Report endpoints shown through the report template but not drawn as separate frames: sales/by-package, returns/detail, payments, stock, movements, shrinkage, modifications, purchases/by-item, purchases/cost-changes, payables/aging, receivables/aging, transfers, commission, rx/dispensing.
