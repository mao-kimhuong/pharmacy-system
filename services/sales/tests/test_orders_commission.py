"""Sale orders (reservation, expiry, partial invoicing, deposits on cancel) and
commission (earned, overrides, reversal on return / cancel, locked periods)."""

from datetime import UTC, datetime

from sqlalchemy import select

from pharmacy_shared import clock
from sales_service.db import db
from sales_service.models import CommissionLine
from sales_service.services.orders import expire_reservations

from .conftest import (
    PP1,
    PREFIX,
    add_product,
    inventory_stock,
    line,
    make_customer,
    outbox,
    pay,
    real_clients,
    receive,
    sales_event,
    sell,
    set_rate,
    user,
)  # fmt: skip

SELLER = user("cashier", "pos.sell,sales.view,sales.orders,sales.return,commission.view_own")
MANAGER = user("branch_manager", "pos.sell,sales.view,sales.orders,sales.cancel,sales.cancel_any,sales.return,"
               "sales.exchange_rate,commission.manage,commission.view_own")  # fmt: skip
OWNER = user("owner", "*", ())


async def quote(client, customer: dict, lines: list[tuple[dict, str, int]]) -> dict:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/sale-orders", headers=SELLER, json={
        "branch_id": str(PP1), "customer_id": customer["id"],
        "lines": [{"medicine_id": p["id"], "pack_unit_id": p[pack], "qty": q} for p, pack, q in lines]})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def confirm(client, order: dict, **body) -> dict:  # noqa: ANN001, ANN003
    r = await client.post(f"{PREFIX}/sale-orders/{order['id']}/confirm", json=body,
                          headers={**SELLER, "Idempotency-Key": f"confirm-{order['id']}"})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


async def test_order_reserves_and_is_invoiced_in_parts_with_its_deposit(client, customers_client) -> None:
    para = await add_product("PARA500")
    await receive(para, [("A", "2028-01-31", 300)])
    await set_rate(client)
    customer = await make_customer(customers_client)
    o = await quote(client, customer, [(para, "box", 2)])  # 16.00
    assert o["number"] == "PP1-SO-2026-000001" and o["status"] == "quote" and o["total"] == "16.00"
    o = await confirm(client, o, reserve=True, reserve_days=3, deposit={"method": "cash", "amount": "5.00"})
    assert o["status"] == "ordered" and o["deposit_usd"] == "5.00"
    assert await inventory_stock(para) == {"A": (300, 200, 0)}  # reserved for the order
    # a walk-in sale cannot take the order's stock
    r = await sell(client, [line(para, "box", 2)], [pay("16.00")])
    assert r.status_code == 409 and r.json()["code"] == "OUT_OF_STOCK"
    r = await client.post(f"{PREFIX}/sale-orders/{o['id']}/invoice", headers={**SELLER, "Idempotency-Key": "so-inv-0001"},
                          json={"lines": [{"order_line_id": o["lines"][0]["id"], "qty": 1}],
                                "payments": [{"method": "deposit", "amount": "5.00", "deposit_id": o["deposit_id"]},
                                             {"method": "cash", "amount": "3.00"}]})  # fmt: skip
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["sale_order_id"] == o["id"] and inv["total"] == "8.00"
    assert await inventory_stock(para) == {"A": (200, 100, 0)}  # 1 box sold, 1 still reserved for the order
    o = (await client.get(f"{PREFIX}/sale-orders/{o['id']}", headers=SELLER)).json()
    assert o["status"] == "partly_fulfilled" and o["lines"][0]["qty_open"] == 1
    deposit = (await customers_client.get(f"/api/customers/v1/customers/{customer['id']}/deposits", headers=OWNER)).json()
    assert deposit[0]["remaining"] == "0.00"
    too_many = await client.post(f"{PREFIX}/sale-orders/{o['id']}/invoice",
                                 headers={**SELLER, "Idempotency-Key": "so-inv-0002"},
                                 json={"lines": [{"order_line_id": o["lines"][0]["id"], "qty": 2}],
                                       "payments": [{"method": "cash", "amount": "16.00"}]})  # fmt: skip
    assert too_many.status_code == 422
    # cancelling the invoice puts the box back on the order and the deposit back
    r = await client.post(f"{PREFIX}/invoices/{inv['id']}/cancel", json={"reason": "wrong order"},
                          headers={**MANAGER, "Idempotency-Key": "so-cancel-01"})  # fmt: skip
    assert r.status_code == 200, r.text
    o = (await client.get(f"{PREFIX}/sale-orders/{o['id']}", headers=SELLER)).json()
    assert o["status"] == "ordered" and o["lines"][0]["qty_open"] == 2
    deposit = (await customers_client.get(f"/api/customers/v1/customers/{customer['id']}/deposits", headers=OWNER)).json()
    assert deposit[0]["remaining"] == "5.00"


