# Pharmacy System Management – Architecture & API Spec

Oct 25, 2026 · @Mao Kim Huong

## Overview

A multi-branch pharmacy system that sells from the oldest-expiring batch first, ties prescription-only and controlled drugs to a recorded prescription, and keeps a tamper-evident register for controlled medicines. It follows the same stack and conventions as the Truck Parts project: FastAPI microservices, PostgreSQL, Docker, Traefik, desktop + mobile, Khmer + English.

**In scope**

- Multi-branch: each branch has its own stock; stock moves between branches only by transfer.
- Batch & expiry: every unit of stock belongs to a batch (lot number + expiry date); sales pick batches FEFO (first expiry, first out).
- Prescriptions: patients, doctors and Rx records; Rx-only drugs cannot be sold without a valid Rx.
- Controlled drugs: a running register per drug per branch, pharmacist sign-off, and a double count on stock takes.
- POS, invoices, customer credit, purchasing, stock counts, reports, Telegram daily report, receipts and labels (as in Truck Parts).

**Roles**

| Role | What they do |
| --- | --- |
| Owner | Everything, across all branches; sees cost and profit |
| Branch manager | Their branch: stock, purchasing, transfers, staff, reports (no cost/profit unless granted) |
| Pharmacist | Sell, dispense Rx, sign controlled-drug entries, approve stock counts |
| Cashier / assistant | Sell OTC items, take payments, receive stock; cannot dispense Rx-only or controlled drugs |

**Ground rules** (carried over from Truck Parts, plus pharmacy rules)

- Invoices, POs, payments, transfers and prescriptions are **cancelled with a reason, never deleted**.
- Medicines, customers, patients, doctors, suppliers, branches and staff are **deactivated, never deleted**.
- Stock changes **only through movements**, and every movement names a branch and a batch.
- Expired or recalled batches are **blocked from sale** automatically.
- Controlled-drug register entries are **append-only**; corrections are new entries that reference the one they fix.
- Cost and profit are visible to the owner only.

## Architecture

Thirteen FastAPI services sit behind one Traefik entry point, each owning its own PostgreSQL database; they talk synchronously over HTTP for reads and asynchronously through an event bus for anything that changes another service's data.

> Diagram (see the online spec): system architecture — clients → Traefik → 14 FastAPI services (core, stock, pharmacy, selling, output, ai) → PostgreSQL (one database per service), event bus (RabbitMQ + outbox), Redis + scheduler.

Requests enter only through Traefik; each service writes to its own database and tells the others what changed through the event bus.

| Service | Owns | Route prefix | Key events published |
| --- | --- | --- | --- |
| auth | users, roles, branch access, sessions | /api/auth/v1 | user.created, user.deactivated |
| branch | branches, settings, opening hours | /api/branch/v1 | branch.created |
| catalog | medicines, generics, strengths, forms, categories, units & pack sizes, Rx/controlled flags | /api/catalog/v1 | medicine.created, medicine.updated |
| inventory | batches, stock per branch per batch, movements, transfers, expiry alerts | /api/inventory/v1 | stock.changed, transfer.\*, transfer\_request.\*, stock.low, batch.expiring, batch.expired |
| stockcount | counts, count lines, approvals | /api/stockcount/v1 | count.started, count.approved, count.cancelled |
| prescription | patients, doctors, prescriptions, dispense records | /api/prescription/v1 | patient.\*, doctor.\*, prescription.created / activated / dispensed / cancelled / expired |
| controlled | controlled-drug register, sign-offs, discrepancies | /api/controlled/v1 | register.discrepancy, register.chain_broken |
| sales | invoices, POS, returns, payments at sale | /api/sales/v1 | invoice.created, invoice.cancelled |
| customers | customers, credit, payments, statements | /api/customers/v1 | payment.recorded |
| purchasing | suppliers, POs, receiving (with batch + expiry), supplier payments, returns to supplier | /api/purchasing/v1 | po.received |
| reports | read models built from events | /api/reports/v1 | – |
| notification + document | Telegram, receipts, A4 invoice, PO PDF, labels | /api/notifications/v1 · /api/documents/v1 | – |

**How it runs**

- **Traefik** routes by path prefix (`PathPrefix(/api/sales)` → sales service), terminates TLS with Let's Encrypt, and applies a ForwardAuth middleware that calls `auth` to validate the JWT and inject `X-User-Id`, `X-Role`, `X-Branch-Ids` headers.
- **Docker Compose** runs one container per service plus one PostgreSQL instance with a database per service (`pharmacy_sales`, `pharmacy_inventory`, …), RabbitMQ (or Redis Streams) for events, Redis for caching and idempotency keys, and a scheduler for the expiry check and the 20:00 Telegram report.
- **Database per service**: no service reads another service's tables. Cross-service data comes from an API call or from a local copy built from events (e.g. sales keeps a copy of medicine name, price and Rx flag).
- **Outbox pattern**: each service writes its event to an `outbox` table in the same transaction as the change; a relay publishes it. This keeps stock, debt and the register consistent even if the broker is down.
- **Sale saga** (orchestrated by sales): validate Rx → reserve stock FEFO in inventory → write controlled-register entries → post debt to customers if credit → confirm invoice. Any failure runs compensations in reverse (release stock, void register entries with a reason).
- **Idempotency**: every POST that changes money or stock takes an `Idempotency-Key` header so a retried request from a flaky connection does not double-sell.

## Data model

The batch is the centre of the model: stock, sales lines, transfers, counts and the controlled register all point at a `batch_id`, never only at a medicine. All tables carry `id UUID`, `created_at`, `created_by`, `updated_at`; money is `NUMERIC(14,2)` in USD with an optional KHR display rate; quantities are stored in the **base unit** (tablet, ml, piece).

