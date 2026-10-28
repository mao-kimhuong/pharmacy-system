import asyncio
from decimal import Decimal

from sqlalchemy import text

from inventory_service.db import db as inventory_db

from .conftest import (
    CASHIER,
    MANAGER,
    OWNER,
    PHARMACIST,
    PREFIX,
    add_product,
    audits,
    customer_balance,
    idem,
    inventory_stock,
    line,
    make_customer,
    outbox,
    pay,
    receive,
    sell,
    set_rate,
)


async def test_cash_sale_in_mixed_usd_and_khr_with_change_and_fefo(client) -> None:
    para = await add_product()
    amox = await add_product("AMOX500", prices=("0.25", "2.35", "22.00"))
    await receive(para, [("LATE", "2028-06-30", 100), ("EARLY", "2027-03-31", 15)])
    await receive(amox, [("K1", "2028-01-31", 50)])
    await set_rate(client, 4100)
    # 2 strips of Panadol (20 tablets: 15 from EARLY, 5 from LATE) + 1 strip of Amoxicillin = 4.15
    r = await sell(
        client, [line(para, "strip", 2), line(amox, "strip", 1)], [pay("2.00"), pay("10000", "KHR")]
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["number"] == "PP1-INV-2026-000001" and inv["status"] == "completed"
    assert (inv["total"], inv["khr_per_usd"], inv["total_khr"]) == ("4.15", 4100, 17000)
    # paid 2.00 + 10,000 riel (2.44) = 4.44 → change 0.29 = 1,189 riel → 1,200 riel handed over
    assert (inv["paid"], inv["change_usd"], inv["change_given_usd"], inv["change_given_khr"]) == (
        "4.44", "0.29", "0.00", 1200)  # fmt: skip
    assert inv["change_rounding_khr"] == "-11.00"
    batches = inv["lines"][0]["batches"]
    assert [(b["lot_no"], b["qty_base"]) for b in batches] == [("EARLY", 15), ("LATE", 5)]  # FEFO + split
    assert await inventory_stock(para) == {"EARLY": (0, 0, 0), "LATE": (95, 0, 0)}
    assert "cost" not in inv["lines"][0] and "margin" not in inv  # cashier: no cost
    event = next(p for t, p in await outbox() if t == "invoice.created")
    assert event["number"] == inv["number"] and event["branch"]["receipt_footer"] == "Thank you"
    assert event["lines"][0]["batches"][0]["cost_per_base"] == "0.0400"  # reports need cost
    assert [a["action"] for a in await audits()][-1] == "invoice.created"


async def test_same_idempotency_key_sells_once(client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 100)])
    key = idem()
    first = await sell(client, [line(para, "strip", 1)], [pay("0.90")], key=key)
    again = await sell(client, [line(para, "strip", 1)], [pay("0.90")], key=key)
    assert first.status_code == again.status_code == 201 and first.json()["id"] == again.json()["id"]
    assert await inventory_stock(para) == {"A": (90, 0, 0)}


async def test_two_tills_selling_the_last_unit_at_once(client) -> None:
    para = await add_product()
    await receive(para, [("LAST", "2028-01-31", 1)])
    a, b = await asyncio.gather(
        sell(client, [line(para, "tablet", 1)], [pay("0.10")]),
        sell(client, [line(para, "tablet", 1)], [pay("0.10")], headers=PHARMACIST),
    )
    assert sorted([a.status_code, b.status_code]) == [201, 409]
    failed = a if a.status_code == 409 else b
    assert failed.json()["code"] == "OUT_OF_STOCK"
    assert await inventory_stock(para) == {"LAST": (0, 0, 0)}  # never negative, nothing left reserved
    listed = (await client.get(f"{PREFIX}/invoices", headers=OWNER)).json()["items"]
    assert sorted(i["status"] for i in listed) == ["completed", "failed"]
    assert [i["number"] for i in listed if i["status"] == "failed"] == [None]  # failed sales take no number


async def test_out_of_stock_leaves_nothing_behind(client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 5)])
    r = await sell(client, [line(para, "strip", 1)], [pay("0.90")])
    assert r.status_code == 409 and r.json()["details"]["lines"][0]["available"] == 5
    assert await inventory_stock(para) == {"A": (5, 0, 0)}
    assert (await audits())[-1]["action"] == "invoice.failed"


async def test_credit_over_the_limit_is_refused_and_releases_the_stock(client, customers_client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 1000)])
    customer = await make_customer(customers_client, limit="20.00")
    r = await sell(
        client, [line(para, "box", 3)], [pay("24.00", method="credit")], customer_id=customer["id"]
    )
    assert r.status_code == 422 and r.json()["code"] == "CREDIT_LIMIT_EXCEEDED"
    assert await inventory_stock(para) == {"A": (1000, 0, 0)}  # no reservation left behind
    assert await customer_balance(customers_client, customer) == Decimal("0.00")
    r = await sell(
        client, [line(para, "box", 2)], [pay("16.00", method="credit")], customer_id=customer["id"]
    )
    assert r.status_code == 201 and r.json()["credit_amount"] == "16.00"
    assert await customer_balance(customers_client, customer) == Decimal("16.00")


