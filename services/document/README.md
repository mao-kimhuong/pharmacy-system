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

## What it does (S1b)

- Keeps a copy of products (`products`, `product_pack_units`) from `medicine.*` events
  (queue `document.events`); older `version`s are ignored.
- `POST /render` with `type: "label"`: shelf 50×30 mm, barcode 40×25 mm or an A4 sheet
  (3 × 8). Returns a PDF. Permission `labels.print`.
- Rendering: WeasyPrint (Pango + HarfBuzz shape Khmer correctly) with Noto Sans Khmer from
  `fonts-noto-core`; Code128 barcodes as SVG (python-barcode). Never ReportLab for Khmer.
- Local tests need Pango: `brew install pango` (otherwise the PDF tests are skipped);
  `make test-docker` always runs them.
- `POST /render` with `type: "purchase_order"` (S2): the A4 PO from the copy kept from
  `purchase_order.*` events; permission `purchasing.order`, own branches only.
