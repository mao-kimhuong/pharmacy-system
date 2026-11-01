"""Dispensing against an Rx (the sale saga's step, over /internal/v1) and the
invoice events that settle it."""

from datetime import date
from uuid import uuid4

import pytest

from pharmacy_shared import clock

from .conftest import (
    INTERNAL,
    PHARMACIST,
    PHARMACIST_PP2,
    PP2,
    PREFIX,
    add_doctor,
    add_patient,
    add_product,
    add_rx,
    event,
    hold,
    invoice_event,
)  # fmt: skip


async def remaining(client, rx: dict) -> dict:  # noqa: ANN001
    r = await client.get(f"{PREFIX}/prescriptions/{rx['id']}/remaining", headers=PHARMACIST)
    return r.json()


async def sell(client, rx: dict, m: str, qty: int, version: int = 1, **extra) -> str:  # noqa: ANN001
    """Hold, then the invoice.created event, like a completed sale."""
    item = rx["items"][0]["id"]
    inv = str(uuid4())
    r = await hold(client, item, m, qty, invoice_id=inv, **extra)
    assert r.status_code == 200, r.text
    await event("invoice.created", invoice_event(inv, [(1, item, qty, 0)], version=version))
    return inv


async def basic(client, qty: int = 10, repeats: int = 0, **patient) -> tuple[dict, str]:  # noqa: ANN001
    p, d, m = await add_patient(client, **patient), await add_doctor(client), await add_product()
    return await add_rx(client, p, d, [{"medicine_id": m, "qty_base": qty, "repeats_allowed": repeats,
                                        "dosage": "1 capsule", "frequency": "3x a day"}]), m  # fmt: skip


async def test_internal_needs_the_service_token(client) -> None:
    body = {"invoice_id": str(uuid4()), "branch_id": str(PP2), "lines": []}
    assert (await client.post("/internal/v1/rx/check-and-hold", json=body)).status_code == 401
    r = await client.post("/internal/v1/rx/check-and-hold", json=body, headers=PHARMACIST)
    assert r.status_code == 401


async def test_partial_then_rest_then_fully_dispensed(client) -> None:
    rx, m = await basic(client)
    r = await hold(client, rx["items"][0]["id"], m, 4)
    line = r.json()["lines"][0]
    assert line["prescription_number"] == rx["number"] and line["dosage"] == "1 capsule"
    assert line["remaining_after"] == 6 and line["patient_name_en"] == "Sok Dara"
    inv = r.json()["invoice_id"]
    await event("invoice.created", invoice_event(inv, [(1, rx["items"][0]["id"], 4, 0)]))
    left = await remaining(client, rx)
    assert left["status"] == "partly_dispensed" and left["items"][0]["remaining_base"] == 6
    await sell(client, rx, m, 6)
    left = await remaining(client, rx)
    assert left["status"] == "fully_dispensed" and left["dispensable"] is False
    r = await hold(client, rx["items"][0]["id"], m, 1)
    assert r.status_code == 409 and r.json()["code"] == "PRESCRIPTION_STATE"


async def test_more_than_remaining_or_one_fill_is_refused(client) -> None:
    rx, m = await basic(client, qty=10, repeats=1)  # 20 in total, 10 per sale
    r = await hold(client, rx["items"][0]["id"], m, 11)
    assert r.status_code == 422 and r.json()["code"] == "RX_QUANTITY_EXCEEDED"
    assert r.json()["details"]["fill_base"] == 10
    await sell(client, rx, m, 10)
    await sell(client, rx, m, 7)
    r = await hold(client, rx["items"][0]["id"], m, 4)
    assert r.status_code == 422 and r.json()["details"]["remaining_base"] == 3
    left = (await remaining(client, rx))["items"][0]
    assert (left["remaining_base"], left["repeats_used"]) == (3, 1)


