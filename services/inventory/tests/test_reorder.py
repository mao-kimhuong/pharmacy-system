"""Re-ordering: the calculation, open POs and transfers counted, settings,
transfer suggestions (spare / near expiry), alerts once a day, requests from a list."""

from uuid import uuid4

from sqlalchemy import select

from inventory_service.db import db
from inventory_service.main import app
from inventory_service.models import Batch
from inventory_service.services.clients import get_purchasing
from inventory_service.services.movements import apply_movement

from .conftest import PP1, PP2, PREFIX, add_product, event, goods_received, outbox, user

MANAGER = user("branch_manager", "inventory.view,inventory.reorder_settings,purchasing.request,transfers.request")
MANAGER2 = user("branch_manager", "inventory.view,inventory.reorder_settings", (PP2,))


async def stock(product: dict, qty: int, branch=PP1, lot: str = "L1", expiry: str = "2028-01-31") -> None:  # noqa: ANN001
    await event("goods.received", goods_received(product, [(lot, expiry, qty, "0.0500")], branch))


async def sell(product: dict, qty: int, branch=PP1) -> None:  # noqa: ANN001
    """Sales in the last 30 days ("out" movements)."""
    async with db.sessionmaker() as s:
        batch = (await s.execute(select(Batch).where(Batch.medicine_id == product["id"])
                                 .order_by(Batch.expiry_date))).scalars().first()  # fmt: skip
        await apply_movement(s, branch_id=branch, batch=batch, type="out", qty_base=-qty, ref_type="sale",
                             ref_id=str(uuid4()))  # fmt: skip
        await s.commit()


async def run(client, branch=PP1, headers=MANAGER) -> dict:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/reorder-lists/run", params={"branch_id": str(branch)}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def line_of(rl: dict, sku: str) -> dict | None:
    return next((x for x in rl["lines"] if x["sku"] == sku), None)


async def test_the_calculation(client) -> None:
    para = await add_product()  # tablet / strip 10 / box 100
    await stock(para, 75)
    await sell(para, 60)  # 2 a day over 30 days; 15 left
    line = line_of(await run(client), "PARA500")
    # point = 2 × (7 lead + 3 safety) = 20; target = 2 × (7 + 3 + 30) = 80; 80 − 15 = 65 → 7 strips
    assert (line["on_hand"], line["avg_daily"], line["reorder_point"], line["target"]) == (15, "2.000", 20, 80)
    assert (line["suggested_qty"], line["pack_unit"], line["pack_qty"]) == (70, "strip", 7)
    assert "last_cost_per_base" not in line  # cost only with finance.cost_profit


async def test_open_po_and_settings(client) -> None:
    para = await add_product()
    await stock(para, 75)
    await sell(para, 60)
    po_line = str(uuid4())
    po = {"purchase_order_id": str(uuid4()), "version": 2, "status": "sent", "branch": {"id": str(PP1)},
          "lines": [{"po_line_id": po_line, "medicine_id": para["id"], "qty_base": 10, "qty_received_base": 0}]}  # fmt: skip
    await event("purchase_order.sent", po)
    assert line_of(await run(client), "PARA500") is None  # 15 + 10 on order > 20
    await event("purchase_order.created", {**po, "version": 1, "status": "draft"})  # older: ignored
    assert line_of(await run(client), "PARA500") is None
    await event("purchase_order.cancelled", {**po, "version": 3, "status": "cancelled"})
    assert line_of(await run(client), "PARA500")["on_order"] == 0
    r = await client.put(f"{PREFIX}/reorder-settings", headers=MANAGER, json={
        "branch_id": str(PP1), "medicine_id": para["id"], "min_qty": 50, "max_qty": 120, "lead_time_days": 14})  # fmt: skip
    assert r.status_code == 200, r.text
    line = line_of(await run(client), "PARA500")
    assert (line["reorder_point"], line["target"], line["suggested_qty"]) == (50, 120, 110)
    bad = await client.put(f"{PREFIX}/reorder-settings", headers=MANAGER, json={
        "branch_id": str(PP1), "medicine_id": para["id"], "min_qty": 50, "max_qty": 10})  # fmt: skip
    assert bad.status_code == 422
    other = await client.put(f"{PREFIX}/reorder-settings", headers=MANAGER2, json={
        "branch_id": str(PP1), "medicine_id": para["id"], "min_qty": 1})  # fmt: skip
    assert other.status_code == 403


