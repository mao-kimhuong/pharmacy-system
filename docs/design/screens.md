# Screen list (generated from docs/design/project)

Every frame of the handoff: file, frame id, name (Group / Screen / Device / Language), roles and the API tag the
designer wrote. The API tags are the designer's guesses at design time; the real endpoint per screen is the one its
page in `web/src/features/` calls. Status per screen (desktop / mobile / KM / EN): `project/ui-audit.md`.

| File | Frame | Name | Roles | Design API tag |
|---|---|---|---|---|
| App Shell | 2a | Shell / Stock on hand / Desktop 1366 / KM | Owner · all branches |  |
| App Shell | 2b | Shell / Stock on hand / Desktop 1366 / EN | Cashier · PP1 · no cost, no Rx menus |  |
| App Shell | 2c | Shell / Stock on hand / Desktop 1366 / EN · sidebar collapsed | Pharmacist · PP1 |  |
| App Shell | 2d | Shell / Stock on hand / Mobile 390 / KM | Manager · PP1, PP2 | GET /api/inventory/v1/stock |
| App Shell | 2e | Shell / Stock on hand / Mobile 390 / EN | Manager · PP1, PP2 | GET /api/inventory/v1/stock |
| App Shell | 2f | Shell / More menu / Mobile 390 / KM | Pharmacist · menu filtered by role | GET /api/auth/v1/me (permissions, menu) |
| Auth | 15a | Auth / Login / Desktop 1366 / KM |  | POST /api/auth/v1/login |
| Auth | 15b | Auth / Login – wrong password / Desktop 1366 / EN |  | POST /api/auth/v1/login → 401 |
| Auth | 15c | Auth / 2FA code – invalid / Desktop 1366 / EN |  | POST /api/auth/v1/login/2fa → INVALID_MFA_CODE · backup_code ⚠ API pending |
| Auth | 15d | Auth / 2FA setup / Desktop 1366 / EN |  | POST /api/auth/v1/2fa/setup · POST …/2fa/enable · GET …/2fa/backup-codes ⚠ API pending |
| Auth | 15e | Auth / Forced 2FA notice / Desktop 1366 / EN |  | GET /api/auth/v1/me → MFA_SETUP_REQUIRED |
| Auth | 15f | Auth / Account locked / Desktop 1366 / EN |  | POST /api/auth/v1/login → error details.locked_until |
| Auth | 15h | Auth / Login / Mobile 390 / KM |  | POST /api/auth/v1/login |
| Auth | 15i | Auth / 2FA code / Mobile 390 / EN |  | POST /api/auth/v1/login/2fa |
| Auth | 15j | Auth / Set PIN – confirm / Mobile 390 / KM |  | PUT /api/auth/v1/me/pin |
| Shared States | 16a | Empty · with next action |  |  |
| Shared States | 16b | Loading skeleton · table + tiles |  |  |
| Shared States | 16c | Server error · retry |  |  |
| Shared States | 16d | Offline · POS keeps scanning |  |  |
| Shared States | 16e | 403 · no permission |  |  |
| Shared States | 16f | 404 · not found |  |  |
| Shared States | 16g | PIN locked |  |  |
| Shared States | 16h | Session expired · re-enter password |  |  |
| Shared States | 16i | Toasts · success / failure / undo |  |  |
| Shared States | 16j | Inline field errors · form submit |  |  |
| POS | 3a | POS / Cash sale – payment / Desktop 1366 / KM | Cashier, Pharmacist, Manager, Owner | POST /api/sales/v1/invoices |
| POS | 3b | POS / Cash sale – payment / Desktop 1366 / EN | Cashier, Pharmacist, Manager, Owner | POST /api/sales/v1/invoices |
| POS | 3c | POS / Sale complete + receipt / Desktop 1366 / EN | All POS roles | POST /api/documents/v1/render (receipt_80mm) |
| POS | 3d | POS / Link Rx drawer / Desktop 1366 / EN | Pharmacist | GET /api/prescription/v1/patients?q= · GET …/prescriptions/{rx_id}/remaining |
| POS | 3e | POS / Pharmacist required / Desktop 1366 / KM | Cashier (blocked state) | POST /api/auth/v1/pin/verify |
| POS | 3f | POS / Allergy override / Desktop 1366 / EN | Pharmacist (override) · Cashier sees remove only | POST /api/sales/v1/carts/price (allergy_override_reason) |
| POS | 3g | POS / Duplicate therapy / Desktop 1366 / KM | Pharmacist | POST /api/sales/v1/carts/price (acknowledge_warnings) |
| POS | 3h | POS / Hard stops / Desktop 1366 / EN | All POS roles | POST /api/sales/v1/carts/price |
| POS | 3i | POS / Controlled sale PIN / Desktop 1366 / EN | Pharmacist only | POST /api/auth/v1/pin/verify · POST /api/sales/v1/invoices (pin_token, patient_id_document) |
| POS | 3j | POS / Discount approval / Desktop 1366 / KM | Cashier requests · Manager/Owner approves | POST /api/auth/v1/pin/witness → discount_approval_token |
| POS | 3k | POS / Credit limit exceeded / Desktop 1366 / EN | Cashier, Pharmacist · limit visible to all, editable by Owner/Manager | POST /api/sales/v1/invoices (payment=credit) |
| POS | 3l | POS / KHQR waiting / Desktop 1366 / KM | All POS roles | POST /api/sales/v1/payments/khqr · GET …/{id}/status · ⚠ API pending |
| POS | 3m | POS / Suspend with note / Desktop 1366 / EN | All POS roles | POST /api/sales/v1/carts/suspend |
| POS | 3n | POS / Resumed cart / Desktop 1366 / EN | All POS roles | POST /api/sales/v1/carts/{cart_id}/resume |
| POS | 3o | POS / Below cost / Desktop 1366 / EN | All POS roles · cost shown only with cost permission | POST /api/sales/v1/carts/price |
| POS Lite | 4a | POS / Cart / Mobile 390 / KM | Cashier, Pharmacist | POST /api/sales/v1/carts/price |
| POS Lite | 4b | POS / Payment sheet / Mobile 390 / EN | Cashier, Pharmacist | POST /api/sales/v1/invoices |
| POS Lite | 4c | POS / Link Rx sheet / Mobile 390 / EN | Pharmacist | GET /api/prescription/v1/patients?q= · GET …/prescriptions/{rx_id}/remaining |
| POS Lite | 4d | POS / KHQR waiting / Mobile 390 / KM | Cashier, Pharmacist | POST /api/sales/v1/payments/khqr · GET …/{id}/status · ⚠ API pending |
| POS Lite | 4e | POS / Cart + hard stop / Tablet 1024 / EN | Cashier, Pharmacist | POST /api/sales/v1/carts/price |
| POS Back Office | 12a | POS / Sale Template list + load / Desktop 1366 / EN | Cashier, Pharmacist, Manager | GET /api/sales/v1/sale-templates · POST …/{template_id}/load |
| POS Back Office | 12b | POS / Suspended carts / Desktop 1366 / EN | Cashier, Pharmacist, Manager | GET /api/sales/v1/carts |
| POS Back Office | 12c | POS / Sale Order detail (quote → order) / Desktop 1366 / EN | Manager, Pharmacist, Cashier (no cost) | GET /api/sales/v1/sale-orders/{order_id} · POST …/invoice · POST …/cancel |
| POS Back Office | 12d | POS / List Sale + cancel with reason / Desktop 1366 / EN | Manager, Owner (cancel); Cashier (own, reprint only) | GET /api/sales/v1/invoices · POST …/{id}/cancel |
| POS Back Office | 12e | POS / Invoice detail / Desktop 1366 / EN | All (cost/profit rows: Owner, granted Manager) | GET /api/sales/v1/invoices/{id} |
| POS Back Office | 12f | POS / Sale Return / Desktop 1366 / EN | Pharmacist, Manager (refund > $20 needs Manager) | POST /api/sales/v1/invoices/{invoice_id}/returns |
| POS Back Office | 12g | POS / Commission list / Desktop 1366 / EN | All staff (own) · Manager (branch) · Owner (all) | GET /api/sales/v1/commission/report · POST …/periods/{branch_id}/{month}/paid |
| POS Back Office | 12h | POS / Promotion editor / Desktop 1366 / EN | Owner, Manager (own branches) | POST /api/catalog/v1/promotions · POST …/preview · ⚠ API pending |
| POS Back Office | 12i | Prescriptions / Dispense from Rx / Desktop 1366 / EN | Pharmacist | GET /api/prescription/v1/prescriptions?status=active · GET …/{rx_id}/remaining |
| POS Back Office | 12j | Purchase / Purchase Order – create / Desktop 1366 / EN | Manager, Owner | POST /api/purchasing/v1/purchase-orders · POST …/{po_id}/send |
| POS Back Office | 12k | Transfer / Stock Transfer Request – create / Desktop 1366 / EN | Pharmacist, Manager (requesting branch) | POST /api/inventory/v1/transfer-requests |
| POS Back Office | 12l | Contacts / Suppliers + supplier groups / Desktop 1366 / EN | Manager, Owner (balances: cost permission) | GET /api/purchasing/v1/suppliers · GET /api/purchasing/v1/supplier-groups |
| POS Back Office | 12n | Warehouse / Medicine detail – info, ingredients, price history / Desktop 1366 / EN | Manager, Owner (cost: permission) | GET /api/catalog/v1/medicines/{medicine_id} · GET …/price-history · ⚠ API pending |
| Prescriptions | 6a | Prescriptions / Patients / Desktop 1366 / EN | Pharmacist, Manager, Owner | GET /api/prescription/v1/patients?q= |
| Prescriptions | 6b | Prescriptions / Patient detail / Desktop 1366 / EN | Pharmacist, Manager, Owner | GET /api/prescription/v1/patients/{id} |
| Prescriptions | 6c | Prescriptions / Find patient in other branch / Desktop 1366 / KM | Pharmacist, Manager, Owner · audited | POST /api/prescription/v1/patients/link (exact phone) |
| Prescriptions | 6d | Prescriptions / Doctors / Desktop 1366 / EN | Pharmacist, Manager, Owner | GET /api/prescription/v1/doctors |
| Prescriptions | 6e | Prescriptions / New Rx / Desktop 1366 / EN | Pharmacist | POST /api/prescription/v1/prescriptions |
| Prescriptions | 6f | Prescriptions / Rx detail + label / Desktop 1366 / EN | Pharmacist, Manager, Owner | GET /api/prescription/v1/prescriptions/{id} |
| Prescriptions | 6g | Prescriptions / Cancel Rx / Desktop 1366 / EN | Pharmacist, Manager, Owner | POST /api/prescription/v1/prescriptions/{id}/cancel |
| Prescriptions | 6h | Prescriptions / New Rx – camera capture / Mobile 390 / KM | Pharmacist | POST /api/prescription/v1/prescriptions/{id}/attachments |
| Controlled Drugs | 7a | Controlled / Register / Desktop 1366 / EN | Pharmacist, Manager, Owner | GET /api/controlled/v1/register?medicine_id=&branch_id= |
| Controlled Drugs | 7b | Controlled / Entry detail / Desktop 1366 / EN | Pharmacist, Manager, Owner | GET /api/controlled/v1/entries/{entry_id} · ⚠ API pending |
| Controlled Drugs | 7c | Controlled / Destroy with witness / Desktop 1366 / KM | Pharmacist starts · Manager/Owner witnesses | POST /api/controlled/v1/entries · POST /api/auth/v1/pin/witness |
| Controlled Drugs | 7d | Controlled / Discrepancies / Desktop 1366 / EN | Pharmacist, Manager, Owner | GET /api/controlled/v1/discrepancies · POST …/{discrepancy_id}/resolve |
| Controlled Drugs | 7e | Controlled / Chain verification / Desktop 1366 / EN | Manager, Owner | GET /api/controlled/v1/register/verify |
| Controlled Drugs | 7f | Controlled / Register export / Desktop 1366 / EN | Pharmacist, Manager, Owner | POST /api/documents/v1/render (controlled_register) |
| Stock | 8a | Stock / Batches & expiry / Desktop 1366 / EN | Pharmacist, Manager, Owner · value column needs cost permission | GET /api/inventory/v1/batches?expiring_within=90 |
| Stock | 8b | Stock / Release quarantine / Desktop 1366 / KM | Pharmacist only | POST /api/inventory/v1/quarantine/release |
| Stock | 8c | Stock / Stock take – create / Desktop 1366 / EN | Manager, Owner | POST /api/stockcount/v1/counts |
| Stock | 8d | Stock / Stock take – review / Desktop 1366 / EN | Manager reviews · Owner approves above threshold | GET /api/stockcount/v1/counts/{count_id}/review · POST …/approve |
| Stock | 8e | Stock / Re-order list / Desktop 1366 / EN | Manager, Owner · last cost needs cost permission | GET /api/inventory/v1/reorder-lists/latest?branch_id= · POST …/{list_id}/purchase-requests · POST …/{list_id}/transfer-requests |
| Stock | 8f | Stock / Shelf locations / Desktop 1366 / EN | Manager, Owner | GET /api/inventory/v1/shelf-locations |
| Stock | 8g | Stock / Recall / Desktop 1366 / EN | Pharmacist, Manager, Owner | GET /api/inventory/v1/recalls/{recall_id} · ⚠ API pending |
| Stock | 8h | Stock / Stock take – blind count / Mobile 390 / KM | Cashier, Pharmacist, Manager (assigned counters) | GET /api/stockcount/v1/counts/{count_id}/lookup · POST …/entries |
| Stock | 8i | Stock / Stock take – second count / Mobile 390 / EN | Second counter (different user) | POST /api/stockcount/v1/counts/{count_id}/recount · POST …/entries |
| Warehouse | 9a | Warehouse / Medicines / Desktop 1366 / EN | Owner, Manager · Pharmacist view · cost column needs permission | GET /api/catalog/v1/medicines |
| Warehouse | 9b | Warehouse / Medicine detail – pack units & prices / Desktop 1366 / EN | Owner, Manager | GET /api/catalog/v1/medicines/{medicine_id} · GET …/pack-units |
| Warehouse | 9c | Warehouse / Add medicine / Desktop 1366 / KM | Owner, Manager | POST /api/catalog/v1/medicines |
| Warehouse | 9d | Warehouse / Hamper editor / Desktop 1366 / EN | Owner, Manager | POST /api/catalog/v1/hampers · PUT …/{hamper_id}/components · GET /api/inventory/v1/hampers/{hamper_id}/availability |
| Warehouse | 9e | Warehouse / Import – validation / Desktop 1366 / EN | Owner, Manager | POST /api/catalog/v1/imports · GET …/{import_id} · POST …/commit |
| Warehouse | 9f | Warehouse / Print label / Desktop 1366 / EN | Owner, Manager, Pharmacist | POST /api/documents/v1/render (label) |
| Warehouse | 9g | Warehouse / Initialize opening stock / Desktop 1366 / EN | Owner only | POST /api/inventory/v1/opening-balances · POST …/{opening_id}/commit |
| Purchase | 10a | Purchase / Purchase Request – approve & route / Desktop 1366 / EN | Manager, Owner approve · any staff can request | POST /api/purchasing/v1/purchase-requests/{request_id}/approve · POST …/to-purchase-orders · POST …/{request_id}/fill-by-transfer |
| Purchase | 10b | Purchase / PO group per branch / Desktop 1366 / EN | Manager, Owner | GET /api/purchasing/v1/po-groups/{group_id} |
| Purchase | 10c | Purchase / Purchase Payment – overpayment refused / Desktop 1366 / EN | Manager, Owner | POST /api/purchasing/v1/supplier-payments |
| Purchase | 10d | Purchase / Supplier Return / Desktop 1366 / EN | Manager, Owner | POST /api/purchasing/v1/supplier-returns · ⚠ API pending |
| Purchase | 10e | Purchase / Receiving Goods / Mobile 390 / KM | Pharmacist, Manager | POST /api/purchasing/v1/purchase-orders/{po_id}/receive |
| Purchase | 10f | Purchase / Quick stock-in (no PO) / Mobile 390 / EN | Manager, Owner | POST /api/inventory/v1/stock-in |
| Transfer | 11a | Transfer / Stock Transfer list / Desktop 1366 / EN | Manager, Owner, Pharmacist | GET /api/inventory/v1/transfers?status= |
| Transfer | 11b | Transfer / Pick (FEFO) / Desktop 1366 / EN | Pharmacist, Manager (source branch) | POST /api/inventory/v1/transfers/{transfer_id}/pick |
| Transfer | 11c | Transfer / Dispatch controlled – PIN + witness / Desktop 1366 / KM | Pharmacist + witness | POST /api/inventory/v1/transfers/{transfer_id}/dispatch · POST /api/auth/v1/pin/witness |
| Transfer | 11d | Transfer / Discrepancy resolution / Desktop 1366 / EN | Manager (source branch), Owner | POST /api/inventory/v1/transfers/{transfer_id}/differences/{discrepancy_id}/resolve |
| Transfer | 11e | Transfer / Shrinkage – new / Desktop 1366 / EN | Any staff records · Manager/Owner approves above threshold | POST /api/inventory/v1/shrinkages · POST …/{shrinkage_id}/photo |
| Transfer | 11f | Transfer / Receive – scan QR / Mobile 390 / KM | Pharmacist, Manager (receiving branch) | GET /api/inventory/v1/transfers/by-number/{number} |
| Transfer | 11g | Transfer / Receive – quantities / Mobile 390 / EN | Pharmacist, Manager (receiving branch) | POST /api/inventory/v1/transfers/{transfer_id}/receive |
| Contacts | 12a | Contacts / Customer groups / Desktop 1366 / EN | Owner, Manager | PATCH /api/customers/v1/customer-groups/{group_id} |
| Contacts | 12b | Contacts / Customers / Desktop 1366 / EN | All roles view · Owner, Manager edit credit | GET /api/customers/v1/customers |
| Contacts | 12c | Contacts / Customer detail / Desktop 1366 / KM | Owner, Manager (credit edit) · others view | GET /api/customers/v1/customers/{customer_id} · GET …/deposits |
| Contacts | 12d | Contacts / Supplier detail / Desktop 1366 / EN | Owner, Manager | GET /api/purchasing/v1/suppliers/{supplier_id} · GET …/balance |
| Dashboard | 5a | Dashboard / All branches / Desktop 1366 / KM | Owner |  |
| Dashboard | 5b | Dashboard / Own branch / Desktop 1366 / EN | Branch manager · no cost permission |  |
| Dashboard | 5c | Dashboard / Mobile 390 / KM | Owner · all branches |  |
| Dashboard | 5d | Dashboard / Mobile 390 / EN | Branch manager · PP1 |  |
| Reports | 13a | Report / Sale Detail / Desktop 1366 / EN | Owner, Manager (own branches) · Cashier: own sales only | GET /api/reports/v1/sales/detail |
| Reports | 13b | Report / Sale Detail / Desktop 1366 / KM | Owner, Manager | GET /api/reports/v1/sales/detail?lang=km |
| Reports | 13c | Report / Sale Margin By Item / Desktop 1366 / EN | Owner (cost permission) | GET /api/reports/v1/sales/margin-by-item |
| Reports | 13d | Report / Sale Margin By Item – cost hidden / Desktop 1366 / EN | Branch manager without cost permission | GET /api/reports/v1/sales/margin-by-item (cost fields omitted by API) |
| Reports | 13e | Report / Expire Alert / Desktop 1366 / EN | Pharmacist, Manager, Owner · value with cost permission | GET /api/reports/v1/expiry?within_days=120 |
| Reports | 13f | Report / Controlled Summary / Desktop 1366 / EN | Pharmacist, Manager, Owner | GET /api/reports/v1/controlled/summary |
| Reports | 13g | Report / Sales Summary / Desktop 1366 / EN | Owner, Manager (own branches) | GET /api/reports/v1/sales/summary?group_by=day |
| Reports | 13h | Report / Profit / Desktop 1366 / EN | Owner · Manager with cost permission | GET /api/reports/v1/sales/profit?group_by=branch |
| Reports | 13i | Report / Sale Cancellations / Desktop 1366 / EN | Owner, Manager | GET /api/reports/v1/sales/cancellations |
| Reports | 13j | Report / Discounts / Desktop 1366 / EN | Owner, Manager | GET /api/reports/v1/sales/discounts |
| Reports | 13k | Report / Slow-moving Stock / Desktop 1366 / EN | Owner, Manager · value with cost permission | GET /api/reports/v1/stock/slow-moving?days=90 |
| Reports | 13l | Report / ABC Analysis / Desktop 1366 / EN | Owner, Manager | GET /api/reports/v1/stock/abc |
| Reports | 13m | Report / Purchase By Supplier / Desktop 1366 / EN | Owner, Manager (cost permission) | GET /api/reports/v1/purchases/by-supplier |
| Reports | 13n | Report / Top Customers / Desktop 1366 / EN | Owner, Manager | GET /api/reports/v1/customers/top?limit=50 |
| Reports | 13o | Report / Stock Count Variances / Desktop 1366 / EN | Owner, Manager · value with cost permission | GET /api/reports/v1/counts/variances |
| Reports | 13p | Report / Transfers In Transit / Desktop 1366 / EN | Owner, Manager | GET /api/reports/v1/transfers/in-transit |
| Users and Settings | 14a | User Management / Users + edit / Desktop 1366 / EN | Owner | PATCH /api/auth/v1/users/{user_id} · POST …/deactivate · …/reset-password · …/2fa/reset |
| Users and Settings | 14b | User Management / Roles – permission matrix / Desktop 1366 / EN | Owner | GET /api/auth/v1/permissions · PATCH /api/auth/v1/roles/{key} |
| Users and Settings | 14c | User Management / User Log – before/after / Desktop 1366 / EN | Owner | GET /api/auth/v1/audit-logs |
| Users and Settings | 14d | User Management / Commission rules / Desktop 1366 / EN | Owner | GET /api/sales/v1/commission/rules · POST …/rules |
| Users and Settings | 14e | Settings / Branches & branch settings / Desktop 1366 / KM | Owner · Manager edits own branch (marked fields only) | GET /api/branch/v1/branches · PUT …/{branch_id}/settings |
| Users and Settings | 14f | Settings / Exchange rate / Desktop 1366 / EN | Owner | PUT /api/sales/v1/exchange-rates/{branch_id} · GET …/history · ⚠ API pending |
| Users and Settings | 14g | Settings / Telegram notifications / Desktop 1366 / EN | Owner | GET /api/notifications/v1/chats · PUT …/chats/{target} · POST /api/notifications/v1/test · GET …/messages |
| Users and Settings | 14h | Settings / Feature switches / Desktop 1366 / EN | Owner | GET /api/branch/v1/features · PUT …/features/{key} |
| Users and Settings | 14i | Settings / My profile / Desktop 1366 / EN | All users | POST /api/auth/v1/me/password · PUT …/me/pin · POST …/2fa/setup · GET …/me/sessions · ⚠ API pending |
| Print Layouts | 17a | Receipt 80 mm · KM |  |  |
| Print Layouts | 17b | Receipt 80 mm · EN |  |  |
| Print Layouts | 17d | A4 invoice |  | POST /api/documents/v1/render (invoice_a4) |
| Print Layouts | 17e | A4 quote / sale order |  | POST /api/documents/v1/render (sale_order) |
| Print Layouts | 17i | Purchase order (single) |  | POST /api/documents/v1/render (purchase_order) |
| Print Layouts | 17f | PO group printout |  | POST /api/documents/v1/render (purchase_order_group) |
| Print Layouts | 17g | Transfer note with QR |  | POST /api/documents/v1/render (transfer_note) |
| Print Layouts | 17h | Customer statement |  | POST /api/documents/v1/render (customer_statement) · ⚠ API pending |
| Print Layouts | 17c | Labels · dispensing, shelf, barcode |  | POST /api/documents/v1/render (dispensing_label · label) |
| API Coverage Screens | 18a | Warehouse / Categories & brands / Desktop 1366 / EN | Owner, Manager | GET /api/catalog/v1/categories · POST · PATCH …/{row_id} · POST …/deactivate · …/activate · same for /brands |
| API Coverage Screens | 18b | Stock / Re-order settings / Desktop 1366 / EN | Manager (own branches), Owner | GET /api/inventory/v1/reorder-settings · PUT … · POST …/bulk · POST /api/inventory/v1/reorder-lists/run |
| API Coverage Screens | 18c | Settings / Notification settings + daily summary preview / Desktop 1366 / EN | Owner | GET /api/notifications/v1/settings · PUT … · POST /api/notifications/v1/daily-summary/run |
| API Coverage Screens | 18d | Stock / Inventory movements / Desktop 1366 / EN | Pharmacist, Manager, Owner (cost: permission) | GET /api/inventory/v1/movements?branch_id=&medicine_id=&from=&to=&type= |
| API Coverage Screens | 18e | Warehouse / Initialize – upload opening stock / Desktop 1366 / EN | Owner (unlock: Owner only) | GET /api/inventory/v1/opening-balances/template.xlsx · POST …/upload · GET …/opening-balances · GET …/{opening_id} · GET /api/inventory/v1/initialize-locks · POST …/{branch_id}/unlock |
| API Coverage Screens | 18f | Purchase / Receipts + supplier payments / Desktop 1366 / EN | Manager, Owner (amounts: cost permission) | GET /api/purchasing/v1/receipts · GET …/{receipt_id} · GET /api/purchasing/v1/supplier-payments · GET …/{payment_id} · POST …/cancel · GET …/suppliers/{id}/statement |
| API Coverage Screens | 18g | Contacts / Customer payments / Desktop 1366 / EN | Cashier (record), Manager, Owner (cancel) | GET /api/customers/v1/customer-payments · POST … · POST …/{payment_id}/cancel · GET /api/customers/v1/customers/{customer_id}/unpaid |
| API Coverage Screens | 18h | Controlled / Register correction – PIN + witness / Desktop 1366 / EN | Pharmacist + witness (Manager/Owner) | GET /api/auth/v1/pin/witnesses · POST /api/auth/v1/pin/verify · POST /api/auth/v1/pin/witness · POST /api/controlled/v1/entries/correction |
| API Coverage Screens | 15k | Auth / 2FA backup codes – shown once + regenerate / Desktop 1366 / EN | All users with 2FA (required for Owner, Manager) | POST /api/auth/v1/2fa/enable → backup_codes · POST /api/auth/v1/2fa/backup-codes (password) ⚠ API pending |


152 frames.
