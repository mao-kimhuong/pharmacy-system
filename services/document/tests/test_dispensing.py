"""Dispensing labels (size from the branch setting, Khmer / English) and the
patient's Rx summary, printed from event copies."""

import io
from uuid import uuid4

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from document_service.db import db
from document_service.main import app
from document_service.models import OutboxEvent
from document_service.services.events import handle_event

from .conftest import PREFIX, needs_pdf, user
from .test_receipts import PP1, invoice_event, store

PHARMACIST = user("pharmacist", "pos.sell,pos.dispense_rx,prescriptions.view", (PP1,))
OTHER_BRANCH = user("pharmacist", "pos.sell,pos.dispense_rx,prescriptions.view", (uuid4(),))
CASHIER = user("cashier", "pos.sell,sales.view", (PP1,))
PATIENT = str(uuid4())


def rx_invoice(size: str | None = None, **extra) -> dict:
    inv = invoice_event(**extra)
    if size:
        inv["branch"]["dispensing_label_size"] = size
    inv["lines"][0]["rx"] = {
        "rx_item_id": str(uuid4()), "prescription_id": str(uuid4()), "prescription_number": "PP1-RX-2026-000007",
        "patient_id": PATIENT, "patient_name_en": "Sok Dara", "patient_name_km": "សុខ ដារា",
        "doctor_name": "Dr Chan", "dosage": "1 tablet", "frequency": "3 times a day", "duration_days": 5,
        "warnings": [], "allergy_override_reason": None, "allergy_override_by": None,
        "warnings_acknowledged_by": None, "warnings_acknowledged_at": None,
    }  # fmt: skip
    inv["lines"][0]["batches"] = [{"batch_id": str(uuid4()), "lot_no": "LOT-A1", "expiry_date": "2028-01-31",
                                   "qty_base": 20, "cost_per_base": "0.04"}]  # fmt: skip
    return inv


async def event(event_type: str, payload: dict) -> None:
    async with db.sessionmaker() as session, session.begin():
        await handle_event(session, event_type, payload, uuid4())


def size_mm(page) -> tuple[int, int]:  # noqa: ANN001
    return round(float(page.mediabox.width) / 72 * 25.4), round(float(page.mediabox.height) / 72 * 25.4)


@pytest.fixture(autouse=True)
def short_wait():
    app.state.settings.document_wait_seconds = 0.5
    yield
    app.state.settings.document_wait_seconds = 5.0


async def label(client, inv: dict, headers=PHARMACIST, **extra):  # noqa: ANN001, ANN201
    return await client.post(f"{PREFIX}/render", json={"type": "dispensing_label", "invoice_id": inv["invoice_id"],
                                                       **extra}, headers=headers)  # fmt: skip


@needs_pdf
async def test_label_70x40_by_default_with_directions_lot_and_pharmacist(client) -> None:
    inv = rx_invoice()
    await store(inv)
    await event("user.updated", {"user_id": inv["cashier_id"], "name": "Pharmacist Lina", "role": "pharmacist",
                                 "is_pharmacist": True, "is_active": True, "branch_ids": [str(PP1)]})  # fmt: skip
    r = await label(client, inv, lang="en")
    assert r.status_code == 200, r.text
    pages = PdfReader(io.BytesIO(r.content)).pages
    assert len(pages) == 1 and size_mm(pages[0]) == (70, 40)  # only the Rx line
    text = pages[0].extract_text()
    for expected in ("Sok Dara", "1 tablet", "3 times a day", "5 days", "PP1-RX-2026-000007", "LOT-A1",
                     "Pharmacist Lina", "Dr Chan"):  # fmt: skip
        assert expected in text, expected


@needs_pdf
async def test_label_size_follows_the_branch_setting_and_khmer(client) -> None:
    inv = rx_invoice("50x30")
    await store(inv)
    r = await label(client, inv)
    page = PdfReader(io.BytesIO(r.content)).pages[0]
    assert size_mm(page) == (50, 30)
    fonts = {str(f.get_object().get("/BaseFont")) for f in page["/Resources"]["/Font"].values()}
    assert any("Khmer" in f for f in fonts)
    r = await label(client, inv, size="a4_sheet")
    assert size_mm(PdfReader(io.BytesIO(r.content)).pages[0]) == (210, 297)


