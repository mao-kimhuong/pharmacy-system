# auth service

Owns: Users, roles, permissions, sessions, PIN, audit log.

- Route prefix: `/api/auth/v1` (via Traefik)
- Database: `pharmacy_auth` (user `auth_user`), no other service reads it
- API docs (local): http://localhost/api/auth/v1/docs

## Layout

- `auth_service/main.py` – FastAPI app
- `auth_service/api/` – routers (HTTP only, no business logic)
- `auth_service/services/` – business logic and rules
- `auth_service/models/` – SQLAlchemy models (this service's tables only)
- `auth_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `auth_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
