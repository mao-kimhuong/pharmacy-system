# customers service

Owns: Customers, customer groups, credit, payments, statements.

- Route prefix: `/api/customers/v1` (via Traefik)
- Database: `pharmacy_customers` (user `customers_user`), no other service reads it
- API docs (local): http://localhost/api/customers/v1/docs

## Layout

- `customers_service/main.py` – FastAPI app
- `customers_service/api/` – routers (HTTP only, no business logic)
- `customers_service/services/` – business logic and rules
- `customers_service/models/` – SQLAlchemy models (this service's tables only)
- `customers_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `customers_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
