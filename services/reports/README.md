# reports service

Owns: Read models built from events; dashboard and all reports.

- Route prefix: `/api/reports/v1` (via Traefik)
- Database: `pharmacy_reports` (user `reports_user`), no other service reads it
- API docs (local): http://localhost/api/reports/v1/docs

## Layout

- `reports_service/main.py` – FastAPI app
- `reports_service/api/` – routers (HTTP only, no business logic)
- `reports_service/services/` – business logic and rules
- `reports_service/models/` – SQLAlchemy models (this service's tables only)
- `reports_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `reports_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
