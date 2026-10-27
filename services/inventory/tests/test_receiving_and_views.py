import pytest

from inventory_service.db import db
from inventory_service.models import Batch
from inventory_service.services.movements import apply_movement

from .conftest import (
    CASHIER,
    OWNER,
    PP1,
    PP2,
    PREFIX,
    add_product,
    event,
    goods_received,
    outbox,
    scalar,
    stock_of,
    user,
)


async def test_goods_received_puts_stock_in_the_branch_fefo(client) -> None:
    para = await add_product()
    # two lots, the later-expiring one listed first
    await event("goods.received", goods_received(para, [("B2", "2028-09-30", 400, "0.0425"),
                                                        ("A1", "2028-03-31", 600, "0.0425")]))  # fmt: skip
    [item] = await stock_of(client)
    assert item["branch_id"] == str(PP1) and item["sku"] == "PARA500"
    assert item["qty_on_hand"] == 1000 and item["qty_available"] == 1000
    assert item["on_hand_in_packs"] == [{"pack_unit": "box", "qty": 10}]
    assert [b["lot_no"] for b in item["batches"]] == ["A1", "B2"]  # earliest expiry first
    assert item["batches"][0]["days_to_expiry"] == 521
    assert item["stock_value"] == "42.50" and item["batches"][0]["cost_per_base"] == "0.0425"
    assert await stock_of(client, branch_id=str(PP2)) == []
    changed = [p for t, p in await outbox() if t == "stock.changed"]
    assert [(c["type"], c["delta"], c["branch_id"]) for c in changed] == [
        ("in", 400, str(PP1)),
        ("in", 600, str(PP1)),
    ]


async def test_pack_breakdown_of_odd_quantities(client) -> None:
    para = await add_product()
    await event("goods.received", goods_received(para, [("A1", "2028-03-31", 1253, "0.04")]))
    [item] = await stock_of(client)
    assert item["on_hand_in_packs"] == [{"pack_unit": "box", "qty": 12}, {"pack_unit": "strip", "qty": 5},
                                        {"pack_unit": "tablet", "qty": 3}]  # fmt: skip


async def test_same_receipt_line_is_booked_once(client) -> None:
    para = await add_product()
    payload = goods_received(para, [("A1", "2028-03-31", 600, "0.0425")])
    await event("goods.received", payload)
    await event("goods.received", payload)  # delivered again with a new message id
    [item] = await stock_of(client)
    assert item["qty_on_hand"] == 600
    assert await scalar("SELECT count(*) FROM movements") == 1


async def test_batch_reused_only_when_lot_expiry_supplier_and_cost_match(client) -> None:
    para = await add_product()
    await event("goods.received", goods_received(para, [("A1", "2028-03-31", 100, "0.0425")]))
    await event("goods.received", goods_received(para, [("A1", "2028-03-31", 100, "0.0425")]))  # same: reused
    await event("goods.received", goods_received(para, [("A1", "2028-03-31", 100, "0.0500")]))  # other cost
    await event("goods.received", goods_received(para, [("A1", "2028-03-31", 100, "0.0425")], branch=PP2))
    assert await scalar("SELECT count(*) FROM batches") == 2
    [item] = await stock_of(client, branch_id=str(PP1))
    # same lot and expiry: FEFO treats them alike, so their order is a tie
    assert sorted((b["lot_no"], b["qty_on_hand"], b["cost_per_base"]) for b in item["batches"]) == [
        ("A1", 100, "0.0500"), ("A1", 200, "0.0425"),
    ]  # fmt: skip
    assert (await stock_of(client, branch_id=str(PP2)))[0]["qty_on_hand"] == 100


async def test_cashier_sees_stock_but_no_cost_fields(client) -> None:
    para = await add_product()
    await event("goods.received", goods_received(para, [("A1", "2028-03-31", 600, "0.0425")]))
    r = await client.get(f"{PREFIX}/stock", headers=CASHIER)
    text = r.text
    assert r.status_code == 200 and r.json()["items"][0]["qty_on_hand"] == 600
    for field in ("cost_per_base", "stock_value", '"value"'):
        assert field not in text
    r = await client.get(f"{PREFIX}/batches", headers=CASHIER)
    assert "cost_per_base" not in r.text and r.json()["items"][0]["lot_no"] == "A1"
    manager_with_cost = user("branch_manager", "inventory.view,finance.cost_profit")
    assert "cost_per_base" in (await client.get(f"{PREFIX}/stock", headers=manager_with_cost)).text


async def test_staff_see_only_their_branches(client) -> None:
    para = await add_product()
    await event("goods.received", goods_received(para, [("A1", "2028-03-31", 10, "0.04")], branch=PP2))
    assert await stock_of(client, headers=CASHIER) == []  # cashier works at PP1
    r = await client.get(f"{PREFIX}/stock", params={"branch_id": str(PP2)}, headers=CASHIER)
    assert r.status_code == 403 and r.json()["code"] == "BRANCH_FORBIDDEN"
    assert len(await stock_of(client)) == 1  # owner sees all


async def test_batches_expiring_within(client) -> None:
    para = await add_product()
    await event("goods.received", goods_received(para, [("SOON", "2026-12-31", 10, "0.04"),
                                                        ("LATER", "2028-03-31", 10, "0.04")]))  # fmt: skip
    r = await client.get(
        f"{PREFIX}/batches", params={"expiring_within": 90, "branch_id": str(PP1)}, headers=OWNER
    )
    assert [b["lot_no"] for b in r.json()["items"]] == ["SOON"]
    r = await client.get(f"{PREFIX}/batches", headers=OWNER)
    assert [b["lot_no"] for b in r.json()["items"]] == ["SOON", "LATER"]


async def test_stock_never_goes_negative(client) -> None:
    para = await add_product()
    await event("goods.received", goods_received(para, [("A1", "2028-03-31", 10, "0.04")]))
    async with db.sessionmaker() as session:
        batch = (await session.execute(Batch.__table__.select())).first()
        batch = await session.get(Batch, batch.id)
        with pytest.raises(Exception) as exc:
            await apply_movement(session, branch_id=PP1, batch=batch, type="adjust_out", qty_base=-11,
                                 ref_type="test", ref_id="x")  # fmt: skip
        assert getattr(exc.value, "code", None) == "OUT_OF_STOCK"
        await session.rollback()
    assert (await stock_of(client))[0]["qty_on_hand"] == 10


async def test_movements_always_add_up_to_stock(client) -> None:
    para = await add_product()
    amox = await add_product("AMOX500")
    for p in (para, amox):
        await event("goods.received", goods_received(p, [("A1", "2028-03-31", 30, "0.04"),
                                                         ("B1", "2029-01-31", 70, "0.05")]))  # fmt: skip
    mismatches = await scalar(
        "SELECT count(*) FROM stock s LEFT JOIN (SELECT branch_id, batch_id, sum(qty_base) q FROM movements "
        "GROUP BY 1, 2) m USING (branch_id, batch_id) WHERE s.qty_on_hand <> coalesce(m.q, 0)"
    )
    assert mismatches == 0


async def test_movements_list(client) -> None:
    para = await add_product()
    await event("goods.received", goods_received(para, [("A1", "2028-03-31", 30, "0.04")]))
    r = await client.get(f"{PREFIX}/movements", params={"branch_id": str(PP1)}, headers=CASHIER)
    [m] = r.json()["items"]
    assert (m["type"], m["qty_base"], m["qty_after"], m["ref_type"]) == ("in", 30, 30, "receipt_line")
    assert m["reason"].startswith("PO receipt")
