"""Sale-order deposits: taken once, used by invoices (never more than is left),
given back when an invoice is undone, settled when the order ends."""

from uuid import uuid4

from .conftest import INTERNAL, OWNER, PP1, PREFIX, create_customer


async def take(client, customer: dict, amount: str = "10.00", ref: str | None = None) -> dict:  # noqa: ANN001
    r = await client.post("/internal/v1/deposits", headers=INTERNAL, json={
        "ref": ref or str(uuid4()), "document_no": "PP1-SO-2026-000001", "customer_id": customer["id"],
        "branch_id": str(PP1), "method": "cash", "amount": amount})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


async def test_take_once_use_and_give_back(client) -> None:
    c = await create_customer(client)
    ref = str(uuid4())
    d = await take(client, c, "10.00", ref)
    assert (await take(client, c, "10.00", ref))["deposit_id"] == d["deposit_id"]  # retried: once
    inv = str(uuid4())
    url = f"/internal/v1/deposits/{d['deposit_id']}"
    r = await client.post(f"{url}/use", headers=INTERNAL, json={"invoice_id": inv, "amount": "6.00"})
    assert r.json()["remaining"] == "4.00"
    again = await client.post(f"{url}/use", headers=INTERNAL, json={"invoice_id": inv, "amount": "6.00"})
    assert again.json()["remaining"] == "4.00"  # same invoice: once
    over = await client.post(f"{url}/use", headers=INTERNAL, json={"invoice_id": str(uuid4()), "amount": "5.00"})
    assert over.status_code == 409 and over.json()["code"] == "DEPOSIT_EXCEEDED"
    r = await client.post(f"{url}/unuse", headers=INTERNAL, json={"invoice_id": inv})
    assert r.json()["remaining"] == "10.00"
    r = await client.post(f"{url}/unuse", headers=INTERNAL, json={"invoice_id": inv})
    assert r.json()["remaining"] == "10.00"  # nothing more to give back


async def test_settle_keep_as_credit_refund_forfeit(client) -> None:
    c = await create_customer(client)
    for action, status in (("keep_as_credit", "credit"), ("refund", "refunded"), ("forfeit", "forfeited")):
        d = await take(client, c, "8.00")
        await client.post(f"/internal/v1/deposits/{d['deposit_id']}/use", headers=INTERNAL,
                          json={"invoice_id": str(uuid4()), "amount": "3.00"})  # fmt: skip
        r = await client.post(f"/internal/v1/deposits/{d['deposit_id']}/settle", headers=INTERNAL,
                              json={"action": action, "reason": "order cancelled"})  # fmt: skip
        assert r.json()["status"] == status
        assert r.json()["remaining"] == ("5.00" if action == "keep_as_credit" else "0.00")
    deposits = (await client.get(f"{PREFIX}/customers/{c['id']}/deposits", headers=OWNER)).json()
    credit = next(x for x in deposits if x["status"] == "credit")
    # credit kept from a cancelled order pays a later sale
    r = await client.post(f"/internal/v1/deposits/{credit['deposit_id']}/use", headers=INTERNAL,
                          json={"invoice_id": str(uuid4()), "amount": "5.00", "customer_id": c["id"]})  # fmt: skip
    assert r.json()["remaining"] == "0.00"
    # the debt balance is not touched by deposits
    assert (await client.get(f"{PREFIX}/customers/{c['id']}", headers=OWNER)).json()["balance"] == "0.00"
