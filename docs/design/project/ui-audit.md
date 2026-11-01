# Audit vs original prompt + api-audit fixes (31/10/2026)

Added in this pass: 17i single PO printout (was partial), 15k 2FA backup codes (was partial: setup step 3 only mentioned in a note).

| Section | Screen | Desktop | Mobile | Khmer | English | Roles | API tag | Status |
|---|---|---|---|---|---|---|---|---|
| 4 Shell | Sidebar + header (branch switcher, Ctrl+K, KM/EN, bell, user menu) | 2a, 2b | — | 2a | 2b | ✓ | GET /api/auth/v1/me | done |
| 4 Shell | Sidebar collapsed to icons | 2c | — | — | 2c | ✓ | GET /api/inventory/v1/stock | done |
| 4 Shell | Mobile bottom tabs (Home, POS, Scan, Approvals, More) | — | 2d, 2e | 2d | 2e | ✓ | GET /api/inventory/v1/stock | done |
| 4 Shell | Mobile More menu (full menu) | — | 2f | 2f | — | ✓ | GET /api/auth/v1/me | done |
| 4 Shell | Page pattern (title, breadcrumb, action, filters) + role-hidden items | all frames | — | ✓ | ✓ | ✓ | GET /api/auth/v1/me | done |
| 5 Menu | Dashboard → Dashboard | 5a–5d | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | POS → POS | 3a–3o | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | POS → Sale Template | 12a | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | POS → Sale Suspend | 12b | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | POS → Sale Order | 12c | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | POS → List Sale | 12d | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | POS → Sale Return | 12f | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | POS → List Commission | 12g | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | POS → Items Promotion | 12h | — | menu KM | menu EN | ✓ | see screen | API pending |
| 5 Menu | Prescriptions → Patients | 6a, 6b | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Prescriptions → Doctors | 6d | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Prescriptions → Prescriptions | 6e, 6f, 6g | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Prescriptions → Dispense from Rx | 12i | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Controlled → Register | 7a, 7b | — | menu KM | menu EN | ✓ | see screen | API pending |
| 5 Menu | Controlled → Discrepancies | 7d | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Controlled → Witness sign-offs | removed (same-device witness dialog) | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Controlled → Register export | 7f | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Stock → Stock on hand | 2a–2e | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Stock → Batches & expiry | 8a, 8b | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Stock → Stock Take | 8c, 8d, 8h, 8i | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Stock → Shelf locations | 8f | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Stock → Re-order list | 8e | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Stock → Recall | 8g | — | menu KM | menu EN | ✓ | see screen | API pending |
| 5 Menu | Stock → Movements (new) | 18d | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Stock → Re-order settings (new) | 18b | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Warehouse → Product (medicines) | 9a–9c, 12n | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Warehouse → Categories & brands (new) | 18a | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Warehouse → Hamper | 9d | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Warehouse → Import Product | 9e | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Warehouse → Print Label | 9f | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Warehouse → Initialize | 9g, 18e | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Purchase → Purchase Request | 10a | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Purchase → Purchase Order | 12j, 10b | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Purchase → Receiving Goods | 10e, 10f | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Purchase → Receipts (new) | 18f | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Purchase → Purchase Payment | 10c | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Purchase → Supplier Return | 10d | — | menu KM | menu EN | ✓ | see screen | API pending |
| 5 Menu | Transfer → Stock Transfer Request | 12k | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Transfer → Stock Transfer | 11a–11d, 11f, 11g | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Transfer → Shrinkage | 11e | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Contacts → Customer Group | Contacts 12a | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Contacts → Customer | Contacts 12b, 12c | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Contacts → Customer Payment (new) | 18g | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Contacts → Supplier Group | 12l | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Contacts → Supplier | 12l, Contacts 12d | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Sale Detail | 13a, 13b | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Sale Margin By Item | 13c, 13d | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Expire Alert | 13e | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Controlled Summary | 13f | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Sales Summary (new) | 13g | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Profit (new) | 13h | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Sale Cancellations (new) | 13i | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Discounts (new) | 13j | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Slow-moving Stock (new) | 13k | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → ABC Analysis (new) | 13l | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Purchase By Supplier (new) | 13m | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Top Customers (new) | 13n | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Stock Count Variances (new) | 13o | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Transfers In Transit (new) | 13p | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Sale Product Package | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Sale Return Detail | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Shrinkage | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Stock | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Expire | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Movement Detail | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Modification | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Cost Change | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Purchase By Item | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Stock Transfer | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Re-order | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Transaction Payment | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Receivables Aging | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Payables Aging | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Commission | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Rx Dispensing | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Report → Branch Comparison | report template (13a) · not drawn separately | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | User Management → User | 14a | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | User Management → Role | 14b | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | User Management → User Log | 14c | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | User Management → Commission rules | 14d | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Settings → Branches | 14e | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Settings → Branch settings | 14e | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Settings → Exchange rate | 14f (history pending) | — | menu KM | menu EN | ✓ | see screen | API pending |
| 5 Menu | Settings → Telegram notifications | 14g | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Settings → Notifications (new) | 18c | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Settings → Feature switches | 14h | — | menu KM | menu EN | ✓ | see screen | done |
| 5 Menu | Settings → My profile | 14i, 15k (sessions + backup codes pending) | — | menu KM | menu EN | ✓ | see screen | API pending |
| 6 Screens | Auth → Login | 15a, 15b | 15h | 15a | 15b | ✓ | ✓ | done |
| 6 Screens | Auth → 2FA code | 15c | 15i | 15i | 15c | ✓ | ✓ | API pending |
| 6 Screens | Auth → 2FA setup (QR, secret, confirm, backup codes) | 15d, 15k | — | — | ✓ | ✓ | ✓ | API pending |
| 6 Screens | Auth → Account locked (details.locked_until) | 15f | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Auth → Forced 2FA notice | 15e | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Auth → Set/Change PIN | 14i | 15j | 15j | 14i | ✓ | ✓ | done |
| 6 Screens | Auth → Session expired | 16h | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Dashboard → KPI tiles, charts, lists, approvals, owner all-branches + comparison | 5a, 5b | 5c, 5d | 5a, 5c | 5b, 5d | ✓ | ✓ | done |
| 6 Screens | POS → Sale Template list + load | 12a | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | POS → Suspended carts | 12b | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | POS → Sale Order | 12c | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | POS → List Sale | 12d | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | POS → Invoice detail | 12e | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | POS → Sale Return | 12f | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | POS → Commission list | 12g | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | POS → Promotion editor (6 types + preview) | 12h | — | — | ✓ | ✓ | ✓ | API pending |
| 6 Screens | POS → Mobile/tablet POS lite | 4e (tablet) | 4a–4d | ✓ | ✓ | ✓ | ✓ | done |
| 6 Screens | Prescriptions → Patients list | 6a | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Prescriptions → Patient detail (linked-branch notice) | 6b | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Prescriptions → Find patient other branch | 6c | — | 6c | — | ✓ | ✓ | done |
| 6 Screens | Prescriptions → Doctors list/detail | 6d | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Prescriptions → New Rx + camera capture | 6e | 6h | 6h | 6e | ✓ | ✓ | done |
| 6 Screens | Prescriptions → Rx detail + cancel | 6f, 6g | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Prescriptions → Dispensing label preview | 6f, 17c | — | ✓ | ✓ | ✓ | ✓ | done |
| 6 Screens | Controlled → Register by medicine/branch | 7a | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Controlled → Entry detail | 7b | — | — | ✓ | ✓ | ✓ | API pending |
| 6 Screens | Controlled → Destroy/adjust PIN + witness | 7c | — | 7c | — | ✓ | ✓ | done |
| 6 Screens | Controlled → Discrepancies | 7d | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Controlled → Chain verification | 7e | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Controlled → Register PDF export | 7f | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Stock → Stock on hand | 2a, 2b | 2d, 2e | ✓ | ✓ | ✓ | ✓ | done |
| 6 Screens | Stock → Batches & expiry + release quarantine | 8a, 8b | — | 8b | 8a | ✓ | ✓ | done |
| 6 Screens | Stock → Stock take create | 8c | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Stock → Counting (blind) | — | 8h | ✓ | — | ✓ | ✓ | done |
| 6 Screens | Stock → Second count | — | 8i | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Stock → Review + approve / owner approval | 8d | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Stock → Shelf locations | 8f | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Stock → Re-order list | 8e | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Stock → Recall | 8g | — | — | ✓ | ✓ | ✓ | API pending |
| 6 Screens | Warehouse → Medicines list | 9a | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Warehouse → Medicine detail tabs | 9b, 12n | — | — | ✓ | ✓ | ✓ | API pending |
| 6 Screens | Warehouse → Add/Edit medicine | 9c | — | 9c | — | ✓ | ✓ | done |
| 6 Screens | Warehouse → Hamper editor | 9d | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Warehouse → Import Product | 9e | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Warehouse → Print Label | 9f | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Warehouse → Initialize opening stock | 9g, 18e | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Purchase → Purchase Request | 10a | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Purchase → Purchase Order + PO group | 12j, 10b | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Purchase → Receiving Goods | — | 10e | 10e | — | ✓ | ✓ | done |
| 6 Screens | Purchase → Quick stock-in (no PO) | — | 10f | — | 10f | ✓ | ✓ | done |
| 6 Screens | Purchase → Purchase Payment | 10c | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Purchase → Supplier Return | 10d | — | — | ✓ | ✓ | ✓ | API pending |
| 6 Screens | Transfer → Transfer Request | 12k | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Transfer → Pick (FEFO) | 11b | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Transfer → Dispatch controlled PIN + witness | 11c | — | 11c | — | ✓ | ✓ | done |
| 6 Screens | Transfer → In transit list | 11a | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Transfer → Receive (scan QR, qty) | — | 11f, 11g | 11f | 11g | ✓ | ✓ | done |
| 6 Screens | Transfer → Discrepancy resolution | 11d | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Transfer → Shrinkage | 11e | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Contacts → Customer groups | 12a | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Contacts → Customers list | 12b | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Contacts → Customer detail (balance, limit, statement, deposits) | 12c | — | 12c | — | ✓ | ✓ | API pending |
| 6 Screens | Contacts → Supplier groups | 12l | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Contacts → Suppliers | 12d, 12l | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Reports → Report template | 13a | — | 13b | 13a | ✓ | ✓ | done |
| 6 Screens | Reports → Sale Detail | 13a, 13b | — | 13b | 13a | ✓ | ✓ | done |
| 6 Screens | Reports → Sale Margin By Item (owner) | 13c | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Reports → Cost hidden (manager) | 13d | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Reports → Expire Alert | 13e | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Reports → Controlled Summary | 13f | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Users & Settings → Users | 14a | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Users & Settings → Roles matrix | 14b | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Users & Settings → User Log diff | 14c | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Users & Settings → Commission rules | 14d | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Users & Settings → Branches + settings | 14e | — | 14e | — | ✓ | ✓ | done |
| 6 Screens | Users & Settings → Exchange rate + history | 14f | — | — | ✓ | ✓ | ✓ | API pending |
| 6 Screens | Users & Settings → Telegram | 14g | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Users & Settings → Feature switches | 14h | — | — | ✓ | ✓ | ✓ | done |
| 6 Screens | Users & Settings → My profile (sessions) | 14i | — | — | ✓ | ✓ | ✓ | API pending |
| 6 POS flows | 1 Cash sale USD/KHR/mixed + receipt | 3a, 3b, 3c | 4a–4c | ✓ | ✓ | ✓ | ✓ | done |
| 6 POS flows | 2 Rx-only → link Rx drawer → pharmacist required | 3d, 3e | 4a–4c | ✓ | ✓ | ✓ | ✓ | done |
| 6 POS flows | 3 Allergy override + duplicate therapy | 3f, 3g | 4a–4c | ✓ | ✓ | ✓ | ✓ | done |
| 6 POS flows | 4 Hard stops (expired batch, expired Rx, RX_QUANTITY_EXCEEDED, out of stock) | 3h | 4a–4c | ✓ | ✓ | ✓ | ✓ | done |
| 6 POS flows | 5 Controlled sale: Rx + patient ID + PIN | 3i | 4a–4c | ✓ | ✓ | ✓ | ✓ | done |
| 6 POS flows | 6 Discount above cap → approval with PIN | 3j | 4a–4c | ✓ | ✓ | ✓ | ✓ | done |
| 6 POS flows | 7a Pay later credit limit | 3k | 4a–4c | ✓ | ✓ | ✓ | ✓ | done |
| 6 POS flows | 7b KHQR QR + waiting | 3l, 4d | 4d | ✓ | ✓ | ✓ | ✓ | API pending |
| 6 POS flows | 8 Suspend + resumed changes | 3m, 3n | 4a–4c | ✓ | ✓ | ✓ | ✓ | done |
| 6 POS flows | 9 Below-cost block | 3o | 4a–4c | ✓ | ✓ | ✓ | ✓ | done |
| 7 Shared states | Empty | 16a | — | ✓ | ✓ | — | — | done |
| 7 Shared states | Loading skeleton | 16b | — | ✓ | ✓ | — | — | done |
| 7 Shared states | Server error + retry | 16c | — | ✓ | ✓ | — | — | done |
| 7 Shared states | Offline + sync pending | 16d | — | ✓ | ✓ | — | — | done |
| 7 Shared states | 403 | 16e | — | ✓ | ✓ | — | — | done |
| 7 Shared states | 404 | 16f | — | ✓ | ✓ | — | — | done |
| 7 Shared states | MFA_SETUP_REQUIRED | 15e | — | ✓ | ✓ | — | — | done |
| 7 Shared states | Account locked | 15f | — | ✓ | ✓ | — | — | done |
| 7 Shared states | PIN locked | 16g | — | ✓ | ✓ | — | — | done |
| 7 Shared states | Session expired | 16h | — | ✓ | ✓ | — | — | done |
| 7 Shared states | Toasts | 16i | — | ✓ | ✓ | — | — | done |
| 7 Shared states | Inline field errors | 16j | — | ✓ | ✓ | — | — | done |
| 7 Shared states | Error code map KM/EN (13 codes) | Design System | — | ✓ | ✓ | — | — | done |
| 8 Print | 80 mm receipt KM + EN | 17a, 17b | — | ✓ | ✓ | — | ✓ | done |
| 8 Print | A4 invoice | 17d | — | ✓ | ✓ | — | ✓ | done |
| 8 Print | A4 quote / sale order | 17e | — | ✓ | ✓ | — | ✓ | done |
| 8 Print | Dispensing label 70×40 + 50×30 | 17c | — | ✓ | ✓ | — | ✓ | done |
| 8 Print | Shelf / barcode label | 17c | — | ✓ | ✓ | — | ✓ | done |
| 8 Print | PO (single) | 17i | — | ✓ | ✓ | — | ✓ | done |
| 8 Print | PO group printout | 17f | — | ✓ | ✓ | — | ✓ | done |
| 8 Print | Transfer note with QR | 17g | — | ✓ | ✓ | — | ✓ | done |
| 8 Print | Controlled register PDF | 7f | — | ✓ | ✓ | — | ✓ | done |
| 8 Print | Customer statement | 17h | — | ✓ | ✓ | — | ✓ | API pending |
| New (audit) | Categories & brands | 18a | — | — | ✓ | ✓ | ✓ | done |
| New (audit) | Re-order settings | 18b | — | — | ✓ | ✓ | ✓ | done |
| New (audit) | Notification settings + daily summary | 18c | — | — | ✓ | ✓ | ✓ | done |
| New (audit) | Inventory movements | 18d | — | — | ✓ | ✓ | ✓ | done |
| New (audit) | Opening-stock upload | 18e | — | — | ✓ | ✓ | ✓ | done |
| New (audit) | Receipts + supplier payments | 18f | — | — | ✓ | ✓ | ✓ | done |
| New (audit) | Customer payments | 18g | — | — | ✓ | ✓ | ✓ | done |
| New (audit) | Controlled register correction (PIN + witness) | 18h | — | — | ✓ | ✓ | ✓ | done |
| New (audit) | 2FA backup codes (shown once, regenerate) | 15k | — | — | ✓ | ✓ | ✓ | API pending |

## Totals
- done: 194
- API pending: 19
- Rows: 213
