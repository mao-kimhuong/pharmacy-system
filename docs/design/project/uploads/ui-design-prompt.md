You are designing the complete UI for **Pharmacy System Management**, a multi-branch pharmacy system used in Cambodia. Design it as a real, production-ready product: a design system first, then every screen, desktop and mobile, in Khmer and English.

## 1. Product and users
- Multi-branch retail pharmacy chain (branches coded PP1, PP2, SR1…). Owner sees all branches; staff see only their assigned branches.
- Roles and what they mostly do:
  - **Owner**: dashboard, reports, profit, approvals, settings. Sees cost and profit everywhere.
  - **Branch manager**: approvals (discounts, shrinkage, stock takes, transfers), staff, purchasing, reports for own branches. Sees cost only if granted.
  - **Pharmacist**: POS, prescriptions, dispensing Rx and controlled drugs (with PIN), witness sign-offs, quarantine release.
  - **Cashier**: POS for non-Rx items, suspend/resume, sale orders, stock counting. Never sees cost, profit, patients or prescriptions.
- Devices: desktop POS (1366×768 and 1920×1080, keyboard + barcode scanner + 80 mm receipt printer + label printer), tablet, and phones (Android, 360–414 px) for managers, stock counting and receiving.
- Languages: Khmer (default) and English, switchable at any time. Currencies: USD and KHR together (e.g. $12.50 · ៛51,300), KHR rounded to 100 riel. Dates DD/MM/YYYY, time zone Asia/Phnom_Penh.

## 2. Design principles
1. **Speed at the counter**: a cashier must finish a simple sale in under 10 seconds with keyboard and scanner only. Every POS action has a shortcut (F2 search, F4 customer, F8 suspend, F9 pay, Esc cancel); show shortcut hints.
2. **Safety is visible, never hidden**: Rx-only, controlled, expired, near-expiry, quarantined, allergy and recalled states each have a distinct, consistent badge (icon + color + text, never color alone). Hard stops (expired batch, expired Rx, over-dispensing) look different from warnings that can be overridden with a reason.
3. **Nothing is deleted**: invoices, POs, payments, transfers and prescriptions show "Cancel (reason required)"; medicines, customers, patients, suppliers, staff and branches show "Deactivate". Never show a Delete button for these.
4. **Approvals are clear**: when an action needs a PIN, a witness, or a manager/owner approval, show who must approve, why, and the pending state.
5. **Calm, clinical, trustworthy**: clean light UI, generous whitespace, high contrast for numbers. No playful illustrations in work screens.
6. **Khmer first**: Khmer text needs more line height and wider space; design every component so Khmer labels (often 30–50% longer) never truncate or overflow.

## 3. Design system (build first)
- **Color tokens**: primary (calm medical teal/green), neutral greys, and semantic colors: success, warning (near-expiry, pending), danger (expired, hard stop, cancelled), info; plus dedicated badge colors for Rx-only, Controlled, Quarantine, Hamper, Promotion. Meet WCAG AA contrast. Provide a dark variant for the POS screen only.
- **Typography**: a Khmer font (Kantumruy Pro or Noto Sans Khmer) paired with a Latin font (Inter). Tabular numerals for all money and quantities. Scale for: page title, section title, table text, POS total (very large), receipt.
- **Spacing and grid**: 4/8 px scale, 12-column desktop grid, 4-column mobile.
- **Components**, each with all states (default, hover, focus, disabled, error, loading):
  buttons (primary, secondary, danger, ghost), inputs (text, number with unit, money USD/KHR, phone, date range, barcode scan field), searchable select, multi-select chips, checkbox matrix (for role permissions), tabs, data table (sort, filter, column chooser, sticky header, row actions, bulk actions, pagination 20/50/100, empty state), cards and KPI tiles, badges and status pills, toasts, inline alerts, modal, side drawer, confirm-with-reason dialog, PIN pad dialog, witness dialog (second user + PIN), approval banner, stepper (for multi-step flows), timeline (status history), file/photo upload with preview, barcode/QR scanner view (mobile camera), branch switcher, language toggle, notification bell, command search (Ctrl+K), skeleton loaders, chart styles (line, bar, donut) for dashboard and reports.
- **Status vocabularies** (use the same pill everywhere):
  invoice: draft, completed, partly returned, returned, cancelled ·
  PO: draft, sent, partly received, received, cancelled ·
  Rx: draft, active, partly dispensed, fully dispensed, expired, cancelled ·
  transfer: requested, approved, picking, in transit, received, closed, discrepancy, cancelled ·
  stock take: open, counting, review, pending owner approval, approved ·
  sale order: quote, order, partly fulfilled, closed, cancelled ·
  batch: available, near expiry, expired, quarantined, recalled.

## 4. App shell
- Left sidebar (collapsible to icons) with the menu below; header with: branch switcher (or "All branches" for owner), Ctrl+K search, language toggle KM/EN, notification bell (approvals, alerts), user menu (profile, PIN, 2FA, logout).
- Mobile: bottom tab bar (Home, POS, Scan, Approvals, More) and the full menu under More.
- Every page: title, breadcrumb, primary action top-right, filters row, content.

