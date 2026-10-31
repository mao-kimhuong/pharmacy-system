"""Report totals match the source: real sales through the saga (real inventory +
customers), then every event the sales and inventory services wrote goes through
the reports service's handlers. The reports agree with the sales database."""

import json
from decimal import Decimal

import reports_service.config as reports_config  # noqa: I001 – set the database before the reports db is built
from pharmacy_shared.testing import test_database_url as database_url

reports_config.get_settings().database_url = database_url("test_sales_reports")

import pytest  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from pharmacy_shared.consumer import process_message  # noqa: E402
from reports_service.db import db as reports_db  # noqa: E402
from reports_service.models import Base as ReportsBase  # noqa: E402
from reports_service.models import ProcessedMessage as ReportsProcessed  # noqa: E402
from reports_service.services.dashboard import dashboard  # noqa: E402
from reports_service.services.events import handle_event as reports_handle  # noqa: E402
from sales_service.db import db  # noqa: E402
from sales_service.models import Invoice, InvoiceLine, InvoicePayment, SaleReturn  # noqa: E402

from .conftest import (  # noqa: E402
    MANAGER,
    PREFIX,
    TODAY,
    _migrate,
    add_product,
    inventory_db,
    line,
    pay,
    receive,
    sell,
    set_rate,
)  # fmt: skip


@pytest.fixture(scope="module", autouse=True)
def reports_database() -> None:
    _migrate("reports", reports_config.get_settings().database_url)


async def feed() -> int:
    """Every outbox event of sales and inventory → reports (outbox id = message id)."""
    tables = ", ".join(t.name for t in ReportsBase.metadata.sorted_tables)
    async with reports_db.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))  # noqa: S608 – own table names
    n = 0
    for source in (inventory_db, db):
        async with source.engine.connect() as conn:
            rows = (await conn.execute(text("SELECT id, event_type, payload FROM outbox ORDER BY seq"))).all()
        for mid, event_type, payload in rows:
            data = payload if isinstance(payload, dict) else json.loads(payload)
            n += await process_message(reports_db, ReportsProcessed, reports_handle, mid, event_type, data)
    return n


async def test_report_totals_match_the_sales_database(client) -> None:
    para = await add_product("PARA500")  # strip 0.90, box 8.00; cost 0.04 a tablet
    await receive(para, [("A", "2028-01-31", 500)])
    await set_rate(client, 4100)
    r1 = await sell(client, [line(para, "strip", 3)], [pay("5.00")])  # change 2.30
    r2 = await sell(client, [line(para, "box", 1)], [pay("32800", "KHR")])  # 8.00 in riel
    r3 = await sell(client, [line(para, "strip", 1)], [pay("0.90", method="ABA")])
    r4 = await sell(client, [line(para, "strip", 2)], [pay("1.80")])
    assert {r.status_code for r in (r1, r2, r3, r4)} == {201}
    cancel = await client.post(f"{PREFIX}/invoices/{r3.json()['id']}/cancel", json={"reason": "wrong item"},
                               headers={**MANAGER, "Idempotency-Key": "match-cancel-0001"})  # fmt: skip
    ret = await client.post(f"{PREFIX}/invoices/{r4.json()['id']}/returns", headers={**MANAGER, "Idempotency-Key": "match-ret-0001"},
                            json={"lines": [{"invoice_line_id": r4.json()["lines"][0]["id"], "qty": 1}],
                                  "refund_method": "cash", "reason": "x"})  # fmt: skip
    assert cancel.status_code == 200 and ret.status_code == 201, (cancel.text, ret.text)
    assert await feed() > 0

    async with db.sessionmaker() as s:
        done = Invoice.status == "completed"
        total, khr, count = (await s.execute(select(func.sum(Invoice.total), func.sum(Invoice.total_khr), func.count())
                                             .where(done))).one()  # fmt: skip
        cost = (await s.execute(select(func.sum(InvoiceLine.cost)).join(Invoice).where(done))).scalar_one()
        refunds = (await s.execute(select(func.sum(SaleReturn.refund_usd)))).scalar_one()
        money_in = (await s.execute(select(func.sum(InvoicePayment.amount_usd)).join(Invoice)
                                    .where(InvoicePayment.method.in_(("cash", "ABA")), done))).scalar_one()  # fmt: skip
        change = (await s.execute(select(func.sum(Invoice.change_usd)).where(done))).scalar_one()
        returned_cost = (await s.execute(text(
            "SELECT sum(l.cost * rl.qty_base / l.qty_base) FROM sale_return_lines rl "
            "JOIN invoice_lines l ON l.id = rl.invoice_line_id"))).scalar_one()  # fmt: skip
    async with reports_db.sessionmaker() as s:
        dash = await dashboard(s, None, True, TODAY)
        from reports_service.models import Payment

        by_method = dict((await s.execute(select(Payment.method, func.sum(Payment.amount_usd))
                                          .group_by(Payment.method))).all())  # fmt: skip
    today = dash["today"]
    assert (Decimal(today["sales"]), today["sales_khr"], today["invoices"]) == (total, khr, count)
    assert Decimal(today["returns"]) == refunds
    assert Decimal(today["gross_profit"]) == (total - refunds) - (cost - returned_cost.quantize(Decimal("0.01")))
    assert by_method.get("ABA", Decimal("0")) == 0  # paid, then given back on the cancel
    assert by_method["cash"] == money_in - change - refunds  # the drawer: in − change − refunds
