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


CUSTOMER = {"id": str(uuid4()), "name": "Sok Dara", "name_km": "", "phone": "012345678"}


class Links:
    """Stands in for the notification service's /internal/v1/link-tokens."""

    def __init__(self, url: str | None = "https://t.me/pharma_bot?start=cabc123") -> None:
        self.url, self.asked = url, []

    async def __call__(self, customer_id: str, ref: str, via: str) -> str | None:
        self.asked.append((customer_id, ref, via))
        return self.url


@pytest.fixture
def links():  # noqa: ANN201
    fake = Links()
    app.state.link_for = fake
    yield fake
    del app.state.link_for


def test_the_telegram_qr_is_only_drawn_with_a_link() -> None:
    from document_service.services.receipts import invoice_a4_html, receipt_html

    inv = invoice_event(customer=CUSTOMER)
    assert "Telegram" not in receipt_html(inv) and "Telegram" not in invoice_a4_html(inv)
    with_qr = receipt_html(inv, lang="en", tg_url="https://t.me/pharma_bot?start=cabc123")
    assert 'alt="Telegram"' in with_qr and "data:image/svg+xml" in with_qr and "Get receipts and reminders" in with_qr
    assert "ទទួលបង្កាន់ដៃ" in invoice_a4_html(inv, "km", "https://t.me/pharma_bot?start=cabc123")


@needs_pdf
async def test_receipt_of_a_customer_asks_for_the_telegram_link_once_per_invoice(client, links) -> None:
    inv = invoice_event(customer=CUSTOMER)
    await store(inv)
    r = await client.post(f"{PREFIX}/render", json={**body(inv), "lang": "en"}, headers=CASHIER)
    assert r.status_code == 200
    assert links.asked == [(CUSTOMER["id"], f"invoice:{inv['invoice_id']}", "receipt")]
    assert "Telegram" in PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    walk_in = invoice_event()
    await store(walk_in)
    await client.post(f"{PREFIX}/render", json=body(walk_in), headers=CASHIER)
    assert len(links.asked) == 1  # no customer: nothing to link


@needs_pdf
async def test_no_link_or_notification_down_still_prints(client, links) -> None:
    from document_service.services.telegram_link import link_getter
    from pharmacy_shared.errors import AppError, ErrorCode

    links.url = None
    inv = invoice_event(customer=CUSTOMER)
    await store(inv)
    r = await client.post(f"{PREFIX}/render", json={**body(inv), "lang": "en"}, headers=CASHIER)
    assert r.status_code == 200 and "Telegram" not in PdfReader(io.BytesIO(r.content)).pages[0].extract_text()

    class Down:
        async def post(self, *_: object, **__: object) -> dict:
            raise AppError(ErrorCode.TEMPORARILY_UNAVAILABLE, "down", status_code=503)

    class Broken:
        async def post(self, *_: object, **__: object) -> dict:
            raise TimeoutError

    assert await link_getter(Down())("c", "invoice:1", "receipt") is None
    assert await link_getter(Broken())("c", "invoice:1", "receipt") is None


@needs_pdf
async def test_internal_render_for_telegram_needs_the_service_token_and_has_no_qr(client, links) -> None:
    import base64

    app.state.settings.service_token = "t" * 40
    try:
        inv = invoice_event(customer=CUSTOMER)
        await store(inv)
        doc = {"type": "invoice_a4", "id": inv["invoice_id"], "lang": "en"}
        assert (await client.post("/internal/v1/render", json=doc)).status_code == 401
        r = await client.post("/internal/v1/render", json=doc, headers={"X-Service-Token": "t" * 40})
        assert r.status_code == 200 and r.json()["filename"] == "PP1-INV-2026-000123.pdf"
        pdf = base64.b64decode(r.json()["pdf_base64"])
        assert "Telegram" not in PdfReader(io.BytesIO(pdf)).pages[0].extract_text() and links.asked == []
        missing = await client.post("/internal/v1/render", json={**doc, "id": str(uuid4())},
                                    headers={"X-Service-Token": "t" * 40})  # fmt: skip
        assert missing.status_code == 409 and missing.json()["code"] == "DOCUMENT_NOT_READY"
    finally:
        app.state.settings.service_token = ""


def test_payment_rows_show_bank_transfer_and_its_reference_escaped() -> None:
    from document_service.services.receipts import _payments

    rows = _payments({"payments": [
        {"method": "ABA", "currency": "USD", "amount": "5.00", "reference": "TT 2026/11-0042"},
        {"method": "PAYWAY", "currency": "USD", "amount": "2.00"},
        {"method": "card", "currency": "KHR", "amount": "4100", "reference": None}]})  # fmt: skip
    assert rows[0][0] == "Bank transfer · TT 2026/11-0042" and rows[1][0] == "Card / Wallet (PayWay)"
    assert rows[2][0] == "Card"
