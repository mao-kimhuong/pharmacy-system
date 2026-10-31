"""Dashboard: today vs yesterday vs the same weekday last week, for one branch or
all of the user's branches (all branches for the owner). Also the 20:00
Telegram summary (internal /daily-summary), which reads the same figures.

Sales = completed sales of the day (cancelled ones leave their day); returns
count on the day they were made; net = sales − returns. KHR = the sum of each
invoice's own KHR total (its rate, rounded to 100 riel as on the receipt). Gross profit only for
users who may see cost (the key is absent otherwise)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock

from ..models import (
    Alert,
    Count,
    Customer,
    Debt,
    DebtAllocation,
    Invoice,
    KnownBranch,
    PendingRequest,
    Product,
    RegisterIssue,
    ReturnLine,
    SalesDaily,
    Shrinkage,
    StockRow,
)
from .common import in_branches, pct, plain

ZERO = Decimal("0")
OPEN_REQUESTS = ("submitted", "pending", "requested")


async def day_figures(session: AsyncSession, branches: list[UUID] | None, day: date, profit: bool) -> dict[str, Any]:
    s = SalesDaily
    net, cost = (await session.execute(select(func.coalesce(func.sum(s.net), 0), func.coalesce(func.sum(s.cost), 0))
        .where(s.day == day, in_branches(s.branch_id, branches)))).one()  # fmt: skip
    invoices, khr = (await session.execute(select(func.count(), func.coalesce(func.sum(Invoice.total_khr), 0)).where(
        Invoice.sale_date == day, Invoice.status == "completed", in_branches(Invoice.branch_id, branches)))).one()  # fmt: skip
    r = ReturnLine
    returns, returns_khr, returns_cost = (await session.execute(select(
        func.coalesce(func.sum(r.amount), 0), func.coalesce(func.sum(r.amount_khr), 0), func.coalesce(func.sum(r.cost), 0))
        .where(r.return_date == day, in_branches(r.branch_id, branches)))).one()  # fmt: skip
    out = {
        "date": day, "sales": Decimal(net), "sales_khr": int(khr), "invoices": int(invoices),
        "average_basket": (Decimal(net) / invoices).quantize(Decimal("0.01")) if invoices else ZERO,
        "returns": Decimal(returns), "net_sales": Decimal(net) - Decimal(returns),
        "net_sales_khr": int(khr) - int(returns_khr),
    }  # fmt: skip
    if profit:
        gross = out["net_sales"] - (Decimal(cost) - Decimal(returns_cost))
        out["gross_profit"] = gross
        out["margin_pct"] = pct(gross, out["net_sales"])
    return {k: plain(v) for k, v in out.items()}


async def top_medicines(session: AsyncSession, branches: list[UUID] | None, day: date, n: int = 5) -> list[dict]:
    s = SalesDaily
    rows = (await session.execute(
        select(Product.sku, Product.brand_name, func.sum(s.qty_base), func.sum(s.net))
        .join(Product, Product.id == s.medicine_id, isouter=True)
        .where(s.day == day, in_branches(s.branch_id, branches))
        .group_by(Product.sku, Product.brand_name).order_by(func.sum(s.net).desc(), Product.sku).limit(n))).all()  # fmt: skip
    return [{"sku": sku, "name": name, "qty_base": int(q), "net": str(v)} for sku, name, q, v in rows]


async def low_stock(session: AsyncSession, branches: list[UUID] | None, day: date) -> list[dict]:
    """The inventory job's stock.low alerts of the latest day, minus those restocked since."""
    latest = (await session.execute(select(func.max(Alert.day)).where(
        Alert.kind == "low", Alert.day <= day, in_branches(Alert.branch_id, branches)))).scalar_one()  # fmt: skip
    if latest is None:
        return []
    alerts = (await session.execute(select(Alert).where(
        Alert.kind == "low", Alert.day == latest, in_branches(Alert.branch_id, branches)))).scalars().all()  # fmt: skip
    out = []
    for a in alerts:
        now = (await session.execute(select(func.coalesce(func.sum(StockRow.qty_on_hand), 0)).where(
            StockRow.branch_id == a.branch_id, StockRow.medicine_id == a.medicine_id,
            StockRow.expiry_date >= day))).scalar_one()  # fmt: skip
        point = int(a.data.get("reorder_point") or 0)
        if now < point or not point:
            out.append({"branch_id": str(a.branch_id), "sku": a.data.get("sku"), "name": a.data.get("name"),
                        "on_hand": int(now), "reorder_point": point})  # fmt: skip
    return sorted(out, key=lambda x: (x["on_hand"] - x["reorder_point"], x["sku"] or ""))


