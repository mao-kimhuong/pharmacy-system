"""Selling against a prescription (S4): the saga's Rx step against the REAL
prescription app – limits, partial dispensing, warnings, compensation."""

from datetime import date
from uuid import uuid4

import httpx
import pytest

from pharmacy_shared import clock
from prescription_service.main import app as prescription_app

from .conftest import (
    CASHIER,
    PP1,
    PREFIX,
    add_product,
    audits,
    inventory_stock,
    line,
    pay,
    prescription_event,
    receive,
    relay_invoices,
    sell,
    user,
)  # fmt: skip

RX = "/api/prescription/v1"
RX_PERMS = ("pos.sell,sales.view,sales.cancel,sales.return,pos.dispense_rx,patients.view,patients.manage,"
            "prescriptions.view,prescriptions.manage")  # fmt: skip
PHARMACIST = user("pharmacist", RX_PERMS + ",prescriptions.override_warning", pharmacist=True)
PHARMACIST_NO_OVERRIDE = user("pharmacist", RX_PERMS, pharmacist=True)
CASHIER_RX = user("cashier", RX_PERMS)  # even with the permissions: not a pharmacist


async def rx_call(method: str, path: str, **kw) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=prescription_app), base_url="http://rx") as c:
        return await c.request(method, f"{RX}{path}", headers=PHARMACIST, **kw)


async def prescribe(product: dict, qty: int = 20, repeats: int = 0, allergies: list | None = None,
                    patient: dict | None = None) -> dict:  # fmt: skip
    if patient is None:
        r = await rx_call("POST", "/patients", json={"branch_id": str(PP1), "name_en": "Sok Dara", "sex": "female",
                                                     "allergies": allergies or []})  # fmt: skip
        assert r.status_code == 201, r.text
        patient = r.json()
    r = await rx_call("POST", "/doctors", json={"name": "Dr Chan", "licence_no": f"MD-{uuid4().hex[:6]}"})
    doctor = r.json()
    r = await rx_call("POST", "/prescriptions", json={
        "branch_id": str(PP1), "patient_id": patient["id"], "doctor_id": doctor["id"], "issued_on": "2026-10-26",
        "items": [{"medicine_id": product["id"], "qty_base": qty, "repeats_allowed": repeats,
                   "dosage": "1 tablet", "frequency": "3 times a day", "duration_days": 7}]})  # fmt: skip
    assert r.status_code == 201, r.text
    rx = (await rx_call("POST", f"/prescriptions/{r.json()['id']}/activate")).json()
    return {**rx, "item": rx["items"][0]["id"], "patient": patient}


async def remaining(rx: dict) -> int:
    return (await rx_call("GET", f"/prescriptions/{rx['id']}/remaining")).json()["items"][0]["remaining_base"]


async def stocked_rx_product(sku: str = "AMOX500", **kw) -> dict:
    product = await add_product(sku, rx=True, **kw)
    await receive(product, [("A", "2028-01-31", 200)])
    return product


async def test_rx_only_needs_a_prescription_and_a_pharmacist(client) -> None:
    amox = await stocked_rx_product()
    rx = await prescribe(amox)
    r = await sell(client, [line(amox, "strip", 1)], [pay("0.90")], PHARMACIST)
    assert r.status_code == 422 and r.json()["code"] == "RX_REQUIRED"
    for who in (CASHIER, CASHIER_RX):
        r = await sell(client, [line(amox, "strip", 1, rx_item_id=rx["item"])], [pay("0.90")], who)
        assert r.status_code == 403 and r.json()["code"] == "PHARMACIST_REQUIRED"
    assert await remaining(rx) == 20 and await inventory_stock(amox) == {"A": (200, 0, 0)}


async def test_partial_dispensing_and_the_rest_later(client) -> None:
    amox = await stocked_rx_product()
    rx = await prescribe(amox, qty=20)
    r = await sell(client, [line(amox, "strip", 1, rx_item_id=rx["item"])], [pay("0.90")], PHARMACIST)
    assert r.status_code == 201, r.text
    inv = r.json()
    ln = inv["lines"][0]
    assert ln["prescription_number"] == rx["number"] and ln["dosage"] == "1 tablet"
    assert ln["patient_name_en"] == "Sok Dara" and inv["patient_id"] == rx["patient"]["id"]
    await relay_invoices()
    assert await remaining(rx) == 10
    await relay_invoices()  # delivered again: nothing changes
    assert await remaining(rx) == 10
    r = await sell(client, [line(amox, "strip", 1, rx_item_id=rx["item"])], [pay("0.90")], PHARMACIST)
    assert r.status_code == 201
    await relay_invoices()
    assert await remaining(rx) == 0
    r = await sell(client, [line(amox, "tablet", 1, rx_item_id=rx["item"])], [pay("0.10")], PHARMACIST)
    assert r.status_code == 409 and r.json()["code"] == "PRESCRIPTION_STATE"


async def test_more_than_the_rx_allows_is_refused_and_nothing_is_kept(client) -> None:
    amox = await stocked_rx_product()
    rx = await prescribe(amox, qty=10, repeats=1)
    r = await sell(client, [line(amox, "strip", 2, rx_item_id=rx["item"])], [pay("1.80")], PHARMACIST)
    assert r.status_code == 422 and r.json()["code"] == "RX_QUANTITY_EXCEEDED"
    assert await remaining(rx) == 20 and await inventory_stock(amox) == {"A": (200, 0, 0)}