async def test_held_quantity_counts_until_released(client) -> None:
    rx, m = await basic(client)
    item = rx["items"][0]["id"]
    first = await hold(client, item, m, 8)
    r = await hold(client, item, m, 3)  # another till: only 2 left while the first sale runs
    assert r.status_code == 422 and r.json()["code"] == "RX_QUANTITY_EXCEEDED"
    rel = await client.post("/internal/v1/rx/release", json={"invoice_id": first.json()["invoice_id"]}, headers=INTERNAL)
    assert rel.json()["released"] == 1
    again = await client.post("/internal/v1/rx/release", json={"invoice_id": first.json()["invoice_id"]},
                              headers=INTERNAL)  # fmt: skip
    assert again.json()["released"] == 0
    assert (await hold(client, item, m, 10)).status_code == 200


async def test_same_invoice_asking_again_holds_once(client) -> None:
    rx, m = await basic(client)
    inv = str(uuid4())
    a = await hold(client, rx["items"][0]["id"], m, 6, invoice_id=inv)
    b = await hold(client, rx["items"][0]["id"], m, 6, invoice_id=inv)
    assert a.status_code == b.status_code == 200
    assert (await remaining(client, rx))["items"][0]["can_dispense_now"] == 4


async def test_expired_rx_is_a_hard_stop_even_before_the_job(client) -> None:
    p, d, m = await add_patient(client), await add_doctor(client), await add_product()
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}], valid_until="2026-10-27")
    assert (await hold(client, rx["items"][0]["id"], m, 1)).status_code == 200
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(clock, "today", lambda: date(2026, 10, 28))
        r = await hold(client, rx["items"][0]["id"], m, 1)
    assert r.status_code == 422 and r.json()["code"] == "RX_EXPIRED"
    assert "ផុតសុពលភាព" in r.json()["message"]


async def test_wrong_medicine_and_draft_refused(client) -> None:
    p, d, m = await add_patient(client), await add_doctor(client), await add_product()
    other = await add_product("IBU400", "Ibuprofen")
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}])
    r = await hold(client, rx["items"][0]["id"], other, 1)
    assert r.status_code == 422
    draft = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}], activate=False)
    r = await hold(client, draft["items"][0]["id"], m, 1)
    assert r.status_code == 409 and r.json()["code"] == "PRESCRIPTION_STATE"


async def test_allergy_blocks_until_override_with_reason(client) -> None:
    p, d = await add_patient(client, allergies=[{"kind": "class", "value": "Penicillins"}]), await add_doctor(client)
    m = await add_product("AMOX500", "Amoxicillin", classes=("penicillins", "beta-lactams"))
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}])
    r = await hold(client, rx["items"][0]["id"], m, 5)
    assert r.status_code == 409 and r.json()["code"] == "ALLERGY_WARNING"
    w = r.json()["details"]["lines"][0]["warnings"][0]
    assert w["value"] == "penicillins" and "allergic" in w["en"] and "អាឡែហ្ស៊ី" in w["km"]
    assert (await remaining(client, rx))["items"][0]["can_dispense_now"] == 10  # nothing held
    r = await hold(client, rx["items"][0]["id"], m, 5, allergy_override_reason="tolerated before, doctor called")
    assert r.status_code == 200 and r.json()["lines"][0]["warnings"][0]["kind"] == "allergy"


async def test_allergy_by_ingredient_ignores_case(client) -> None:
    p = await add_patient(client, allergies=[{"kind": "ingredient", "value": "CLAVULANIC ACID"}])
    d = await add_doctor(client)
    m = await add_product("AUGM625", "Amoxicillin + Clavulanic acid", ingredients=("Amoxicillin", "Clavulanic acid"))
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 14}])
    r = await hold(client, rx["items"][0]["id"], m, 14)
    assert r.json()["code"] == "ALLERGY_WARNING"


