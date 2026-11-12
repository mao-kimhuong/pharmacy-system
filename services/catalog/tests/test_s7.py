"""Hampers and promotions in the catalog (S7)."""

from datetime import UTC, datetime
from uuid import uuid4

from .conftest import CASHIER, OWNER, PREFIX, count, create_medicine, outbox, user

HAMPERS = user("branch_manager", "products.view,catalog.hampers")
MY_BRANCH = uuid4()
PROMOS = user("branch_manager", "products.view,catalog.promotions", (MY_BRANCH,))


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
    return await client.post(f"{PREFIX}/promotions", headers=headers,
                             json={"name": "Promo", "branch_ids": [str(MY_BRANCH)], **body})  # fmt: skip


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


async def test_promotion_preview_sends_the_draft_to_sales_and_saves_nothing(client) -> None:
    from catalog_service.api.s7 import get_sales
    from catalog_service.main import app

    para = await create_medicine(client)
    sent = {}

    class Sales:
        async def post(self, path: str, body: dict, **kw) -> dict:  # noqa: ANN003
            sent.update(path=path, **body)
            return {"lines": [], "conflicts": [], "can_post": False}

    app.dependency_overrides[get_sales] = lambda: Sales()
    try:
        before = await count("promotions"), await count("outbox")
        branch = uuid4()
        manager = user("branch_manager", "products.view,catalog.promotions", (branch,))
        body = {"promotion": {"code": "new20", "name": "New 20", "type": "percent_off", "value": "20",
                              "medicine_ids": [para["id"]], "branch_ids": [str(branch)]},
                "cart": {"branch_id": str(branch), "lines": [{"medicine_id": para["id"],
                                                                "pack_unit_id": para["pack_units"][0]["id"], "qty": 1}]}}  # fmt: skip
        r = await client.post(f"{PREFIX}/promotions/preview", json=body, headers=manager)
        assert r.status_code == 200, r.text
        assert sent["path"] == "/carts/preview" and sent["draft_promotion"]["code"] == "NEW20"
        assert sent["draft_promotion"]["medicine_ids"] == [para["id"]]
        assert (await count("promotions"), await count("outbox")) == before  # nothing saved
        bad = {**body, "promotion": {**body["promotion"], "value": "200"}}
        assert (await client.post(f"{PREFIX}/promotions/preview", json=bad, headers=manager)).status_code == 422
        other = {**body, "promotion": {**body["promotion"], "branch_ids": [str(MY_BRANCH)]}}
        assert (await client.post(f"{PREFIX}/promotions/preview", json=other, headers=PROMOS)).status_code == 403
    finally:
        app.dependency_overrides.clear()


async def test_promotion_errors_name_the_field_and_a_reason_the_web_app_translates(client) -> None:
    para = await create_medicine(client, "PARA500")
    target = {"medicine_ids": [para["id"]]}
    cases = [
        (dict(type="percent_off", value="150", **target), "value", "percent_range"),
        (dict(type="amount_off", **target), "value", "amount_required"),
        (dict(type="buy_x_get_y", **target), "buy_qty", "buy_get_required"),
        (dict(type="qty_tiers", **target), "tiers", "tiers_invalid"),
        (dict(type="bundle_price", value="1.00", bundle_items=[{"medicine_id": para["id"], "qty_base": 1}]),
         "bundle_items", "bundle_min"),
        (dict(type="percent_off", value="10"), "medicine_ids", "targets_required"),
        (dict(type="group_price", value="0.05", **target), "customer_group_ids", "groups_required"),
        (dict(type="percent_off", value="5", starts_at="2026-11-02T00:00:00+07:00",
              ends_at="2026-11-01T00:00:00+07:00", **target), "ends_at", "end_before_start"),
        (dict(type="percent_off", value="5", medicine_ids=[str(uuid4())]), "medicine_ids", "unknown_id"),
    ]  # fmt: skip
    for i, (body, field, reason) in enumerate(cases):
        r = await promo(client, code=f"E{i}", **body)
        assert r.status_code == 422 and r.json()["details"] == {"field": field, "reason": reason}, r.text


async def test_all_six_types_save_with_their_fields(client) -> None:
    para, ors = await create_medicine(client, "PARA500"), await create_medicine(client, "ORS")
    group = str(uuid4())
    target = {"medicine_ids": [para["id"]]}
    bodies = [
        dict(type="percent_off", value="10", **target),
        dict(type="amount_off", value="0.50", **target),
        dict(type="buy_x_get_y", buy_qty=2, get_qty=1, **target),
        dict(type="bundle_price", value="1.50", bundle_items=[{"medicine_id": para["id"], "qty_base": 1},
                                                              {"medicine_id": ors["id"], "qty_base": 1}]),
        dict(type="qty_tiers", tiers=[{"min_qty": 10, "percent": "5"}], **target),
        dict(type="group_price", value="0.40", customer_group_ids=[group], **target),
    ]  # fmt: skip
    for i, body in enumerate(bodies):
        r = await promo(client, code=f"T{i}", days_of_week=[0, 4], max_uses_total=100, max_uses_per_customer=2,
                        stackable=True, include_rx=True, starts_at="2026-12-01T09:30:00+07:00", **body)  # fmt: skip
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["days_of_week"] == [0, 4] and out["max_uses_total"] == 100 and out["stackable"] is True
        assert out["include_rx"] is True
        assert datetime.fromisoformat(out["starts_at"]) == datetime(2026, 12, 1, 2, 30, tzinfo=UTC)


async def test_a_limit_or_date_can_be_cleared_on_edit(client) -> None:
    para = await create_medicine(client, "PARA500")
    p = (await promo(client, code="CLR", type="percent_off", value="5", medicine_ids=[para["id"]], max_uses_total=5,
                     starts_at="2026-12-01T09:30:00+07:00")).json()  # fmt: skip
    r = await client.patch(f"{PREFIX}/promotions/{p['id']}", headers=PROMOS, json={"max_uses_total": None, "starts_at": None})
    assert r.status_code == 200 and r.json()["max_uses_total"] is None and r.json()["starts_at"] is None


async def test_managers_stay_inside_their_own_branches(client) -> None:
    para = await create_medicine(client, "PARA500")
    base = dict(type="percent_off", value="5", medicine_ids=[para["id"]])
    everywhere = await promo(client, code="M1", branch_ids=[], **base)
    assert everywhere.status_code == 422 and everywhere.json()["details"]["reason"] == "all_branches_owner_only"
    other = await promo(client, code="M2", branch_ids=[str(uuid4())], **base)
    assert other.status_code == 422 and other.json()["details"] == {"field": "branch_ids", "reason": "other_branch"}
    mine = await promo(client, code="M3", **base)
    assert mine.status_code == 201
    widen = await client.patch(f"{PREFIX}/promotions/{mine.json()['id']}", headers=PROMOS, json={"branch_ids": []})
    assert widen.status_code == 422
    # the owner may use every branch; a manager then cannot change or switch that promotion
    owners = await promo(client, headers=OWNER, code="O1", branch_ids=[], **base)
    assert owners.status_code == 201, owners.text
    url = f"{PREFIX}/promotions/{owners.json()['id']}"
    edit = await client.patch(url, headers=PROMOS, json={"name": "Mine now"})
    assert edit.status_code == 403 and edit.json()["code"] == "BRANCH_FORBIDDEN"
    assert (await client.post(f"{url}/deactivate", headers=PROMOS)).status_code == 403
    assert (await client.post(f"{url}/deactivate", headers=OWNER)).status_code == 200