| Service | Table | Key columns |
| --- | --- | --- |
| auth | users | name, phone, password\_hash, role, is\_active, locale (km/en) |
| auth | user\_branches | user\_id, branch\_id |
| branch | branches | code, name\_km, name\_en, address, phone, license\_no, is\_active |
| catalog | medicines | sku, barcode, brand\_name, generic\_name, strength, dosage\_form, category\_id, manufacturer, base\_unit, is\_rx\_only, controlled\_schedule (null / I–IV), storage (room / cold), reorder\_level, is\_active |
| catalog | pack\_units | medicine\_id, name (box / strip / tablet), qty\_in\_base, barcode, sell\_price |
| catalog | categories · brands | name\_km, name\_en, is\_active |
| inventory | batches | medicine\_id, lot\_no, expiry\_date, cost\_per\_base, supplier\_id, received\_at, status (active / blocked / recalled / expired) |
| inventory | stock | branch\_id, batch\_id, qty\_on\_hand, qty\_reserved — unique (branch\_id, batch\_id) |
| inventory | movements | branch\_id, batch\_id, type (in / out / adjust / transfer\_out / transfer\_in / return / expire\_writeoff), qty (signed), ref\_type, ref\_id, reason |
| inventory | transfers | from\_branch\_id, to\_branch\_id, request\_id, status (approved / picked / dispatched / received / closed / cancelled), dispatched\_by, received\_by, witnesses, cancel\_reason |
| inventory | transfer\_lines · transfer\_picks · transfer\_discrepancies | line: medicine, qty; pick: batch\_id, qty, override\_reason, qty\_received, qty\_damaged; difference: short / damaged / extra, resolution (write\_off / return\_to\_source / accept / reject) |
| stockcount | counts · count\_lines · count\_entries | branch\_id, status (counting / review / approved / cancelled), scope (full / category / location / controlled), as\_of\_seq; line: batch\_id, snapshot\_qty, expected\_qty, counted\_qty, needs\_double, round; entry: user, qty, round, counted\_at |
| prescription | patients | name, phone, dob, sex, allergies, notes, is\_active |
| prescription | doctors | name, license\_no, clinic, phone, is\_active |
| prescription | prescriptions | patient\_id, doctor\_id, rx\_no, issued\_on, valid\_until, image\_url, status (open / partially\_dispensed / dispensed / cancelled / expired), cancel\_reason |
| prescription | rx\_items | prescription\_id, medicine\_id, dose, frequency, duration\_days, qty\_prescribed, qty\_dispensed, refills\_allowed, refills\_used |
| controlled | register\_entries | branch\_id, medicine\_id, batch\_id, entry\_type (receive / dispense / transfer / return / destroy / adjust / correction), qty, balance\_after, ref\_type, ref\_id, prescription\_id, patient\_id, pharmacist\_id, witness\_id, corrects\_entry\_id, prev\_hash, hash |
| sales | invoices | branch\_id, invoice\_no, customer\_id, patient\_id, prescription\_id, payment\_type (cash / credit / card / ABA / KHQR), subtotal, discount, total, paid, status, cancel\_reason |
| sales | invoice\_lines | invoice\_id, medicine\_id, batch\_id, pack\_unit\_id, qty\_base, unit\_price, cost\_per\_base, rx\_item\_id |
| customers | customers · customer\_payments · payment\_allocations | phone (unique), credit\_limit, balance; payments applied oldest invoice first |
| purchasing | suppliers · purchase\_orders · po\_lines | po\_line: medicine\_id, qty\_ordered, qty\_received, unit\_cost |
| purchasing | receipts · receipt\_lines | receipt\_line: po\_line\_id, lot\_no, expiry\_date, qty, unit\_cost → creates a batch in inventory |
| purchasing | supplier\_payments · supplier\_returns | supplier\_returns cover expired or damaged batches sent back |

Every service also has an `outbox` table (id, event\_type, payload JSONB, published\_at) and an `idempotency_keys` table.

## Business rules

These are the rules the services enforce on the server; the UI only mirrors them.

**Batch & expiry (FEFO)**

1. Receiving a PO line requires lot number and expiry date; an expiry date in the past is refused (`BATCH_EXPIRED`).
2. A sale reserves stock from the branch's active batches ordered by `expiry_date ASC, received_at ASC`, splitting one line across batches when needed.
3. The pharmacist may override the batch (e.g. a customer asks for a longer date); the override is logged on the line.
4. A nightly job (00:05) marks batches past expiry as `expired`, blocks them from sale, and posts an `expire_writeoff` movement only when a manager confirms disposal.
5. Near-expiry alerts at 180, 90 and 30 days (configurable per branch) appear on the dashboard and in the 20:00 Telegram report.
6. A recall sets matching lot numbers to `recalled` in every branch at once and lists affected invoices for follow-up.

**Prescriptions**

1. A medicine with `is_rx_only` cannot be added to an invoice without a linked prescription item (`RX_REQUIRED`).
2. The Rx must be within `valid_until`, not cancelled, and have quantity left (`qty_prescribed − qty_dispensed`, plus refills).
3. Partial dispensing is allowed; the Rx stays `partially_dispensed` until the balance or refills run out.
4. Only a pharmacist can dispense Rx items; a cashier's attempt returns `PHARMACIST_REQUIRED`.
5. On sale the system warns if the patient has a recorded allergy matching the medicine's generic or category (warning, not a block; acknowledgement is logged).
6. Cancelling an invoice returns its quantities to the Rx balance.

**Controlled drugs**

1. Any medicine with a `controlled_schedule` writes a register entry for every receive, dispense, transfer, return, destruction and adjustment, in the same saga as the stock movement.
2. Each entry stores `balance_after`; the register balance must always equal stock for that medicine at that branch, or a `register.discrepancy` event alerts the owner.
3. Dispensing needs a prescription, the patient's ID, and the pharmacist's PIN re-entered at the moment of sale.
4. Destruction and adjustments need a second staff member as witness; for destruction the witness is a branch manager or the owner.
5. Entries are hash-chained (`hash = sha256(prev_hash + entry)`) so editing a past row is detectable; corrections are new rows.
6. Stock counts of controlled drugs need two independent counts before approval.
7. Exact schedules, record-keeping periods and reporting forms must be confirmed against Cambodia's Ministry of Health (Department of Drugs and Food) requirements before go-live.

**Multi-branch & transfers**

