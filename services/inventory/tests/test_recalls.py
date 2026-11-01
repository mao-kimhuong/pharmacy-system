"""Recalls: the owner blocks lots everywhere, a manager only in their branches;
blocked stock is never sold; per line return to the supplier or destroy; close
when nothing is left; the owner lifts a mistaken recall."""

from uuid import uuid4

from inventory_service.main import app
from inventory_service.services.clients import get_purchasing

from .conftest import (
    INTERNAL,
    OWNER,
    PP1,
    PP2,
    PREFIX,
    add_product,
    event,
    goods_received,
    idem,
    outbox,
    user,
)  # fmt: skip

RECALLER = user("branch_manager", "inventory.view,inventory.recall,inventory.shrinkage", (PP1,))


async def stocked() -> dict:
    para = await add_product("PARA500")
    await event("goods.received", goods_received(para, [("BAD", "2028-01-31", 100, "0.0500"),
                                                        ("OK", "2028-06-30", 50, "0.0500")]))  # fmt: skip
    await event("goods.received", goods_received(para, [("BAD", "2028-01-31", 40, "0.0500")], branch=PP2))
    return para


async def reserve(client, para: dict, qty: int, branch=PP1, batch_id: str | None = None):  # noqa: ANN001, ANN201
    line = {"line_no": 1, "medicine_id": para["id"], "qty_base": qty, **({"batch_id": batch_id} if batch_id else {})}
    return await client.post("/internal/v1/reservations", headers=INTERNAL, json={
        "ref_type": "invoice", "ref_id": str(uuid4()), "branch_id": str(branch), "lines": [line]})  # fmt: skip


async def recall(client, para: dict, who: dict = OWNER, lots: tuple = ("BAD",)) -> dict:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/recalls", headers={**who, **idem()},
                          json={"medicine_id": para["id"], "lot_nos": list(lots), "reason": "MoH letter 12/2026"})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def test_owner_recall_blocks_the_lot_everywhere(client) -> None:
    para = await stocked()
    rc = await recall(client, para)
    assert rc["number"] == "RC-2026-000001" and rc["all_branches"]
    assert (await reserve(client, para, 60)).json()["code"] == "OUT_OF_STOCK"  # only lot OK (50) is sellable
    assert (await reserve(client, para, 40, PP2)).json()["code"] == "OUT_OF_STOCK"
    detail = (await client.get(f"{PREFIX}/recalls/{rc['id']}", headers=OWNER)).json()
    bad = detail["lines"][0]["batch_id"]
    assert sorted((x["on_hand"], x["action"]) for x in detail["lines"]) == [(40, "pending"), (100, "pending")]
    r = await reserve(client, para, 1, batch_id=bad)
    assert r.json()["code"] == "BATCH_BLOCKED" and r.json()["details"]["status"] == "recalled"
    alerts = [p for t, p in await outbox() if t == "batch.recalled"]
    assert sorted(a["qty_base"] for a in alerts) == [40, 100] and alerts[0]["lots"] == ["BAD"]
    assert (await client.post(f"{PREFIX}/recalls", headers={**user("cashier", "inventory.recall"), **idem()},
                              json={"medicine_id": para["id"], "lot_nos": ["BAD"], "reason": "x x"})).status_code == 403  # fmt: skip


async def test_a_manager_recalls_only_their_branches_then_returns_destroys_and_closes(client) -> None:
    para = await stocked()
    rc = await recall(client, para, RECALLER)
    assert not rc["all_branches"]
    assert (await reserve(client, para, 40, PP2)).status_code == 200  # PP2 is not theirs: still sellable
    line = (await client.get(f"{PREFIX}/recalls/{rc['id']}", headers=RECALLER)).json()["lines"][0]
    assert line["on_hand"] == 100 and line["branch_id"] == str(PP1)
    sent = {}

    class Purchasing:
        async def post(self, path: str, body: dict, **kw) -> dict:  # noqa: ANN003
            sent.update(path=path, **body)
            return {"id": str(uuid4()), "number": "PP1-SRN-2026-000001"}

    app.dependency_overrides[get_purchasing] = lambda: Purchasing()
    try:
        r = await client.post(f"{PREFIX}/recalls/{rc['id']}/lines/{line['id']}/return", headers={**RECALLER, **idem()})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 201 and r.json()["number"] == "PP1-SRN-2026-000001"
    assert sent["path"] == "/supplier-returns/from-recall" and sent["lines"][0]["qty_base"] == 100
    again = await client.post(f"{PREFIX}/recalls/{rc['id']}/lines/{line['id']}/destroy", json={},
                              headers={**RECALLER, **idem()})  # fmt: skip
    assert again.status_code == 409 and again.json()["code"] == "RECALL_STATE"  # already sent back
    closing = await client.post(f"{PREFIX}/recalls/{rc['id']}/close", headers=RECALLER)
    assert closing.status_code == 409  # the 100 tablets are still here until purchasing submits the return
    body = {"return_id": str(uuid4()), "number": "PP1-SRN-2026-000001", "branch_id": str(PP1),
            "supplier_id": "00000000-0000-0000-0000-00000000005a",
            "lines": [{"line_no": 1, "batch_id": line["batch_id"], "medicine_id": para["id"], "qty_base": 100}]}  # fmt: skip
    moved = await client.post("/internal/v1/movements/supplier-return", json=body, headers=INTERNAL)
    assert moved.status_code == 200 and moved.json()["lines"][0]["cost_per_base"] == "0.0500"
    assert (await client.post(f"{PREFIX}/recalls/{rc['id']}/close", headers=RECALLER)).json()["status"] == "closed"


async def test_destroy_a_line_and_the_owner_lifts_a_mistake(client) -> None:
    para = await stocked()
    rc = await recall(client, para)
    lines = (await client.get(f"{PREFIX}/recalls/{rc['id']}", headers=OWNER)).json()["lines"]
    pp2 = next(x for x in lines if x["branch_id"] == str(PP2))
    r = await client.post(f"{PREFIX}/recalls/{rc['id']}/lines/{pp2['id']}/destroy", json={}, headers={**OWNER, **idem()})
    assert r.status_code == 201 and r.json()["reason"] == "recalled" and r.json()["status"] == "posted"
    assert (await client.post(f"{PREFIX}/recalls/{rc['id']}/lift", json={"reason": "wrong lot"},
                              headers=RECALLER)).status_code == 403  # fmt: skip
    r = await client.post(f"{PREFIX}/recalls/{rc['id']}/lift", json={"reason": "wrong lot number"}, headers=OWNER)
    assert r.json()["status"] == "lifted"
    assert (await reserve(client, para, 150)).status_code == 200  # BAD is sellable again at PP1