async def test_bulk_settings_by_category(client) -> None:
    cat = str(uuid4())
    a, b = await add_product("A1", category=cat), await add_product("B1", category=cat)
    await add_product("C1")
    r = await client.post(f"{PREFIX}/reorder-settings/bulk", headers=MANAGER,
                          json={"branch_id": str(PP1), "category_id": cat, "min_qty": 5, "max_qty": 30})  # fmt: skip
    assert r.json() == {"updated": 2}
    rows = (await client.get(f"{PREFIX}/reorder-settings", params={"branch_id": str(PP1)}, headers=MANAGER)).json()
    assert {x["medicine_id"] for x in rows} == {a["id"], b["id"]}
    rl = await run(client)  # nothing in stock, min 5: both suggested, from settings alone
    assert {x["sku"]: x["suggested_qty"] for x in rl["lines"]} == {"A1": 30, "B1": 30}


async def test_near_expiry_stock_elsewhere_is_suggested(client) -> None:
    para = await add_product()
    await stock(para, 25)
    await sell(para, 20)  # this branch sells 20 a month, 5 left
    await stock(para, 100, PP2, lot="SHORT", expiry="2026-12-06")  # PP2: 40 days left, sells nothing
    line = line_of(await run(client), "PARA500")
    assert line["source_branch_id"] == str(PP2) and line["source_reason"] == "near_expiry"
    assert line["source_qty"] == min(100, line["suggested_qty"])


async def test_spare_stock_elsewhere_is_suggested(client) -> None:
    para = await add_product()
    await stock(para, 75)
    await sell(para, 60)
    await stock(para, 500, PP2, lot="LONG", expiry="2029-01-31")
    await client.put(f"{PREFIX}/reorder-settings", headers=MANAGER2, json={
        "branch_id": str(PP2), "medicine_id": para["id"], "max_qty": 300})  # fmt: skip
    line = line_of(await run(client), "PARA500")
    assert (line["source_branch_id"], line["source_reason"], line["source_qty"]) == (str(PP2), "spare", 70)


async def test_alerts_once_a_day(client) -> None:
    para = await add_product()
    await stock(para, 75, expiry="2026-12-01")  # 35 days left: inside the 90-day alert
    await sell(para, 60)
    await run(client)
    await run(client)
    low = [p for e, p in await outbox() if e == "stock.low"]
    expiring = [p for e, p in await outbox() if e == "batch.expiring"]
    assert len(low) == 1 and low[0]["sku"] == "PARA500" and low[0]["reorder_point"] == 20
    assert len(expiring) == 1 and (expiring[0]["days_left"], expiring[0]["threshold_days"]) == (35, 90)


class FakePurchasing:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, path: str, body: dict | None = None, **_) -> dict:  # noqa: ANN003
        self.calls.append(body or {})
        return {"request_id": str(uuid4()), "number": "PP1-PR-2026-000009", "status": "submitted"}


async def test_list_to_purchase_and_transfer_requests(client) -> None:
    para, ors = await add_product(), await add_product("ORS")
    for p in (para, ors):
        await stock(p, 75)
        await sell(p, 60)
    await stock(ors, 500, PP2, lot="SPARE", expiry="2029-01-31")
    rl = await run(client)
    fake = FakePurchasing()
    app.dependency_overrides[get_purchasing] = lambda: fake
    try:
        para_line, ors_line = line_of(rl, "PARA500"), line_of(rl, "ORS")
        r = await client.post(f"{PREFIX}/reorder-lists/{rl['id']}/purchase-requests", headers=MANAGER,
                              json={"line_ids": [para_line["id"]]})  # fmt: skip
        assert r.status_code == 200, r.text
        assert line_of(r.json(), "PARA500")["status"] == "purchase_requested"
        assert fake.calls[0]["lines"][0]["qty_base"] == 70 and fake.calls[0]["source_ref"].startswith("reorder:")
        again = await client.post(f"{PREFIX}/reorder-lists/{rl['id']}/purchase-requests", headers=MANAGER,
                                  json={"line_ids": [para_line["id"]]})  # fmt: skip
        assert again.status_code == 409
    finally:
        app.dependency_overrides.pop(get_purchasing, None)
    r = await client.post(f"{PREFIX}/reorder-lists/{rl['id']}/transfer-requests", headers=MANAGER,
                          json={"line_ids": [ors_line["id"]]})  # fmt: skip
    assert line_of(r.json(), "ORS")["status"] == "transfer_requested"
    requests = (await client.get(f"{PREFIX}/transfer-requests", params={"branch_id": str(PP1)},
                                 headers=user("branch_manager", "transfers.request"))).json()  # fmt: skip
    assert [(x["from_branch_id"], x["lines"][0]["qty_base"]) for x in requests] == [(str(PP2), 70)]