1. A user sees and acts on only the branches in `user_branches`; the owner sees all, plus a combined view.
2. A transfer moves specific batches: `sent` deducts from the source (transfer\_out), `received` adds to the destination (transfer\_in) with the same batch and expiry; differences need a reason.
3. Prices can be set per branch (optional override of the catalog price).
4. Invoice and PO numbers are prefixed per branch: `PP1-INV-2026-000123`.

**Cancellations & money** (same as Truck Parts)

1. Cancel with a reason; stock goes back to the original batch, debt is reversed, controlled entries get a correction row.
2. Customer payments are applied to the oldest unpaid invoices first; a sale on credit above `credit_limit` returns `CREDIT_LIMIT_EXCEEDED`.
3. Returns of opened medicines are refused by default (configurable); returned stock goes to a `quarantine` status until a pharmacist releases it.

## Screen → API map

Every screen ships in desktop and mobile, Khmer and English, and in Figma carries an "API · …" tag naming its endpoints, as in Truck Parts. A branch switcher in the header sets `X-Branch-Id` for every call.

| Area | Screens | Main endpoints |
| --- | --- | --- |
| Auth / staff | Login, PIN re-entry, Settings, Staff list, Edit staff (role + branches), Reset password | POST /api/auth/v1/login · POST /verify-pin · POST/PATCH /users · POST /users/{id}/reset-password |
| Branches | Branch list, Branch detail, Branch settings (expiry alert days, price override, receipt header) | /api/branch/v1/branches (GET/POST/PATCH) |
| Catalog | Medicines list, Medicine detail (batches tab), Add/Edit medicine, Pack units, Deactivate, Categories & brands, Excel import, Print shelf labels | /api/catalog/v1/medicines (GET/POST/PATCH) · /medicines/{id}/pack-units · /categories · /brands · POST /imports (validate → commit) · POST /labels |
| Inventory | Stock by branch, Batches (expiry view), Near-expiry list, Quick stock-in, Adjustment, Movements, Recall | /api/inventory/v1/stock · /batches?expiring\_within=90 · POST /movements · POST /batches/{id}/block · POST /recalls |
| Transfers | Transfer list, Create transfer, Pick, Dispatch, Receive transfer | /api/inventory/v1/transfers · POST /transfers/{id}/pick · /dispatch · /receive · /cancel · /differences/{id}/resolve |
| Stock count | Start count, Count (scan), Second count (controlled), Review & approve | POST /api/stockcount/v1/counts · POST /counts/{id}/lines · POST /counts/{id}/approve |
| Prescriptions | Patients, Patient detail (Rx history, allergies), Doctors, New Rx (photo upload), Rx detail, Dispense from Rx, Cancel Rx | /api/prescription/v1/patients · /doctors · /prescriptions · POST /prescriptions/{id}/cancel · GET /prescriptions/{id}/remaining |
| Controlled drugs | Register by medicine, Register entry detail, Witness sign-off, Discrepancies, Register export (PDF) | GET /api/controlled/v1/register?medicine\_id&branch\_id · POST /entries (adjust / destroy / correction) · POST /entries/{id}/witness · GET /discrepancies |
| Sales | Sell (POS with batch picker + Rx link), Pay now (cash / card / KHQR), Pay later, Invoices, Invoice detail, Cancel invoice, Return | POST /api/sales/v1/invoices (saga: Rx check → FEFO reserve → register → debt) · POST /invoices/{id}/cancel {reason} · POST /invoices/{id}/returns |
| Customers | Customers, Customer detail, Add/Edit customer, Record payment, Statement | /api/customers/v1/customers · POST /customers/{id}/payments · GET /customers/{id}/statement |
| Purchasing | Suppliers, Supplier payment, Create PO, PO detail, Receive PO (lot + expiry per line), Return to supplier | /api/purchasing/v1/suppliers · /purchase-orders · POST /purchase-orders/{id}/receive · /cancel · /supplier-payments · /supplier-returns |
| Reports | Dashboard (all branches / one branch), Sales, Stock value, Expiry & waste, Debtors, Controlled-drug summary, Branch comparison | GET /api/reports/v1/daily · /sales · /stock-value · /expiry · /debtors · /controlled · /branches |
| Notification | Telegram daily report per branch (20:00), near-expiry digest, discrepancy alert, invoice PDF to customer | POST /api/notifications/v1/telegram/send |
| Document | 80mm receipt, A4 invoice, dispensing label (patient, dose, frequency), PO PDF, register PDF, shelf labels | /api/documents/v1/render |
| Shared states | Empty, loading, error (5xx), offline, 403, toasts, Rx-required modal, allergy warning, expired-batch block | error codes below |

## Menu structure

The sidebar follows your menu in 9 groups and 44 items; each maps to one service, so no new service is needed, but 9 items add features the spec did not have yet (marked **New**). Where your menu says "Warehouse", the system means a branch's stock location.