async def test_duplicate_therapy_needs_acknowledgement(client) -> None:
    p, d = await add_patient(client), await add_doctor(client)
    amox = await add_product("AMOX500", "Amoxicillin")
    augm = await add_product("AUGM625", "Amoxicillin + Clavulanic acid", ingredients=("Amoxicillin", "Clavulanic acid"))
    first = await add_rx(client, p, d, [{"medicine_id": amox, "qty_base": 10}])
    second = await add_rx(client, p, d, [{"medicine_id": augm, "qty_base": 14}])
    r = await hold(client, second["items"][0]["id"], augm, 14)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_THERAPY_WARNING"
    assert r.json()["details"]["lines"][0]["warnings"][0]["prescription"] == first["number"]
    r = await hold(client, second["items"][0]["id"], augm, 14, acknowledge_warnings=True)
    assert r.status_code == 200


async def test_invoice_events_are_idempotent_and_follow_cancel_and_return(client) -> None:
    rx, m = await basic(client)
    item = rx["items"][0]["id"]
    inv = str(uuid4())
    await hold(client, item, m, 6, invoice_id=inv)
    created = invoice_event(inv, [(1, item, 6, 0)], version=1)
    msg = uuid4()
    await event("invoice.created", created, msg)
    await event("invoice.created", created, msg)  # same message again: skipped
    await event("invoice.created", created)  # same version, new message id: no change
    assert (await remaining(client, rx))["items"][0]["remaining_base"] == 4
    await event("invoice.returned", invoice_event(inv, [(1, item, 6, 2)], version=3))
    assert (await remaining(client, rx))["items"][0]["remaining_base"] == 6
    await event("invoice.returned", invoice_event(inv, [(1, item, 6, 1)], version=2))  # older: ignored
    assert (await remaining(client, rx))["items"][0]["remaining_base"] == 6
    await event("invoice.cancelled", invoice_event(inv, [(1, item, 6, 2)], version=4, status="cancelled"))
    left = await remaining(client, rx)
    assert left["items"][0]["remaining_base"] == 10 and left["status"] == "active"


async def test_a_return_reopens_a_fully_dispensed_rx(client) -> None:
    rx, m = await basic(client)
    item = rx["items"][0]["id"]
    inv = await sell(client, rx, m, 10)
    assert (await remaining(client, rx))["status"] == "fully_dispensed"
    await event("invoice.returned", invoice_event(inv, [(1, item, 10, 3)], version=2))
    left = await remaining(client, rx)
    assert left["status"] == "partly_dispensed" and left["items"][0]["can_dispense_now"] == 3


async def test_dispensing_at_another_branch_links_the_patient(client) -> None:
    rx, m = await basic(client)
    r = await hold(client, rx["items"][0]["id"], m, 1, branch=PP2)
    assert r.status_code == 200
    p = rx["patient"]["id"]
    assert (await client.get(f"{PREFIX}/patients/{p}", headers=PHARMACIST_PP2)).status_code == 200


async def test_rx_check_is_the_same_check_and_holds_nothing(client) -> None:
    rx, m = await basic(client, qty=10)
    item = rx["items"][0]["id"]
    body = {"branch_id": str(rx["branch_id"]), "lines": [{"line_no": 1, "rx_item_id": item, "medicine_id": m,
                                                          "qty_base": 10}]}  # fmt: skip
    r = await client.post("/internal/v1/rx/check", json=body, headers=INTERNAL)
    assert r.status_code == 200 and r.json()["invoice_id"] is None and r.json()["lines"][0]["remaining_after"] == 10
    assert (await remaining(client, rx))["items"][0]["remaining_base"] == 10  # nothing held
    too_many = {**body, "lines": [{**body["lines"][0], "qty_base": 11}]}
    r = await client.post("/internal/v1/rx/check", json=too_many, headers=INTERNAL)
    assert r.status_code == 422 and r.json()["code"] == "RX_QUANTITY_EXCEEDED"  # same code as check-and-hold
    assert (await hold(client, item, m, 10)).status_code == 200  # the full fill can still be held
