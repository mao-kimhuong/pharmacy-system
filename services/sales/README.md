# sales service

Owns: POS, invoices, sale orders, suspend, templates, returns, commission; sale saga.

- Route prefix: `/api/sales/v1` (via Traefik)
- Database: `pharmacy_sales` (user `sales_user`), no other service reads it
- API docs (local): http://localhost/api/sales/v1/docs

## Layout

- `sales_service/main.py` – FastAPI app
- `sales_service/api/` – routers (HTTP only, no business logic)
- `sales_service/services/` – business logic and rules
- `sales_service/models/` – SQLAlchemy models (this service's tables only)
- `sales_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `sales_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