async def test_out_of_stock_gives_the_rx_quantity_back(client) -> None:
    amox = await add_product("AMOX500", rx=True)
    await receive(amox, [("A", "2028-01-31", 5)])
    rx = await prescribe(amox, qty=10)
    r = await sell(client, [line(amox, "strip", 1, rx_item_id=rx["item"])], [pay("0.90")], PHARMACIST)
    assert r.status_code == 409 and r.json()["code"] == "OUT_OF_STOCK"
    r = await rx_call("GET", f"/prescriptions/{rx['id']}")
    assert r.json()["items"][0]["held_base"] == 0


async def test_cancel_and_return_give_the_quantity_back_to_the_rx(client) -> None:
    amox = await stocked_rx_product()
    rx = await prescribe(amox, qty=20)
    inv = (await sell(client, [line(amox, "strip", 2, rx_item_id=rx["item"])], [pay("1.80")], PHARMACIST)).json()
    await relay_invoices()
    assert await remaining(rx) == 0
    r = await client.post(f"{PREFIX}/invoices/{inv['id']}/returns", headers={**PHARMACIST, "Idempotency-Key": "return-0001"},
                          json={"lines": [{"invoice_line_id": inv["lines"][0]["id"], "qty": 1}], "reason": "too many",
                                "refund_method": "cash"})  # fmt: skip
    assert r.status_code == 201, r.text
    await relay_invoices()
    assert await remaining(rx) == 10
    r = await sell(client, [line(amox, "strip", 1, rx_item_id=rx["item"])], [pay("0.90")], PHARMACIST)
    assert r.status_code == 201, r.text
    inv2 = r.json()
    await relay_invoices()
    assert await remaining(rx) == 0
    r = await client.post(f"{PREFIX}/invoices/{inv2['id']}/cancel", json={"reason": "wrong patient"},
                          headers={**PHARMACIST, "Idempotency-Key": "cancel-0001"})  # fmt: skip
    assert r.status_code == 200, r.text
    await relay_invoices()
    assert await remaining(rx) == 10


async def test_allergy_override_is_recorded_on_the_line_and_in_the_log(client) -> None:
    amox = await stocked_rx_product(classes=("penicillins",), ingredients=("Amoxicillin",))
    rx = await prescribe(amox, allergies=[{"kind": "class", "value": "penicillins"}])
    r = await sell(client, [line(amox, "strip", 1, rx_item_id=rx["item"])], [pay("0.90")], PHARMACIST)
    assert r.status_code == 409 and r.json()["code"] == "ALLERGY_WARNING"
    assert "អាឡែហ្ស៊ី" in r.json()["message"]
    assert await remaining(rx) == 20 and await inventory_stock(amox) == {"A": (200, 0, 0)}
    override = line(amox, "strip", 1, rx_item_id=rx["item"], allergy_override_reason="no reaction last 3 courses")
    r = await sell(client, [override], [pay("0.90")], PHARMACIST_NO_OVERRIDE)
    assert r.status_code == 403 and r.json()["code"] == "PHARMACIST_REQUIRED"
    r = await sell(client, [override], [pay("0.90")], PHARMACIST)
    assert r.status_code == 201, r.text
    ln = r.json()["lines"][0]
    assert ln["allergy_override_reason"] == "no reaction last 3 courses"
    assert ln["allergy_override_by"] == PHARMACIST["X-User-Id"] and ln["warnings"][0]["kind"] == "allergy"
    entry = next(a for a in await audits() if a["action"] == "dispensing.allergy_override")
    assert entry["after"]["reason"] == "no reaction last 3 courses"


async def test_duplicate_therapy_acknowledged_by_whom_and_when(client) -> None:
    amox = await stocked_rx_product(ingredients=("Amoxicillin",))
    augm = await stocked_rx_product("AUGM625", ingredients=("Amoxicillin", "Clavulanic acid"))
    first = await prescribe(amox)
    second = await prescribe(augm, patient=first["patient"])
    r = await sell(client, [line(augm, "strip", 1, rx_item_id=second["item"])], [pay("0.90")], PHARMACIST)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_THERAPY_WARNING"
    r = await sell(client, [line(augm, "strip", 1, rx_item_id=second["item"], acknowledge_warnings=True)],
                   [pay("0.90")], PHARMACIST_NO_OVERRIDE)  # fmt: skip
    assert r.status_code == 201, r.text
    ln = r.json()["lines"][0]
    assert ln["warnings_acknowledged_by"] == PHARMACIST_NO_OVERRIDE["X-User-Id"]
    assert ln["warnings_acknowledged_at"].startswith("2026-10-27")
    entry = next(a for a in await audits() if a["action"] == "dispensing.warning_acknowledged")
    assert entry["after"]["prescription"] == second["number"]


async def test_expired_rx_cannot_be_sold(client) -> None:
    amox = await stocked_rx_product()
    rx = await prescribe(amox)
    await prescription_event("prescription.noop", {})  # unknown events are ignored
    r = await rx_call("GET", f"/prescriptions/{rx['id']}")
    assert r.json()["valid_until"] == "2026-11-25"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(clock, "today", lambda: date(2026, 11, 26))
        r = await sell(client, [line(amox, "strip", 1, rx_item_id=rx["item"])], [pay("0.90")], PHARMACIST)
    assert r.status_code == 422 and r.json()["code"] == "RX_EXPIRED"
