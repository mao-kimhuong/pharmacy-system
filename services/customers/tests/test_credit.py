import asyncio
from uuid import uuid4

from .conftest import (
    CASHIER,
    INTERNAL,
    OWNER,
    PP1,
    PREFIX,
    audits,
    charge,
    create_customer,
    get,
    idem,
    reverse,
)


async def test_charge_within_the_limit_and_refuse_above_it(client) -> None:
    c = await create_customer(client, limit="100.00")
    r = await charge(client, c, "60.00")
    assert r.status_code == 200 and r.json()["balance_after"] == "60.00"
    r = await charge(client, c, "40.01")
    assert r.status_code == 422 and r.json()["code"] == "CREDIT_LIMIT_EXCEEDED"
    assert r.json()["details"]["available"] == "40.00"
    assert (await get(client, c))["balance"] == "60.00"
    assert (await charge(client, c, "40.00")).status_code == 200
    assert [a["action"] for a in await audits()][-1] == "credit.charged"


async def test_the_same_invoice_is_charged_once(client) -> None:
    c = await create_customer(client)
    invoice = uuid4()
    first = await charge(client, c, "30.00", invoice)
    again = await charge(client, c, "30.00", invoice)
    assert first.json() == again.json()
    assert (await get(client, c))["balance"] == "30.00"


async def test_two_tills_cannot_both_use_the_last_credit(client) -> None:
    c = await create_customer(client, limit="100.00")
    results = await asyncio.gather(*[charge(client, c, "60.00") for _ in range(4)])
    assert sorted(r.status_code for r in results) == [200, 422, 422, 422]
    assert (await get(client, c))["balance"] == "60.00"


async def test_internal_calls_need_the_service_token(client) -> None:
    c = await create_customer(client)
    body = {"invoice_id": str(uuid4()), "customer_id": c["id"], "branch_id": str(PP1), "amount": "1.00"}
    r = await client.post(
        "/internal/v1/credit/charge", json=body, headers={**INTERNAL, "X-Service-Token": "nope"}
    )
    assert r.status_code == 401
    r = await client.post("/internal/v1/credit/charge", json=body, headers=OWNER)  # a user, not a service
    assert r.status_code == 401


async def test_deactivated_customer_gets_no_credit(client) -> None:
    c = await create_customer(client)
    await client.post(f"{PREFIX}/customers/{c['id']}/deactivate", json={"reason": "x"}, headers=OWNER)
    assert (await charge(client, c, "1.00")).json()["code"] == "CUSTOMER_REQUIRED"


async def test_cancel_reverses_the_whole_charge_once(client) -> None:
    c = await create_customer(client)
    invoice = uuid4()
    await charge(client, c, "30.00", invoice)
    r = await reverse(client, c, invoice, reason="customer changed mind")
    assert r.json()["amount"] == "-30.00" and r.json()["balance_after"] == "0.00"
    assert (await reverse(client, c, invoice)).json()["amount"] == "-30.00"  # again: same entry
    assert (await get(client, c))["balance"] == "0.00"
    unpaid = (await client.get(f"{PREFIX}/customers/{c['id']}/unpaid", headers=OWNER)).json()
    assert unpaid == []
    assert (await audits())[-1]["after"]["reason"] == "customer changed mind"


async def test_return_credit_note_lowers_the_debt_then_cancel_takes_the_rest(client) -> None:
    c = await create_customer(client)
    invoice = uuid4()
    await charge(client, c, "30.00", invoice)
    ret = str(uuid4())
    r = await reverse(client, c, invoice, kind="return", ref_id=ret, amount="10.00", reason="1 box back")
    assert r.json()["balance_after"] == "20.00"
    assert (await reverse(client, c, invoice, kind="return", ref_id=ret, amount="10.00")).json()[
        "balance_after"
    ] == "20.00"
    [debt] = (await client.get(f"{PREFIX}/customers/{c['id']}/unpaid", headers=OWNER)).json()
    assert debt["due"] == "20.00"
    assert (await reverse(client, c, invoice)).json()["amount"] == "-20.00"
    assert (await get(client, c))["balance"] == "0.00"


async def test_cancelling_a_partly_paid_invoice_leaves_credit_on_the_account(client) -> None:
    c = await create_customer(client)
    invoice = uuid4()
    await charge(client, c, "30.00", invoice)
    r = await client.post(f"{PREFIX}/customer-payments", headers={**OWNER, **idem()}, json={
        "customer_id": c["id"], "branch_id": str(PP1), "method": "cash", "amount": "10.00"})  # fmt: skip
    assert r.status_code == 201
    await reverse(client, c, invoice)
    assert (await get(client, c))["balance"] == "-10.00"  # the pharmacy owes the customer 10


