"""Quote / sale order PDF from the copy of sale_order.* events."""

import io
from uuid import uuid4

import pytest
from pypdf import PdfReader

from document_service.main import app

from .conftest import PREFIX, needs_pdf, user
from .test_s6_docs import event

PP1 = uuid4()
SELLER = user("cashier", "sales.orders", (PP1,))


@pytest.fixture(autouse=True)
def short_wait():
    app.state.settings.document_wait_seconds = 0.5
    yield
    app.state.settings.document_wait_seconds = 5.0


def order(version: int, status: str) -> dict:
    return {"sale_order_id": "00000000-0000-0000-0000-000000000001", "version": version, "number": "PP1-SO-2026-000002",
            "status": status, "branch": {"id": str(PP1), "code": "PP1", "name_en": "Phnom Penh 1", "name_km": "សាខា១"},
            "customer": {"id": str(uuid4()), "name": "Sokha Clinic", "name_km": "គ្លីនិកសុខា", "phone": "012 345 678"},
            "note": "deliver Friday", "valid_until": "2026-11-07", "reserve_until": None, "deposit_usd": "0.00",
            "subtotal": "16.00", "discount": "1.60", "total": "14.40", "created_at": "2026-10-31T03:00:00+00:00",
            "cancel_reason": None,
            "lines": [{"line_no": 1, "medicine_id": str(uuid4()), "sku": "PARA500", "name": "Panadol 500",
                       "name_km": "ប៉ាណាដុល", "pack_unit": "box", "qty": 2, "qty_invoiced": 0, "unit_price": "8.00",
                       "line_total": "16.00", "promo_discount": "1.60"}]}  # fmt: skip


@needs_pdf
async def test_quote_then_order_pdf(client) -> None:
    await event("sale_order.created", order(1, "quote"))
    body = {"type": "sale_order", "sale_order_id": "00000000-0000-0000-0000-000000000001"}
    r = await client.post(f"{PREFIX}/render", json=body, headers=SELLER)
    assert r.status_code == 200, r.text
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    for expected in ("QUOTATION", "PP1-SO-2026-000002", "Sokha Clinic", "Panadol 500", "14.40", "2026-11-07"):
        assert expected in text, expected
    await event("sale_order.ordered", {**order(2, "ordered"), "deposit_usd": "5.00",
                                       "reserve_until": "2026-11-03T03:00:00+00:00"})  # fmt: skip
    await event("sale_order.created", order(1, "quote"))  # older: ignored
    text = PdfReader(io.BytesIO((await client.post(f"{PREFIX}/render", json=body, headers=SELLER)).content)
                     ).pages[0].extract_text()  # fmt: skip
    assert "SALE ORDER" in text and "5.00" in text and "QUOTATION" not in text
    assert (await client.post(f"{PREFIX}/render", json=body, headers=user("cashier", "sales.orders", (uuid4(),)))
            ).status_code == 404  # fmt: skip
    assert (await client.post(f"{PREFIX}/render", json=body, headers=user("cashier", "labels.print", (PP1,)))
            ).status_code == 403  # fmt: skip
    missing = {"type": "sale_order", "sale_order_id": str(uuid4())}
    r = await client.post(f"{PREFIX}/render", json=missing, headers=SELLER)
    assert r.status_code == 409 and r.json()["code"] == "DOCUMENT_NOT_READY"