## 5. Navigation menu (group → items)
1. **Dashboard**: Dashboard
2. **POS**: POS · Sale Template · Sale Suspend · Sale Order · List Sale · Sale Return · List Commission · Items Promotion
3. **Prescriptions**: Patients · Doctors · Prescriptions · Dispense from Rx
4. **Controlled drugs**: Register · Discrepancies · Witness sign-offs · Register export
5. **Stock**: Stock on hand · Batches & expiry · Stock Take · Shelf locations · Re-order list · Recall
6. **Warehouse**: Product (medicines) · Hamper · Import Product · Print Label · Initialize (opening stock)
7. **Purchase**: Purchase Request · Purchase Order · Receiving Goods · Purchase Payment · Supplier Return
8. **Transfer**: Stock Transfer Request · Stock Transfer · Shrinkage
9. **Contacts**: Customer Group · Customer · Supplier Group · Supplier
10. **Report**: Sale Detail · Sale Margin By Item · Sale Product Package · Sale Return Detail · Shrinkage · Stock · Expire · Expire Alert · Movement Detail · Modification · Cost Change · Purchase By Item · Stock Transfer · Re-order · Transaction Payment · Receivables Aging · Payables Aging · Commission · Rx Dispensing · Controlled Summary · Branch Comparison
11. **User Management**: User · Role · User Log · Commission rules
12. **Settings**: Branches · Branch settings · Exchange rate · Telegram notifications · Feature switches · My profile (password, PIN, 2FA)

Hide menu items the current role has no permission for; never show cost or profit columns to users without the cost permission.

## 6. Screens to design (desktop + mobile where marked 📱)

### Auth
Login (phone + password) 📱 · 2FA code step 📱 · 2FA setup (QR code, secret, confirm code) · Account locked (shows unlock time) · Forced 2FA setup notice for owner/manager · Set/Change PIN 📱 · Session expired.

### Dashboard 📱
KPI tiles: today's sales, invoices, average basket, gross profit (owner only), each vs yesterday and same day last week. Charts: sales by hour, last 30 days, by branch. Lists: top medicines, low stock, near expiry, open controlled discrepancies, pending approvals (one tap to approve), debtors. Owner: All branches view + branch comparison.

### POS (most important; design in full detail)
- Layout: left = cart lines (medicine, pack unit selector box/strip/tablet, batch with expiry (FEFO default, changeable), qty, price, discount, line total, badges); right = customer, totals, payment. Large search/scan field always focused.
- Cart line badges: Rx-only, Controlled, Promotion applied (show name and saving), Hamper (expandable components), Near expiry.
- Flows to show as separate frames:
  1. Simple cash sale: scan → pay in USD, KHR or mixed → change in both currencies with KHR rounding → print 80 mm receipt.
  2. Rx-only item added → "Link prescription" drawer (search patient by phone, pick active Rx item, shows remaining qty and repeats) → **pharmacist required** state if a cashier is logged in.
  3. **Allergy warning** modal (patient allergy matches ingredient/class): pharmacist overrides with typed reason, or removes item. **Duplicate therapy** acknowledgement.
  4. **Hard stops**: expired batch, expired Rx, quantity above Rx remaining (RX_QUANTITY_EXCEEDED), out of stock.
  5. Controlled drug sale: Rx + patient ID + pharmacist PIN pad.
  6. Manual discount above role cap → approval by a different user with PIN.
  7. Pay later (credit) with credit-limit check (CREDIT_LIMIT_EXCEEDED); KHQR payment with QR display and waiting state.
  8. Suspend cart (note) and resumed-cart screen listing price/stock changes.
  9. Below-cost block.
- Sale Template list + load into cart · Suspended carts list · Sale Order (quote → order, deposit, stock hold until date, partial invoice, cancel with deposit rule) · List Sale (filters, reprint, cancel with reason) · Invoice detail (lines, batches, payments, Rx links, promotion savings, status timeline, audit) · Sale Return (choose lines, reason, opened-pack rule, refund or credit, return goes to quarantine) · Commission list (own / branch, period open/closed/paid) · Promotion editor (6 types: % / amount off, buy X get Y, bundle price, quantity tiers, customer-group price; date/time window, days, branches, groups, limits, stackable/exclusive, preview).

### Prescriptions
Patients list (search name/phone) · Patient detail (profile, allergies, chronic conditions, Rx history, dispensing history; "linked from another branch" notice) · Find patient from another branch by exact phone (audited notice) · Doctors list/detail · New Rx (patient, doctor, dates, items with dose/frequency/duration/repeats, photo/PDF upload 📱 camera capture) · Rx detail (balance per item: prescribed, dispensed, remaining, repeats used; attachments viewer; cancel with reason) · Dispensing label preview (70×40 mm, KM/EN).

### Controlled drugs
Register by medicine and branch (running balance, reference, actor, witness, hash-verified badge) · Entry detail · Destroy / adjust with PIN + witness (witness must be manager/owner for destruction) · Discrepancies (register vs stock, explain + close with witness) · Chain verification result (valid / broken) · Register PDF export.

