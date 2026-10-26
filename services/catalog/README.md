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