async def test_ready_for_pickup_says_what_is_left_to_pay(client, customers_client) -> None:
    """T2: sale_order.ready (the customer's Telegram): open lines at the order's prices minus the unused deposit."""
    para = await add_product("PARA500")
    await receive(para, [("A", "2028-01-31", 300)])
    customer = await make_customer(customers_client)
    q = await quote(client, customer, [(para, "box", 2)])  # 16.00
    r = await client.post(f"{PREFIX}/sale-orders/{q['id']}/ready", headers=SELLER)
    assert r.status_code == 409 and r.json()["code"] == "ORDER_STATE"  # a quote is not ready
    o = await confirm(client, q, deposit={"method": "cash", "amount": "5.00"})
    r = await client.post(f"{PREFIX}/sale-orders/{o['id']}/ready", headers=SELLER)
    assert r.status_code == 200 and r.json()["ready_at"]
    ready = [p for t, p in await outbox() if t == "sale_order.ready"]
    assert ready[-1]["remaining_usd"] == "11.00" and ready[-1]["number"] == o["number"]
    r = await client.post(f"{PREFIX}/sale-orders/{o['id']}/invoice", headers={**SELLER, "Idempotency-Key": "so-rdy-01"},
                          json={"lines": [{"order_line_id": o["lines"][0]["id"], "qty": 1}],
                                "payments": [{"method": "deposit", "amount": "5.00", "deposit_id": o["deposit_id"]},
                                             {"method": "cash", "amount": "3.00"}]})  # fmt: skip
    assert r.status_code == 201, r.text
    await client.post(f"{PREFIX}/sale-orders/{o['id']}/ready", headers=SELLER)
    assert [p for t, p in await outbox() if t == "sale_order.ready"][-1]["remaining_usd"] == "8.00"  # deposit used
    no_orders = user("cashier", "pos.sell")
    assert (await client.post(f"{PREFIX}/sale-orders/{o['id']}/ready", headers=no_orders)).status_code == 403


async def test_reservation_expires_and_releases_the_stock(client, customers_client, monkeypatch) -> None:
    para = await add_product("PARA500")
    await receive(para, [("A", "2028-01-31", 100)])
    customer = await make_customer(customers_client)
    o = await confirm(client, await quote(client, customer, [(para, "strip", 3)]), reserve=True, reserve_days=1)
    assert await inventory_stock(para) == {"A": (100, 30, 0)}
    async with db.sessionmaker() as s:
        assert await expire_reservations(s, real_clients()) == 0
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 10, 29, 3, 0, tzinfo=UTC))
    async with db.sessionmaker() as s:
        assert await expire_reservations(s, real_clients()) == 1
    assert await inventory_stock(para) == {"A": (100, 0, 0)}
    o = (await client.get(f"{PREFIX}/sale-orders/{o['id']}", headers=SELLER)).json()
    assert o["status"] == "ordered" and o["reservation_released_at"]


async def test_deposit_on_cancel_follows_the_branch_setting(client, customers_client) -> None:
    para = await add_product("PARA500")
    customer = await make_customer(customers_client)
    for setting, status in (("keep_as_credit", "credit"), ("refund", "refunded"), ("forfeit", "forfeited")):
        await sales_event("branch.settings_updated", {"branch_id": str(PP1), "order_deposit_on_cancel": setting})
        o = await confirm(client, await quote(client, customer, [(para, "strip", 1)]),
                          deposit={"method": "cash", "amount": "0.50"})  # fmt: skip
        who = SELLER if setting != "forfeit" else MANAGER
        if setting == "forfeit":
            r = await client.post(f"{PREFIX}/sale-orders/{o['id']}/cancel", json={"reason": "x"}, headers=SELLER)
            assert r.status_code == 403  # forfeiting a deposit: a manager or the owner
        r = await client.post(f"{PREFIX}/sale-orders/{o['id']}/cancel", json={"reason": "customer changed mind"},
                              headers=who)  # fmt: skip
        assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
        deposits = (await customers_client.get(f"/api/customers/v1/customers/{customer['id']}/deposits",
                                               headers=OWNER)).json()  # fmt: skip
        assert deposits[-1]["status"] == status


