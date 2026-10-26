# stockcount service

Owns: Stock takes, count lines, double count, approval.

- Route prefix: `/api/stockcount/v1` (via Traefik)
- Database: `pharmacy_stockcount` (user `stockcount_user`), no other service reads it
- API docs (local): http://localhost/api/stockcount/v1/docs

## Layout

- `stockcount_service/main.py` – FastAPI app
- `stockcount_service/api/` – routers (HTTP only, no business logic)
- `stockcount_service/services/` – business logic and rules
- `stockcount_service/models/` – SQLAlchemy models (this service's tables only)
- `stockcount_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `stockcount_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
