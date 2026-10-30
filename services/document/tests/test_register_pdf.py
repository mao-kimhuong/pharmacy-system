"""The controlled-drug register PDF (data from the controlled service)."""

import io
from uuid import uuid4

from pypdf import PdfReader

from document_service.api.render import get_controlled
from document_service.main import app

from .conftest import PREFIX, needs_pdf, user

PP1 = uuid4()
MED = str(uuid4())
VIEWER = user("pharmacist", "controlled.view", (PP1,))


class FakeControlled:
    def __init__(self) -> None:
        self.asked: list[dict] = []

    async def post(self, path: str, body: dict | None = None, **_) -> dict:  # noqa: ANN003
        self.asked.append(body or {})
        entry = {"id": str(uuid4()), "seq": 1, "branch_id": str(PP1), "medicine_id": MED, "batch_id": str(uuid4()),
                 "lot_no": "D1", "expiry_date": "2028-01-31", "entry_type": "receive", "qty_base": 100,
                 "balance_after": 100, "ref_type": "receipt_line", "ref_id": "x", "prescription_number": "",
                 "patient_id": None, "patient_name": "", "patient_id_document": "", "actor_id": None,
                 "actor_name": "Lina", "witness_id": None, "witness_name": "", "reason": "PO receipt",
                 "corrects_entry_id": None, "occurred_at": "2026-10-27T03:00:00+00:00", "entry_hash": "a" * 64}  # fmt: skip
        out = {**entry, "seq": 2, "id": str(uuid4()), "entry_type": "dispense", "qty_base": -5, "balance_after": 95,
               "prescription_number": "PP1-RX-2026-000003", "patient_name": "Sok Dara",
               "patient_id_document": "ID-0123", "witness_name": ""}  # fmt: skip
        return {"branch_id": str(PP1), "branch_name_en": "Phnom Penh 1", "branch_name_km": "សាខាភ្នំពេញ១",
                "chain_valid": True, "chains": [{"medicine_id": MED, "valid": True, "entries": 2,
                                                 "first_bad_entry_id": None, "problem": ""}],
                "medicines": [{"id": MED, "sku": "DIAZ5", "name": "Valium (Diazepam)", "name_km": "ឌីអាហ្សេប៉ាម",
                               "strength": "5mg", "base_unit": "tablet", "schedule": "IV"}],
                "entries": [entry, out]}  # fmt: skip


@needs_pdf
async def test_register_pdf_lists_entries_with_balance_and_patient(client) -> None:
    fake = FakeControlled()
    app.dependency_overrides[get_controlled] = lambda: fake
    try:
        r = await client.post(f"{PREFIX}/render", headers=VIEWER, json={
            "type": "controlled_register", "branch_id": str(PP1), "date_from": "2026-10-01"})  # fmt: skip
        assert r.status_code == 200, r.text
        text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
        for expected in ("Controlled drug register", "Valium (Diazepam)", "PP1-RX-2026-000003", "Sok Dara", "ID-0123",
                         "95", "Chain verified"):  # fmt: skip
            assert expected in text, expected
        assert fake.asked[0]["date_from"] == "2026-10-01"
        other = user("pharmacist", "controlled.view", (uuid4(),))
        body = {"type": "controlled_register", "branch_id": str(PP1)}
        assert (await client.post(f"{PREFIX}/render", headers=other, json=body)).status_code == 403
        no_perm = user("cashier", "pos.sell", (PP1,))
        assert (await client.post(f"{PREFIX}/render", headers=no_perm, json=body)).status_code == 403
    finally:
        app.dependency_overrides.pop(get_controlled, None)