### Stock
Stock on hand (per branch, per batch, value for permitted users) · Batches & expiry (filters 30/90/180 days, expired, quarantined; release quarantine needs pharmacist + reason) · Stock Take: create (full / category / location / controlled only) → counting 📱 (blind: no expected qty, scan barcode, pick batch, enter qty) → second count for controlled/high value 📱 → review (variance qty and value) → approve / owner approval · Shelf locations · Re-order list (on hand, in transit, on PO, suggested qty, supplier, last cost; one tap to purchase request or transfer request; transfer-source suggestions) · Recall.

### Warehouse
Medicines list · Medicine detail (tabs: info, pack units & prices, batches, ingredients & drug classes, Rx/controlled flags, price history) · Add/Edit medicine · Hamper editor (components, price, availability) · Import Product (upload Excel → validation results with row errors → commit) · Print Label (shelf and barcode labels, preview) · Initialize opening stock (batch, expiry, cost per branch → validate → commit → locked).

### Purchase
Purchase Request (create, approve/reject with reason, convert to PO or fill by transfer, status follow-through) · Purchase Order (create, combined group of POs per branch with group printout, send PDF, cancel with reason) · Receiving Goods 📱 (per line: lot, expiry, qty, cost; quick stock-in without PO) · Purchase Payment (allocate to oldest bills, overpayment refused) · Supplier Return.

### Transfer
Transfer Request · Stock Transfer: pick (FEFO, override with reason) → dispatch (controlled: PIN + witness) → in transit → receive 📱 (scan QR on transfer note, enter received qty) → discrepancy resolution (write-off or return to source) · Shrinkage (reason, photo, value, approval above threshold, controlled needs witness).

### Contacts
Customer groups (price level, default discount) · Customers (list, detail with balance, credit limit (owner/manager only), payments, statement PDF, deposits) · Supplier groups · Suppliers (terms, balance, bills, payments).

### Reports
One consistent report template: filter bar (date range, branch, staff, category, supplier, customer), summary tiles, chart, table, export menu (CSV, XLSX, PDF). Design the template once, then show 4 concrete examples: Sale Detail, Sale Margin By Item (owner), Expire Alert, Controlled Summary. Show the "cost hidden" version for a manager without permission.

### User Management & Settings
Users (create, edit role + branches, pharmacist flag, deactivate, reset password, reset 2FA) · Roles (permission checklist matrix grouped by area; owner role locked) · User Log (filterable audit trail with before/after diff) · Commission rules · Branches and branch settings (Rx validity days, controlled Rx days, label size, thresholds, deposit rule, opened-pack returns, receipt header) · Exchange rate with history · Telegram (chat IDs per branch/owner, test message, message log) · Feature switches · My profile.

## 7. Shared states (design once, reuse)
Empty (with the next action), loading skeleton, server error with retry, offline banner (POS can keep scanning; show sync pending), 403 "You don't have permission", 404, MFA_SETUP_REQUIRED, account locked, PIN locked, session expired, toasts for success/failure, and inline field errors. Map error codes to friendly KM/EN messages: OUT_OF_STOCK, CREDIT_LIMIT_EXCEEDED, RX_REQUIRED, PHARMACIST_REQUIRED, RX_QUANTITY_EXCEEDED, DISCOUNT_APPROVAL_REQUIRED, BELOW_COST, HAMPER_NOT_STOCKED, PERIOD_LOCKED, SUPPLIER_OVERPAYMENT, DUPLICATE_PHONE, PIN_LOCKED, INVALID_MFA_CODE.

## 8. Print layouts
80 mm receipt (KM/EN, USD + KHR, exchange rate, promotion savings, QR of invoice number) · A4 invoice · A4 quote/sale order · Dispensing label 70×40 mm and 50×30 mm · Shelf/barcode label · PO and PO group printout · Transfer note with QR · Controlled register PDF · Customer statement.

## 9. Sample data (use realistic, consistent data)
Branches: PP1 Phnom Penh – Toul Kork, PP2 Phnom Penh – BKK1, SR1 Siem Reap. Staff with Khmer names in both scripts (e.g. សុខ ដារ៉ា / Sok Dara). Medicines: Paracetamol 500 mg (box 10×10), Amoxicillin 500 mg (Rx-only), Cetirizine 10 mg, ORS sachet (buy 2 get 1), Diazepam 5 mg (controlled), Omeprazole 20 mg, First-aid kit (hamper). Exchange rate 4,100 KHR/USD. Show expiry dates near, past and far.

## 10. Deliverables and order
1. Design system page (tokens, type, components, badges, states).
2. App shell desktop + mobile, both languages.
3. POS with all 9 flows (desktop, then the mobile/tablet lite version).
4. Remaining modules in menu order.
5. Print layouts.
For every screen: frame name "Group / Screen / Device / Language", note the role(s) that can see it, and a small "API" tag naming the endpoint it uses (e.g. `POST /api/sales/v1/invoices`). Show Khmer and English versions for the shell, POS, login, dashboard and one report; other screens may use one language plus a note.
