from decimal import Decimal

from sqlalchemy import text

from pharmacy_shared.errors import AppError, ErrorCode
from sales_service.db import db
from sales_service.main import app
from sales_service.services.clients import get_clients
from sales_service.services.recovery import recover

from .conftest import (
    CASHIER,
    MANAGER,
    PHARMACIST,
    PP1,
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
    real_clients,
    receive,
    sales_event,
    sell,
)


async def sold(client, headers=None):
    para = await add_product()
    await receive(para, [("EARLY", "2027-03-31", 15), ("LATE", "2028-06-30", 100)])
    r = await sell(client, [line(para, "strip", 2)], [pay("1.80")], headers=headers)
    assert r.status_code == 201, r.text
    return para, r.json()


async def cancel(client, inv: dict, headers, reason: str = "wrong item"):
    return await client.post(
        f"{PREFIX}/invoices/{inv['id']}/cancel", json={"reason": reason}, headers=headers
    )


async def make_yesterday(inv: dict) -> None:
    async with db.engine.begin() as conn:
        await conn.execute(text("UPDATE invoices SET completed_at = completed_at - interval '1 day' WHERE id = :i"),
                           {"i": inv["id"]})  # fmt: skip


# ---------------------------------------------------------------- cancel


async def test_cashier_cannot_cancel(client) -> None:
    _, inv = await sold(client)
    r = await cancel(client, inv, CASHIER)
    assert r.status_code == 403


async def test_cancel_returns_stock_to_the_same_batches(client) -> None:
    para, inv = await sold(client)
    assert await inventory_stock(para) == {"EARLY": (0, 0, 0), "LATE": (95, 0, 0)}
    r = await cancel(client, inv, PHARMACIST)
    assert (
        r.status_code == 200
        and r.json()["status"] == "cancelled"
        and r.json()["cancel_reason"] == "wrong item"
    )
    assert await inventory_stock(para) == {"EARLY": (15, 0, 0), "LATE": (100, 0, 0)}
    assert (await cancel(client, inv, PHARMACIST)).status_code == 200  # again: no change
    assert await inventory_stock(para) == {"EARLY": (15, 0, 0), "LATE": (100, 0, 0)}
    assert [t for t, _ in await outbox()].count("invoice.cancelled") == 1
    assert (await audits())[-1]["after"]["reason"] == "wrong item"


async def test_cancel_needs_a_reason(client) -> None:
    _, inv = await sold(client)
    r = await client.post(f"{PREFIX}/invoices/{inv['id']}/cancel", json={}, headers=PHARMACIST)
    assert r.status_code == 422


async def test_pharmacist_cancels_only_todays_invoices(client) -> None:
    _, inv = await sold(client)
    await make_yesterday(inv)
    r = await cancel(client, inv, PHARMACIST)
    assert r.status_code == 403 and r.json()["details"]["permission"] == "sales.cancel_any"
    r = await cancel(client, inv, MANAGER)  # has sales.cancel_any
    assert r.status_code == 200


async def test_cancel_reverses_credit(client, customers_client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 1000)])
    customer = await make_customer(customers_client, limit="50.00")
    inv = (await sell(client, [line(para, "box", 2)], [pay("16.00", method="credit")],
                      customer_id=customer["id"])).json()  # fmt: skip
    assert await customer_balance(customers_client, customer) == Decimal("16.00")
    assert (await cancel(client, inv, MANAGER)).status_code == 200
    assert await customer_balance(customers_client, customer) == Decimal("0.00")
    assert await inventory_stock(para) == {"A": (1000, 0, 0)}


# ---------------------------------------------------------------- returns


async def ret(client, inv: dict, qty: int, headers=None, **extra):
    body = {"lines": [{"invoice_line_id": inv["lines"][0]["id"], "qty": qty, **extra.pop("line", {})}],
            "refund_method": "cash", "reason": "not needed", **extra}  # fmt: skip
    return await client.post(f"{PREFIX}/invoices/{inv['id']}/returns", json=body,
                             headers={**(headers or PHARMACIST), **idem()})  # fmt: skip


async def test_partial_return_goes_back_to_the_last_used_batch(client) -> None:
    para, inv = await sold(client)  # 15 from EARLY + 5 from LATE
    r = await ret(client, inv, 1)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["number"] == "PP1-RT-2026-000001" and body["refund_usd"] == "0.90"
    # 10 tablets back: the 5 from LATE (used last), then 5 to EARLY
    assert await inventory_stock(para) == {"EARLY": (5, 0, 0), "LATE": (100, 0, 0)}
    r = await ret(client, inv, 2)
    assert r.status_code == 422 and r.json()["code"] == "RETURN_EXCEEDS_SOLD"
    assert (await ret(client, inv, 1)).status_code == 201  # the second strip
    assert await inventory_stock(para) == {"EARLY": (15, 0, 0), "LATE": (100, 0, 0)}
    detail = (await client.get(f"{PREFIX}/invoices/{inv['id']}", headers=PHARMACIST)).json()
    assert detail["returned_total"] == "1.80" and detail["lines"][0]["returned_qty_base"] == 20
    assert (await cancel(client, inv, MANAGER)).json()["code"] == "INVOICE_STATE"  # returned: no cancel
    assert [t for t, _ in await outbox()].count("invoice.returned") == 2


