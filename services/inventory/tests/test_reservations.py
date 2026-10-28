import asyncio
from uuid import uuid4

from sqlalchemy import text

from inventory_service.db import db

from .conftest import (
    INTERNAL,
    MANAGER,
    OWNER,
    PHARMACIST,
    PP1,
    PREFIX,
    add_product,
    audits,
    event,
    goods_received,
    scalar,
    stock_of,
)


async def stocked(lots=(("A", "2027-03-31", 30), ("B", "2028-03-31", 100))) -> dict:
    para = await add_product()
    await event("goods.received", goods_received(para, [(lot, exp, qty, "0.04") for lot, exp, qty in lots]))
    return para


async def reserve(client, product: dict, qty: int, ref: str | None = None, **line):
    return await client.post("/internal/v1/reservations", headers=INTERNAL, json={
        "ref_id": ref or str(uuid4()), "branch_id": str(PP1),
        "lines": [{"line_no": 1, "medicine_id": product["id"], "qty_base": qty, **line}]})  # fmt: skip


async def batch_ids() -> dict[str, str]:
    async with db.engine.connect() as conn:
        return {r[0]: str(r[1]) for r in await conn.execute(text("SELECT lot_no, id FROM batches"))}


async def test_fefo_takes_the_earliest_expiry_first_and_splits(client) -> None:
    para = await stocked()
    r = await reserve(client, para, 50)
    assert r.status_code == 200, r.text
    assert [(x["lot_no"], x["qty_base"]) for x in r.json()["lines"]] == [("A", 30), ("B", 20)]
    [item] = await stock_of(client)
    assert (item["qty_on_hand"], item["qty_reserved"], item["qty_available"]) == (130, 50, 80)


async def test_skips_expired_blocked_and_quarantined_batches(client) -> None:
    para = await stocked((("PAST", "2026-10-26", 10), ("BLK", "2027-01-31", 10), ("OK", "2028-01-31", 10)))
    async with db.engine.begin() as conn:  # the night job has not run yet for PAST; BLK was blocked
        await conn.execute(text("UPDATE batches SET status = 'blocked' WHERE lot_no = 'BLK'"))
    r = await reserve(client, para, 11)
    assert r.status_code == 409 and r.json()["details"]["lines"][0]["available"] == 10
    r = await reserve(client, para, 10)
    assert [x["lot_no"] for x in r.json()["lines"]] == ["OK"]


async def test_same_invoice_reserves_once(client) -> None:
    para = await stocked()
    ref = str(uuid4())
    first = await reserve(client, para, 40, ref)
    again = await reserve(client, para, 40, ref)
    assert first.json() == again.json()
    assert (await stock_of(client))[0]["qty_reserved"] == 40


async def test_out_of_stock_lists_every_short_line_and_holds_nothing(client) -> None:
    para = await stocked()
    amox = await add_product("AMOX500")
    r = await client.post("/internal/v1/reservations", headers=INTERNAL, json={
        "ref_id": str(uuid4()), "branch_id": str(PP1), "lines": [
            {"line_no": 1, "medicine_id": para["id"], "qty_base": 10},
            {"line_no": 2, "medicine_id": amox["id"], "qty_base": 5},
            {"line_no": 3, "medicine_id": para["id"], "qty_base": 125}]})  # fmt: skip
    assert r.status_code == 409 and r.json()["code"] == "OUT_OF_STOCK"
    assert [(x["line_no"], x["requested"], x["available"]) for x in r.json()["details"]["lines"]] == [
        (2, 5, 0), (3, 125, 120)]  # fmt: skip
    assert (await stock_of(client))[0]["qty_reserved"] == 0
    assert await scalar("SELECT count(*) FROM reservations") == 0


async def test_batch_override(client) -> None:
    para = await stocked((("A", "2027-03-31", 30), ("B", "2028-03-31", 100), ("OLD", "2026-10-20", 5)))
    ids = await batch_ids()
    r = await reserve(client, para, 20, batch_id=ids["B"])
    assert [(x["lot_no"], x["overridden"]) for x in r.json()["lines"]] == [("B", True)]
    assert (await reserve(client, para, 1, batch_id=ids["OLD"])).json()["code"] == "BATCH_EXPIRED"
    async with db.engine.begin() as conn:
        await conn.execute(text("UPDATE batches SET status = 'recalled' WHERE lot_no = 'A'"))
    assert (await reserve(client, para, 1, batch_id=ids["A"])).json()["code"] == "BATCH_BLOCKED"
    assert (await reserve(client, para, 81, batch_id=ids["B"])).json()["code"] == "OUT_OF_STOCK"


async def test_confirm_sells_from_the_reserved_batches_once(client) -> None:
    para = await stocked()
    rid = (await reserve(client, para, 50)).json()["id"]
    for _ in range(2):
        r = await client.post(f"/internal/v1/reservations/{rid}/confirm", headers=INTERNAL)
        assert r.status_code == 200 and r.json()["status"] == "confirmed"
    [item] = await stock_of(client)
    assert (item["qty_on_hand"], item["qty_reserved"]) == (80, 0)
    assert {b["lot_no"]: b["qty_on_hand"] for b in item["batches"]} == {"B": 80}
    assert await scalar("SELECT count(*) FROM movements WHERE type = 'out'") == 2
    assert await scalar("SELECT sum(qty_base) FROM movements") == 80


