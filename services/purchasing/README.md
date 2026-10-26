# purchasing service

Owns: Suppliers, supplier groups, purchase requests, POs, receiving, supplier payments and returns.

- Route prefix: `/api/purchasing/v1` (via Traefik)
- Database: `pharmacy_purchasing` (user `purchasing_user`), no other service reads it
- API docs (local): http://localhost/api/purchasing/v1/docs

## Layout

- `purchasing_service/main.py` – FastAPI app
- `purchasing_service/api/` – routers (HTTP only, no business logic)
- `purchasing_service/services/` – business logic and rules
- `purchasing_service/models/` – SQLAlchemy models (this service's tables only)
- `purchasing_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `purchasing_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
