# UI → API inventory

| File | Frame | Endpoint(s) |
|---|---|---|
| App Shell |  | `GET /api/stock/v1/on-hand` |
| App Shell | 2d | `GET /api/stock/v1/on-hand` |
| App Shell | 2e | `GET /api/stock/v1/on-hand` |
| App Shell | 2f | `GET /api/auth/v1/me/permissions` |
| Auth | 15h | `POST /api/auth/v1/login` |
| Auth | 15i | `POST /api/auth/v1/mfa/verify` |
| Auth | 15j | `PUT /api/auth/v1/me/pin` |
| Auth | 15a | `POST /api/auth/v1/login` |
| Auth | 15b | `POST /api/auth/v1/login → 401` |
| Auth | 15c | `POST /api/auth/v1/mfa/verify → INVALID_MFA_CODE` |
| Auth | 15d | `POST /api/auth/v1/mfa/setup · /confirm` |
| Auth | 15e | `GET /api/auth/v1/me → MFA_SETUP_REQUIRED` |
| Auth | 15f | `POST /api/auth/v1/login → 423 locked_until` |
| Contacts | 12a | `PUT /api/contacts/v1/customer-groups/{id}` |
| Contacts | 12b | `GET /api/contacts/v1/customers` |
| Contacts | 12c | `GET /api/contacts/v1/customers/{id}` |
| Contacts | 12d | `GET /api/contacts/v1/suppliers/{id}` |
| Controlled Drugs | 7a | `GET /api/controlled/v1/register?medicine=&branch=` |
| Controlled Drugs | 7b | `GET /api/controlled/v1/register/{entryId}` |
| Controlled Drugs | 7c | `POST /api/controlled/v1/adjustments` |
| Controlled Drugs | 7d | `GET /api/controlled/v1/discrepancies · POST …/{id}/close` |
| Controlled Drugs | 7e | `POST /api/controlled/v1/register/verify` |
| Controlled Drugs | 7f | `GET /api/controlled/v1/register/export.pdf` |
| Dashboard |  | `GET /api/dashboard/v1/summary?branch=&amp;date=` |
| Dashboard |  | `GET /api/dashboard/v1/summary` |
| POS Back Office | 12a | `GET /api/sales/v1/templates · POST …/{id}/load` |
| POS Back Office | 12b | `GET /api/sales/v1/suspended` |
| POS Back Office | 12c | `GET /api/sales/v1/orders/{id} · POST …/invoice · POST …/cancel` |
| POS Back Office | 12d | `GET /api/sales/v1/invoices · POST …/{id}/cancel` |
| POS Back Office | 12e | `GET /api/sales/v1/invoices/{id}` |
| POS Back Office | 12f | `POST /api/sales/v1/returns` |
| POS Back Office | 12g | `GET /api/commissions/v1?period=` |
| POS Back Office | 12h | `POST /api/promotions/v1 · POST …/preview` |
| POS Back Office | 12i | `GET /api/rx/v1/prescriptions?status=active · POST /api/sales/v1/carts/{id}/rx-lines` |
| POS Back Office | 12j | `POST /api/purchase/v1/orders · POST …/{id}/send` |
| POS Back Office | 12k | `POST /api/transfers/v1/requests` |
| POS Back Office | 12l | `GET /api/contacts/v1/suppliers · GET …/supplier-groups` |
| POS Back Office | 12m | `GET /api/controlled/v1/witness-requests · POST …/{id}/sign` |
| POS Back Office | 12n | `GET /api/catalog/v1/medicines/{id} · GET …/price-history` |
| POS Lite | 4a | `POST /api/sales/v1/carts/{id}/lines` |
| POS Lite | 4b | `POST /api/sales/v1/invoices` |
| POS Lite | 4c | `GET /api/rx/v1/prescriptions?phone=` |
| POS Lite | 4d | `POST /api/payments/v1/khqr` |
| POS Lite | 4e | `POST /api/sales/v1/carts/{id}/lines` |
| POS | 3a | `POST /api/sales/v1/invoices` |
| POS | 3b | `POST /api/sales/v1/invoices` |
| POS | 3c | `POST /api/sales/v1/invoices/{id}/print` |
| POS | 3d | `GET /api/rx/v1/prescriptions?phone=&item=` |
| POS | 3e | `POST /api/sales/v1/carts/{id}/handoff` |
| POS | 3f | `POST /api/sales/v1/carts/{id}/overrides` |
| POS | 3g | `POST /api/sales/v1/carts/{id}/acknowledgements` |
| POS | 3h | `POST /api/sales/v1/carts/{id}/lines` |
| POS | 3i | `POST /api/controlled/v1/dispense` |
| POS | 3j | `POST /api/approvals/v1/discounts` |
| POS | 3k | `POST /api/sales/v1/invoices (payment=credit)` |
| POS | 3l | `POST /api/payments/v1/khqr · GET …/status` |
| POS | 3m | `POST /api/sales/v1/carts/{id}/suspend` |
| POS | 3n | `POST /api/sales/v1/carts/{id}/resume` |
| POS | 3o | `POST /api/sales/v1/carts/{id}/lines` |
| Prescriptions | 6h | `POST /api/rx/v1/prescriptions/{id}/attachments` |
| Prescriptions | 6a | `GET /api/rx/v1/patients?q=` |
| Prescriptions | 6b | `GET /api/rx/v1/patients/{id}` |
| Prescriptions | 6c | `GET /api/rx/v1/patients/lookup?phone= (exact)` |
| Prescriptions | 6d | `GET /api/rx/v1/doctors` |
| Prescriptions | 6e | `POST /api/rx/v1/prescriptions` |
| Prescriptions | 6f | `GET /api/rx/v1/prescriptions/{id}` |
| Prescriptions | 6g | `POST /api/rx/v1/prescriptions/{id}/cancel` |
| Print Layouts |  | `GET /api/sales/v1/invoices/{id}/receipt?lang={{ r.lang }}` |
| Print Layouts | 17c | `POST /api/labels/v1/render` |
| Print Layouts | 17d | `GET /api/sales/v1/invoices/{id}.pdf` |
| Print Layouts | 17e | `GET /api/sales/v1/orders/{id}.pdf` |
| Print Layouts | 17f | `GET /api/purchase/v1/po-groups/{id}.pdf` |
| Print Layouts | 17g | `GET /api/transfers/v1/{id}/note.pdf` |
| Print Layouts | 17h | `GET /api/contacts/v1/customers/{id}/statement.pdf` |
| Purchase | 10a | `POST /api/purchase/v1/requests/{id}/approve` |
| Purchase | 10b | `GET /api/purchase/v1/po-groups/{id}` |
| Purchase | 10c | `POST /api/purchase/v1/payments` |
| Purchase | 10d | `POST /api/purchase/v1/supplier-returns` |
| Purchase | 10e | `POST /api/purchase/v1/receipts` |
| Purchase | 10f | `POST /api/purchase/v1/receipts (poId=null)` |
| Reports | 13a | `GET /api/reports/v1/sale-detail` |
| Reports | 13b | `GET /api/reports/v1/sale-detail?lang=km` |
| Reports | 13c | `GET /api/reports/v1/sale-margin-by-item` |
| Reports | 13d | `GET /api/reports/v1/sale-margin-by-item (cost fields omitted by API)` |
| Reports | 13e | `GET /api/reports/v1/expire-alert?within=120` |
| Reports | 13f | `GET /api/reports/v1/controlled-summary` |
| Stock | 8a | `GET /api/stock/v1/batches?expiresWithin=90` |
| Stock | 8b | `POST /api/stock/v1/batches/{id}/release` |
| Stock | 8c | `POST /api/stock/v1/stock-takes` |
| Stock | 8d | `GET /api/stock/v1/stock-takes/{id}/variances · POST …/approve` |
| Stock | 8e | `GET /api/stock/v1/reorder?branch=PP1` |
| Stock | 8f | `GET /api/stock/v1/locations` |
| Stock | 8g | `GET /api/stock/v1/recalls/{id}` |
| Stock | 8h | `POST /api/stock/v1/stock-takes/{id}/counts` |
| Stock | 8i | `POST /api/stock/v1/stock-takes/{id}/counts?round=2` |
| Transfer | 11f | `GET /api/transfers/v1/by-qr/{code}` |
| Transfer | 11g | `POST /api/transfers/v1/{id}/receive` |
| Transfer | 11a | `GET /api/transfers/v1?status=` |
| Transfer | 11b | `POST /api/transfers/v1/{id}/pick` |
| Transfer | 11c | `POST /api/transfers/v1/{id}/dispatch` |
| Transfer | 11d | `POST /api/transfers/v1/{id}/resolve` |
| Transfer | 11e | `POST /api/stock/v1/shrinkage` |
| Users and Settings | 14a | `PATCH /api/auth/v1/users/{id}` |
| Users and Settings | 14b | `PUT /api/auth/v1/roles/{id}/permissions` |
| Users and Settings | 14c | `GET /api/audit/v1/events` |
| Users and Settings | 14d | `GET /api/commission/v1/rules` |
| Users and Settings | 14e | `PUT /api/settings/v1/branches/{id}` |
| Users and Settings | 14f | `POST /api/settings/v1/exchange-rates` |
| Users and Settings | 14g | `GET /api/notify/v1/telegram/chats · POST …/test` |
| Users and Settings | 14h | `PUT /api/settings/v1/features` |
| Users and Settings | 14i | `PUT /api/auth/v1/me/password · /pin · /mfa` |
| Warehouse | 9a | `GET /api/catalog/v1/products` |
| Warehouse | 9b | `GET /api/catalog/v1/products/{id}` |
| Warehouse | 9c | `POST /api/catalog/v1/products` |
| Warehouse | 9d | `PUT /api/catalog/v1/hampers/{id}` |
| Warehouse | 9e | `POST /api/catalog/v1/imports/{id}/validate` |
| Warehouse | 9f | `POST /api/labels/v1/print` |
| Warehouse | 9g | `POST /api/stock/v1/opening/{branch}/commit` |
