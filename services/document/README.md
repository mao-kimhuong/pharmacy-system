# document service

Owns: Receipts, A4 invoices, labels, PO and register PDFs.

- Route prefix: `/api/documents/v1` (via Traefik)
- Database: `pharmacy_document` (user `document_user`), no other service reads it
- API docs (local): http://localhost/api/documents/v1/docs

## Layout

- `document_service/main.py` – FastAPI app
- `document_service/api/` – routers (HTTP only, no business logic)
- `document_service/services/` – business logic and rules
- `document_service/models/` – SQLAlchemy models (this service's tables only)
- `document_service/schemas/` – Pydantic request/response models (`extra="forbid"` on inputs)
- `document_service/events/` – event publishers and consumers
- `migrations/` – Alembic
- `tests/`