async def test_release_gives_the_stock_back_unsold(client) -> None:
    para = await stocked()
    ref = str(uuid4())
    rid = (await reserve(client, para, 50, ref)).json()["id"]
    r = await client.post("/internal/v1/reservations/release-by-ref", headers=INTERNAL, json={"ref_id": ref})
    assert r.json()["status"] == "released"
    assert (
        await client.post(f"/internal/v1/reservations/{rid}/release", headers=INTERNAL)
    ).status_code == 200
    assert (await stock_of(client))[0]["qty_reserved"] == 0
    r = await client.post(f"/internal/v1/reservations/{rid}/confirm", headers=INTERNAL)
    assert r.status_code == 409
    r = await client.post(
        "/internal/v1/reservations/release-by-ref", headers=INTERNAL, json={"ref_id": "unknown"}
    )
    assert r.status_code == 200 and r.json() is None


async def test_reverse_puts_a_cancelled_sale_back_into_the_same_batches(client) -> None:
    para = await stocked()
    rid = (await reserve(client, para, 50)).json()["id"]
    await client.post(f"/internal/v1/reservations/{rid}/confirm", headers=INTERNAL)
    for _ in range(2):
        r = await client.post(
            f"/internal/v1/reservations/{rid}/reverse", headers=INTERNAL, json={"reason": "x"}
        )
        assert r.json()["status"] == "reversed"
    [item] = await stock_of(client)
    assert {b["lot_no"]: b["qty_on_hand"] for b in item["batches"]} == {"A": 30, "B": 100}


async def test_two_tills_cannot_sell_the_same_last_unit(client) -> None:
    para = await stocked((("LAST", "2028-03-31", 1),))
    results = await asyncio.gather(*[reserve(client, para, 1) for _ in range(10)])
    assert sorted(r.status_code for r in results) == [200] + [409] * 9
    rid = next(r.json()["id"] for r in results if r.status_code == 200)
    await client.post(f"/internal/v1/reservations/{rid}/confirm", headers=INTERNAL)
    assert await scalar("SELECT min(qty_on_hand) FROM stock") == 0


async def test_many_tills_selling_together_never_oversell(client) -> None:
    para = await stocked((("A", "2027-03-31", 3), ("B", "2028-03-31", 4)))
    results = await asyncio.gather(*[reserve(client, para, 2) for _ in range(12)])
    ok = [r for r in results if r.status_code == 200]
    assert len(ok) == 3  # 7 units: three sales of 2
    await asyncio.gather(*[client.post(f"/internal/v1/reservations/{r.json()['id']}/confirm", headers=INTERNAL)
                           for r in ok])  # fmt: skip
    assert (await stock_of(client))[0]["qty_on_hand"] == 1
    assert await scalar("SELECT count(*) FROM stock WHERE qty_on_hand < 0 OR qty_reserved < 0") == 0


async def test_returns_to_stock_or_quarantine(client) -> None:
    para = await stocked((("A", "2028-03-31", 10),))
    ids = await batch_ids()
    rid = (await reserve(client, para, 6)).json()["id"]
    await client.post(f"/internal/v1/reservations/{rid}/confirm", headers=INTERNAL)
    body = {"branch_id": str(PP1), "reason": "customer return", "items": [
        {"ref_id": "ret-1:a", "batch_id": ids["A"], "qty_base": 2}]}  # fmt: skip
    r = await client.post("/internal/v1/returns", headers=INTERNAL, json={**body, "to": "stock"})
    assert r.json()[0]["booked"] is True
    again = await client.post("/internal/v1/returns", headers=INTERNAL, json={**body, "to": "stock"})
    assert again.json()[0]["booked"] is False
    q = {
        "branch_id": str(PP1),
        "to": "quarantine",
        "items": [{"ref_id": "ret-2:a", "batch_id": ids["A"], "qty_base": 3}],
    }
    await client.post("/internal/v1/returns", headers=INTERNAL, json=q)
    [item] = await stock_of(client)
    assert (item["qty_on_hand"], item["qty_quarantined"], item["qty_available"]) == (9, 3, 6)
    assert (await reserve(client, para, 7)).status_code == 409  # quarantined goods are not sold


async def test_only_a_pharmacist_releases_quarantine_with_a_reason(client) -> None:
    await stocked((("A", "2028-03-31", 10),))
    ids = await batch_ids()
    await client.post("/internal/v1/returns", headers=INTERNAL, json={
        "branch_id": str(PP1), "to": "quarantine", "items": [{"ref_id": "r:1", "batch_id": ids["A"], "qty_base": 2}]})  # fmt: skip
    body = {"branch_id": str(PP1), "batch_id": ids["A"], "qty_base": 2, "reason": "sealed, undamaged"}
    r = await client.post(f"{PREFIX}/quarantine/release", json=body, headers=MANAGER)
    assert r.status_code == 403 and r.json()["code"] == "PHARMACIST_REQUIRED"
    r = await client.post(f"{PREFIX}/quarantine/release", json={**body, "reason": ""}, headers=PHARMACIST)
    assert r.status_code == 422
    r = await client.post(f"{PREFIX}/quarantine/release", json={**body, "qty_base": 3}, headers=PHARMACIST)
    assert r.status_code == 422
    r = await client.post(f"{PREFIX}/quarantine/release", json=body, headers=PHARMACIST)
    assert r.status_code == 200 and r.json()["qty_quarantined"] == 0
    audit = (await audits())[-1]
    assert audit["action"] == "quarantine.released" and audit["after"]["reason"] == "sealed, undamaged"
    assert (await stock_of(client, headers=OWNER))[0]["qty_available"] == 12


async def test_internal_endpoints_need_the_service_token(client) -> None:
    para = await stocked()
    r = await client.post("/internal/v1/reservations", headers=OWNER, json={
        "ref_id": "x", "branch_id": str(PP1), "lines": [{"line_no": 1, "medicine_id": para["id"], "qty_base": 1}]})  # fmt: skip
    assert r.status_code == 401
