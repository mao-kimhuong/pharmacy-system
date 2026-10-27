from uuid import uuid4

from .conftest import CASHIER, OWNER, PP1, PREFIX, SUPPLIER, add_product, audits, idem, scalar, stock_of


def body(product: dict, **line) -> dict:
    return {"branch_id": str(PP1), "reason": "Donation from clinic", "supplier_id": str(SUPPLIER), "lines": [{
        "medicine_id": product["id"], "pack_unit_id": product["box"], "lot_no": "Q1",
        "expiry_date": "2028-03-31", "qty": 2, "unit_cost": "4.00", **line}]}  # fmt: skip


async def test_quick_stock_in_adds_a_batch_and_is_logged(client) -> None:
    para = await add_product()
    r = await client.post(f"{PREFIX}/stock-in", json=body(para), headers={**OWNER, **idem()})
    assert r.status_code == 201, r.text
    line = r.json()["lines"][0]
    assert (line["qty_base"], line["qty_after"], line["cost_per_base"], line["short_expiry"]) == (
        200,
        200,
        "0.0400",
        False,
    )
    assert (await stock_of(client))[0]["qty_on_hand"] == 200
    audit = (await audits())[-1]
    assert audit["action"] == "stock_in.created" and audit["after"]["reason"] == "Donation from clinic"


async def test_stock_in_follows_the_receiving_expiry_rules(client) -> None:
    para = await add_product()
    r = await client.post(
        f"{PREFIX}/stock-in", json=body(para, expiry_date="2026-10-26"), headers={**OWNER, **idem()}
    )
    assert r.status_code == 409 and r.json()["code"] == "BATCH_EXPIRED"
    assert await scalar("SELECT count(*) FROM movements") == 0
    r = await client.post(
        f"{PREFIX}/stock-in", json=body(para, expiry_date="2027-01-31"), headers={**OWNER, **idem()}
    )
    assert r.json()["lines"][0]["short_expiry"] is True
    assert (await audits())[-1]["after"]["short_expiry"] == ["lot Q1 exp 2027-01-31"]


async def test_stock_in_needs_a_reason_known_supplier_and_key(client) -> None:
    para = await add_product()
    r = await client.post(
        f"{PREFIX}/stock-in", json={**body(para), "reason": ""}, headers={**OWNER, **idem()}
    )
    assert r.status_code == 422
    r = await client.post(f"{PREFIX}/stock-in", json={**body(para), "supplier_id": str(uuid4())},
                          headers={**OWNER, **idem()})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "UNKNOWN_SUPPLIER"
    r = await client.post(f"{PREFIX}/stock-in", json=body(para), headers=OWNER)
    assert r.status_code == 400 and r.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_same_key_stocks_in_once(client) -> None:
    para = await add_product()
    key = idem()
    for _ in range(2):
        r = await client.post(f"{PREFIX}/stock-in", json=body(para), headers={**OWNER, **key})
        assert r.status_code == 201
    assert (await stock_of(client))[0]["qty_on_hand"] == 200


async def test_cashier_can_stock_in_without_seeing_cost(client) -> None:
    para = await add_product()
    r = await client.post(f"{PREFIX}/stock-in", json=body(para), headers={**CASHIER, **idem()})
    assert r.status_code == 201 and "cost" not in r.text
