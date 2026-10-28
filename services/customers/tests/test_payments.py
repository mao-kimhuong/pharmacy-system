from uuid import uuid4

from .conftest import CASHIER, OWNER, PP1, PREFIX, audits, charge, create_customer, get, idem


async def pay(client, c: dict, amount: str, headers=None, method: str = "cash"):
    return await client.post(f"{PREFIX}/customer-payments", headers={**(headers or OWNER), **idem()}, json={
        "customer_id": c["id"], "branch_id": str(PP1), "method": method, "amount": amount})  # fmt: skip


async def test_payment_goes_to_the_oldest_invoice_first(client) -> None:
    c = await create_customer(client)
    await charge(client, c, "30.00", uuid4(), "PP1-INV-2026-000001")
    await charge(client, c, "20.00", uuid4(), "PP1-INV-2026-000002")
    r = await pay(client, c, "40.00", method="KHQR", headers=CASHIER)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["number"] == "PP1-CP-2026-000001"
    assert [(a["invoice_no"], a["amount"]) for a in p["allocations"]] == [
        ("PP1-INV-2026-000001", "30.00"), ("PP1-INV-2026-000002", "10.00")]  # fmt: skip
    assert (await get(client, c))["balance"] == "10.00"
    [left] = (await client.get(f"{PREFIX}/customers/{c['id']}/unpaid", headers=OWNER)).json()
    assert (left["invoice_no"], left["due"]) == ("PP1-INV-2026-000002", "10.00")
    assert (await audits())[-1]["action"] == "customer_payment.created"


async def test_paying_more_than_owed_is_refused(client) -> None:
    c = await create_customer(client)
    await charge(client, c, "30.00")
    r = await pay(client, c, "30.01")
    assert r.status_code == 422 and r.json()["code"] == "CUSTOMER_OVERPAYMENT"


async def test_cancel_puts_the_debt_back(client) -> None:
    c = await create_customer(client)
    await charge(client, c, "30.00")
    p = (await pay(client, c, "30.00")).json()
    r = await client.post(
        f"{PREFIX}/customer-payments/{p['id']}/cancel", json={"reason": "bounced"}, headers=OWNER
    )
    assert r.json()["status"] == "cancelled"
    assert (await get(client, c))["balance"] == "30.00"
    r = await client.post(f"{PREFIX}/customer-payments/{p['id']}/cancel", json={"reason": "x"}, headers=OWNER)
    assert r.status_code == 409


async def test_statement_is_the_ledger_with_a_running_balance(client) -> None:
    c = await create_customer(client)
    await charge(client, c, "30.00", uuid4(), "PP1-INV-2026-000001")
    await pay(client, c, "12.50")
    st = (await client.get(f"{PREFIX}/customers/{c['id']}/statement", headers=OWNER)).json()
    assert [(e["kind"], e["debit"], e["credit"], e["balance"]) for e in st["entries"]] == [
        ("charge", "30.00", "0.00", "30.00"), ("payment", "0.00", "12.50", "17.50")]  # fmt: skip
    assert st["closing_balance"] == st["balance"] == "17.50"
