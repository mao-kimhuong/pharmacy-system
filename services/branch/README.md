# branch service

Owns: Branches, branch settings, feature switches.

- Route prefix: `/api/branch/v1` (via Traefik)
- Database: `pharmacy_branch` (user `branch_user`), no other service reads it
- API docs (local): http://localhost/api/branch/v1/docs

## Layout

- `branch_service/main.py` – FastAPI app
- `branch_service/api/` – routers (HTTP only, no business logic)
- `branch_service/services/` – business logic and rules
- `branch_service/models/` – SQLAlchemy models (this service's tables only)
- `branch_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `branch_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
