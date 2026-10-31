"""make seed-demo: about a year of demo data in the reports read models, to time
the reports (make bench-reports). Refused unless APP_ENV=development (and never
when ENVIRONMENT=production). Only DEMO branches (codes DEMO1..DEMO3) and DEMO-
products are written; running it again first removes the previous demo rows.

The rows have the shapes the event handlers write (invoices, lines, payments,
movements, stock, receipts, bills, returns, commission, debts, alerts); they are
bulk-inserted, because one event at a time would take an hour for ~270 000
invoices. The daily rollup is then built by the same rebuild_day() as live events.
"""

import os
import random
import time
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.db import Database

from ..config import get_settings
from ..models import (
    Alert,
    Bill,
    CommissionLine,
    Customer,
    Debt,
    Invoice,
    InvoiceLine,
    KnownBranch,
    Lookup,
    Movement,
    Payment,
    Product,
    ReceiptLine,
    ReturnLine,
    SalesDaily,
    Staff,
    StockRow,
    Supplier,
)
from .events import rebuild_day

PRODUCTS, CUSTOMERS, STAFF_PER_BRANCH = 300, 200, 4
CENT = Decimal("0.01")
BRANCH_TABLES = (InvoiceLine, Invoice, Payment, Movement, StockRow, ReceiptLine, Bill, ReturnLine, CommissionLine,
                 Debt, Alert, SalesDaily)  # fmt: skip


def demo_id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"pharmacy-demo:{name}")


def allowed() -> None:
    if os.environ.get("APP_ENV") != "development" or get_settings().is_production:
        raise SystemExit("seed-demo refused: it runs only with APP_ENV=development (never in production)")


async def _bulk(session: AsyncSession, model: type, rows: list[dict[str, Any]], chunk: int = 2000) -> None:
    for i in range(0, len(rows), chunk):
        await session.execute(insert(model), rows[i: i + chunk])


async def _clear(session: AsyncSession, branches: list[UUID]) -> None:
    for model in BRANCH_TABLES:
        await session.execute(delete(model).where(model.branch_id.in_(branches)))
    await session.commit()


