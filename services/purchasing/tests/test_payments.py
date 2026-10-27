from .conftest import (
    CASHIER,
    MANAGER,
    OWNER,
    PP1,
    PREFIX,
    add_product,
    audits,
    create_po,
    create_supplier,
    idem,
    receive,
)


async def two_bills(client) -> tuple[dict, list[dict]]:
    """Bills of 42.50 then 21.25 for one supplier at PP1."""
    s = await create_supplier(client)
    para = await add_product("PARA500")
    po = await create_po(client, s, [(para, "box", 15, "4.25")], send=True)
    bills = []
    for qty in (10, 5):
        r = await receive(client, po, [{"po_line_id": po["lines"][0]["id"], "lot_no": "A1",
                                        "expiry_date": "2028-03-31", "qty": qty}])  # fmt: skip
        bills.append(r.json())
    return s, bills


async def pay(client, s: dict, amount: str, headers=None, method: str = "cash"):
    return await client.post(f"{PREFIX}/supplier-payments", headers={**(headers or OWNER), **idem()}, json={
        "supplier_id": s["id"], "branch_id": str(PP1), "method": method, "amount": amount})  # fmt: skip


async def balance(client, s: dict) -> dict:
    return (await client.get(f"{PREFIX}/suppliers/{s['id']}/balance", headers=OWNER)).json()


async def test_payment_goes_to_the_oldest_bill_first_and_brings_the_balance_to_zero(client) -> None:
    s, bills = await two_bills(client)
    assert (await balance(client, s))["owed"] == "63.75"
    r = await pay(client, s, "50.00", method="ABA")
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["number"] == "PP1-SP-2026-000001"
    assert [(a["receipt_id"], a["amount"]) for a in p["allocations"]] == [
        (bills[0]["id"], "42.50"), (bills[1]["id"], "7.50"),
    ]  # fmt: skip
    assert (await balance(client, s))["owed"] == "13.75"
    await pay(client, s, "13.75")
    assert (await balance(client, s))["owed"] == "0.00"
    listed = (await client.get(f"{PREFIX}/receipts?supplier_id={s['id']}", headers=OWNER)).json()["items"]
    assert {r["status"] for r in listed} == {"paid"}
    assert [a["action"] for a in await audits()][-1] == "supplier_payment.created"


async def test_paying_more_than_owed_is_refused(client) -> None:
    s, _ = await two_bills(client)
    r = await pay(client, s, "63.76")
    assert r.status_code == 422 and r.json()["code"] == "SUPPLIER_OVERPAYMENT"
    assert r.json()["details"]["owed"] == "63.75"
    s2 = await create_supplier(client, code="NEW")
    assert (await pay(client, s2, "1.00")).json()["code"] == "SUPPLIER_OVERPAYMENT"


async def test_cancel_reverses_the_allocations(client) -> None:
    s, _ = await two_bills(client)
    p = (await pay(client, s, "50.00")).json()
    r = await client.post(f"{PREFIX}/supplier-payments/{p['id']}/cancel", json={"reason": "wrong amount"},
                          headers=OWNER)  # fmt: skip
    assert r.json()["status"] == "cancelled" and all(a["reversed"] for a in r.json()["allocations"])
    assert (await balance(client, s))["owed"] == "63.75"
    r = await client.post(
        f"{PREFIX}/supplier-payments/{p['id']}/cancel", json={"reason": "again"}, headers=OWNER
    )
    assert r.status_code == 409
    assert (await audits())[-1]["after"]["reason"] == "wrong amount"


async def test_statement_has_a_running_balance(client) -> None:
    s, bills = await two_bills(client)
    await pay(client, s, "50.00")
    st = (await client.get(f"{PREFIX}/suppliers/{s['id']}/statement", headers=OWNER)).json()
    assert [(e["kind"], e["debit"], e["credit"], e["balance"]) for e in st["entries"]] == [
        ("receipt", "42.50", "0.00", "42.50"), ("receipt", "21.25", "0.00", "63.75"),
        ("payment", "0.00", "50.00", "13.75"),
    ]  # fmt: skip
    assert st["closing_balance"] == "13.75" and st["opening_balance"] == "0.00"
    later = (
        await client.get(f"{PREFIX}/suppliers/{s['id']}/statement?from=2026-10-28", headers=OWNER)
    ).json()
    assert later["entries"] == [] and later["opening_balance"] == "13.75"


async def test_only_payers_pay_and_see_balances(client) -> None:
    s, _ = await two_bills(client)
    assert (await pay(client, s, "1.00", headers=CASHIER)).status_code == 403
    r = await client.get(f"{PREFIX}/suppliers/{s['id']}/balance", headers=CASHIER)
    assert r.status_code == 403
    assert (await pay(client, s, "1.00", headers=MANAGER)).status_code == 201