async def test_label_permissions_branch_and_lines(client) -> None:
    inv = rx_invoice()
    await store(inv)
    assert (await label(client, inv, CASHIER)).status_code == 403
    assert (await label(client, inv, OTHER_BRANCH)).status_code == 404
    plain = invoice_event()
    await store(plain)
    assert (await label(client, plain)).status_code == 404  # no Rx line
    cancelled = rx_invoice(status="cancelled")
    await store(cancelled)
    assert (await label(client, cancelled)).status_code == 409


def patient_event(version: int = 1, branches: tuple = (PP1,)) -> dict:
    return {"patient_id": PATIENT, "version": version, "name_en": "Sok Dara", "name_km": "សុខ ដារា", "sex": "female",
            "dob": "1990-05-01", "phone": "012345678", "customer_id": None, "chronic_conditions": "Asthma",
            "notes": "", "is_active": True, "home_branch_id": str(branches[0]),
            "branch_ids": [str(b) for b in branches],
            "allergies": [{"kind": "class", "value": "penicillins", "note": ""}]}  # fmt: skip


def rx_event(version: int = 1, status: str = "partly_dispensed", branch=PP1) -> dict:  # noqa: ANN001
    return {"prescription_id": str(uuid4()), "version": version, "number": "PP1-RX-2026-000007", "rx_no": "A-1",
            "status": status, "branch_id": str(branch), "issued_on": "2026-10-25", "valid_until": "2026-11-24",
            "patient": {"id": PATIENT, "name_km": "សុខ ដារា", "name_en": "Sok Dara", "sex": "female",
                        "dob": None, "phone": ""},
            "doctor": {"id": str(uuid4()), "name": "Dr Chan", "licence_no": "MD-1", "clinic": "Calmette"},
            "notes": "", "cancel_reason": None,
            "items": [{"rx_item_id": str(uuid4()), "line_no": 1, "medicine_id": str(uuid4()), "sku": "AMOX500",
                       "name": "Ospamox (Amoxicillin)", "name_km": "អាម៉ុកស៊ីស៊ីលីន", "strength": "500mg",
                       "base_unit": "capsule", "qty_base": 21, "dosage": "1 capsule", "frequency": "3x a day",
                       "duration_days": 7, "repeats_allowed": 1, "repeats_used": 0, "dispensed_base": 10,
                       "remaining_base": 32}]}  # fmt: skip


@needs_pdf
async def test_rx_summary_lists_allergies_and_remaining_and_is_logged(client) -> None:
    await event("patient.created", patient_event())
    await event("prescription.dispensed", rx_event())
    other = rx_event(branch=uuid4())
    other["number"] = "PP9-RX-2026-000001"
    await event("prescription.created", other)
    r = await client.post(f"{PREFIX}/render", json={"type": "rx_summary", "patient_id": PATIENT}, headers=PHARMACIST)
    assert r.status_code == 200, r.text
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    for expected in ("Sok Dara", "penicillins", "Asthma", "PP1-RX-2026-000007", "Ospamox", "32"):
        assert expected in text, expected
    assert "PP9-RX" not in text  # another branch's Rx
    async with db.sessionmaker() as s:
        rows = (await s.execute(select(OutboxEvent).where(OutboxEvent.event_type == "audit.recorded"))).scalars()
        assert [x.payload["action"] for x in rows] == ["rx_summary.printed"]


async def test_rx_summary_permission_and_branch(client) -> None:
    await event("patient.created", patient_event())
    body = {"type": "rx_summary", "patient_id": PATIENT}
    assert (await client.post(f"{PREFIX}/render", json=body, headers=CASHIER)).status_code == 403
    assert (await client.post(f"{PREFIX}/render", json=body, headers=OTHER_BRANCH)).status_code == 404
    await event("patient.updated", patient_event(version=0, branches=(uuid4(),)))  # older: ignored
    assert (await client.post(f"{PREFIX}/render", json={"type": "rx_summary", "patient_id": str(uuid4())},
                              headers=PHARMACIST)).status_code == 409  # fmt: skip