async def test_cashier_cannot_return(client) -> None:
    _, inv = await sold(client)
    assert (await ret(client, inv, 1, headers=CASHIER)).status_code == 403


async def test_opened_packs_only_where_the_branch_allows(client) -> None:
    _, inv = await sold(client)
    r = await ret(client, inv, 1, line={"opened": True})
    assert r.status_code == 422 and r.json()["code"] == "OPENED_PACK_RETURN"
    await sales_event("branch.settings_updated", {"branch_id": str(PP1), "receipt_header": "", "receipt_footer": "",
                                                  "allow_opened_pack_returns": True})  # fmt: skip
    assert (await ret(client, inv, 1, line={"opened": True})).status_code == 201


async def test_return_to_quarantine(client) -> None:
    para, inv = await sold(client)
    assert (await ret(client, inv, 1, to="quarantine")).status_code == 201
    assert await inventory_stock(para) == {"EARLY": (5, 0, 5), "LATE": (100, 0, 5)}


async def test_credit_sale_is_refunded_as_a_credit_note(client, customers_client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 1000)])
    customer = await make_customer(customers_client, limit="50.00")
    inv = (await sell(client, [line(para, "box", 2)], [pay("16.00", method="credit")],
                      customer_id=customer["id"])).json()  # fmt: skip
    r = await ret(client, inv, 1)
    assert r.status_code == 422  # not cash
    r = await ret(client, inv, 1, refund_method="credit_note")
    assert r.status_code == 201
    assert await customer_balance(customers_client, customer) == Decimal("8.00")


# ---------------------------------------------------------------- compensations and recovery


class Failing:
    """Wraps a real client; fails the calls whose path contains `fail_on`."""

    def __init__(self, real, fail_on: str, code: ErrorCode = ErrorCode.TEMPORARILY_UNAVAILABLE) -> None:
        self.real, self.fail_on, self.code, self.calls = real, fail_on, code, []

    async def post(self, path: str, body=None, **kw):  # noqa: ANN001, ANN003
        self.calls.append(path)
        if self.fail_on in path:
            raise AppError(self.code, f"{path} failed", status_code=503)
        return await self.real.post(path, body, **kw)


async def test_a_failing_confirm_undoes_the_reservation_and_the_charge(client, customers_client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 1000)])
    customer = await make_customer(customers_client, limit="50.00")
    real = real_clients()
    inventory = Failing(real.inventory, "/confirm")
    app.dependency_overrides[get_clients] = lambda: real_clients(inventory=inventory)
    r = await sell(client, [line(para, "box", 1)], [pay("8.00", method="credit")], customer_id=customer["id"])
    assert r.status_code == 503
    assert await inventory_stock(para) == {"A": (1000, 0, 0)}
    assert await customer_balance(customers_client, customer) == Decimal("0.00")
    [inv] = (await client.get(f"{PREFIX}/invoices", headers=MANAGER)).json()["items"]
    assert inv["status"] == "failed" and inv["number"] is None


async def test_a_compensation_that_cannot_run_is_finished_by_the_recovery_task(client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 1000)])
    real = real_clients()
    # confirm fails AND the release cannot reach inventory either
    app.dependency_overrides[get_clients] = lambda: real_clients(inventory=Failing(real.inventory, "/re"))
    original = Failing.post

    async def confirm_and_release_fail(self, path, body=None, **kw):  # noqa: ANN001, ANN003
        if "/reservations" == path:
            return await self.real.post(path, body, **kw)
        return await original(self, path, body, **kw)

    Failing.post = confirm_and_release_fail
    try:
        r = await sell(client, [line(para, "box", 1)], [pay("8.00")])
    finally:
        Failing.post = original
    assert r.status_code == 503
    [inv] = (await client.get(f"{PREFIX}/invoices", headers=MANAGER)).json()["items"]
    assert inv["status"] == "needs_attention"
    assert await inventory_stock(para) == {"A": (1000, 100, 0)}  # still held
    result = await recover(db, real_clients(), pending_timeout_seconds=0)
    assert result["failed"] == 1
    assert await inventory_stock(para) == {"A": (1000, 0, 0)}
    inv = (await client.get(f"{PREFIX}/invoices/{inv['id']}", headers=MANAGER)).json()
    assert inv["status"] == "failed"


async def test_recovery_undoes_a_sale_interrupted_by_a_crash(client) -> None:
    para = await add_product()
    await receive(para, [("A", "2028-01-31", 1000)])
    real = real_clients()

    class CrashAfterReserve(Failing):
        async def post(self, path, body=None, **kw):  # noqa: ANN001, ANN003
            result = await self.real.post(path, body, **kw)
            if path == "/reservations":
                raise AppError(ErrorCode.TEMPORARILY_UNAVAILABLE, "lost the answer", status_code=503)
            return result

    app.dependency_overrides[get_clients] = lambda: real_clients(
        inventory=CrashAfterReserve(real.inventory, "")
    )
    r = await sell(client, [line(para, "box", 1)], [pay("8.00")])
    assert r.status_code == 503  # the answer was lost, but the saga released by invoice
    assert await inventory_stock(para) == {"A": (1000, 0, 0)}
