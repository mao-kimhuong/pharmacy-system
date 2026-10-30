"""Selling a controlled medicine (S5): Rx + pharmacist + controlled.dispense +
the patient's ID document + the pharmacist's PIN; the stock movements carry
what the controlled-drug register records (Rx, patient, pharmacist), also on
cancel and return."""

from sqlalchemy import select

from inventory_service.db import db as inventory_db
from inventory_service.models import Movement

from .conftest import AUTH, PP1, PREFIX, add_product, line, pay, receive, sell, user
from .test_dispensing import RX_PERMS, prescribe

CONTROLLED_PHARMACIST = user("pharmacist", RX_PERMS + ",controlled.dispense", pharmacist=True)
PLAIN_PHARMACIST = user("pharmacist", RX_PERMS, pharmacist=True)


def pin(who: dict = CONTROLLED_PHARMACIST, action: str = "controlled.dispense") -> str:
    return AUTH.issue(who["X-User-Id"], action, branches=(PP1,), name="Pharmacist Lina")


async def movements(medicine_id: str) -> list[Movement]:
    async with inventory_db.sessionmaker() as s:
        return list((await s.execute(select(Movement).where(Movement.medicine_id == medicine_id)
                                     .order_by(Movement.seq))).scalars())  # fmt: skip


async def stocked() -> dict:
    diaz = await add_product("DIAZ5", controlled="IV")
    await receive(diaz, [("D1", "2028-01-31", 100)])
    return diaz


async def test_controlled_sale_needs_rx_pharmacist_id_and_pin(client) -> None:
    diaz = await stocked()
    rx = await prescribe(diaz, qty=10)
    good = line(diaz, "tablet", 5, rx_item_id=rx["item"], patient_id_document="ID-0123456")
    r = await sell(client, [line(diaz, "tablet", 5, rx_item_id=rx["item"])], [pay("0.50")], CONTROLLED_PHARMACIST,
                   pin_token=pin())  # fmt: skip
    assert r.status_code == 422 and r.json()["details"]["field"] == "patient_id_document"
    r = await sell(client, [good], [pay("0.50")], PLAIN_PHARMACIST, pin_token=pin(PLAIN_PHARMACIST))
    assert r.status_code == 403 and r.json()["code"] == "PHARMACIST_REQUIRED"
    r = await sell(client, [good], [pay("0.50")], CONTROLLED_PHARMACIST)
    assert r.status_code == 401 and r.json()["code"] == "PIN_REQUIRED"
    r = await sell(client, [good], [pay("0.50")], CONTROLLED_PHARMACIST, pin_token=pin(action="controlled.adjust"))
    assert r.status_code == 401 and r.json()["code"] == "PIN_INVALID"
    other = user("pharmacist", "x", pharmacist=True)
    r = await sell(client, [good], [pay("0.50")], CONTROLLED_PHARMACIST, pin_token=pin(other))
    assert r.status_code == 401  # someone else's PIN confirmation
    token = pin()
    r = await sell(client, [good], [pay("0.50")], CONTROLLED_PHARMACIST, pin_token=token)
    assert r.status_code == 201, r.text
    ln = r.json()["lines"][0]
    assert ln["is_controlled"] and ln["patient_id_document"] == "ID-0123456"
    assert ln["pin_confirmed_by"] == CONTROLLED_PHARMACIST["X-User-Id"]
    out = (await movements(diaz["id"]))[-1]
    assert out.type == "out" and out.meta["prescription_number"] == rx["number"]
    assert out.meta["patient_id_document"] == "ID-0123456" and out.meta["pharmacist_name"] == "Pharmacist Lina"
    # the PIN works once
    r = await sell(client, [good], [pay("0.50")], CONTROLLED_PHARMACIST, pin_token=token)
    assert r.status_code == 401


async def test_cancel_and_return_carry_the_register_details(client) -> None:
    diaz = await stocked()
    rx = await prescribe(diaz, qty=10)
    good = line(diaz, "tablet", 6, rx_item_id=rx["item"], patient_id_document="P-778899")
    inv = (await sell(client, [good], [pay("0.60")], CONTROLLED_PHARMACIST, pin_token=pin())).json()
    r = await client.post(f"{PREFIX}/invoices/{inv['id']}/returns", headers={**CONTROLLED_PHARMACIST,
                          "Idempotency-Key": "return-ctl-01"}, json={"lines": [{"invoice_line_id": inv["lines"][0]["id"],
                          "qty": 2}], "reason": "patient stopped", "refund_method": "cash"})  # fmt: skip
    assert r.status_code == 201, r.text
    ret = (await movements(diaz["id"]))[-1]
    assert ret.type == "return" and ret.meta["patient_id_document"] == "P-778899"
    inv2 = (await sell(client, [line(diaz, "tablet", 2, rx_item_id=rx["item"], patient_id_document="P-778899")],
                       [pay("0.20")], CONTROLLED_PHARMACIST, pin_token=pin())).json()  # fmt: skip
    manager = user("branch_manager", "sales.cancel,sales.view")
    r = await client.post(f"{PREFIX}/invoices/{inv2['id']}/cancel", json={"reason": "wrong patient"},
                          headers={**manager, "Idempotency-Key": "cancel-ctl-01"})  # fmt: skip
    assert r.status_code == 200, r.text
    back = (await movements(diaz["id"]))[-1]
    assert back.type == "sale_cancel" and back.meta["prescription_number"] == rx["number"]