async def test_credit_needs_a_customer(client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 100)])
    r = await sell(client, [line(para, "strip", 1)], [pay("0.90", method="credit")])
    assert r.status_code == 422 and r.json()["code"] == "CUSTOMER_REQUIRED"


async def test_rx_only_and_controlled_items_are_refused_with_clear_codes(client) -> None:
    amox = await add_product("AMOX500", rx=True)
    diaz = await add_product("DIAZ5", controlled="IV")
    for product, code, word in ((amox, "RX_REQUIRED", "S4"), (diaz, "CONTROLLED_NOT_AVAILABLE", "S5")):
        await receive(product, [("A", "2028-01-31", 100)])
        r = await sell(client, [line(product, "strip", 1)], [pay("0.90")])
        assert r.status_code == 422 and r.json()["code"] == code and word in r.json()["message"]
        assert await inventory_stock(product) == {"A": (100, 0, 0)}


async def test_short_payment_and_unknown_products(client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 100)])
    r = await sell(client, [line(para, "strip", 2)], [pay("1.79")])
    assert r.status_code == 422 and r.json()["code"] == "PAYMENT_SHORT"
    r = await sell(client, [line(para, "strip", 1)], [pay("1.00"), pay("4100", "KHR")])
    assert r.status_code == 422 and r.json()["code"] == "EXCHANGE_RATE_MISSING"


async def test_batch_override_is_for_pharmacists_with_a_reason(client) -> None:
    para = await add_product()
    await receive(para, [("EARLY", "2027-03-31", 50), ("LATE", "2028-06-30", 50)])
    await set_rate(client)
    async with inventory_db.engine.connect() as conn:
        late = str((await conn.execute(text("SELECT id FROM batches WHERE lot_no = 'LATE'"))).scalar_one())
    r = await sell(
        client, [line(para, "strip", 1, batch_id=late, override_reason="customer travels")], [pay("1")]
    )
    assert r.status_code == 403 and r.json()["code"] == "PHARMACIST_REQUIRED"
    r = await sell(client, [line(para, "strip", 1, batch_id=late)], [pay("1")], headers=PHARMACIST)
    assert r.status_code == 422
    r = await sell(client, [line(para, "strip", 1, batch_id=late, override_reason="customer travels")], [pay("1")],
                   headers=PHARMACIST)  # fmt: skip
    assert r.status_code == 201 and r.json()["lines"][0]["batches"][0]["lot_no"] == "LATE"
    assert (await audits())[-1]["after"]["batch_overrides"] == ["line 1: customer travels"]


async def test_exchange_rate_history_and_permission(client) -> None:
    from .conftest import PP1

    await set_rate(client, 4100)
    await set_rate(client, 4050)
    r = await client.put(f"{PREFIX}/exchange-rates/{PP1}", json={"khr_per_usd": 4000}, headers=CASHIER)
    assert r.status_code == 403
    history = (await client.get(f"{PREFIX}/exchange-rates/{PP1}", headers=CASHIER)).json()
    assert [(h["khr_per_usd"], h["previous"]) for h in history] == [(4050, 4100), (4100, None)]
    audit = (await audits())[-1]
    assert audit["before"] == {"khr_per_usd": 4100} and audit["after"] == {"khr_per_usd": 4050}


async def test_list_sale_filters_branches_and_cost(client) -> None:
    from .conftest import PP2, user

    para = await add_product()
    await receive(para, [("A", "2028-01-31", 100)])
    inv = (await sell(client, [line(para, "strip", 1)], [pay("0.90")])).json()
    owner = (await client.get(f"{PREFIX}/invoices/{inv['id']}", headers=OWNER)).json()
    assert owner["cost_total"] == "0.40" and owner["margin"] == "0.50"
    assert "cost_total" not in (await client.get(f"{PREFIX}/invoices/{inv['id']}", headers=CASHIER)).json()
    other = user("cashier", "pos.sell,sales.view", (PP2,))
    assert (await client.get(f"{PREFIX}/invoices/{inv['id']}", headers=other)).status_code == 404
    assert (await client.get(f"{PREFIX}/invoices", headers=other)).json()["total"] == 0
    found = await client.get(f"{PREFIX}/invoices", params={"number": "000001", "status": "completed",
                                                           "from": "2020-01-01"}, headers=MANAGER)  # fmt: skip
    assert found.json()["total"] == 1


async def test_a_credit_sales_debt_gets_the_invoice_number(client, customers_client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 1000)])
    customer = await make_customer(customers_client, limit="50.00")
    inv = (await sell(client, [line(para, "box", 1)], [pay("8.00", method="credit")],
                      customer_id=customer["id"])).json()  # fmt: skip
    unpaid = (
        await customers_client.get(f"/api/customers/v1/customers/{customer['id']}/unpaid", headers=OWNER)
    ).json()
    assert [(d["invoice_no"], d["due"]) for d in unpaid] == [(inv["number"], "8.00")]
