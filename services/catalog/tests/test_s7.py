"""Hampers and promotions in the catalog (S7)."""

from .conftest import CASHIER, OWNER, PREFIX, create_medicine, outbox, user

HAMPERS = user("branch_manager", "products.view,catalog.hampers")
PROMOS = user("branch_manager", "products.view,catalog.promotions")


async def hamper(client, components: list[tuple[dict, int]], sku: str = "KIT-FLU", headers=HAMPERS):  # noqa: ANN001, ANN201
    return await client.post(f"{PREFIX}/hampers", headers=headers, json={
        "sku": sku, "name": "Flu care kit", "price": "5.00", "barcode": f"{sku}-BC",
        "components": [{"medicine_id": m["id"], "qty_base": q} for m, q in components]})  # fmt: skip


async def test_hamper_is_a_kit_with_one_pack_and_components_in_events(client) -> None:
    para, ors = await create_medicine(client, "PARA500"), await create_medicine(client, "ORS")
    r = await hamper(client, [(para, 10), (ors, 2)])
    assert r.status_code == 201, r.text
    h = r.json()
    assert h["kind"] == "hamper" and h["is_rx_only"] is False and len(h["pack_units"]) == 1
    assert [(c["component_id"], c["qty_base"]) for c in h["components"]] == [(para["id"], 10), (ors["id"], 2)]
    payload = [p for t, p in await outbox() if t == "medicine.created"][-1]
    assert payload["kind"] == "hamper" and payload["components"][0] == {"medicine_id": para["id"], "qty_base": 10}
    r = await client.post(f"{PREFIX}/medicines/{h['id']}/pack-units", headers=OWNER,
                          json={"name": "box", "qty_in_base": 5, "sell_price": "20.00"})  # fmt: skip
    assert r.status_code == 422
    assert (await hamper(client, [(para, 1), (ors, 1)], headers=CASHIER)).status_code == 403


async def test_rx_component_makes_the_hamper_rx_only_and_follows_changes(client) -> None:
    para = await create_medicine(client, "PARA500")
    amox = await create_medicine(client, "AMOX500", is_rx_only=True)
    h = (await hamper(client, [(para, 10), (amox, 21)])).json()
    assert h["is_rx_only"] is True
    ors = await create_medicine(client, "ORS")
    h2 = (await hamper(client, [(para, 10), (ors, 1)], "KIT-2")).json()
    assert h2["is_rx_only"] is False
    # PARA500 becomes Rx-only: KIT-2 follows (a new version is sent)
    r = await client.patch(f"{PREFIX}/medicines/{para['id']}", json={"is_rx_only": True}, headers=OWNER)
    assert r.status_code == 200
    updates = [p for t, p in await outbox() if t == "medicine.updated" and p["sku"] == "KIT-2"]
    assert updates and updates[-1]["is_rx_only"] is True


async def test_hamper_rules(client) -> None:
    para = await create_medicine(client, "PARA500")
    diaz = await create_medicine(client, "DIAZ5", controlled_schedule="IV")
    assert (await hamper(client, [(para, 1), (diaz, 1)])).status_code == 422  # no controlled
    assert (await hamper(client, [(para, 1)])).status_code == 422  # at least two units
    h = (await hamper(client, [(para, 2)])).json()
    nested = await client.post(f"{PREFIX}/hampers", headers=HAMPERS, json={
        "sku": "KIT-X", "name": "x", "price": "1.00", "components": [{"medicine_id": h["id"], "qty_base": 2}]})  # fmt: skip
    assert nested.status_code == 422  # a hamper is not a component
    r = await client.post(f"{PREFIX}/medicines/{para['id']}/deactivate", json={"reason": "x"}, headers=OWNER)
    assert r.status_code == 409  # still in an active hamper


async def promo(client, headers=PROMOS, **body):  # noqa: ANN001, ANN201
    return await client.post(f"{PREFIX}/promotions", headers=headers, json={"name": "Promo", **body})


async def test_promotion_types_are_checked_and_sent_as_events(client) -> None:
    para = await create_medicine(client, "PARA500")
    ok = await promo(client, code="b2g1", type="buy_x_get_y", buy_qty=2, get_qty=1, medicine_ids=[para["id"]])
    assert ok.status_code == 201, ok.text
    assert ok.json()["code"] == "B2G1" and ok.json()["include_rx"] is False
    event = [p for t, p in await outbox() if t == "promotion.created"][-1]
    assert event["type"] == "buy_x_get_y" and event["medicine_ids"] == [para["id"]] and event["version"] == 1
    bad = [
        dict(code="P1", type="percent_off", value="150", medicine_ids=[para["id"]]),
        dict(code="P2", type="percent_off", value="10"),  # no target
        dict(code="P3", type="group_price", value="0.05", medicine_ids=[para["id"]]),  # no groups
        dict(code="P4", type="bundle_price", value="1.00", bundle_items=[{"medicine_id": para["id"], "qty_base": 1}]),
        dict(code="P5", type="qty_tiers", medicine_ids=[para["id"]]),
        dict(code="P6", type="percent_off", value="5", medicine_ids=[para["id"]], starts_at="2026-11-02T00:00:00+07:00",
             ends_at="2026-11-01T00:00:00+07:00"),
    ]  # fmt: skip
    for body in bad:
        assert (await promo(client, **body)).status_code == 422, body
    assert (await promo(client, code="b2g1", type="percent_off", value="5", medicine_ids=[para["id"]])).status_code == 409
    assert (await promo(client, headers=CASHIER, code="X", type="percent_off", value="5",
                        medicine_ids=[para["id"]])).status_code == 403  # fmt: skip


async def test_promotion_update_and_deactivate_bump_the_version(client) -> None:
    para = await create_medicine(client, "PARA500")
    p = (await promo(client, code="TIER", type="qty_tiers", medicine_ids=[para["id"]],
                     tiers=[{"min_qty": 100, "percent": "10"}, {"min_qty": 50, "percent": "5"}])).json()  # fmt: skip
    assert [t["min_qty"] for t in p["tiers"]] == [50, 100]
    r = await client.patch(f"{PREFIX}/promotions/{p['id']}", headers=PROMOS, json={"stackable": True})
    assert r.json()["version"] == 2 and r.json()["stackable"] is True
    r = await client.post(f"{PREFIX}/promotions/{p['id']}/deactivate", headers=PROMOS)
    assert r.json()["is_active"] is False and r.json()["version"] == 3
    assert [t for t, _ in await outbox() if t.startswith("promotion.")] == [
        "promotion.created", "promotion.updated", "promotion.deactivated"]  # fmt: skip
