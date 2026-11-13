import io
from uuid import uuid4

import pytest
from pypdf import PdfReader

from document_service.db import db
from document_service.main import app
from document_service.services.receipts import upsert_invoice

from .conftest import PREFIX, needs_pdf, user

PP1 = uuid4()
CASHIER = user("cashier", "pos.sell,sales.view", (PP1,))
OTHER = user("cashier", "pos.sell,sales.view", (uuid4(),))
LABELLER = user("pharmacist", "labels.print", (PP1,))


def invoice_event(version: int = 1, status: str = "completed", **extra) -> dict:
    return {
        "invoice_id": extra.pop("invoice_id", str(uuid4())), "version": version, "number": "PP1-INV-2026-000123",
        "status": status,
        "branch": {"id": str(PP1), "code": "PP1", "name_en": "Phnom Penh 1", "name_km": "សាខាភ្នំពេញ១",
                   "receipt_header": "St 271, Phnom Penh\nTel 012 000 111", "receipt_footer": "Thank you · អរគុណ"},
        "customer": None, "cashier_id": str(uuid4()), "completed_at": "2026-10-27T03:15:00+00:00",
        "lines": [
            {"line_no": 1, "line_id": str(uuid4()), "medicine_id": str(uuid4()), "pack_unit_id": str(uuid4()),
             "sku": "PARA500", "name": "Panadol (Paracetamol)", "name_km": "ប៉ាណាដុល ប៉ារ៉ាសេតាម៉ុល",
             "pack_unit": "strip", "qty": 2, "qty_in_base": 10, "qty_base": 20, "unit_price": "0.90",
             "line_total": "1.80", "cost": "0.80", "returned_qty_base": 0, "batch_override": None, "batches": []},
            {"line_no": 2, "line_id": str(uuid4()), "medicine_id": str(uuid4()), "pack_unit_id": str(uuid4()),
             "sku": "ORS", "name": "ORS", "name_km": "", "pack_unit": "sachet", "qty": 5, "qty_in_base": 1,
             "qty_base": 5, "unit_price": "0.47", "line_total": "2.35", "cost": "0.50", "returned_qty_base": 0,
             "batch_override": None, "batches": []},
        ],
        "subtotal": "4.15", "discount": "0.00", "total": "4.15", "khr_per_usd": 4100, "total_khr": 17000,
        "payments": [{"method": "cash", "currency": "USD", "amount": "2.00", "amount_usd": "2.00"},
                     {"method": "cash", "currency": "KHR", "amount": "10000", "amount_usd": "2.44"}],
        "paid": "4.44", "credit_amount": "0.00", "change_usd": "0.29", "change_in": "USD_KHR",
        "change_given_usd": "0.00", "change_given_khr": 1200, "change_rounding_khr": "-11.00",
        "returned_total": "0.00", "cancel_reason": None, "cancelled_at": None, "returns": [], **extra,
    }  # fmt: skip


async def store(payload: dict) -> bool:
    async with db.sessionmaker() as session, session.begin():
        return await upsert_invoice(session, payload)


def body(inv: dict, kind: str = "receipt_80mm") -> dict:
    return {"type": kind, "invoice_id": inv["invoice_id"]}


@pytest.fixture(autouse=True)
def short_wait():
    app.state.settings.document_wait_seconds = 0.5
    yield
    app.state.settings.document_wait_seconds = 5.0


@needs_pdf
async def test_80mm_receipt_shows_usd_khr_payments_and_change(client) -> None:
    inv = invoice_event()
    await store(inv)
    r = await client.post(f"{PREFIX}/render", json=body(inv), headers=CASHIER)
    assert r.status_code == 200, r.text
    reader = PdfReader(io.BytesIO(r.content))
    page = reader.pages[0]
    width_mm, height_mm = float(page.mediabox.width) / 72 * 25.4, float(page.mediabox.height) / 72 * 25.4
    assert round(width_mm) == 80 and 60 < height_mm < 200  # cut to its content, not a 2 m page
    text = page.extract_text()
    for expected in ("PP1-INV-2026-000123", "Panadol (Paracetamol)", "$4.15", "17,000", "10,000", "1,200",
                     "1 USD = 4,100", "St 271, Phnom Penh", "2026-10-27 10:15"):  # fmt: skip
        assert expected in text, expected
    fonts = {str(f.get_object().get("/BaseFont")) for f in page["/Resources"]["/Font"].values()}
    assert any("Khmer" in f for f in fonts)
    assert "CANCELLED" not in text


@needs_pdf
async def test_a4_invoice_and_cancelled_mark(client) -> None:
    inv = invoice_event(version=2, status="cancelled")
    await store(inv)
    r = await client.post(f"{PREFIX}/render", json={**body(inv, "invoice_a4"), "lang": "en"}, headers=CASHIER)
    assert r.status_code == 200
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    assert "PP1-INV-2026-000123" in text and "4.15" in text and "CANCELLED" in text
    r = await client.post(f"{PREFIX}/render", json={**body(inv), "lang": "en"}, headers=CASHIER)
    assert "CANCELLED" in PdfReader(io.BytesIO(r.content)).pages[0].extract_text()


async def test_receipts_need_sales_access_and_the_branch(client) -> None:
    inv = invoice_event()
    await store(inv)
    assert (await client.post(f"{PREFIX}/render", json=body(inv), headers=LABELLER)).status_code == 403
    assert (await client.post(f"{PREFIX}/render", json=body(inv), headers=OTHER)).status_code == 404


async def test_an_invoice_still_on_its_way_waits_then_409(client) -> None:
    r = await client.post(f"{PREFIX}/render", json={"type": "receipt_80mm", "invoice_id": str(uuid4())},
                          headers=CASHIER)  # fmt: skip
    assert r.status_code == 409 and r.json()["code"] == "DOCUMENT_NOT_READY"


async def test_older_invoice_events_are_ignored(client) -> None:
    inv = invoice_event(version=2, status="cancelled")
    assert await store(inv) is True
    assert await store({**inv, "version": 1, "status": "completed"}) is False


def test_payment_rows_show_bank_transfer_and_its_reference_escaped() -> None:
    from document_service.services.receipts import _payments

    rows = _payments({"payments": [
        {"method": "ABA", "currency": "USD", "amount": "5.00", "reference": "TT 2026/11-0042"},
        {"method": "PAYWAY", "currency": "USD", "amount": "2.00"},
        {"method": "card", "currency": "KHR", "amount": "4100", "reference": None}]})  # fmt: skip
    assert rows[0][0] == "Bank transfer · TT 2026/11-0042" and rows[1][0] == "Card / Wallet (PayWay)"
    assert rows[2][0] == "Card"
