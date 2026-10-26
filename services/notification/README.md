# notification service

Owns: Telegram daily report, alerts.

- Route prefix: `/api/notifications/v1` (via Traefik)
- Database: `pharmacy_notification` (user `notification_user`), no other service reads it
- API docs (local): http://localhost/api/notifications/v1/docs

## Layout

- `notification_service/main.py` – FastAPI app
- `notification_service/api/` – routers (HTTP only, no business logic)
- `notification_service/services/` – business logic and rules
- `notification_service/models/` – SQLAlchemy models (this service's tables only)
- `notification_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `notification_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