async def near_expiry(session: AsyncSession, branches: list[UUID] | None, day: date) -> dict[str, Any]:
    """Batches on hand that expire within the branch's longest alert (expiry_alert_days)."""
    rows = (await session.execute(select(KnownBranch.id, KnownBranch.expiry_alert_days).where(
        in_branches(KnownBranch.id, branches)))).all()  # fmt: skip
    horizon = {b: max([int(d) for d in (days or [180, 90, 30])] or [90]) for b, days in rows}
    items, count = [], 0
    for branch, days in horizon.items():
        q = (select(StockRow.expiry_date, StockRow.lot_no, StockRow.qty_on_hand, Product.sku)
             .join(Product, Product.id == StockRow.medicine_id, isouter=True)
             .where(StockRow.branch_id == branch, StockRow.qty_on_hand > 0, StockRow.expiry_date >= day,
                    StockRow.expiry_date <= day + timedelta(days=days)).order_by(StockRow.expiry_date))  # fmt: skip
        found = (await session.execute(q)).all()
        count += len(found)
        items += [{"branch_id": str(branch), "sku": sku, "lot_no": lot, "expiry_date": exp.isoformat(),
                   "days_left": (exp - day).days, "qty_base": int(qty)} for exp, lot, qty, sku in found]  # fmt: skip
    items.sort(key=lambda x: x["expiry_date"])
    return {"count": count, "soonest": items[:10]}


async def pending(session: AsyncSession, branches: list[UUID] | None) -> dict[str, int]:
    async def n(model: Any, *cond: Any) -> int:
        return int((await session.execute(select(func.count()).select_from(model).where(
            *cond, in_branches(model.branch_id, branches)))).scalar_one())  # fmt: skip

    return {
        "shrinkages": await n(Shrinkage, Shrinkage.status == "pending_approval"),
        "stock_takes": await n(Count, Count.status == "review"),
        "transfer_requests": await n(PendingRequest, PendingRequest.kind == "transfer_request",
                                     PendingRequest.status.in_(OPEN_REQUESTS)),
        "purchase_requests": await n(PendingRequest, PendingRequest.kind == "purchase_request",
                                     PendingRequest.status.in_(OPEN_REQUESTS)),
    }  # fmt: skip


async def top_debtors(session: AsyncSession, branches: list[UUID] | None, n: int = 5) -> list[dict]:
    a = DebtAllocation
    paid = (select(Invoice.id.label("invoice_id"), func.sum(a.amount).label("paid"))
            .join(Invoice, Invoice.number == a.invoice_no).group_by(Invoice.id).subquery())  # fmt: skip
    open_ = Debt.amount - Debt.reversed - func.coalesce(paid.c.paid, 0)
    rows = (await session.execute(
        select(Customer.name, func.sum(open_)).join(paid, paid.c.invoice_id == Debt.invoice_id, isouter=True)
        .join(Customer, Customer.id == Debt.customer_id, isouter=True)
        .where(in_branches(Debt.branch_id, branches), open_ > 0)
        .group_by(Customer.name).order_by(func.sum(open_).desc()).limit(n))).all()  # fmt: skip
    return [{"customer": name, "owes": str(v)} for name, v in rows]


async def dashboard(session: AsyncSession, branches: list[UUID] | None, profit: bool,
                    day: date | None = None) -> dict[str, Any]:  # fmt: skip
    today = day or clock.today()
    open_issues = (await session.execute(select(func.count()).select_from(RegisterIssue).where(
        RegisterIssue.status == "open", in_branches(RegisterIssue.branch_id, branches)))).scalar_one()  # fmt: skip
    return {
        "branch_ids": [str(b) for b in branches] if branches is not None else "all",
        "today": await day_figures(session, branches, today, profit),
        "yesterday": await day_figures(session, branches, today - timedelta(days=1), profit),
        "same_day_last_week": await day_figures(session, branches, today - timedelta(days=7), profit),
        "top_medicines": await top_medicines(session, branches, today),
        "low_stock": await low_stock(session, branches, today),
        "near_expiry": await near_expiry(session, branches, today),
        "open_controlled_discrepancies": int(open_issues),
        "pending_approvals": await pending(session, branches),
        "top_debtors": await top_debtors(session, branches),
    }
