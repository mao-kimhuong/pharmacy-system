# controlled service

Owns: Controlled-drug register (append-only, hash-chained), witness, discrepancies.

- Route prefix: `/api/controlled/v1` (via Traefik)
- Database: `pharmacy_controlled` (user `controlled_user`), no other service reads it
- API docs (local): http://localhost/api/controlled/v1/docs

## Layout

- `controlled_service/main.py` – FastAPI app
- `controlled_service/api/` – routers (HTTP only, no business logic)
- `controlled_service/services/` – business logic and rules
- `controlled_service/models/` – SQLAlchemy models (this service's tables only)
- `controlled_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `controlled_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
