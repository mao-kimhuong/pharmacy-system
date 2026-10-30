"""Transfer note (QR of the number) and the PO group printout for the supplier."""

import io
from uuid import uuid4

import pytest
from pypdf import PdfReader

from document_service.db import db
from document_service.main import app
from document_service.services.events import handle_event
from document_service.services.transfer_note import qr_data_uri

from .conftest import PREFIX, needs_pdf, user

PP1, PP2 = uuid4(), uuid4()
SENDER = user("pharmacist", "transfers.dispatch", (PP1,))
RECEIVER = user("cashier", "transfers.receive", (PP2,))
BUYER = user("owner", "*", ())


@pytest.fixture(autouse=True)
def short_wait():
    app.state.settings.document_wait_seconds = 0.5
    yield
    app.state.settings.document_wait_seconds = 5.0


async def event(event_type: str, payload: dict) -> None:
    async with db.sessionmaker() as session, session.begin():
        await handle_event(session, event_type, payload, uuid4())


def transfer(version: int = 3, status: str = "dispatched") -> dict:
    tid = str(uuid4())
    return {"transfer_id": tid, "version": version, "number": "PP1-TR-2026-000004", "status": status,
            "from_branch": {"id": str(PP1), "code": "PP1", "name_en": "Phnom Penh 1", "name_km": "សាខា១"},
            "to_branch": {"id": str(PP2), "code": "PP2", "name_en": "Siem Reap", "name_km": "សៀមរាប"},
            "request_id": None, "request_number": "PP2-TQ-2026-000001", "note": "", "created_at": "2026-10-27T03:00:00+00:00",
            "dispatched_at": "2026-10-27T04:00:00+00:00", "received_at": None, "dispatch_witness": "Dara",
            "receive_witness": "", "cancel_reason": None,
            "lines": [{"line_no": 1, "medicine_id": str(uuid4()), "qty_base": 40, "is_controlled": False,
                       "source_ref": None, "sku": "PARA500", "name": "Panadol (Paracetamol)", "name_km": "ប៉ាណាដុល",
                       "base_unit": "tablet"}],
            "picks": [{"pick_id": str(uuid4()), "line_no": 1, "batch_id": str(uuid4()), "lot_no": "EARLY",
                       "expiry_date": "2027-03-31", "supplier_id": None, "cost_per_base": "0.1000", "qty_base": 30,
                       "qty_received": None, "qty_damaged": None, "override_reason": None},
                      {"pick_id": str(uuid4()), "line_no": 1, "batch_id": str(uuid4()), "lot_no": "LATE",
                       "expiry_date": "2028-06-30", "supplier_id": None, "cost_per_base": "0.1200", "qty_base": 10,
                       "qty_received": None, "qty_damaged": None, "override_reason": None}],
            "discrepancies": []}  # fmt: skip


def test_qr_code_is_an_svg_of_the_number() -> None:
    uri = qr_data_uri("PP1-TR-2026-000004")
    assert uri.startswith("data:image/svg+xml")


@needs_pdf
async def test_transfer_note_for_both_branches_only(client) -> None:
    t = transfer()
    await event("transfer.dispatched", t)
    await event("transfer.picked", {**t, "version": 2, "status": "picked"})  # older: ignored
    for who in (SENDER, RECEIVER):
        r = await client.post(f"{PREFIX}/render", json={"type": "transfer_note", "transfer_id": t["transfer_id"]},
                              headers=who)  # fmt: skip
        assert r.status_code == 200, r.text
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    for expected in ("PP1-TR-2026-000004", "Panadol (Paracetamol)", "EARLY", "2027-03-31", "LATE", "Siem Reap",
                     "dispatched", "Dara"):  # fmt: skip
        assert expected in text, expected
    assert "0.1000" not in text  # no cost on a transfer note
    outsider = user("pharmacist", "transfers.dispatch", (uuid4(),))
    body = {"type": "transfer_note", "transfer_id": t["transfer_id"]}
    assert (await client.post(f"{PREFIX}/render", json=body, headers=outsider)).status_code == 404
    no_perm = user("cashier", "pos.sell", (PP1,))
    assert (await client.post(f"{PREFIX}/render", json=body, headers=no_perm)).status_code == 403


def po(branch, number: str, group: dict) -> dict:  # noqa: ANN001
    return {"purchase_order_id": str(uuid4()), "version": 1, "number": number, "status": "draft",
            "branch": {"id": str(branch), "code": number[:3], "name_en": f"Branch {number[:3]}", "name_km": ""},
            "supplier": {"id": str(uuid4()), "code": "DKSH", "name": "DKSH Cambodia", "name_km": "", "phone": "023",
                         "address": "Phnom Penh", "payment_terms_days": 30},
            "note": "", "expected_on": None, "created_at": "2026-10-27T03:00:00+00:00", "sent_at": None,
            "cancel_reason": None, "total": "12.00", "group": group,
            "lines": [{"line_no": 1, "po_line_id": str(uuid4()), "medicine_id": str(uuid4()), "sku": "PARA500",
                       "name": "Panadol", "name_km": "", "strength": "", "dosage_form": "", "base_unit": "tablet",
                       "pack_unit_id": str(uuid4()), "pack_unit": "box", "qty_in_base": 100, "qty": 3,
                       "qty_base": 300, "unit_cost": "4.0000", "line_total": "12.00", "qty_received_base": 0}]}  # fmt: skip


@needs_pdf
async def test_po_group_printout_has_a_section_per_branch(client) -> None:
    group = {"id": str(uuid4()), "number": "PP1-PG-2026-000001"}
    await event("purchase_order.created", po(PP1, "PP1-PO-2026-000007", group))
    await event("purchase_order.created", po(PP2, "PP2-PO-2026-000003", group))
    r = await client.post(f"{PREFIX}/render", json={"type": "purchase_order_group", "group_id": group["id"]},
                          headers=BUYER)  # fmt: skip
    assert r.status_code == 200, r.text
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    for expected in ("PP1-PG-2026-000001", "PP1-PO-2026-000007", "PP2-PO-2026-000003", "Branch PP1", "Branch PP2",
                     "DKSH Cambodia", "24.00"):  # fmt: skip
        assert expected in text, expected
    one_branch = user("branch_manager", "purchasing.order", (PP2,))
    r = await client.post(f"{PREFIX}/render", json={"type": "purchase_order_group", "group_id": group["id"]},
                          headers=one_branch)  # fmt: skip
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "PP2-PO-2026-000003" in text and "PP1-PO-2026-000007" not in text
    missing = await client.post(f"{PREFIX}/render", json={"type": "purchase_order_group", "group_id": str(uuid4())},
                                headers=BUYER)  # fmt: skip
    assert missing.status_code == 409
