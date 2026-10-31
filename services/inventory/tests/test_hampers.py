"""Hampers in inventory: no stock or batches of their own. Selling one reserves
its components FEFO (all or nothing); availability = the lowest component; a
hamper never appears in stock-in, transfers, stock takes or re-order settings."""

from uuid import uuid4

from .conftest import INTERNAL, OWNER, PP1, PP2, PREFIX, add_product, event, goods_received, idem, user


async def hamper(components: list[tuple[dict, int]], sku: str = "KIT-FLU") -> dict:
    hamper_id, pack = str(uuid4()), str(uuid4())
    await event("medicine.created", {
        "medicine_id": hamper_id, "version": 1, "sku": sku, "brand_name": "Flu kit", "generic_name": "Hamper",
        "base_unit": "hamper", "is_rx_only": False, "controlled_schedule": None, "is_active": True, "kind": "hamper",
        "components": [{"medicine_id": p["id"], "qty_base": q} for p, q in components],
        "pack_units": [{"id": pack, "name": "hamper", "qty_in_base": 1, "barcode": None, "sell_price": "5.00",
                        "is_base": True, "is_active": True}]})  # fmt: skip
    return {"id": hamper_id, "hamper": pack}


async def stocked() -> tuple[dict, dict, dict]:
    para, ors = await add_product("PARA500"), await add_product("ORS")
    await event("goods.received", goods_received(para, [("P-EARLY", "2027-03-31", 25, "0.05"),
                                                        ("P-LATE", "2028-03-31", 100, "0.05")]))  # fmt: skip
    await event("goods.received", goods_received(ors, [("O1", "2028-01-31", 6, "0.20")]))
    return para, ors, await hamper([(para, 10), (ors, 2)])


async def test_availability_is_the_lowest_component(client) -> None:
    para, ors, kit = await stocked()  # PARA 125 / 10 = 12; ORS 6 / 2 = 3
    r = await client.get(f"{PREFIX}/hampers/{kit['id']}/availability", params={"branch_id": str(PP1)}, headers=OWNER)
    assert r.json()["available"] == 3
    r = await client.post("/internal/v1/stock/available", headers=INTERNAL,
                          json={"branch_id": str(PP1), "items": [{"medicine_id": kit["id"], "qty_base": 4}]})  # fmt: skip
    assert r.json()["items"][0] == {"medicine_id": kit["id"], "available": 3, "requested": 4, "enough": False}


async def test_selling_reserves_and_takes_the_components_fefo(client) -> None:
    para, ors, kit = await stocked()
    body = {"ref_type": "invoice", "ref_id": str(uuid4()), "branch_id": str(PP1),
            "lines": [{"line_no": 1, "medicine_id": kit["id"], "qty_base": 3}]}  # fmt: skip
    r = await client.post("/internal/v1/reservations", json=body, headers=INTERNAL)
    assert r.status_code == 200, r.text
    got = sorted((x["lot_no"], x["qty_base"], x["hamper_id"]) for x in r.json()["lines"])
    assert got == [("O1", 6, kit["id"]), ("P-EARLY", 25, kit["id"]), ("P-LATE", 5, kit["id"])]  # 30 PARA, FEFO
    # all or nothing: one more hamper is short of ORS, nothing else is reserved
    more = {**body, "ref_id": str(uuid4()), "lines": [{"line_no": 1, "medicine_id": kit["id"], "qty_base": 1}]}
    r = await client.post("/internal/v1/reservations", json=more, headers=INTERNAL)
    assert r.status_code == 409 and r.json()["code"] == "OUT_OF_STOCK"
    reservation = (await client.post("/internal/v1/reservations", json=body, headers=INTERNAL)).json()
    r = await client.post(f"/internal/v1/reservations/{reservation['id']}/confirm", headers=INTERNAL)
    assert r.status_code == 200
    stock = {i["sku"]: i["qty_on_hand"] for i in (await client.get(
        f"{PREFIX}/stock", params={"branch_id": str(PP1)}, headers=OWNER)).json()["items"]}  # fmt: skip
    assert stock == {"PARA500": 95}  # ORS sold out (not listed); the hamper itself has no stock row


async def test_a_hamper_has_no_stock_of_its_own(client) -> None:
    para, ors, kit = await stocked()
    r = await client.post(f"{PREFIX}/stock-in", headers={**OWNER, **idem()}, json={
        "branch_id": str(PP1), "reason": "x", "lines": [{"medicine_id": kit["id"], "pack_unit_id": kit["hamper"],
        "lot_no": "K1", "expiry_date": "2028-01-31", "qty": 1, "unit_cost": "1.00"}]})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "HAMPER_NOT_STOCKED"
    manager = user("branch_manager", "transfers.dispatch,inventory.view", (PP1,))
    r = await client.post(f"{PREFIX}/transfers", headers=manager, json={
        "from_branch_id": str(PP1), "to_branch_id": str(PP2), "lines": [{"medicine_id": kit["id"], "qty_base": 1}]})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "HAMPER_NOT_STOCKED"
    snap = await client.post("/internal/v1/stock/snapshot", json={"branch_id": str(PP1)}, headers=INTERNAL)
    assert {x["sku"] for x in snap.json()["lines"]} == {"PARA500", "ORS"}  # stock takes: components only
    r = await client.put(f"{PREFIX}/reorder-settings", headers=user("branch_manager", "inventory.reorder_settings"),
                         json={"branch_id": str(PP1), "medicine_id": kit["id"], "min_qty": 1})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "HAMPER_NOT_STOCKED"


async def test_order_reservation_split_to_an_invoice(client) -> None:
    para, ors, kit = await stocked()
    order = {"ref_type": "sale_order", "ref_id": str(uuid4()), "branch_id": str(PP1),
             "lines": [{"line_no": 1, "medicine_id": para["id"], "qty_base": 40},
                       {"line_no": 2, "medicine_id": kit["id"], "qty_base": 2}]}  # fmt: skip
    r = (await client.post("/internal/v1/reservations", json=order, headers=INTERNAL)).json()
    inv = str(uuid4())
    body = {"ref_id": inv, "lines": [{"from_line_no": 1, "to_line_no": 1, "qty_base": 30},
                                     {"from_line_no": 2, "to_line_no": 2, "qty_base": 1}]}  # fmt: skip
    split = await client.post(f"/internal/v1/reservations/{r['id']}/split", json=body, headers=INTERNAL)
    assert split.status_code == 200, split.text
    moved = sorted((x["line_no"], x["medicine_id"] == para["id"], x["qty_base"]) for x in split.json()["lines"])
    assert sum(q for n, is_para, q in moved if n == 1) == 30
    assert sorted(q for n, _, q in moved if n == 2) == [2, 10]  # one hamper: 10 PARA + 2 ORS
    again = await client.post(f"/internal/v1/reservations/{r['id']}/split", json=body, headers=INTERNAL)
    assert again.json()["id"] == split.json()["id"]  # once per invoice
    too_much = {"ref_id": str(uuid4()), "lines": [{"from_line_no": 1, "to_line_no": 1, "qty_base": 11}]}
    r2 = await client.post(f"/internal/v1/reservations/{r['id']}/split", json=too_much, headers=INTERNAL)
    assert r2.status_code == 409  # only 10 of line 1 left on the order
