# Front end: plan (waiting for "go")

Sources:
- the design handoff in `docs/design/` (152 frames, `tokens.json`, `error-messages.json`, `screens.md`);
- the current API (304 endpoints, `make openapi` → `openapi/*.json`, S8b included);
- CLAUDE.md.

Frame ids such as 3a or 12h refer to `docs/design/screens.md`. Endpoints are written without the `/api/` prefix.

## 1. Stack and layout

- **App:** `web/` uses React 19, TypeScript (strict) and Vite.
  - Routing: React Router (data routers).
  - Server state: TanStack Query.
  - Forms: react-hook-form with zod, where zod mirrors the OpenAPI request schemas.
  - Charts: Recharts.
  - QR codes: `qrcode` for the KHQR string.
  - Camera barcode and QR: `@zxing/browser`, falling back from `BarcodeDetector`.
  - Lint and format: ESLint and Prettier.
- **Styling:** Tailwind CSS.
  - `tailwind.config.ts` reads `docs/design/tokens.json`: colours, safety badges, status pills, type scale with a Khmer line-height variant, spacing, radii, shadows and breakpoints.
  - Fonts: Inter, Kantumruy Pro and JetBrains Mono, self-hosted with `@fontsource`. No Google Fonts at runtime, so the app works offline.
  - All numbers use tabular figures.
- **i18n:** react-i18next with `km` as the default and `en`.
  - The choice is remembered per device.
  - The `<html lang>` and font stack switch with the language.
  - Error codes map to `error-messages.json` and then to the API's own message.
  - Dates are DD/MM/YYYY in Asia/Phnom_Penh.
  - Money is USD plus KHR, with KHR rounded to 100 riel. The amounts always come from the API.
- **API client (`make api-types`):** runs `scripts/openapi.py` and then `openapi-typescript` on each `openapi/<service>.json`, writing `web/src/api/gen/<service>.ts` (generated, committed, never edited).
  - A typed `openapi-fetch` client per service (`web/src/api/clients.ts`) adds:
    - the bearer token;
    - one refresh on 401;
    - an `Idempotency-Key` on every operation whose OpenAPI lists it, with the key kept for retries of the same action;
    - parsing of `ErrorOut {code, message, details}` into a typed `ApiError`.
  - Pages call only these clients, through query hooks in `web/src/api/hooks/`.
  - A CI check fails if `web/src` calls `fetch` directly or uses a path that is not in the generated types.
- **PWA:** `vite-plugin-pwa`.
  - Manifest with KM/EN names and icons.
  - Service worker that precaches the app shell and fonts. API responses are never cached, except the F8 offline POS data, which follows F8's rules.
- **Serving:** a `web` service in docker-compose.
  - Multi-stage build: node builds `web/dist`, then `nginx:alpine` serves it.
  - SPA fallback to `index.html`; long cache for hashed assets; `no-cache` for `index.html` and `sw.js`.
  - Headers: CSP (`default-src 'self'`, `connect-src 'self'`, `img-src 'self' data: blob:`, no inline script), `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` (camera on self only).
  - Traefik router `PathPrefix(/)` at priority 1, so every `/api/...` router (10–100) wins. It is public (static files only) with the security headers middleware. `make up` serves the app at http://localhost and the APIs stay at `/api/*`.
- **Folder layout:**
  - `web/src/app` (shell, router, providers);
  - `web/src/design` (tokens and components);
  - `web/src/features/<module>`;
  - `web/src/i18n/{km,en}/*.json`;
  - `web/src/api`;
  - `web/e2e` (Playwright).