async def rule(client, **body) -> dict:  # noqa: ANN001, ANN003
    r = await client.post(f"{PREFIX}/commission/rules", headers=MANAGER, json={
        "name": "Rule", "branch_id": str(PP1), "starts_on": "2026-10-01", **body})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def lines_of(invoice_id: str) -> list[tuple[str, str]]:
    async with db.sessionmaker() as s:
        rows = (await s.execute(select(CommissionLine).where(CommissionLine.invoice_id == invoice_id)
                                .order_by(CommissionLine.created_at))).scalars()  # fmt: skip
        return [(r.source.split(":")[0], str(r.amount)) for r in rows]


async def test_commission_earned_overridden_and_reversed(client) -> None:
    para, ors = await add_product("PARA500"), await add_product("ORS")
    await receive(para, [("A", "2028-01-31", 500)])
    await receive(ors, [("O", "2028-01-31", 500)])
    await rule(client, kind="percent", value="5", scope="all")
    await rule(client, kind="per_unit", value="0.01", scope="medicine", target_id=ors["id"])
    await rule(client, kind="percent", value="10", scope="medicine", target_id=para["id"], staff_id=SELLER["X-User-Id"])
    r = await sell(client, [line(para, "box", 1), line(ors, "strip", 2)], [pay("9.80")], SELLER)
    inv = r.json()
    # PARA: the seller's override 10 % of 8.00; ORS: 20 tablets × 0.01
    assert sorted(await lines_of(inv["id"])) == [("sale", "0.20"), ("sale", "0.80")]
    r = await client.post(f"{PREFIX}/invoices/{inv['id']}/returns", headers={**SELLER, "Idempotency-Key": "com-ret-1"},
                          json={"lines": [{"invoice_line_id": inv["lines"][1]["id"], "qty": 1}],
                                "refund_method": "cash", "reason": "x"})  # fmt: skip
    assert r.status_code == 201
    assert ("return", "-0.10") in await lines_of(inv["id"])
    sent = [(p["source"].split(":")[0], p["amount"], p["month"]) for t, p in await outbox() if t == "commission.recorded"]
    assert sorted(sent) == [("return", "-0.10", "2026-10-01"), ("sale", "0.20", "2026-10-01"), ("sale", "0.80", "2026-10-01")]
    # someone else selling PARA: the general 5 %
    other = user("cashier", "pos.sell,sales.view")
    r = await sell(client, [line(para, "box", 1)], [pay("8.00")], other)
    assert await lines_of(r.json()["id"]) == [("sale", "0.40")]


async def test_closed_period_is_locked_and_report_scopes(client, monkeypatch) -> None:
    para = await add_product("PARA500")
    await receive(para, [("A", "2028-01-31", 500)])
    await rule(client, kind="percent", value="10", scope="all")
    inv = (await sell(client, [line(para, "box", 1)], [pay("8.00")], SELLER)).json()
    r = await client.post(f"{PREFIX}/commission/periods/{PP1}/2026-10-01/close", headers=MANAGER)
    assert r.status_code == 200 and r.json()["status"] == "closed"
    again = await client.post(f"{PREFIX}/commission/periods/{PP1}/2026-10-01/close", headers=MANAGER)
    assert again.status_code == 409 and again.json()["code"] == "PERIOD_LOCKED"
    r = await client.post(f"{PREFIX}/invoices/{inv['id']}/cancel", json={"reason": "x"},
                          headers={**MANAGER, "Idempotency-Key": "com-cancel-1"})  # fmt: skip
    assert r.status_code == 200
    october = (await client.get(f"{PREFIX}/commission/report", params={"branch_id": str(PP1), "month": "2026-10-01"},
                                headers=MANAGER)).json()  # fmt: skip
    november = (await client.get(f"{PREFIX}/commission/report", params={"branch_id": str(PP1), "month": "2026-11-01"},
                                 headers=MANAGER)).json()  # fmt: skip
    assert (october["status"], october["total"]) == ("closed", "0.80")  # unchanged
    assert november["total"] == "-0.80"  # the reversal went to the next open period
    mine = (await client.get(f"{PREFIX}/commission/report", params={"branch_id": str(PP1), "month": "2026-10-01"},
                             headers=SELLER)).json()  # fmt: skip
    assert [s["staff_id"] for s in mine["staff"]] == [SELLER["X-User-Id"]]
    other = await client.get(f"{PREFIX}/commission/report/{MANAGER['X-User-Id']}",
                             params={"branch_id": str(PP1), "month": "2026-10-01"}, headers=SELLER)  # fmt: skip
    assert other.status_code == 403
    drill = (await client.get(f"{PREFIX}/commission/report/{SELLER['X-User-Id']}",
                              params={"branch_id": str(PP1), "month": "2026-10-01"}, headers=SELLER)).json()  # fmt: skip
    assert [(x["invoice_number"], x["amount"]) for x in drill] == [(inv["number"], "0.80")]