| Menu group | Menu item | What the screen does | Service · main endpoints |
| --- | --- | --- | --- |
| Dashboard | Dashboard | Today's sales, profit (owner), near-expiry, low stock, debtors, per branch or all | reports · GET /reports/v1/daily |
| User Management | User | Create, edit, deactivate staff; assign branches; reset password | auth · /users |
| User Management | Role | Roles with a permission checklist (matrix below becomes editable) | auth · /roles · /permissions |
| User Management | User Log | Who did what, when, at which branch (login, sale, cancel, price change) | auth · GET /audit-logs (fed by events from all services) |
| User Management | Commission **New** | Commission rules: % or fixed amount per item, category or staff | sales · /commission-rules |
| POS | POS | Sell with barcode scan, FEFO batch, Rx link, cash / credit / KHQR | sales · POST /invoices |
| POS | Sale Template **New** | Saved baskets (e.g. a clinic's regular order) loaded into POS in one tap | sales · /sale-templates |
| POS | Sale Suspend **New** | Park a basket and resume it later; no stock is reserved while parked | sales · POST /invoices/suspend · GET /suspended · POST /suspended/{id}/resume |
| POS | Sale Order **New** | Customer order taken now, delivered later; reserves stock, becomes an invoice on delivery | sales · /sale-orders · POST /sale-orders/{id}/convert |
| POS | List Sale | Invoices with filters, reprint, cancel with reason | sales · GET /invoices · POST /invoices/{id}/cancel |
| POS | Sale Return | Return lines of an invoice to the original batch or to quarantine; refund or credit | sales · POST /invoices/{id}/returns |
| POS | List Commission | Commission earned per staff per period, mark as paid | sales · GET /commissions · POST /commissions/pay |
| POS | Items Promotion **New** | Discount % / fixed, buy X get Y, by item, category or customer group, with date range and branches | catalog · /promotions (applied by sales at checkout) |
| Stock | Stock Take | Start count, scan, double count for controlled, approve | stockcount · /counts |
| Contacts | Customer Group **New** | Groups (retail, clinic, wholesale) with price level and default discount | customers · /customer-groups |
| Contacts | Customer | Customers, credit limit, balance, payments, statement | customers · /customers |
| Contacts | Supplier Group | Supplier categories (importer, local distributor) | purchasing · /supplier-groups |
| Contacts | Supplier | Suppliers, terms, balance | purchasing · /suppliers |
| Warehouse | Product | Medicines: generic, strength, form, pack units, Rx / controlled flags, prices | catalog · /medicines |
| Warehouse | Hamper **New** | A bundle sold as one item (e.g. first-aid kit); selling it deducts each component FEFO | catalog · /bundles (components: medicine + qty) |
| Warehouse | Import Product | Excel import of products, validate then commit | catalog · POST /imports |
| Warehouse | Print Label | Shelf and barcode labels | document · POST /render (type: label) |
| Warehouse | Initialize **New** | Opening stock at go-live: batch, expiry and cost per branch, once, then locked | inventory · POST /opening-balances (validate → commit) |
| Purchase | Purchase Request **New** | Branch asks for stock; manager approves and turns it into a PO | purchasing · /purchase-requests · POST /{id}/approve · /convert |
| Purchase | Purchase Order | Create, send PDF, cancel with reason | purchasing · /purchase-orders |
| Purchase | Receiving Goods | Receive against PO with lot and expiry per line | purchasing · POST /purchase-orders/{id}/receive |
| Purchase | Purchase Payment | Pay suppliers, allocate to oldest bills | purchasing · /supplier-payments |
| Transfer | Stock Transfer Request | Branch requests stock from another branch; sender approves | inventory · /transfer-requests · POST /{id}/approve |
| Transfer | Stock Transfer | Send and receive specific batches | inventory · /transfers |
| Transfer | Shrinkage | Write off damaged, lost, expired or stolen stock with reason (+ witness if controlled) | inventory · POST /movements (type: shrinkage, reason) |
| Report | Sale Detail | Every sold line by date, branch, staff, customer | reports · GET /sales/detail |
| Report | Sale Margin By Item | Revenue, cost, margin per item (owner only) | reports · GET /sales/margin-by-item |
| Report | Sale Product Package | Sales of hampers and pack units (box vs strip vs tablet) | reports · GET /sales/by-package |
| Report | Sale Return Detail | Returned lines, reasons, refunds | reports · GET /returns/detail |
| Report | Shrinkage | Written-off quantity and value by reason, branch, item | reports · GET /shrinkage |
| Report | Stock | Stock on hand per branch per batch, with value (cost to owner only) | reports · GET /stock-value |
| Report | Expire | Batches already expired and their value | reports · GET /expiry?status=expired |
| Report | Expire Alert | Batches expiring within 30 / 90 / 180 days | reports · GET /expiry?within=90 |
| Report | Movement Detail | Every stock movement by batch, type and reference | reports · GET /movements |
| Report | Modification | Price, cost and product changes with old and new value | reports · GET /modifications (from audit log) |
| Report | Purchase By Item | Quantity and cost purchased per item and supplier | reports · GET /purchases/by-item |
| Report | Stock Transfer | Transfers sent and received, with differences | reports · GET /transfers |
| Report | Re-order | Items below reorder level, suggested quantity from recent sales | reports · GET /reorder (one tap to a Purchase Request) |
| Report | Transaction Payment | All money in and out: sales, customer payments, refunds, supplier payments, by method | reports · GET /payments |

**What the new items add to the data model**

- sales: `commission_rules`, `commissions`, `sale_templates` + lines, `suspended_sales` (basket JSON), `sale_orders` + lines.
- catalog: `promotions` (type, value, buy\_qty, get\_qty, start/end, branch ids, customer group ids), `bundles` + `bundle_components`.
- customers: `customer_groups` (price level, default discount); `customers.group_id`.
- purchasing: `supplier_groups`, `purchase_requests` + lines.
- inventory: `transfer_requests` + lines, `opening_balances` (locked after commit); movement type `shrinkage` with reason codes.
- auth: `roles` + `role_permissions` replace the fixed role list, so the permissions matrix becomes data the owner can edit.

Two items in your list need a decision: **Stock Take** sits under POS in your menu but belongs with Stock here, and **Modification** is read as a report of price and product changes — say if you meant something else.

## Endpoint reference

All endpoints are versioned (`/v1`), return JSON, paginate with `?page=&size=` (default 20, max 100), and wrap errors as `{"code": "OUT_OF_STOCK", "message": "…", "details": {…}}`. Below are the endpoints that carry pharmacy-specific logic; plain CRUD follows the same shape as Truck Parts.

**POST /api/sales/v1/invoices** — create a sale (runs the saga)

```json
{
  "branch_id": "…",
  "customer_id": null,
  "patient_id": "…",
  "prescription_id": "…",
  "payment": {"type": "cash", "amount": 12.50},
  "lines": [
    {"medicine_id": "…", "pack_unit_id": "…", "qty": 2, "rx_item_id": "…", "batch_id": null}
  ],
  "controlled_pin": "****"
}
```

Response `201` returns the invoice with each line split into the batches actually used (`batch_id`, `lot_no`, `expiry_date`, `qty_base`). Leave `batch_id` null for FEFO; set it to override.

**POST /api/purchasing/v1/purchase-orders/{id}/receive**

```json
{"lines": [{"po_line_id": "…", "lot_no": "A2391", "expiry_date": "2028-03-31", "qty": 100, "unit_cost": 0.08}]}
```

Creates or tops up a batch in inventory, posts an `in` movement, and writes a `receive` register entry for controlled medicines.

**POST /api/inventory/v1/transfer-requests** → **/{id}/approve** (or **POST /transfers** to push) → **/transfers/{id}/pick** → **/dispatch** → **/receive**

```json
{"from_branch_id": "…", "to_branch_id": "…", "lines": [{"medicine_id": "…", "qty_base": 30}]}
```

Pick is FEFO unless a line names batches with a reason. Receive takes `{"lines": [{"pick_id": "…", "qty_received": 28, "qty_damaged": 1, "location": "A3"}]}`; short, damaged or extra quantities open differences resolved with a reason.

**GET /api/inventory/v1/batches?branch\_id=&expiring\_within=90&status=active** — near-expiry list, sorted by expiry.

**POST /api/prescription/v1/prescriptions** — patient, doctor, `rx_no`, `issued_on`, `valid_until`, and `items[]` (`medicine_id`, `qty_base` = one fill, `dosage`, `frequency`, `duration_days`, `repeats_allowed`). The photo is uploaded after: **POST /prescriptions/{id}/attachments** (JPEG/PNG/PDF ≤ 10 MB) and read back only through **GET /prescriptions/{id}/attachments/{att_id}** (checked and logged on every request).

**GET /api/prescription/v1/prescriptions/{id}/remaining** — what can still be dispensed per item; the POS calls this before adding Rx lines.

**POST /api/controlled/v1/entries** — manual adjust, destroy or correction; requires `witness_id` and `reason`; `correction` requires `corrects_entry_id`.

**GET /api/controlled/v1/register?branch\_id=&medicine\_id=&from=&to=** — running register with `balance_after` and a `chain_valid` flag.

**GET /api/reports/v1/expiry?branch\_id=&from=&to=** — value of stock expiring and written off, by branch and supplier.

## Errors, security & permissions

**Error codes**

| Code | HTTP | When |
| --- | --- | --- |
| OUT\_OF\_STOCK | 409 | Not enough active, unexpired stock across batches at this branch |
| BATCH\_EXPIRED | 409 | Chosen or received batch is past expiry |
| BATCH\_BLOCKED | 409 | Batch is blocked, recalled or in quarantine |
| RX\_REQUIRED | 422 | Rx-only medicine added without a prescription item |
| RX\_EXPIRED | 422 | Prescription is past `valid_until` |
| RX\_QUANTITY\_EXCEEDED | 422 | Quantity is more than what is left on the Rx |
| PHARMACIST\_REQUIRED | 403 | Rx or controlled dispense by a non-pharmacist |
| PIN\_REQUIRED / PIN\_INVALID | 401 | Controlled dispense without a valid PIN re-entry |
| WITNESS\_REQUIRED | 422 | Controlled destroy or adjust without a second staff member |
| WITNESS\_INVALID | 422 | The witness is the actor, works elsewhere or may not witness |
| PIN\_LOCKED | 423 | 5 wrong PINs: the PIN is locked for 15 minutes |
| COUNT\_STATE / SHRINKAGE\_STATE / REGISTER\_STATE | 409 | Action not allowed in the stock take's, shrinkage's or discrepancy's status |
| OWNER\_APPROVAL\_REQUIRED | 403 | Stock-take variance above the branch limit: only the owner approves |
| ALLERGY\_WARNING | 409 | Patient allergy match; resend with `allergy_acknowledged: true` |
| CREDIT\_LIMIT\_EXCEEDED | 422 | Credit sale over the customer's limit |
| DUPLICATE\_PHONE | 409 | Customer or patient phone already exists |
| BRANCH\_FORBIDDEN | 403 | User has no access to the requested branch |
| TRANSFER\_STATE | 409 | Action not allowed in the transfer's current status (e.g. cancel after dispatch) |
| REQUEST\_STATE | 409 | Purchase request or re-order line already decided or requested |

**Security**

Authentication, rate limits, injection protection, secrets, data protection, monitoring and replication are covered in full in the Security & reliability section below.

**Permissions matrix**

| Action | Owner | Branch manager | Pharmacist | Cashier |
| --- | --- | --- | --- | --- |
| Sell OTC medicines | Yes | Yes | Yes | Yes |
| Dispense Rx-only | Yes\* | Yes\* | Yes | No |
| Dispense controlled | Yes\* | Yes\* | Yes | No |
| Witness controlled entry | Yes | Yes | Yes | No |
| Cancel invoice | Yes | Yes | Own branch | No |
| Receive PO / stock-in | Yes | Yes | Yes | Yes |
| Create PO, supplier payment | Yes | Yes | No | No |
| Transfers (send / receive) | Yes | Yes | Yes | Receive only |
| Approve stock count | Yes | Yes | Yes | No |
| Edit medicines & prices | Yes | Yes | No | No |
| See cost & profit | Yes | If granted | No | No |
| Manage staff & branches | Yes | Own branch staff | No | No |

\* Only if the user is also registered as a licensed pharmacist (`is_pharmacist` flag).

## Security & reliability

Every request passes three checks before it touches data: Traefik (TLS, headers, per-IP limits), the auth ForwardAuth (valid token, not revoked), and the service itself (per-user limits, Pydantic validation, branch and role checks). Data is replicated to a standby server and archived continuously, so a server failure loses under a minute of data and is back within 15 minutes.

**Rate limits**

Two layers: Traefik's RateLimit middleware per IP (coarse protection against floods), and a Redis token bucket per user in the shared library (fair use per staff member). Over the limit → `429 RATE_LIMITED` with a `Retry-After` header. Numbers are starting values, set in config and tuned after the pilot.

| Endpoint group | Limit | Counted per |
| --- | --- | --- |
| POST /auth/login | 5 per minute; 10 failures → account locked 15 min | IP + phone |
| Reset password, verify PIN | 3 per minute; PIN locks after 5 wrong tries | user |
| POS checkout (POST /invoices) | 60 per minute | user |
| Other writes (POST, PATCH) | 120 per minute | user |
| Reads (GET) | 600 per minute | user |
| Imports, exports, report PDFs | 10 per minute | user |
| AI endpoints | 20 per minute + daily cap from Settings | user |
| Any route, before login | 60 per minute | IP |

**Injection and input attacks**

| Attack | Where it could happen here | Protection |
| --- | --- | --- |
| SQL injection | Search boxes, filters, report parameters | SQLAlchemy ORM and bound parameters only; no SQL built with f-strings or `+` (ruff/bandit rule S608 fails CI); each service's DB user has rights only to its own database |
| SQL via AI | "Ask your data" | The model never writes SQL; it can only call fixed report endpoints with allow-listed parameters |
| Mass assignment | PATCH on users, medicines, invoices | Separate Create/Update schemas with `extra="forbid"`; role, cost, branch and user IDs are taken from the token, never from the request body |
| Access to other branches' data (IDOR) | Any `/{id}` endpoint | Every query is filtered by the branch IDs in the token; tests try to read another branch's records and must get 404 |
| Cross-site scripting (XSS) | Product names, customer notes, patient names shown in the UI | Front-end escapes all text, no raw HTML rendering; Content-Security-Policy header; text escaped again in PDF receipts and labels |
| Spreadsheet formula injection | Excel import and every export | Exports prefix cells starting with `= + - @` with `'`; imports read values only and refuse macro files (.xlsm) |
| Malicious file upload | Excel import, prescription photos | Size limit (10 MB), type checked from file content not the name, random UUID file names, stored in private MinIO, never on the web server |
| Command injection | PDF and label rendering | No shell commands with user input; rendering through Python libraries only |
| Server-side request forgery (SSRF) | Image or link fields | The system never fetches URLs supplied by users; images go to DeepSeek as base64, not as links |
| Prompt injection | Imported product lists, typed questions, Rx text sent to AI | User text is passed as data, not instructions; AI output must match a JSON schema; AI has no write access (see AI service rules) |
| Log injection | Any logged text | Structured JSON logs; newlines and control characters escaped |
| CSRF | Browser sessions | Tokens sent in the Authorization header, not cookies; if cookies are ever used: SameSite=Strict + CSRF token |
| Telegram bot abuse | Owner "Ask" bot, daily report | Only allow-listed chat IDs; every bot command checks the linked user's role |

**Logins and sessions**

- Each staff member has their own account; shared POS devices switch user with a 4–6 digit PIN, so the audit log always names the real person.
- 2FA (authenticator app) required for owner and branch managers.
- Access token 15 min, refresh token 7 days, rotated on use; a revocation list in Redis lets the owner log a user out everywhere.
- POS screens lock after 5 minutes idle; deactivating a user revokes all their sessions at once.

**Network and Traefik**

- Only Traefik is exposed (ports 80 → 443); services, PostgreSQL, RabbitMQ and Redis sit on a private Docker network with no published ports.
- Service-to-service calls carry a signed service token, so a service cannot act as a user it was not asked to act for.
- Headers on every response: HSTS, Content-Security-Policy, X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy.
- CORS limited to the system's own domains; request body limit 10 MB; Traefik dashboard and admin routes reachable only from an IP allow-list or VPN.

**Secrets**

- Database passwords, JWT signing key, Telegram token and DeepSeek key live in Docker secrets (or a vault), never in Git or images; `.env` files are git-ignored.
- Keys are rotated every 6 months and immediately after any staff member with server access leaves.
- CI scans every commit for leaked secrets (gitleaks) and dependencies for known vulnerabilities.

**Data protection**

- Patient phone, allergies and Rx images are encrypted at rest (column encryption + encrypted storage); backups are encrypted.
- Only owner and managers can export customer or patient lists; every export is logged.
- Retention: prescriptions and controlled-drug records kept for the period the Ministry of Health requires (to confirm); inactive patient data reviewed yearly.

**Monitoring and incident response**

- Alerts (Telegram to the owner, Grafana): 10+ failed logins in 5 minutes, account lockouts, large exports, invoice cancellations after hours, register discrepancies, replication lag over 60 seconds, a failed backup.
- If a device is stolen or a password leaks: revoke that user's sessions, rotate affected keys, review the audit log for the period, and record what happened.

**Replication and backups**

| Layer | Setup | Protects against |
| --- | --- | --- |
| PostgreSQL | Primary + hot standby on a second server with streaming replication; synchronous for the sales and controlled databases, asynchronous for the rest | Server failure |
| Failover | Manual promote runbook at launch; Patroni + etcd (3 nodes) for automatic failover once there are several branches | Downtime without someone on site |
| Point-in-time recovery | pgBackRest: continuous WAL archiving + nightly full backup, encrypted, stored off-site | Bad imports, deleted data, corruption |
| Read replica | Reports and AI "Ask your data" read from the standby | Heavy reports slowing the POS |
| Event bus | RabbitMQ quorum queues on 3 nodes; outbox tables can resend any event | Lost stock or debt updates |
| Files | MinIO / S3 replication + versioning for Rx images and PDFs | Lost or overwritten files |
| Redis | No replication; it holds only cache and idempotency keys | – |

- Targets: data loss (RPO) under 1 minute (zero for sales and controlled-drug data); downtime (RTO) under 15 minutes.
- A failover drill and a restore test every quarter, logged in the maintenance report.
- **Branch internet outage:** the POS keeps selling OTC items for cash and queues sales locally with idempotency keys, then syncs when back online. Rx-only and controlled-drug sales are blocked offline because they need live checks.

**New error codes:** `RATE_LIMITED` (429), `ACCOUNT_LOCKED` (423), `SESSION_REVOKED` (401), `FILE_REJECTED` (422).

## AI service (DeepSeek)

A 14th service, `ai`, adds DeepSeek-powered help that only **suggests**: it reads data through other services' APIs with the user's own permissions, and a person confirms before anything is saved. It is off by default (Settings → "Use AI"), and each feature has its own switch and role list.

**Features**

| # | Feature | Where it appears | Who uses it | Release |
| --- | --- | --- | --- | --- |
| 1 | Product import cleanup: split messy names into generic, strength, form, pack size; match existing products; suggest Khmer and English names | Import Product → "Clean with AI" | Manager, owner | Phase A |
| 2 | Ask your data: questions in Khmer or English answered from the reports API ("Which items lost money last month?") | Dashboard → "Ask" box; Telegram bot for the owner | Owner, manager | Phase A |
| 3 | Daily report summary: short written highlights added to the 20:00 Telegram report | Telegram | Owner | Phase A |
| 4 | Substitute suggestions: same generic and strength in stock when an item is out; fixes misspelled or unknown brand names | POS search, out-of-stock message | Pharmacist, cashier | Phase B |
| 5 | Prescription entry assist: turns typed Rx text, or a photo with the patient area cropped out, into draft Rx items (medicine, dose, frequency, duration, qty) | New Rx → "Fill from text / photo" | Pharmacist | Phase B |
| 6 | Re-order and expiry advice: explains suggested order quantities and near-expiry options (transfer, return to supplier, promote) | Re-order and Expire Alert reports | Manager, owner | Phase B |
| 7 | Unusual activity notes: plain-language explanation of patterns worth a look (many cancellations by one user, register discrepancies, sharp margin drops) | Dashboard, User Log | Owner | Phase C |

**Endpoints** (`/api/ai/v1`)

| Endpoint | Input | Returns |
| --- | --- | --- |
| POST /imports/clean | import\_id (from catalog validate step) | Per row: proposed fields, matched product\_id, confidence; nothing saved |
| POST /ask | question, branch\_id | Answer text, the report calls it made, a table of figures |
| POST /reports/daily-summary | branch\_id, date (called by notification at 20:00) | 3–5 highlight lines |
| POST /substitutes | medicine\_id or free text, branch\_id | Candidate products in stock with the reason for each match |
| POST /prescriptions/parse | text or image (patient area removed) | Draft rx\_items with confidence; pharmacist edits and saves through the prescription service |
| POST /advice/reorder · /advice/expiry | branch\_id | Suggestions with the numbers behind them |
| POST /insights/anomalies | period, branch\_id | Notes linked to the records they refer to |
| GET /usage | month | Requests, tokens, cost per feature and user (owner only) |

**Rules**

1. **Suggest, never act.** The ai service has no write access to stock, invoices, payments, prescriptions or the controlled register. Every suggestion is applied by a person through the normal endpoint, so all existing rules (FEFO, Rx checks, permissions) still apply.
2. **No clinical decisions.** It never gives dosing, interaction or diagnosis advice; drug interactions come from a verified drug database, not the model. Prescription parsing is a draft the pharmacist must check line by line.
3. **Patient privacy.** DeepSeek's servers are outside Cambodia, so before any call the service replaces patient names, phone numbers, IDs and allergies with internal IDs. Prescription photos are sent only if the owner turns that switch on, and only with the patient area cropped.
4. **Same permissions as the user.** "Ask your data" calls report endpoints with the asking user's token, so a cashier can never see cost or profit through AI.
5. **Structured output.** Calls that fill fields use JSON output mode and are validated against a Pydantic schema; anything invalid is shown as "could not read" instead of guessed.
6. **Cost control.** A monthly spending cap and a per-user daily limit in Settings; when the cap is hit, AI features turn off and the system works as normal.
7. **Audit.** Every request is logged (user, feature, tokens, cost, the suggestion, and whether it was accepted) and shows in User Log.
8. **Fail safe.** If DeepSeek is slow or down, a 10-second timeout returns `AI_UNAVAILABLE` and the screen continues without AI; no core flow depends on it.

**New error codes:** `AI_DISABLED` (403), `AI_UNAVAILABLE` (503), `AI_LIMIT_REACHED` (429), `AI_UNREADABLE` (422).

**Setup**

- The API is OpenAI-compatible: use the `openai` Python client with `base_url=https://api.deepseek.com`. Current model names are `deepseek-flash` (also accepts images) and `deepseek-v4-pro` ([DeepSeek docs](https://api-docs.deepseek.com/), [vision guide](https://api-docs.deepseek.com/guides/vision)).
- Keep `DEEPSEEK_API_KEY` and the model names in environment variables of the ai service only, never in the front end or the database, so a model rename needs no code change.
- Use `deepseek-flash` for fast, cheap tasks (1, 3, 4, 5) and `deepseek-v4-pro` for longer reasoning (2, 6, 7).
- Tables: `ai_requests` (user\_id, branch\_id, feature, model, tokens\_in, tokens\_out, cost, accepted, created\_at) and `ai_settings` (feature switches, caps, roles).
- SDLC: Phase A ships as sprint S10 after the reports sprint; Phases B and C follow once Phase A is in daily use.

## SDLC

The project runs in six phases with a sign-off gate between each, and the build phase is ten 2-week Scrum sprints that deliver the full menu, one menu group at a time. Every menu item is built; optional ones (commission, hampers, sale orders, sale templates, customer and supplier groups, purchase requests) sit behind feature switches in Settings, and each role sees only its menu items.

> Diagram (see the online spec): SDLC roadmap — Plan → Design → Build (sprints S0–S10) → Test → Deploy → Maintain, each closed by a sign-off gate.

No phase starts until the gate before it is signed; prescriptions and controlled drugs come right after the POS so the pharmacy rules are tested longest.

**Phases and gates**

| # | Phase | Main activities | Deliverables | Gate to move on |
| --- | --- | --- | --- | --- |
| 1 | Plan (requirements) | Interview owner, pharmacists, cashiers; confirm menu, business rules, Ministry of Health rules for controlled drugs | This spec, menu list, open questions closed | Owner signs off scope |
| 2 | Design | Figma screens (desktop + mobile, km/en) with API tags, DB schema per service, API contracts (OpenAPI) | Figma file, ERD, OpenAPI files | Owner approves key screens: POS, Rx dispense, Receive PO, Stock |
| 3 | Build | Sprints 0–9 (below); demo at the end of each sprint | Working services + UI per sprint, on staging | All sprint stories meet the Definition of Done |
| 4 | Test | System test, security test, performance test, UAT by a pharmacist and a cashier | Test report, UAT sign-off sheet | No open critical or high bugs; UAT signed |
| 5 | Deploy | Pilot at one branch, data load via Initialize and Import Product, staff training, then roll-out | Live system, trained staff | Pilot runs 2 weeks with stock and cash reconciling daily |
| 6 | Maintain | Bug fixes, monthly releases, monitoring, backups; new requests go back to phase 1 | Release notes, monthly health report | – |

**Sprint plan (2 weeks each)**

| Sprint | Menu groups and items | Services | Done when |
| --- | --- | --- | --- |
| S0 Setup | Repo, Docker Compose, Traefik, CI pipeline, shared library, login | all (skeleton), auth | `docker compose up` runs every service behind Traefik; CI green |
| S1 Settings | User, Role (permission checklist), User Log, Branches, feature switches; Product, Import Product, Print Label | auth, branch, catalog | Owner can set up branches, staff and products |
| S2 Stock & buying | Stock, Initialize, Supplier, Supplier Group, Purchase Order, Receiving Goods (lot + expiry), Purchase Payment | inventory, purchasing | Opening stock loaded; a PO received creates batches |
| S3 POS & sales | POS (FEFO, cash / credit / KHQR), List Sale, Sale Return, Customer, Customer Group, receipts | sales, customers, document | A full day of sales reconciles with stock and cash |
| S4 Prescriptions | Patients, Doctors, Prescriptions, Rx dispensing in POS, allergy warning, dispensing label | prescription, sales | Rx-only items cannot be sold without a valid Rx |
| S5 Controlled & counts | Controlled Drugs Register, Discrepancies, PIN + witness; Stock Take with double count; Shrinkage | controlled, stockcount, inventory | Register balance always equals stock |
| S6 Branches | Stock Transfer Request, Stock Transfer, Purchase Request, Re-order | inventory, purchasing | Batches move between branches with expiry kept |
| S7 Sales extras | Sale Order, Sale Suspend, Sale Template, Items Promotion, Hamper, Commission rules, List Commission | sales, catalog | Each works when its switch is on and disappears when off |
| S8 Reports | Dashboard and all 14 reports, Telegram 20:00 report, expiry alerts | reports, notification | Report totals match the source data on test sets |
| S9 Hardening | Performance, security review, offline handling, Khmer text review, UAT fixes | all | Ready for phase 4 gate |

**Definition of Done (every story)**

- Code reviewed and merged; API matches the OpenAPI contract.
- Unit and integration tests pass in CI; business rules covered by tests.
- Screen works on desktop and mobile, in Khmer and English.
- Permissions checked for each role; audit log entry written for every change.
- Alembic migration included; demoed on staging.

**Testing**

| Level | Tool | What it covers |
| --- | --- | --- |
| Unit | pytest | Business rules: FEFO picking, Rx balance, credit limit, register hash chain |
| Integration | pytest + Testcontainers (PostgreSQL, RabbitMQ) | Each service with its own database and events |
| Contract | Schemathesis / OpenAPI checks | Services and front end agree on request and response shapes |
| End-to-end | Playwright | Critical flows: sell OTC, dispense Rx, dispense controlled, receive PO, transfer, cancel invoice |
| Performance | Locust | POS checkout and stock lookup under a busy-hour load |
| Security | OWASP ZAP, dependency scan | Auth, permissions, injection, exposed patient data |
| UAT | Checklist per role | Pharmacist and cashier run real daily tasks on staging |

**Environments and CI/CD**

| Environment | Runs on | Deployed when |
| --- | --- | --- |
| Local | Docker Compose on each developer's machine | Any time |
| Staging | Server with Traefik, test data, `staging.` subdomain | Every merge to `main` |
| Production | Server with Traefik + Let's Encrypt, real data | A tagged release, after staging check |

The pipeline (GitHub Actions or GitLab CI) runs lint (ruff), type check, tests, builds one Docker image per service, pushes to the registry, runs Alembic migrations, and deploys. Rollback = redeploy the previous image tag; migrations are written to be backward-compatible for one release.

**Go-live and maintenance**

1. Load products with Import Product and opening stock per batch with Initialize, then lock Initialize.
2. Train by role: cashier (POS, returns), pharmacist (Rx, controlled register, stock take), manager (purchasing, transfers, reports), owner (settings, margins).
3. Run the pilot branch, reconcile stock and cash every evening, fix issues, then roll out branch by branch.
4. After go-live: nightly PostgreSQL backups kept off-server, a monthly restore test, monitoring with Prometheus + Grafana, logs in Loki, errors in Sentry.
5. Bugs: critical (cannot sell) fixed the same day; others go into the monthly release. New feature requests start again at phase 1.

Open question: team size and start date, which set the real calendar dates for the sprints.

## Repo layout & delivery

One monorepo, one folder per service with the same internal shape, so a new service is a copy of the template.

```
pharmacy/
├── docker-compose.yml          # all services + postgres + rabbitmq + redis + traefik
├── traefik/                    # traefik.yml, dynamic routes, ForwardAuth
├── shared/                     # pydantic base models, error codes, outbox relay, auth headers
├── services/
│   ├── auth/
│   │   ├── app/
│   │   │   ├── main.py         # FastAPI app, routers mounted at /api/auth/v1
│   │   │   ├── api/            # routers
│   │   │   ├── models/         # SQLAlchemy 2.0 models
│   │   │   ├── schemas/        # Pydantic v2 request/response
│   │   │   ├── services/       # business logic
│   │   │   └── events/         # publishers + consumers
│   │   ├── migrations/         # Alembic
│   │   ├── tests/
│   │   └── Dockerfile
│   ├── branch/ catalog/ inventory/ stockcount/ prescription/
│   ├── controlled/ sales/ customers/ purchasing/
│   └── reports/ notification/ document/
└── web/                        # front end (desktop + mobile, km/en)
```

**Delivery**

The build order, sprints and release process are in the SDLC section above.

**Open questions**

- [ ] Which controlled-drug schedules and record formats does the Ministry of Health require in Cambodia?
- [ ] Payment methods at launch: cash and credit only, or also card and KHQR / ABA?
- [ ] Does one owner run all branches, or do branches have separate owners and separate reports?
- [ ] Should prices differ by branch from day one?
- [ ] Event bus: RabbitMQ (more features) or Redis Streams (one less container)?