- **Make targets:**
  - `make api-types`;
  - `make web-dev` (Vite on :5173, with `/api` proxied to http://localhost);
  - `make web-test` (typecheck, lint, Vitest with coverage, production build and a bundle-size check);
  - `make web-e2e` (Playwright against `BASE_URL`, default http://localhost, see choice D);
  - `make web-test-docker` (the same in a node container, like `make test-docker`).

## 2. Rules for every F-sprint (from your brief)

- **API.**
  - Only the generated clients.
  - No fake data, no mock endpoints in the app, no hard-coded sample rows.
  - A designed field the API does not return is hidden and listed under "missing".
  - Vitest uses MSW with fixtures typed from the generated types. Those fixtures exist only in tests.
- **Look and language.**
  - Match the frames.
  - KM and EN for every string.
  - Mobile layouts where a frame exists (390 px): shell, auth, POS lite, dashboard, stock count, receiving, transfer receive, Rx camera capture.
  - Every other screen is responsive down to 1024 px. Below that it scrolls rather than reflows.
- **Roles.**
  - Menu items come from `GET auth/v1/me` (`menu`, `permissions`).
  - Feature switches come from `GET branch/v1/features` (`hides`).
  - A route the role cannot use shows 403 (16e). Actions need `user.has(...)`.
  - Cost columns and tiles appear only when the API sent the field. Nothing is ever computed from a hidden value.
  - "Delete" never appears. Cancel and deactivate always ask for a reason when the API takes one.
- **Tests.**
  - Vitest covers logic (money and KHR display, error mapping, permission gating, cart state, i18n completeness: every key in km and en) and components (Testing Library plus `vitest-axe`).
  - Playwright covers the sprint's main flows against the running stack, per role (owner, branch_manager, pharmacist, cashier). The users and seed come from a fixture script that uses the public API (`web/e2e/seed.ts`, the same way `scripts/smoke.py` creates its data).
- **Done.**
  - `make web-test` and `make web-e2e` pass, and the backend `make test` stays green.
  - Commit `F<n>: <name>`, tick the sprint in CLAUDE.md.
  - Stop with verify steps and wait for "OK F<n+1>".

## 3. Sprints

Each sprint lists its screens, the endpoints they use, the endpoints that are **missing** and **design vs API**
(designed details the API does not support; they are hidden or adapted, never faked).

### F0: design system, app shell, auth, shared states

**Screens:**
- Design System: every component with its states. Built as components plus a `/dev/design` route, behind `APP_ENV=development`.
- App shell 2a–2f (sidebar expanded/collapsed with Ctrl B, branch switcher, Ctrl K, KM/EN, bell, user menu, mobile tabs, More).
- Auth 15a–15k (login, wrong password, 2FA code and backup code, 2FA setup with backup codes, forced 2FA, account locked with countdown, set PIN, backup codes).
- Shared states 16a–16j.
- Error map: `error-messages.json` plus every `ErrorOut` code.

**Endpoints:**
- auth: `login`, `login/2fa`, `refresh`, `logout`, `me`, `2fa/setup`, `2fa/enable`, `2fa/backup-codes`, `me/pin`;
- branch: `branches` (switcher), `features`;
- reports: `dashboard` (bell counts: `pending_approvals`, `open_controlled_discrepancies`);
- catalog: `medicines/search`, sales `invoices?number=`, customers `customers?q=`, prescription `patients?q=` (Ctrl K, each shown only with its permission).

**Missing:**
1. **Refresh token in an httpOnly cookie.** Today `/login` and `/refresh` return the refresh token in the body, so the browser would keep it in JS storage. See choice B.
2. **Attempts left on a wrong password.** 15b shows "2 tries left": `details.attempts_left` on the 401. Without it the line is hidden.
3. **Unlocking a PIN lockout.** 16g says "the Owner can unlock now", for example `POST auth/v1/users/{id}/pin/unlock`. Today `DELETE users/{id}/pin` only clears the PIN. Without it the button is hidden.
4. **A request id for "Copy error ID".** 16c needs an `X-Request-ID` response header. Today no header is set.
5. **A bell feed.** The bell needs a per-user alert list, for example `GET notifications/v1/inbox`. Without it the bell shows only the dashboard's pending counts.

**Design vs API:**
- "Forgot password?" (15a) has no self-service API. It becomes the existing "Trouble signing in? Contact your owner" line.

**Also built in F0:**
- the `web/` scaffold;
- `make api-types`, `web-*` targets;
- the nginx `web` service and Traefik route;
- the PWA shell;
- the e2e seed script.

**e2e:**
- each role logs in (with 2FA for the owner and manager);
- the menu shows only permitted groups;
- the cashier gets 403 on a cost route;
- account lockout shows the Phnom Penh unlock time;
- 2FA setup with backup codes, then login with a backup code;
- language switch persists.

### F1: POS (all 9 flows, using `/carts/preview`)

**Screens:**
- 3a–3o:
  1. cash sale in USD, KHR or mixed, with change and receipt;
  2. Rx line, the link-Rx drawer, and "pharmacist required";
  3. allergy override and duplicate-therapy acknowledgement;
  4. hard stops;
  5. controlled sale with Rx, ID and PIN;
  6. discount approval with a witness PIN;
  7. credit limit check and KHQR;
  8. suspend and resume with changes;
  9. below cost.
- POS lite 4a–4e (phone and tablet).
- POS back office 12a–12h (templates, suspended carts, sale order, list sale with cancel, invoice detail, sale return, commission list, promotion editor with preview).
- Printing 17a/17b/17d/17e through render.
- POS dark variant.

**Endpoints:**
- sales:
  - `carts/preview` after every cart change, debounced. It drives the badges, hard stops, warnings and `can_post`, and the Pay button stays disabled until `can_post`;
  - `invoices` (create, list, get, cancel, returns), `carts/suspend`, `carts`, `carts/{id}/resume`, `sale-templates` (+ `load`), `sale-orders` (+ `confirm`, `invoice`, `cancel`, `close`), `commission/report` (+ drill-down, periods close and paid), `payments/khqr` (+ status poll), `exchange-rates/{branch}` (current rate);
- catalog: `medicines/search`, `hampers`, `promotions` (+ `preview`);
- inventory: `batches?medicine_id=` (pharmacist batch override), `hampers/{id}/availability`;
- customers: `customers?q=`, `customers/{id}`;
- prescription: `patients?q=`, `prescriptions?patient_id=&status=active`, `prescriptions/{id}/remaining`;
- auth: `pin/verify`, `pin/witness`, `pin/witnesses`;
- documents: `render` (`receipt_80mm`, `invoice_a4`, `sale_order`, `dispensing_label`).

**Missing:**
1. **POS quick keys.** The tablet favourites row (4e) needs something like `GET sales/v1/quick-items?branch_id=`. The top-medicine report needs `reports.sales`, which a cashier does not have. Without it the row is hidden.

**Design vs API:**
- Pharmacist hand-off (3e) uses suspend, then the pharmacist resumes. There is no hand-off endpoint.
- A return refund over $20 needing a manager (12f) is not an API rule. Hidden.
- Promotion "priority", a daily time window and "limit per invoice" (12h) are not in `PromotionCreate`. Hidden. Days, dates, branches, groups and the total/per-customer limits are shown.
- `carts/price` is not used (deprecated).

**e2e:**
- cashier: cash sale in USD and KHR with the change amounts and the receipt PDF;
- cashier: an Rx line is blocked as PHARMACIST_REQUIRED before payment;
- pharmacist: Rx link, allergy override, controlled sale with PIN;
- cashier: discount above cap approved by the manager's witness PIN;
- credit over limit is blocked;
- KHQR paid through the dev fake-pay;
- suspend and resume showing changes;
- below cost blocks a cashier;
- cancel and return.

### F2: Prescriptions and controlled drugs

**Screens:**
- 6a–6h (patients, patient detail with allergies and linked-branch notice, find in another branch, doctors, new Rx with camera capture on mobile, Rx detail, cancel);
- 12i (dispense from Rx);
- 7a–7f (register, entry detail, destroy or adjust with PIN and witness, discrepancies, chain verification, register PDF);
- 18h (correction);
- `rx_summary` and `dispensing_label` printing.

**Endpoints:**
- prescription: `patients` (+ `link`, `allergies`, remove allergy, deactivate/activate), `doctors`, `prescriptions` (create, patch, `activate`, `cancel`, `remaining`, `attachments` upload and download);
- controlled: `register`, `register/verify`, `entries`, `entries/{id}`, `entries/correction`, `discrepancies`, `discrepancies/{id}/resolve`;
- auth: `pin/verify`, `pin/witness`, `pin/witnesses`;
- catalog: `medicines/search`;
- documents: `render` (`controlled_register`, `rx_summary`, `dispensing_label`).

**Missing:**
1. **Patient dispensing history (6b).** It needs dates, invoice, quantity and pharmacist per line, for example `GET prescription/v1/patients/{id}/dispensings`. Prescription already receives the invoice events. Without it the tab shows only Rx balances.
2. **Dispensing-label preview before dispensing (6f).** Render needs an `invoice_id`. Without a preview endpoint the label prints only for dispensed lines.

**Design vs API:**
- Discrepancy resolution (7d) offers "adjust stock to register" and "report as loss". The API resolves with a reason and an optional correction entry (register = stock). The screen shows the API's two outcomes.
- "A broken chain freezes dispensing" (7e) is not API behaviour (it alerts only). The sentence is hidden.
- The destroy dialog's "photo attached" note (7c) has no controlled entry photo. Hidden.

**e2e:**
- pharmacist creates a patient with an allergy and an Rx with an attachment;
- cashier cannot open Prescriptions;
- find a patient from another branch by exact phone;
- destroy controlled stock with a manager witness; a pharmacist witness is refused;
- correction entry;
- chain verify;
- register PDF.

### F3: Warehouse and stock (incl. mobile stock count)

**Screens:**
- stock on hand 2a/2b, with value only with cost;
- 8a–8g (batches and expiry, release quarantine, stock take create and review/approve, re-order list, shelf locations, recall);
- 8h/8i (mobile blind count with camera scan, second count);
- 9a–9g (medicines list, detail, add/edit, hamper editor, Excel import, print label, initialize);
- 12n (medicine detail with price history);
- 18a (categories and brands), 18b (re-order settings), 18d (movements), 18e (opening-stock upload).

**Endpoints:**
- inventory: `stock`, `batches`, `movements`, `quarantine/release`, `shelf-locations`, `reorder-settings` (+ `bulk`), `reorder-lists/run` / `latest` / `{id}/purchase-requests` / `{id}/transfer-requests`, `recalls` (+ detail, line `return` / `destroy`, `close`, `lift`), `opening-balances` (template, upload, list, get, commit), `initialize-locks` (+ unlock), `hampers/{id}/availability`;
- stockcount: all 10 (`counts`, `lookup`, `entries`, `submit`, `recount`, `review`, `approve` with PIN, `cancel`);
- catalog: `categories`, `brands`, `medicines` (CRUD, `pack-units`, `export.xlsx`, `price-history`), `imports` (template, upload, list, get, commit), `hampers` (+ `components`);
- sales: `invoices/by-batches` (recall: affected sales);
- reports: `stock/abc` (ABC column in 18b);
- documents: `render` (`label`).

**Missing:** none blocking.

**Design vs API:**
- Price history 12n shows cost and margin, but the catalog has no cost. It shows sell prices; the cost history is the Cost Change report (F6).
- Categories "code" and brands "manufacturer, country" (18a) are not fields. Hidden.
- Re-order "runs daily 06:00, next run" (18b): the job runs at 00:30 and the run time is not exposed. Hidden.

**e2e:**
- import sample products with validate then commit;
- print shelf labels;
- initialize opening stock and see the branch locked;
- mobile stock take with blind count and second count, then owner approve;
- recall a lot, then sale blocked and recall closed;
- release quarantine as pharmacist;
- re-order list to purchase request.

### F4: Purchase and transfer (incl. mobile receiving)

**Screens:**
- 10a (purchase requests: approve, then route to PO or fill by transfer);
- 10b (PO group), 12j (PO create);
- 10c (supplier payment, overpayment refused);
- 10d (supplier return);
- 10e (mobile receiving with lot, expiry, qty and cost per line), 10f (mobile quick stock-in);
- 18f (receipts and supplier payments);
- 12k (transfer request);
- 11a–11d (transfers, FEFO pick, controlled dispatch with PIN and witness, differences);
- 11e (shrinkage, with approve/reject);
- 11f/11g (mobile receive by QR);
- printing 17f/17g/17i and the supplier return note.

**Endpoints:**
- purchasing: `purchase-requests` (+ `approve`, `reject`, `cancel`, `fill-by-transfer`, `to-purchase-orders`), `purchase-orders` (+ `send`, `cancel`, `receive`), `po-groups/{id}`, `receipts`, `supplier-payments` (+ `cancel`), `suppliers/{id}/balance` / `statement`, `supplier-returns` (+ `submit`, `cancel`);
- inventory: `stock-in`, `transfer-requests` (+ approve/reject/cancel), `transfers` (+ push, `in-transit`, `by-number`, `pick`, `dispatch`, `receive`, differences `resolve`, `cancel`), `shrinkages` (+ approve, reject, photo);
- auth: `pin/verify`, `pin/witness`;
- reports: `purchases/cost-changes` ("last cost" on 12j, with `reports.purchases`);
- documents: `render` (`purchase_order`, `purchase_order_group`, `transfer_note`, `supplier_return`).

**Missing:**
1. **Stock at other branches.** The transfer request (12k) shows "PP2 / PP1 on hand", but a manager sees only their own branches. It needs quantity per active branch with no cost and no batches, for example `GET inventory/v1/availability?medicine_ids=`. Without it only own-branch columns show.
2. **Photo uploads.** Receiving (10e/10f, the supplier invoice photo) and transfer receive (11g) have no upload endpoint. Without them the buttons are hidden.

**Design vs API:**
- "Allocate manually" (10c): the API allocates to the oldest bills first. Hidden.
- "Replacement goods" (10d): the API settles by credit or refund only. Hidden.
- Stock-in "manager approval above $200" (10f) and transfer request "owner approval above $200" and "priority" (12k) are not API rules. Hidden.
- 10a approves the whole request, then routes lines with two separate actions. The design shows routing per line on approve, so the screen does approve first, then the routing actions.

**e2e:**
- manager: PR, then PO group, then send PDF;
- pharmacist: mobile receive with 2 lots and the PO partly received;
- pay to 0, then overpayment is refused;
- supplier return as credit;
- transfer request, approve, FEFO pick, controlled dispatch with a witness, mobile QR receive with a short line, resolve write-off;
- shrinkage above the threshold approved by another user.

### F5: Contacts

**Screens:**
- 12a (customer groups), 12b (customers), 12c (customer detail with balance, limit, unpaid, deposits and statement);
- 18g (customer payments);
- 12l (suppliers and supplier groups), 12d (supplier detail with bills, payments, POs and returns);
- 17h (customer statement PDF).

**Endpoints:**
- customers: `customer-groups` (+ deactivate/activate), `customers` (CRUD, deactivate/activate, `unpaid`, `statement`, `deposits`), `customer-payments` (+ `cancel`);
- purchasing: `suppliers`, `supplier-groups`, `suppliers/{id}/balance` / `statement`, `receipts?supplier_id=`, `supplier-payments?supplier_id=`, `purchase-orders?supplier_id=`, `supplier-returns`;
- documents: `render` (`customer_statement`).

**Missing:**
1. **Customer list columns.** The list (12b) shows "credit used", "oldest unpaid" and "deposits". It needs `oldest_unpaid_on` and a deposit total in `CustomerPage` items; one request per row is not acceptable. Without them only the balance and limit columns show.

**Design vs API:**
- Customer group "price level", "default credit limit" and "stacks with promotions" (12a) do not exist; groups have only `default_discount_pct`. Hidden.
- Customer payment terms, due dates and overdue aging (12c) do not exist: debts have no due date. The screen shows invoice age, not "overdue".
- Customer payment in KHR (18g): `PaymentCreate` is USD only. The KHR field is hidden.
- Supplier VAT TIN, contact person and early-payment discount (12d) are not fields. Hidden.

**e2e:**
- manager sets a credit limit; a cashier cannot;
- record a payment oldest-first, then cancel it with a reason;
- statement PDF in km and en;
- deactivate a customer;
- supplier detail balance matches the payments.

### F6: Dashboard and reports

**Screens:**
- 5a–5d (owner all-branches with comparison, manager own branch, mobile);
- 13a–13p (one report template: filters, tiles, chart, table, totals, export CSV/XLSX/PDF, cost-hidden variant);
- the remaining menu reports through the same template, driven by `reports/v1/catalog`.

**Endpoints:**
- reports: `dashboard`, `catalog`, and all 29 report endpoints with `format=csv|xlsx|pdf`, plus `sales/summary?by=day|branch` for the 30-day and by-branch charts;
- inventory, stockcount and purchasing list endpoints for the approval items behind the dashboard's pending counts (`shrinkages?status=pending`, `counts?status=submitted`, `transfer-requests`, `purchase-requests`), with approve actions calling the existing approve endpoints.

**Missing:**
1. **Sales by hour (5a).** It needs `by=hour` on `sales/summary`, or an hourly series on the dashboard. Without it the chart is hidden.

**Design vs API:**
- "Discount 18% waiting for approval" on the dashboard: discount approval is synchronous (a witness PIN at the till). Not shown.
- Report columns the API does not have, such as "suggested action" (13e, 13k), are hidden. The template renders exactly the columns of each report's typed model (S8b).
- "Save view" (13a) is kept per device in localStorage (filters only, no data). If it must follow the user, it needs an endpoint; say so.

**e2e:**
- owner dashboard shows profit; manager without cost shows none;
- Sale Detail totals equal the invoices made in the run;
- margin report gives 403 to a cashier;
- CSV, XLSX and PDF downloads;
- a manager filtering another branch gets BRANCH_FORBIDDEN.

### F7: User management and settings

**Screens:**
- 14a (users: create, edit role and branches, pharmacist flag, deactivate, reset password, reset 2FA, clear PIN);
- 14b (roles: permission matrix, owner locked);
- 14c (User Log with before/after diff);
- 14d (commission rules);
- 14e (branches and branch settings, including `receipt_lang` and `khqr`);
- 14f (exchange rate with history);
- 14g (Telegram chats, test message, message log);
- 14h (feature switches);
- 14i (my profile: password, PIN, 2FA, sessions with revoke, backup codes 15k);
- 18c (notification settings).

**Endpoints:**
- auth: `users` (all), `roles`, `permissions`, `audit-logs`, `me/password`, `me/pin`, `2fa/*`, `me/sessions` (+ `revoke`);
- sales: `commission/rules` (+ deactivate), `commission/periods/*`, `exchange-rates/{branch}` (put, history);
- branch: `branches`, `branches/{id}/settings`, `features`;
- notifications: `chats`, `test`, `messages`, `settings`, `daily-summary/run`.

**Missing:**
1. **Notification settings (18c).** The design has alert toggles, daily summary on/off, send time, quiet hours, language, near-expiry window and low-stock rule. `SettingsOut` has only `large_discount_pct` and `large_discount_usd`, and the summary is fixed at 20:00. Without new fields only those two show.
2. **Daily summary preview (18c).** It needs something like `GET notifications/v1/daily-summary/preview?branch_id=`. `daily-summary/run` sends for real. Without it the preview panel is hidden.

**Design vs API:**
- Commission rules cannot be edited: deactivate, then add a new one.

**e2e:**
- owner creates a cashier and assigns branches; the cashier logs in and sees only POS menus;
- a role permission change shows in the User Log diff;
- exchange rate history pages;
- revoke a session ends it at once;
- regenerating backup codes needs the password.

### F8: Print layouts, offline POS sync, polish, accessibility

**Screens:**
- print preview and print for 17a–17i: render to PDF, show it in a sandboxed `<iframe>`, then `print()`. The 80 mm receipt uses the API's PDF;
- offline POS 16d.

**Offline POS needs backend support that does not exist yet.** It is listed in S9 as "offline POS". It needs:
- a device catalog/price snapshot for a branch;
- posting a sale made offline with its original Idempotency-Key and the time it was made;
- reporting the conflicts when stock or price changed.

Without these, F8 can queue sales locally, but posting them later runs today's checks (e.g. OUT_OF_STOCK). See choice C.

**Polish and accessibility:**
- axe on every route in Playwright;
- keyboard paths (POS F2/F4/F8/F9/Esc, with focus back to the scan field after each action);
- focus rings, `prefers-reduced-motion`, 44 px touch targets on mobile, Khmer text never truncated (visual checks at 360 px);
- Lighthouse PWA and performance budget (POS first load < 2 s on a mid Android over 4G).

**Design vs API:**
- The barcode label is 38×25 mm in 17c but 40×25 mm in the API. The API size is used.

## 4. Choices (recommendation first)

**A. Missing endpoints**
- *Recommended:* a short backend sprint, **S8c "UI gaps"**, before F1. It would add:
  - the refresh cookie;
  - `attempts_left`;
  - PIN unlock;
  - `X-Request-ID`;
  - quick items;
  - patient dispensings;
  - cross-branch availability;
  - receipt and transfer photos;
  - the customer list aging fields;
  - `by=hour`;
  - notification settings fields and the summary preview.

  It follows the usual S-sprint rules, tests and smoke, and each F-sprint then has its API ready.
- *Alternative:* the F-sprints ship with those details hidden, and you pick later which gaps to build.

**B. Token storage**
- *Recommended:* the auth service sets the refresh token as an `HttpOnly; Secure; SameSite=Strict` cookie scoped to `/api/auth/v1`, and the access token lives in memory only. This is part of S8c and keeps tokens out of reach of injected script.
- *Alternative:* refresh token in `sessionStorage` (lost when the tab closes; readable by script).

**C. Offline POS**
- *Recommended:* move the offline part of F8 after S9's offline-POS backend work, and F8 does print, polish and accessibility only.
- *Alternative:* F8 also builds the backend part (snapshot and offline posting with conflicts).

**D. e2e target**
- *Recommended:* `make web-e2e` runs against `BASE_URL`, default http://localhost (`make up`). It creates its own users and branch through the public API, as the smoke does, and can point at the throwaway stack.
- *Alternative:* Playwright starts its own compose project each run, which is slower.

**E. Generated client**
- *Recommended:* `openapi-typescript` with `openapi-fetch`. These are types plus a thin typed fetch, and the hooks are written per feature.
- *Alternative:* `orval`, which generates TanStack Query hooks; it is heavier and harder to fit with Idempotency-Key and refresh.

**F. Which frames to build in F0**
- *Recommended:* the Design System page is built as a dev-only route (`/dev/design`) with every component state, and also used for visual tests.
- *Alternative:* components only, no page.