async def test_cashier_cannot_reach_internal_endpoints_through_its_token(client) -> None:
    c = await create_customer(client)
    r = await client.post("/internal/v1/credit/reverse", headers=CASHIER, json={
        "invoice_id": str(uuid4()), "customer_id": c["id"], "kind": "cancel"})  # fmt: skip
    assert r.status_code == 401


async def test_the_sales_number_reaches_the_debt_directly_or_by_event(client) -> None:
    from customers_service.db import db
    from customers_service.models import ProcessedMessage
    from customers_service.services.events import handle_event
    from pharmacy_shared.consumer import process_message

    c = await create_customer(client)
    first, second = uuid4(), uuid4()
    await charge(client, c, "10.00", first, invoice_no="")
    await charge(client, c, "5.00", second, invoice_no="")
    r = await client.post("/internal/v1/credit/number", headers=INTERNAL,
                          json={"invoice_id": str(first), "invoice_no": "PP1-INV-2026-000007"})  # fmt: skip
    assert r.json() == {"updated": True}
    await process_message(db, ProcessedMessage, handle_event, uuid4(), "invoice.created",
                          {"invoice_id": str(second), "number": "PP1-INV-2026-000008", "credit_amount": "5.00"})  # fmt: skip
    unpaid = (await client.get(f"{PREFIX}/customers/{c['id']}/unpaid", headers=OWNER)).json()
    assert [d["invoice_no"] for d in unpaid] == ["PP1-INV-2026-000007", "PP1-INV-2026-000008"]
    st = (await client.get(f"{PREFIX}/customers/{c['id']}/statement", headers=OWNER)).json()
    assert [e["document_no"] for e in st["entries"]] == ["PP1-INV-2026-000007", "PP1-INV-2026-000008"]


async def test_credit_status_and_statement_for_other_services(client) -> None:
    c = await create_customer(client, limit="100.00")
    await charge(client, c, "60.00")
    r = await client.get(f"/internal/v1/customers/{c['id']}/credit", headers=INTERNAL)
    assert r.status_code == 200 and (r.json()["balance"], r.json()["available"]) == ("60.00", "40.00")
    assert (await client.get(f"/internal/v1/customers/{c['id']}/credit")).status_code == 401
    st = await client.get(f"/internal/v1/customers/{c['id']}/statement", headers=INTERNAL)
    assert st.status_code == 200 and st.json()["closing_balance"] == "60.00"


async def test_overdue_follows_the_customers_credit_terms(client) -> None:
    """T2: a credit invoice is due credit_terms_days after the sale (Telegram balance reminders)."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    from customers_service.db import db
    from customers_service.models import CustomerDebt

    c = await create_customer(client, credit_terms_days=30, preferred_lang="en")
    assert (c["credit_terms_days"], c["preferred_lang"]) == (30, "en")
    old, new = uuid4(), uuid4()
    await charge(client, c, "25.00", old)
    await charge(client, c, "10.00", new)
    async with db.sessionmaker() as s:  # sold on 20 Sep (due 20 Oct) and 20 Oct (due 19 Nov); today is 27 Oct
        for inv, day in ((old, 20), (new, None)):
            await s.execute(update(CustomerDebt).where(CustomerDebt.invoice_id == inv).values(
                created_at=datetime(2026, 9 if day else 10, 20, 3, tzinfo=UTC)))  # fmt: skip
        await s.commit()
    r = (await client.get(f"/internal/v1/customers/{c['id']}/credit", headers=INTERNAL)).json()
    assert (r["balance"], r["overdue"], r["oldest_due_on"]) == ("35.00", "25.00", "2026-10-20")
    await client.patch(f"{PREFIX}/customers/{c['id']}", json={"credit_terms_days": 60}, headers=OWNER)
    r = (await client.get(f"/internal/v1/customers/{c['id']}/credit", headers=INTERNAL)).json()
    assert (r["overdue"], r["oldest_due_on"]) == ("0.00", "2026-11-19")
    assert (await client.post(f"{PREFIX}/customers", json={"phone": "098 765 432", "name": "X", "preferred_lang": "fr"},
                              headers=OWNER)).status_code == 422  # fmt: skip
