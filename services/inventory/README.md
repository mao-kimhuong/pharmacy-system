# inventory service

Owns: Batches, stock per branch, movements, transfers, shrinkage, opening stock, recalls.

- Route prefix: `/api/inventory/v1` (via Traefik)
- Database: `pharmacy_inventory` (user `inventory_user`), no other service reads it
- API docs (local): http://localhost/api/inventory/v1/docs

## Layout

- `inventory_service/main.py` – FastAPI app
- `inventory_service/api/` – routers (HTTP only, no business logic)
- `inventory_service/services/` – business logic and rules
- `inventory_service/models/` – SQLAlchemy models (this service's tables only)
- `inventory_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `inventory_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`

## What it does (S2)

See CLAUDE.md → "Purchasing (from S2)", "Batches and movements", "Cost visibility" and
"Expiry job". Business rules are listed at the top of each module in `*_service/services/`.