async def run(db: Database, days: int = 365, per_day: int = 250, seed: int = 8) -> dict[str, Any]:
    allowed()
    started = time.monotonic()
    rnd = random.Random(seed)
    today = clock.today()
    branches = [demo_id(f"branch:{i}") for i in range(1, 4)]
    counts: dict[str, int] = {}
    async with db.sessionmaker() as s:
        await _clear(s, branches)
        for i, b in enumerate(branches, start=1):
            await s.merge(KnownBranch(id=b, code=f"DEMO{i}", name_en=f"Demo branch {i}", name_km="សាខាសាកល្បង",
                                      is_active=True, expiry_alert_days=[180, 90, 30]))  # fmt: skip
        categories = [demo_id(f"category:{i}") for i in range(12)]
        for i, c in enumerate(categories):
            await s.merge(Lookup(id=c, kind="category", name_en=f"Demo category {i}", name_km=""))
        products = []
        for i in range(PRODUCTS):
            pid = demo_id(f"product:{i}")
            price = Decimal(rnd.choice(["0.05", "0.08", "0.10", "0.15", "0.25", "0.40", "0.90"]))
            products.append((pid, f"DEMO-{i:03d}", price, categories[i % len(categories)]))
            await s.merge(Product(id=pid, version=1, sku=f"DEMO-{i:03d}", brand_name=f"Demo medicine {i}",
                                  generic_name="Demo", base_unit="tablet", is_active=True, category_id=categories[i % 12],
                                  controlled_schedule="II" if i % 97 == 0 else None))  # fmt: skip
        staff = {b: [demo_id(f"staff:{b}:{k}") for k in range(STAFF_PER_BRANCH)] for b in branches}
        for b, ids in staff.items():
            for k, sid in enumerate(ids):
                await s.merge(Staff(id=sid, name=f"Demo staff {str(b)[:4]}-{k}", role="cashier"))
        customers = [demo_id(f"customer:{i}") for i in range(CUSTOMERS)]
        for i, c in enumerate(customers):
            await s.merge(Customer(id=c, name=f"Demo customer {i}"))
        supplier = demo_id("supplier")
        await s.merge(Supplier(id=supplier, code="DEMO", name="Demo supplier", payment_terms_days=30))
        await s.commit()

        weights = [1 / (i + 1) ** 0.9 for i in range(PRODUCTS)]  # a few items sell most (ABC)
        seq = 10**12  # far from real movement seqs
        for d in range(days, -1, -1):
            day = today - timedelta(days=d)
            inv_rows, line_rows, pay_rows, move_rows, com_rows, ret_rows, debt_rows = [], [], [], [], [], [], []
            for b in branches:
                for _ in range(int(per_day * rnd.uniform(0.8, 1.2))):
                    iid = uuid4()
                    at = datetime.combine(day, dtime(rnd.randint(7, 20), rnd.randint(0, 59)), clock.TIMEZONE)
                    cashier = rnd.choice(staff[b])
                    customer = rnd.choice(customers) if rnd.random() < 0.15 else None
                    total = cost_total = Decimal("0")
                    for n, k in enumerate(rnd.choices(range(PRODUCTS), weights, k=rnd.randint(1, 5)), start=1):
                        pid, sku, price, cat = products[k]
                        qty_base = rnd.choice([1, 5, 10, 10, 20, 30])
                        gross = (price * qty_base).quantize(CENT)
                        promo = (gross * Decimal("0.1")).quantize(CENT) if rnd.random() < 0.08 else Decimal("0")
                        net = gross - promo
                        cost = (net * Decimal(str(rnd.uniform(0.55, 0.8)))).quantize(CENT)
                        total += net
                        cost_total += cost
                        lid = uuid4()
                        line_rows.append({"id": lid, "invoice_id": iid, "branch_id": b, "sale_date": day,
                                          "status": "completed", "staff_id": cashier, "customer_id": customer,
                                          "line_no": n, "medicine_id": pid, "category_id": cat, "brand_id": None,
                                          "sku": sku, "name": sku, "pack_unit": "tablet", "qty": qty_base,
                                          "qty_base": qty_base, "unit_price": price, "line_total": gross,
                                          "promo_discount": promo, "manual_discount": Decimal("0"), "net": net,
                                          "net_khr": int(net * 4100), "cost": cost, "promotion_ids": [],
                                          "is_hamper": False, "is_rx": k % 13 == 0, "is_controlled": k % 97 == 0,
                                          "rx_number": None, "doctor_name": None, "returned_qty_base": 0})  # fmt: skip
                        seq += 1
                        move_rows.append({"id": uuid4(), "seq": seq, "branch_id": b, "batch_id": demo_id(f"batch:{b}:{k}"),
                                          "medicine_id": pid, "type": "out", "delta": -qty_base, "qty_after": 1000,
                                          "lot_no": f"L{k}", "expiry_date": today + timedelta(days=30 + k * 2),
                                          "cost_per_base": Decimal("0.0500"), "reason": "", "reason_code": "",
                                          "ref_type": "reservation_line", "ref_id": str(lid),
                                          "is_controlled": k % 97 == 0, "created_by": cashier, "occurred_at": at,
                                          "day": day})  # fmt: skip
                        if rnd.random() < 0.33:
                            com_rows.append({"id": uuid4(), "period_id": demo_id(f"period:{b}:{day:%Y-%m}"),
                                             "month": day.replace(day=1), "branch_id": b, "staff_id": cashier,
                                             "invoice_number": "", "source": "sale", "medicine_id": pid, "sku": sku,
                                             "qty_base": qty_base, "net_usd": net,
                                             "amount": (net * Decimal("0.02")).quantize(CENT), "created_at": at})  # fmt: skip
                        if rnd.random() < 0.005 and d > 0:
                            back = (day + timedelta(days=1))
                            ret_rows.append({"id": f"{uuid4()}", "return_id": uuid4(), "number": None,
                                             "invoice_id": iid, "invoice_number": None, "line_id": lid,
                                             "branch_id": b, "return_date": back, "staff_id": cashier,
                                             "medicine_id": pid, "sku": sku, "name": sku, "qty_base": qty_base,
                                             "amount": net, "amount_khr": int(net * 4100), "cost": cost,
                                             "refund_method": "cash", "reason": "demo", "to_quarantine": False})  # fmt: skip
                    method = rnd.choices(["cash", "ABA", "card", "credit"], [70, 20, 7, 3])[0]
                    if method == "credit" and customer is None:
                        method = "cash"
                    inv_rows.append({"id": iid, "version": 1, "number": f"DEMO-INV-{iid.hex[:10]}", "branch_id": b,
                                     "status": "completed", "cashier_id": cashier, "customer_id": customer,
                                     "completed_at": at, "sale_date": day, "cancelled_at": None, "cancel_date": None,
                                     "cancel_reason": None, "subtotal": total, "discount": Decimal("0"), "total": total,
                                     "cost": cost_total, "khr_per_usd": 4100, "total_khr": int(total * 41) * 100,
                                     "credit_amount": total if method == "credit" else Decimal("0"),
                                     "returned_total": Decimal("0")})  # fmt: skip
                    if method == "credit":
                        debt_rows.append({"invoice_id": iid, "customer_id": customer, "branch_id": b, "amount": total,
                                          "reversed": Decimal("0"), "charged_on": day})  # fmt: skip
                    else:
                        pay_rows.append({"id": f"sale:{iid}:0", "branch_id": b, "day": day, "occurred_at": at,
                                         "kind": "sale", "method": method, "currency": "USD", "amount": total,
                                         "amount_usd": total, "reference": "", "party": "", "staff_id": cashier})  # fmt: skip
            for model, rows in ((Invoice, inv_rows), (InvoiceLine, line_rows), (Payment, pay_rows),
                                (Movement, move_rows), (CommissionLine, com_rows), (ReturnLine, ret_rows),
                                (Debt, debt_rows)):  # fmt: skip
                await _bulk(s, model, rows)
                counts[model.__tablename__] = counts.get(model.__tablename__, 0) + len(rows)
            for b in branches:
                await rebuild_day(s, b, day)
            if day.weekday() == 0:  # weekly delivery per branch: receipts and bills
                for b in branches:
                    rid = uuid4()
                    at = datetime.combine(day, dtime(9), clock.TIMEZONE)
                    lines = [{"id": uuid4(), "receipt_id": rid, "number": f"DEMO-GRN-{rid.hex[:8]}", "branch_id": b,
                              "supplier_id": supplier, "received_at": at, "day": day, "medicine_id": products[k][0],
                              "qty_base": 500, "lot_no": f"W{d}", "expiry_date": day + timedelta(days=540),
                              "cost_per_base": (products[k][2] * Decimal(str(rnd.uniform(0.55, 0.75)))).quantize(
                                  Decimal("0.0001")), "line_total": Decimal("0")} for k in rnd.sample(range(PRODUCTS), 40)]  # fmt: skip
                    for x in lines:
                        x["line_total"] = (x["cost_per_base"] * 500).quantize(CENT)
                    await _bulk(s, ReceiptLine, lines)
                    await _bulk(s, Bill, [{"id": rid, "number": lines[0]["number"], "branch_id": b,
                                           "supplier_id": supplier, "received_on": day, "due_on": day + timedelta(days=30),
                                           "total": sum((x["line_total"] for x in lines), Decimal("0"))}])  # fmt: skip
                    counts["receipt_lines"] = counts.get("receipt_lines", 0) + len(lines)
            await s.commit()
        # stock now: a few batches per product and branch, some expired, some expiring soon
        stock = []
        for b in branches:
            for k, (pid, _, _, _) in enumerate(products):
                for j in range(3):
                    expiry = today + timedelta(days=rnd.randint(-60, 720))
                    stock.append({"branch_id": b, "batch_id": demo_id(f"batch:{b}:{k}:{j}"), "medicine_id": pid,
                                  "lot_no": f"S{k}-{j}", "expiry_date": expiry, "cost_per_base": Decimal("0.0500"),
                                  "qty_on_hand": rnd.choice([0, 20, 100, 500]), "last_seq": 0,
                                  "last_movement_at": datetime.now(UTC)})  # fmt: skip
                if k % 25 == 0:
                    await s.merge(Alert(kind="low", ref=str(pid), day=today, branch_id=b, medicine_id=pid,
                                        data={"sku": f"DEMO-{k:03d}", "name": "Demo", "reorder_point": 400}))  # fmt: skip
        await _bulk(s, StockRow, stock)
        await s.commit()
        counts["stock"] = len(stock)
        counts["days"] = days + 1
        total = (await s.execute(select(InvoiceLine.id).limit(1))).first()
        counts["seconds"] = round(time.monotonic() - started)
        counts["ok"] = total is not None
    return counts
