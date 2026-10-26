# ai service

Owns: DeepSeek features: import cleanup, ask your data, summaries, substitutes, Rx parsing.

- Route prefix: `/api/ai/v1` (via Traefik)
- Database: `pharmacy_ai` (user `ai_user`), no other service reads it
- API docs (local): http://localhost/api/ai/v1/docs

## Layout

- `ai_service/main.py` – FastAPI app
- `ai_service/api/` – routers (HTTP only, no business logic)
- `ai_service/services/` – business logic and rules
- `ai_service/models/` – SQLAlchemy models (this service's tables only)
- `ai_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `ai_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
