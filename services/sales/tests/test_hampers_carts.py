"""Hampers at the till (components FEFO, whole-hamper returns, Rx-only), suspend
and resume on another terminal (price and stock notices, end-of-day expiry),
templates."""

from datetime import date
from uuid import uuid4

from sqlalchemy import select

from sales_service.db import db
from sales_service.models import SuspendedCart
from sales_service.services.carts import expire

from .conftest import (
    CASHIER,
    PP1,
    PREFIX,
    add_product,
    everywhere,
    inventory_stock,
    line,
    pay,
    receive,
    sell,
    user,
)  # fmt: skip

SUSPENDER = user("cashier", "pos.sell,sales.view,sales.suspend,sales.templates")
OTHER_TILL = user("cashier", "pos.sell,sales.view,sales.suspend,sales.templates")
MANAGER = user("branch_manager", "pos.sell,sales.view,sales.return,sales.exchange_rate")


async def hamper(components: list[tuple[dict, int]], price: str = "2.00", rx: bool = False) -> dict:
    hamper_id, pack = str(uuid4()), str(uuid4())
    await everywhere("medicine.created", {
        "medicine_id": hamper_id, "version": 1, "sku": "KIT-FLU", "brand_name": "Flu kit", "generic_name": "Hamper",
        "base_unit": "hamper", "is_rx_only": rx, "controlled_schedule": None, "is_active": True, "kind": "hamper",
        "components": [{"medicine_id": p["id"], "qty_base": q} for p, q in components],
        "pack_units": [{"id": pack, "name": "hamper", "qty_in_base": 1, "barcode": None, "sell_price": price,
                        "is_base": True, "is_active": True}]})  # fmt: skip
    return {"id": hamper_id, "hamper": pack}


async def test_a_hamper_takes_its_components_and_comes_back_whole(client) -> None:
    para, ors = await add_product("PARA500"), await add_product("ORS")
    await receive(para, [("P1", "2027-06-30", 15), ("P2", "2028-06-30", 100)])
    await receive(ors, [("O1", "2028-01-31", 10)])
    kit = await hamper([(para, 10), (ors, 2)])
    r = await sell(client, [line(kit, "hamper", 2)], [pay("4.00")])
    assert r.status_code == 201, r.text
    ln = r.json()["lines"][0]
    assert ln["is_hamper"] and sorted((b["lot_no"], b["qty_base"]) for b in ln["batches"]) == [
        ("O1", 4), ("P1", 15), ("P2", 5)]  # fmt: skip
    assert await inventory_stock(para) == {"P1": (0, 0, 0), "P2": (95, 0, 0)}
    assert await inventory_stock(ors) == {"O1": (6, 0, 0)}
    r = await client.post(f"{PREFIX}/invoices/{r.json()['id']}/returns", headers={**MANAGER, "Idempotency-Key": "ret-kit-01"},
                          json={"lines": [{"invoice_line_id": ln["id"], "qty": 1}], "refund_method": "cash",
                                "reason": "not needed"})  # fmt: skip
    assert r.status_code == 201, r.text
    assert r.json()["refund_usd"] == "2.00"
    para_back = await inventory_stock(para)
    assert sum(q for q, _, _ in para_back.values()) == 105 and await inventory_stock(ors) == {"O1": (8, 0, 0)}


async def test_a_hamper_with_an_rx_component_is_rx_only(client) -> None:
    para, amox = await add_product("PARA500"), await add_product("AMOX500", rx=True)
    await receive(para, [("P1", "2028-06-30", 100)])
    await receive(amox, [("A1", "2028-06-30", 100)])
    kit = await hamper([(para, 10), (amox, 21)], rx=True)  # the catalog sets is_rx_only from the components
    r = await sell(client, [line(kit, "hamper", 1)], [pay("2.00")])
    assert r.status_code == 422 and r.json()["code"] == "RX_REQUIRED"


