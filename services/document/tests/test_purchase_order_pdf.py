import asyncio
import io
from uuid import UUID, uuid4

import pytest
from pypdf import PdfReader

from document_service.db import db
from document_service.main import app
from document_service.services.purchase_orders import upsert_po

from .conftest import CASHIER, OWNER, PREFIX, needs_pdf, user

PP1 = str(uuid4())
PP1_ID = UUID(PP1)
BUYER = user("branch_manager", "purchasing.order,labels.print", (PP1_ID,))


def po_event(version: int = 2, status: str = "sent", branch: str = PP1, **extra) -> dict:
    return {
        "purchase_order_id": extra.pop("po_id", str(uuid4())), "version": version, "number": "PP1-PO-2026-000001",
        "status": status,
        "branch": {"id": branch, "code": "PP1", "name_en": "Phnom Penh 1", "name_km": "សាខាភ្នំពេញ១"},
        "supplier": {"id": str(uuid4()), "code": "DKSH", "name": "DKSH Cambodia", "name_km": "ឌីខេអេសអេច",
                     "phone": "023 999 000", "address": "St 271, Phnom Penh", "payment_terms_days": 30},
        "note": "Deliver before Friday", "expected_on": "2026-11-05", "created_at": "2026-10-27T03:00:00+00:00",
        "sent_at": "2026-10-27T04:00:00+00:00", "cancel_reason": None, "total": "52.50",
        "lines": [
            {"line_no": 1, "po_line_id": str(uuid4()), "medicine_id": str(uuid4()), "sku": "PARA500",
             "name": "Panadol (Paracetamol)", "name_km": "ប៉ាណាដុល ប៉ារ៉ាសេតាម៉ុល", "strength": "500mg",
             "dosage_form": "tablet", "base_unit": "tablet", "pack_unit_id": str(uuid4()), "pack_unit": "box",
             "qty_in_base": 120, "qty": 10, "qty_base": 1200, "unit_cost": "4.2500", "line_total": "42.50",
             "qty_received_base": 0},
            {"line_no": 2, "po_line_id": str(uuid4()), "medicine_id": str(uuid4()), "sku": "ORS",
             "name": "ORS (Oral rehydration salts)", "name_km": "អូរ៉េស៊ីត", "strength": "20.5g",
             "dosage_form": "sachet", "base_unit": "sachet", "pack_unit_id": str(uuid4()), "pack_unit": "box",
             "qty_in_base": 20, "qty": 4, "qty_base": 80, "unit_cost": "2.5000", "line_total": "10.00",
             "qty_received_base": 0},
        ],
        **extra,
    }  # fmt: skip


async def store(payload: dict) -> bool:
    async with db.sessionmaker() as session, session.begin():
        return await upsert_po(session, payload)


def body(po: dict) -> dict:
    return {"type": "purchase_order", "purchase_order_id": po["purchase_order_id"]}


@pytest.fixture(autouse=True)
def short_wait():
    app.state.settings.document_wait_seconds = 0.5
    yield
    app.state.settings.document_wait_seconds = 5.0


@needs_pdf
async def test_po_pdf_shows_supplier_lines_and_total(client) -> None:
    po = po_event()
    await store(po)
    r = await client.post(f"{PREFIX}/render", json=body(po), headers=OWNER)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert 'filename="PP1-PO-2026-000001.pdf"' in r.headers["content-disposition"]
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    for expected in ("PP1-PO-2026-000001", "DKSH Cambodia", "Panadol (Paracetamol)", "4.25", "42.50",
                     "52.50", "St 271, Phnom Penh"):  # fmt: skip
        assert expected in text, expected
    assert "DRAFT" not in text
    reader = PdfReader(io.BytesIO(r.content))
    fonts = {str(f.get_object().get("/BaseFont")) for f in reader.pages[0]["/Resources"]["/Font"].values()}
    assert any("Khmer" in f for f in fonts)


@needs_pdf
async def test_draft_po_is_watermarked(client) -> None:
    po = po_event(version=1, status="draft")
    await store(po)
    r = await client.post(f"{PREFIX}/render", json=body(po), headers=BUYER)
    assert "DRAFT" in PdfReader(io.BytesIO(r.content)).pages[0].extract_text()


async def test_needs_purchasing_order_and_the_branch(client) -> None:
    po = po_event()
    await store(po)
    r = await client.post(f"{PREFIX}/render", json=body(po), headers=CASHIER)
    assert r.status_code == 403
    other = user("branch_manager", "purchasing.order", (uuid4(),))
    r = await client.post(f"{PREFIX}/render", json=body(po), headers=other)
    assert r.status_code == 404


async def test_waits_for_a_po_still_on_its_way_then_409(client) -> None:
    po = po_event()
    r = await client.post(f"{PREFIX}/render", json=body(po), headers=OWNER)
    assert r.status_code == 409 and r.json()["code"] == "DOCUMENT_NOT_READY"


@needs_pdf
async def test_a_po_arriving_during_the_wait_is_printed(client) -> None:
    po = po_event()

    async def arrive_later() -> None:
        await asyncio.sleep(0.2)
        await store(po)

    task = asyncio.create_task(arrive_later())
    r = await client.post(f"{PREFIX}/render", json=body(po), headers=OWNER)
    await task
    assert r.status_code == 200


async def test_older_po_events_are_ignored(client) -> None:
    po = po_event(version=3, status="received")
    assert await store(po) is True
    assert await store({**po, "version": 2, "status": "sent"}) is False
    assert await store({**po, "version": 3}) is False
    assert await store({**po, "version": 4, "status": "cancelled"}) is True
