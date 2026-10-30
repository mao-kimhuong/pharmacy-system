"""Transfers between branches: request → approve → pick (FEFO) → dispatch →
receive; stock conserved, in transit visible, differences resolved, branch
rules, controlled sign-off."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from inventory_service.db import db
from inventory_service.main import app
from inventory_service.models import Shrinkage, Stock
from inventory_service.services.clients import get_auth

from .conftest import PP1, PP2, PREFIX, add_product, event, goods_received, idem, outbox, user
from .fake_auth import FakeAuth

PERMS = "inventory.view,transfers.request,transfers.approve,transfers.dispatch,transfers.receive,transfers.resolve"
SOURCE = user("branch_manager", PERMS, (PP1,))
DEST = user("branch_manager", PERMS, (PP2,))
DEST_CASHIER = user("cashier", "inventory.view,transfers.receive", (PP2,))


@pytest.fixture
def auth():  # noqa: ANN201
    fake = FakeAuth()
    app.dependency_overrides[get_auth] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_auth, None)


async def total_on_hand(medicine_id: str) -> dict:
    async with db.sessionmaker() as s:
        rows = await s.execute(select(Stock.branch_id, func.sum(Stock.qty_on_hand), func.sum(Stock.qty_reserved))
                               .join(Stock.batch).where(Stock.batch.has(medicine_id=medicine_id))
                               .group_by(Stock.branch_id))  # fmt: skip
        return {b: (int(q), int(r)) for b, q, r in rows}


async def in_transit(client, medicine_id: str) -> int:  # noqa: ANN001
    rows = (await client.get(f"{PREFIX}/transfers/in-transit", headers=user("owner", "*", ()))).json()
    return sum(r["qty_base"] for r in rows if r["medicine_id"] == medicine_id)


async def conserved(client, medicine_id: str) -> int:  # noqa: ANN001
    return sum(q for q, _ in (await total_on_hand(medicine_id)).values()) + await in_transit(client, medicine_id)


async def stocked(sku: str = "PARA500", controlled: str | None = None) -> dict:
    product = await add_product(sku, controlled=controlled)
    await event("goods.received", goods_received(product, [("EARLY", "2027-03-31", 30, "0.1000"),
                                                           ("LATE", "2028-06-30", 70, "0.1200")]))  # fmt: skip
    return product


async def requested_transfer(client, product: dict, qty: int = 40) -> dict:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/transfer-requests", headers=DEST, json={
        "from_branch_id": str(PP1), "to_branch_id": str(PP2), "reason": "running low",
        "lines": [{"medicine_id": product["id"], "qty_base": qty}]})  # fmt: skip
    assert r.status_code == 201, r.text
    assert r.json()["number"] == "PP2-TQ-2026-000001" or r.json()["number"].startswith("PP2-TQ-")
    r = await client.post(f"{PREFIX}/transfer-requests/{r.json()['id']}/approve", headers=SOURCE)
    assert r.status_code == 200, r.text
    return r.json()


async def test_full_transfer_conserves_stock_and_keeps_batches(client) -> None:
    para = await stocked()
    start = await conserved(client, para["id"])
    t = await requested_transfer(client, para)
    assert t["status"] == "approved" and t["number"].startswith("PP1-TR-")
    t = (await client.post(f"{PREFIX}/transfers/{t['id']}/pick", json={}, headers=SOURCE)).json()
    assert [(p["lot_no"], p["qty_base"]) for p in t["picks"]] == [("EARLY", 30), ("LATE", 10)]  # FEFO split
    assert (await total_on_hand(para["id"]))[PP1] == (100, 40)  # reserved: no sale can take it
    assert await conserved(client, para["id"]) == start
    t = (await client.post(f"{PREFIX}/transfers/{t['id']}/dispatch", json={}, headers={**SOURCE, **idem()})).json()
    assert t["status"] == "dispatched"
    assert (await total_on_hand(para["id"]))[PP1] == (60, 0)
    assert await in_transit(client, para["id"]) == 40 and await conserved(client, para["id"]) == start
    seen_by_dest = (await client.get(f"{PREFIX}/transfers/in-transit", params={"branch_id": str(PP2)},
                                     headers=DEST)).json()  # fmt: skip
    assert sum(r["qty_base"] for r in seen_by_dest) == 40 and "cost_per_base" not in seen_by_dest[0]
    lines = [{"pick_id": p["id"], "qty_received": p["qty_base"]} for p in t["picks"]]
    t = (await client.post(f"{PREFIX}/transfers/{t['id']}/receive", json={"lines": lines},
                           headers={**DEST, **idem()})).json()  # fmt: skip
    assert t["status"] == "closed" and await in_transit(client, para["id"]) == 0
    assert await total_on_hand(para["id"]) == {PP1: (60, 0), PP2: (40, 0)}
    assert await conserved(client, para["id"]) == start
    moves = [p for e, p in await outbox() if e == "stock.changed"][-4:]
    assert {(m["type"], m["lot_no"], m["cost_per_base"]) for m in moves} == {
        ("transfer_out", "EARLY", "0.1000"), ("transfer_out", "LATE", "0.1200"),
        ("transfer_in", "EARLY", "0.1000"), ("transfer_in", "LATE", "0.1200")}  # fmt: skip
    events = [e for e, _ in await outbox() if e.startswith("transfer.")]
    assert events == ["transfer.created", "transfer.picked", "transfer.dispatched", "transfer.received", "transfer.closed"]


async def test_override_batch_needs_a_reason(client) -> None:
    para = await stocked()
    t = await requested_transfer(client, para, 20)
    stock = (await client.get(f"{PREFIX}/stock", params={"branch_id": str(PP1)}, headers=SOURCE)).json()["items"][0]
    late = next(b["batch_id"] for b in stock["batches"] if b["lot_no"] == "LATE")
    body = {"lines": [{"line_no": 1, "batches": [{"batch_id": late, "qty_base": 20, "reason": ""}]}]}
    assert (await client.post(f"{PREFIX}/transfers/{t['id']}/pick", json=body, headers=SOURCE)).status_code == 422
    body["lines"][0]["batches"][0]["reason"] = "Send the longer-dated lot to the slower branch"
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/pick", json=body, headers=SOURCE)
    assert r.status_code == 200, r.text
    assert [(p["lot_no"], p["override_reason"]) for p in r.json()["picks"]] == [
        ("LATE", "Send the longer-dated lot to the slower branch")]  # fmt: skip
    # picking again (FEFO) replaces the earlier pick and its reservation
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/pick", json={}, headers=SOURCE)
    assert [p["lot_no"] for p in r.json()["picks"]] == ["EARLY"]
    assert (await total_on_hand(para["id"]))[PP1] == (100, 20)


async def test_cancel_only_before_dispatch(client) -> None:
    para = await stocked()
    t = await requested_transfer(client, para, 10)
    await client.post(f"{PREFIX}/transfers/{t['id']}/pick", json={}, headers=SOURCE)
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/cancel", json={"reason": "changed my mind"}, headers=SOURCE)
    assert r.json()["status"] == "cancelled" and (await total_on_hand(para["id"]))[PP1] == (100, 0)
    t2 = await requested_transfer(client, para, 10)
    await client.post(f"{PREFIX}/transfers/{t2['id']}/pick", json={}, headers=SOURCE)
    await client.post(f"{PREFIX}/transfers/{t2['id']}/dispatch", json={}, headers={**SOURCE, **idem()})
    r = await client.post(f"{PREFIX}/transfers/{t2['id']}/cancel", json={"reason": "too late"}, headers=SOURCE)
    assert r.status_code == 409 and r.json()["code"] == "TRANSFER_STATE"


async def _dispatched(client, para: dict, qty: int = 30) -> dict:  # noqa: ANN001
    t = await requested_transfer(client, para, qty)
    await client.post(f"{PREFIX}/transfers/{t['id']}/pick", json={}, headers=SOURCE)
    return (await client.post(f"{PREFIX}/transfers/{t['id']}/dispatch", json={}, headers={**SOURCE, **idem()})).json()


async def test_short_receipt_opens_a_difference_written_off_on_the_source(client) -> None:
    para = await stocked()
    start = await conserved(client, para["id"])
    t = await _dispatched(client, para)
    pick = t["picks"][0]
    t = (await client.post(f"{PREFIX}/transfers/{t['id']}/receive", headers={**DEST_CASHIER, **idem()},
                           json={"lines": [{"pick_id": pick["id"], "qty_received": 27}]})).json()  # fmt: skip
    assert t["status"] == "received"
    diff = t["discrepancies"][0]
    assert (diff["kind"], diff["qty_base"], diff["status"]) == ("short", 3, "open")
    assert await in_transit(client, para["id"]) == 3 and await conserved(client, para["id"]) == start
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/differences/{diff['id']}/resolve", headers={**DEST_CASHIER,
                          **idem()}, json={"resolution": "write_off", "reason": "x"})  # fmt: skip
    assert r.status_code == 403  # transfers.resolve
    bad = await client.post(f"{PREFIX}/transfers/{t['id']}/differences/{diff['id']}/resolve",
                            headers={**DEST, **idem()}, json={"resolution": "accept", "reason": "x"})  # fmt: skip
    assert bad.status_code == 422
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/differences/{diff['id']}/resolve",
                          headers={**DEST, **idem()}, json={"resolution": "write_off", "reason": "Lost on the bus"})  # fmt: skip
    assert r.json()["status"] == "closed" and await in_transit(client, para["id"]) == 0
    async with db.sessionmaker() as s:
        sh = (await s.execute(select(Shrinkage))).scalar_one()
    assert (sh.branch_id, sh.qty_base, sh.reason, sh.status) == (PP1, 3, "lost_theft", "posted")
    assert await conserved(client, para["id"]) == start - 3


async def test_short_quantity_returned_to_the_source(client) -> None:
    para = await stocked()
    start = await conserved(client, para["id"])
    t = await _dispatched(client, para, 20)
    pick = t["picks"][0]
    t = (await client.post(f"{PREFIX}/transfers/{t['id']}/receive", headers={**DEST, **idem()},
                           json={"lines": [{"pick_id": pick["id"], "qty_received": 15, "qty_damaged": 2,
                                            "location": "b2"}]})).json()  # fmt: skip
    kinds = {d["kind"]: d for d in t["discrepancies"]}
    assert (kinds["damaged"]["qty_base"], kinds["short"]["qty_base"]) == (2, 3)
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/differences/{kinds['short']['id']}/resolve",
                          headers={**DEST, **idem()}, json={"resolution": "return_to_source", "reason": "Found it"})  # fmt: skip
    assert r.json()["status"] == "received"  # the damaged one is still open
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/differences/{kinds['damaged']['id']}/resolve",
                          headers={**DEST, **idem()}, json={"resolution": "write_off", "reason": "Crushed box"})  # fmt: skip
    assert r.json()["status"] == "closed"
    assert await total_on_hand(para["id"]) == {PP1: (83, 0), PP2: (15, 0)}
    assert await conserved(client, para["id"]) == start - 2
    rows = (await client.get(f"{PREFIX}/shelf-locations", params={"branch_id": str(PP2)}, headers=DEST)).json()
    assert [r["code"] for r in rows] == ["B2"]


async def test_extra_quantity_accepted_into_stock(client) -> None:
    para = await stocked()
    t = await _dispatched(client, para, 10)
    t = (await client.post(f"{PREFIX}/transfers/{t['id']}/receive", headers={**DEST, **idem()},
                           json={"lines": [{"pick_id": t["picks"][0]["id"], "qty_received": 12}]})).json()  # fmt: skip
    diff = t["discrepancies"][0]
    assert (diff["kind"], diff["qty_base"]) == ("extra", 2) and (await total_on_hand(para["id"]))[PP2] == (10, 0)
    await client.post(f"{PREFIX}/transfers/{t['id']}/differences/{diff['id']}/resolve",
                      headers={**DEST, **idem()}, json={"resolution": "accept", "reason": "Counted twice"})  # fmt: skip
    assert (await total_on_hand(para["id"]))[PP2] == (12, 0)


async def test_branch_rules(client) -> None:
    para = await stocked()
    t = await requested_transfer(client, para, 10)
    # a user of the destination branch cannot pick, dispatch or cancel at the source
    for path in ("pick", "dispatch"):
        r = await client.post(f"{PREFIX}/transfers/{t['id']}/{path}", json={}, headers={**DEST, **idem()})
        assert r.status_code == 403, path
    await client.post(f"{PREFIX}/transfers/{t['id']}/pick", json={}, headers=SOURCE)
    await client.post(f"{PREFIX}/transfers/{t['id']}/dispatch", json={}, headers={**SOURCE, **idem()})
    lines = [{"pick_id": p["id"], "qty_received": p["qty_base"]} for p in t.get("picks", [])] or [
        {"pick_id": (await client.get(f"{PREFIX}/transfers/{t['id']}", headers=SOURCE)).json()["picks"][0]["id"],
         "qty_received": 10}]  # fmt: skip
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/receive", json={"lines": lines}, headers={**SOURCE, **idem()})
    assert r.status_code == 403  # the source cannot receive its own transfer
    outsider = user("branch_manager", PERMS, (uuid4(),))
    assert (await client.get(f"{PREFIX}/transfers/{t['id']}", headers=outsider)).status_code == 404
    r = await client.post(f"{PREFIX}/transfer-requests", headers=DEST, json={
        "from_branch_id": str(PP1), "to_branch_id": str(PP1), "lines": [{"medicine_id": para["id"], "qty_base": 1}]})  # fmt: skip
    assert r.status_code == 403  # asking on behalf of another branch


async def test_reject_and_push_without_request(client) -> None:
    para = await stocked()
    r = await client.post(f"{PREFIX}/transfer-requests", headers=DEST, json={
        "from_branch_id": str(PP1), "to_branch_id": str(PP2), "lines": [{"medicine_id": para["id"], "qty_base": 5}]})  # fmt: skip
    r = await client.post(f"{PREFIX}/transfer-requests/{r.json()['id']}/reject", json={"reason": "We need it"},
                          headers=SOURCE)  # fmt: skip
    assert r.json()["status"] == "rejected" and r.json()["decision_reason"] == "We need it"
    r = await client.post(f"{PREFIX}/transfers", headers=SOURCE, json={
        "from_branch_id": str(PP1), "to_branch_id": str(PP2), "lines": [{"medicine_id": para["id"], "qty_base": 5}]})  # fmt: skip
    assert r.status_code == 201 and r.json()["status"] == "approved" and r.json()["request_id"] is None
    by_number = await client.get(f"{PREFIX}/transfers/by-number/{r.json()['number'].lower()}", headers=DEST)
    assert by_number.json()["id"] == r.json()["id"]


async def test_controlled_transfer_needs_pin_and_witness_on_both_sides(client, auth) -> None:
    diaz = await stocked("DIAZ5", controlled="IV")
    t = await requested_transfer(client, diaz, 10)
    await client.post(f"{PREFIX}/transfers/{t['id']}/pick", json={}, headers=SOURCE)
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/dispatch", json={}, headers={**SOURCE, **idem()})
    assert r.status_code == 401 and r.json()["code"] == "PIN_REQUIRED"
    pin = auth.issue(SOURCE["X-User-Id"], "transfers.dispatch", branches=(PP1,))
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/dispatch", json={"pin_token": pin},
                          headers={**SOURCE, **idem()})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_REQUIRED"
    sign = {"pin_token": auth.issue(SOURCE["X-User-Id"], "transfers.dispatch", branches=(PP1,)),
            "witness_token": auth.issue(str(uuid4()), "transfers.dispatch", "witness", branches=(PP1,), name="Dara")}  # fmt: skip
    t = (await client.post(f"{PREFIX}/transfers/{t['id']}/dispatch", json=sign, headers={**SOURCE, **idem()})).json()
    assert t["dispatch_witness"] == "Dara"
    lines = [{"pick_id": p["id"], "qty_received": p["qty_base"]} for p in t["picks"]]
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/receive", json={"lines": lines}, headers={**DEST, **idem()})
    assert r.status_code == 401
    # a witness from the source branch cannot sign at the destination
    far = {"pin_token": auth.issue(DEST["X-User-Id"], "transfers.receive", branches=(PP2,)),
           "witness_token": auth.issue(str(uuid4()), "transfers.receive", "witness", branches=(PP1,))}  # fmt: skip
    r = await client.post(f"{PREFIX}/transfers/{t['id']}/receive", json={"lines": lines, **far},
                          headers={**DEST, **idem()})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_INVALID"
    sign = {"pin_token": auth.issue(DEST["X-User-Id"], "transfers.receive", branches=(PP2,)),
            "witness_token": auth.issue(str(uuid4()), "transfers.receive", "witness", branches=(PP2,), name="Sok")}  # fmt: skip
    t = (await client.post(f"{PREFIX}/transfers/{t['id']}/receive", json={"lines": lines, **sign},
                           headers={**DEST, **idem()})).json()  # fmt: skip
    assert t["status"] == "closed" and t["receive_witness"] == "Sok"
    moves = [p for e, p in await outbox() if e == "stock.changed" and p["type"].startswith("transfer")]
    assert {(m["type"], m["meta"].get("witness_name")) for m in moves} == {("transfer_out", "Dara"),
                                                                            ("transfer_in", "Sok")}  # fmt: skip
    assert all(m["is_controlled"] for m in moves)