async def test_suspend_then_resume_on_another_till_with_notices(client) -> None:
    para, ors = await add_product("PARA500"), await add_product("ORS")
    await receive(para, [("P1", "2028-06-30", 100)])
    await receive(ors, [("O1", "2028-06-30", 3)])
    body = {"branch_id": str(PP1), "note": "customer went to the ATM",
            "lines": [line(para, "strip", 2), line(ors, "tablet", 5)]}  # fmt: skip
    r = await client.post(f"{PREFIX}/carts/suspend", json=body, headers=SUSPENDER)
    assert r.status_code == 201, r.text
    cart = r.json()
    assert cart["number"] == "PP1-SP-2026-000001" and cart["status"] == "suspended"
    assert await inventory_stock(para) == {"P1": (100, 0, 0)}  # nothing reserved
    listed = (await client.get(f"{PREFIX}/carts", params={"branch_id": str(PP1)}, headers=OTHER_TILL)).json()
    assert [c["id"] for c in listed] == [cart["id"]]
    # the price of a strip goes up while the cart waits
    await everywhere("medicine.updated", {
        "medicine_id": para["id"], "version": 2, "sku": "PARA500", "brand_name": "Para500", "generic_name": "Generic",
        "base_unit": "tablet", "is_rx_only": False, "controlled_schedule": None, "is_active": True,
        "pack_units": [{"id": para["tablet"], "name": "tablet", "qty_in_base": 1, "barcode": None, "sell_price": "0.10",
                        "is_base": True, "is_active": True},
                       {"id": para["strip"], "name": "strip", "qty_in_base": 10, "barcode": None, "sell_price": "1.00",
                        "is_base": False, "is_active": True},
                       {"id": para["box"], "name": "box", "qty_in_base": 100, "barcode": None, "sell_price": "8.00",
                        "is_base": False, "is_active": True}]})  # fmt: skip
    r = await client.post(f"{PREFIX}/carts/{cart['id']}/resume", headers=OTHER_TILL)
    assert r.status_code == 200, r.text
    changes = {(c["sku"], c["change"]): c for c in r.json()["changes"]}
    assert (changes[("PARA500", "price")]["was"], changes[("PARA500", "price")]["now"]) == ("0.90", "1.00")
    assert changes[("ORS", "stock")]["now"] == 3  # only 3 left
    assert r.json()["lines"][0]["unit_price"] == "1.00"
    again = await client.post(f"{PREFIX}/carts/{cart['id']}/resume", headers=OTHER_TILL)
    assert again.status_code == 409 and again.json()["code"] == "CART_STATE"
    other_branch = user("cashier", "sales.suspend", (uuid4(),))
    assert (await client.post(f"{PREFIX}/carts/{cart['id']}/resume", headers=other_branch)).status_code == 404


async def test_unresumed_carts_expire_at_day_end_and_are_kept(client) -> None:
    para = await add_product("PARA500")
    body = {"branch_id": str(PP1), "lines": [line(para, "strip", 1)]}
    await client.post(f"{PREFIX}/carts/suspend", json=body, headers=SUSPENDER)
    async with db.sessionmaker() as s:
        assert await expire(s, date(2026, 10, 27)) == 0  # same day: still parked
    async with db.sessionmaker() as s:
        assert await expire(s, date(2026, 10, 28)) == 1
    async with db.sessionmaker() as s:
        assert (await s.execute(select(SuspendedCart.status))).scalars().all() == ["expired"]
    assert (await client.post(f"{PREFIX}/carts/suspend", json=body, headers=CASHIER)).status_code == 403


async def test_templates_load_priced_now(client) -> None:
    para, ors = await add_product("PARA500"), await add_product("ORS")
    r = await client.post(f"{PREFIX}/sale-templates", headers=SUSPENDER, json={
        "name": "Clinic weekly order", "branch_id": str(PP1),
        "lines": [{"medicine_id": para["id"], "pack_unit_id": para["box"], "qty": 2},
                  {"medicine_id": ors["id"], "pack_unit_id": ors["strip"], "qty": 5}]})  # fmt: skip
    assert r.status_code == 201, r.text
    t = r.json()
    loaded = (await client.post(f"{PREFIX}/sale-templates/{t['id']}/load", headers=OTHER_TILL)).json()
    assert [(x["sku"], x["qty"], x["line_total"]) for x in loaded["lines"]] == [("PARA500", 2, "16.00"),
                                                                                 ("ORS", 5, "4.50")]  # fmt: skip
    r = await client.patch(f"{PREFIX}/sale-templates/{t['id']}", headers=SUSPENDER, json={"is_active": False})
    assert r.json()["is_active"] is False
    assert (await client.post(f"{PREFIX}/sale-templates/{t['id']}/load", headers=OTHER_TILL)).status_code == 404
    assert (await client.get(f"{PREFIX}/sale-templates", params={"branch_id": str(PP1)}, headers=CASHIER)).status_code == 403
