"""S8b documents: receipt language (branch setting or asked), the supplier return
note (values only with purchase-price permissions), the customer statement."""

import io
from uuid import uuid4

import pytest
from pypdf import PdfReader

from document_service.api.render import get_customers
from document_service.main import app

from .conftest import PREFIX, needs_pdf, user
from .test_receipts import CASHIER, PP1, body, invoice_event, store
from .test_s6_docs import event


@pytest.fixture(autouse=True)
def short_wait():
    app.state.settings.document_wait_seconds = 0.5
    yield
    app.state.settings.document_wait_seconds = 5.0


def text_of(pdf: bytes) -> str:
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


@needs_pdf
async def test_receipt_language_from_the_branch_or_asked(client) -> None:
    inv = invoice_event()
    inv["branch"]["receipt_lang"] = "en"
    await store(inv)
    english = text_of((await client.post(f"{PREFIX}/render", json=body(inv, "invoice_a4"), headers=CASHIER)).content)
    assert "INVOICE" in english and "Total USD" in english
    khmer = await client.post(f"{PREFIX}/render", json={**body(inv, "invoice_a4"), "lang": "km"}, headers=CASHIER)
    assert "Total USD" not in text_of(khmer.content)


def supplier_return(version: int = 2) -> dict:
    return {"return_id": "00000000-0000-0000-0000-0000000000f1", "version": version, "number": "PP1-SRN-2026-000001",
            "status": "credited", "reason": "damaged", "note": "", "total": "4.25",
            "submitted_at": "2026-10-31T03:00:00+00:00", "cancel_reason": None,
            "branch": {"id": str(PP1), "code": "PP1", "name_en": "Phnom Penh 1", "name_km": "សាខា១"},
            "supplier": {"id": str(uuid4()), "code": "DKSH", "name": "DKSH Cambodia"},
            "lines": [{"line_no": 1, "batch_id": str(uuid4()), "medicine_id": str(uuid4()), "sku": "PARA500",
                       "name": "Panadol", "qty_base": 100, "lot_no": "A1", "expiry_date": "2028-03-31",
                       "cost_per_base": "0.0425", "line_total": "4.25"}]}  # fmt: skip


@needs_pdf
async def test_supplier_return_note_values_only_with_price_permission(client) -> None:
    await event("supplier_return.submitted", supplier_return())
    req = {"type": "supplier_return", "supplier_return_id": "00000000-0000-0000-0000-0000000000f1", "lang": "en"}
    buyer = user("branch_manager", "purchasing.return,purchasing.order", (PP1,))
    full = text_of((await client.post(f"{PREFIX}/render", json=req, headers=buyer)).content)
    assert "PP1-SRN-2026-000001" in full and "DKSH Cambodia" in full and "4.25" in full and "A1" in full
    clerk = user("pharmacist", "purchasing.return", (PP1,))
    blind = text_of((await client.post(f"{PREFIX}/render", json=req, headers=clerk)).content)
    assert "Panadol" in blind and "4.25" not in blind and "0.0425" not in blind
    assert (await client.post(f"{PREFIX}/render", json=req, headers=user("cashier", "pos.sell", (PP1,)))).status_code == 403


@needs_pdf
async def test_customer_statement_from_the_customers_service(client) -> None:
    asked = {}

    class Customers:
        async def get(self, path: str, params: dict, **kw) -> dict:  # noqa: ANN003
            asked.update(path=path, **params)
            return {"customer": "Sokha Clinic", "from": "2026-10-01", "to": "2026-10-31", "opening_balance": "0.00",
                    "closing_balance": "12.50", "entries": [{"on": "2026-10-05", "kind": "invoice",
                    "document_no": "PP1-INV-2026-000009", "debit": "12.50", "credit": "0.00", "balance": "12.50"}]}  # fmt: skip

    app.dependency_overrides[get_customers] = lambda: Customers()
    try:
        req = {"type": "customer_statement", "customer_id": str(uuid4()), "date_from": "2026-10-01", "lang": "en"}
        r = await client.post(f"{PREFIX}/render", json=req, headers=user("cashier", "contacts.customers", (PP1,)))
        assert r.status_code == 200, r.text
        text = text_of(r.content)
        assert "CUSTOMER STATEMENT" in text and "Sokha Clinic" in text and "PP1-INV-2026-000009" in text
        assert asked["date_from"] == "2026-10-01"
        km = await client.post(f"{PREFIX}/render", json={**req, "lang": "km"},
                               headers=user("cashier", "contacts.customers", (PP1,)))  # fmt: skip
        assert km.status_code == 200 and "CUSTOMER STATEMENT" not in text_of(km.content)
    finally:
        app.dependency_overrides.clear()
