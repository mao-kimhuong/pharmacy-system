# prescription service

Owns: Patients, doctors, prescriptions, Rx items, dispensing balance.

- Route prefix: `/api/prescription/v1` (via Traefik)
- Database: `pharmacy_prescription` (user `prescription_user`), no other service reads it
- API docs (local): http://localhost/api/prescription/v1/docs

## Layout

- `prescription_service/main.py` – FastAPI app
- `prescription_service/api/` – routers (HTTP only, no business logic)
- `prescription_service/services/` – business logic and rules
- `prescription_service/models/` – SQLAlchemy models (this service's tables only)
- `prescription_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `prescription_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
