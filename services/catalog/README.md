# catalog service

Owns: Medicines, pack units, categories, brands, promotions, hampers, imports.

- Route prefix: `/api/catalog/v1` (via Traefik)
- Database: `pharmacy_catalog` (user `catalog_user`), no other service reads it
- API docs (local): http://localhost/api/catalog/v1/docs

## Layout

- `catalog_service/main.py` – FastAPI app
- `catalog_service/api/` – routers (HTTP only, no business logic)
- `catalog_service/services/` – business logic and rules
- `catalog_service/models/` – SQLAlchemy models (this service's tables only)
- `catalog_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `catalog_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`

## What it does (S1b)

- Categories, brands, medicines, pack units (box / strip / tablet). Never deleted: deactivate.
- Rules in `catalog_service/services/medicines.py` (docstring at the top).
- Search: `GET /medicines/search?q=` – exact barcode, then SKU, then brand / generic / Khmer name.
- Import Product: `GET /imports/template.xlsx` → `POST /imports` (validate only) →
  `GET /imports/{id}` (row errors) → `POST /imports/{id}/commit` (Idempotency-Key;
  `create_missing`, `skip_invalid`). Rules in `catalog_service/services/imports.py`.
- Samples: `docs/samples/products-sample.xlsx` (20 products) and `products-sample-broken.xlsx`
  (one bad row); regenerate with `.venv/bin/python scripts/make_products_sample.py`.
- Events: `medicine.created|updated|activated|deactivated` (full product with pack units and
  a `version`), `category.*`, `brand.*`, and `audit.recorded` for every change.
