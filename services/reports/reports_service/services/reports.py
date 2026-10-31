"""The reports (docs/spec.md → Menu structure → Report). Each one: a permission,
columns (cost ones marked secret) and a builder over the read models.

Sales are counted on the day they were completed; cancelled invoices leave
that day; returns count on the day they were made (choice K). KHR uses each
invoice's own rate.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import String, and_, case, cast, func, literal, or_, select

from pharmacy_shared import clock
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import (
    Bill,
    BillAllocation,
    CommissionLine,
    Count,
    CountLine,
    Customer,
    Debt,
    DebtAllocation,
    Invoice,
    InvoiceLine,
    KnownBranch,
    Lookup,
    Modification,
    Movement,
    Payment,
    Product,
    ReceiptLine,
    RegisterIssue,
    ReturnLine,
    SalesDaily,
    Staff,
    StockRow,
    Supplier,
    Transfer,
)
from .common import Col, Ctx, Result, in_branches, page, pct, run_query

ZERO = Decimal("0")
Builder = Callable[[Ctx], Awaitable[Result]]


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    permissions: tuple[str, ...]  # all of them are needed; "a|b" = either
    build: Builder


REPORTS: dict[str, Report] = {}


def report(key: str, title: str, *permissions: str) -> Callable[[Builder], Builder]:
    def wrap(fn: Builder) -> Builder:
        REPORTS[key] = Report(key, title, permissions, fn)
        return fn

    return wrap


def _branch_name() -> Any:
    return KnownBranch.code


def _lines(ctx: Ctx) -> Any:
    """Completed sale lines in the period, filtered."""
    f, x = ctx.f, InvoiceLine
    cond = [x.status == "completed", x.sale_date.between(f.date_from, f.date_to), in_branches(x.branch_id, ctx.branches)]
    if f.staff_id:
        cond.append(x.staff_id == f.staff_id)
    if f.customer_id:
        cond.append(x.customer_id == f.customer_id)
    if f.medicine_id:
        cond.append(x.medicine_id == f.medicine_id)
    if f.category_id:
        cond.append(x.category_id == f.category_id)
    return and_(*cond)


# ---------------------------------------------------------------- sales


@report("sales/detail", "Sale Detail", "reports.sales")
async def sales_detail(ctx: Ctx) -> Result:
    x = InvoiceLine
    cols = [Col("sale_date", "Date", "date"), Col("invoice", "Invoice"), Col("branch", "Branch"),
            Col("staff", "Staff"), Col("customer", "Customer"), Col("sku", "SKU"), Col("name", "Medicine"),
            Col("pack_unit", "Pack"), Col("qty", "Qty", "qty"), Col("unit_price", "Price", "money"),
            Col("gross", "Gross", "money"), Col("discount", "Discount", "money"), Col("net", "Net", "money"),
            Col("net_khr", "Net KHR", "khr"), Col("cost", "Cost", "money", "cost"),
            Col("profit", "Profit", "money", "cost")]  # fmt: skip
    q = (select(x.sale_date.label("sale_date"), Invoice.number.label("invoice"), _branch_name().label("branch"),
                Staff.name.label("staff"), Customer.name.label("customer"), x.sku.label("sku"), x.name.label("name"),
                x.pack_unit.label("pack_unit"), x.qty.label("qty"), x.unit_price.label("unit_price"),
                x.line_total.label("gross"), (x.promo_discount + x.manual_discount).label("discount"),
                x.net.label("net"), x.net_khr.label("net_khr"), x.cost.label("cost"),
                (x.net - x.cost).label("profit"))
         .join(Invoice, Invoice.id == x.invoice_id).join(KnownBranch, KnownBranch.id == x.branch_id, isouter=True)
         .join(Staff, Staff.id == x.staff_id, isouter=True).join(Customer, Customer.id == x.customer_id, isouter=True)
         .where(_lines(ctx)).order_by(x.sale_date, Invoice.number, x.line_no))  # fmt: skip
    totals = (await ctx.session.execute(select(
        func.coalesce(func.sum(x.net), 0), func.coalesce(func.sum(x.net_khr), 0), func.coalesce(func.sum(x.cost), 0),
        func.count(func.distinct(x.invoice_id)), func.count()).where(_lines(ctx)))).one()  # fmt: skip
    result = await run_query(ctx, q, cols, "Sale Detail", total=int(totals[4]))  # the joins are 1:1
    result.summary = {"net": str(totals[0]), "net_khr": int(totals[1]), "cost": str(totals[2]),
                      "profit": str(totals[0] - totals[2]), "invoices": int(totals[3])}  # fmt: skip
    return result


SUMMARY_BY = {"day", "branch", "staff", "medicine", "category", "payment_method"}


@report("sales/summary", "Sales summary", "reports.sales")
async def sales_summary(ctx: Ctx) -> Result:
    by = ctx.f.extra.get("by") or "day"
    if by not in SUMMARY_BY:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"by: one of {sorted(SUMMARY_BY)}", status_code=422)
    if by == "payment_method":
        p = Payment
        cond = [p.day.between(ctx.f.date_from, ctx.f.date_to), in_branches(p.branch_id, ctx.branches)]
        q = (select(p.method.label("key"), p.kind.label("kind"), func.count().label("count"),
                    func.sum(p.amount_usd).label("amount_usd"))
             .where(*cond).group_by(p.method, p.kind).order_by(p.method, p.kind))  # fmt: skip
        cols = [Col("key", "Method"), Col("kind", "Kind"), Col("count", "Count", "qty"),
                Col("amount_usd", "Amount USD", "money")]  # fmt: skip
        return await run_query(ctx, q, cols, "Sales by payment method")
    x = InvoiceLine
    key, label = {
        "day": (x.sale_date, "Day"), "branch": (KnownBranch.code, "Branch"), "staff": (Staff.name, "Staff"),
        "medicine": (x.sku, "SKU"), "category": (Lookup.name_en, "Category"),
    }[by]  # fmt: skip
    q = (select(key.label("key"), func.count(func.distinct(x.invoice_id)).label("invoices"),
                func.sum(x.qty_base).label("qty_base"), func.sum(x.line_total).label("gross"),
                func.sum(x.promo_discount + x.manual_discount).label("discount"), func.sum(x.net).label("net"),
                func.sum(x.net_khr).label("net_khr"), func.sum(x.cost).label("cost"),
                func.sum(x.net - x.cost).label("profit"))
         .select_from(x).join(KnownBranch, KnownBranch.id == x.branch_id, isouter=True)
         .join(Staff, Staff.id == x.staff_id, isouter=True).join(Lookup, Lookup.id == x.category_id, isouter=True)
         .where(_lines(ctx)).group_by(key).order_by(key))  # fmt: skip
    cols = [Col("key", label), Col("invoices", "Invoices", "qty"), Col("qty_base", "Qty (base)", "qty"),
            Col("gross", "Gross", "money"), Col("discount", "Discount", "money"), Col("net", "Net", "money"),
            Col("net_khr", "Net KHR", "khr"), Col("cost", "Cost", "money", "cost"),
            Col("profit", "Profit", "money", "cost")]  # fmt: skip
    return await run_query(ctx, q, cols, f"Sales by {by}")


@report("sales/margin-by-item", "Sale Margin By Item", "reports.sales", "finance.cost_profit")
async def margin_by_item(ctx: Ctx) -> Result:
    x = InvoiceLine
    net, cost = func.sum(x.net), func.sum(x.cost)
    q = (select(x.sku.label("sku"), func.max(x.name).label("name"), func.sum(x.qty_base).label("qty_base"),
                net.label("net"), cost.label("cost"), (net - cost).label("profit"),
                case((net > 0, func.round((net - cost) * 100 / net, 2)), else_=None).label("margin_pct"))
         .where(_lines(ctx)).group_by(x.sku).order_by((net - cost).desc()))  # fmt: skip
    cols = [Col("sku", "SKU"), Col("name", "Medicine"), Col("qty_base", "Qty (base)", "qty"),
            Col("net", "Revenue", "money"), Col("cost", "Cost", "money", "cost"),
            Col("profit", "Margin", "money", "cost"), Col("margin_pct", "Margin %", "pct", "cost")]  # fmt: skip
    return await run_query(ctx, q, cols, "Sale Margin By Item")


@report("sales/profit", "Profit and margin", "reports.sales", "finance.cost_profit")
async def profit(ctx: Ctx) -> Result:
    """Per day: sales − returns (on their day) = net revenue; minus cost = gross profit."""
    f = ctx.f
    s = SalesDaily
    sold = {r.day: r for r in (await ctx.session.execute(
        select(s.day, func.sum(s.net).label("net"), func.sum(s.cost).label("cost"), func.sum(s.net_khr).label("khr"))
        .where(s.day.between(f.date_from, f.date_to), in_branches(s.branch_id, ctx.branches)).group_by(s.day)))}  # fmt: skip
    r = ReturnLine
    back = {x.day: x for x in (await ctx.session.execute(
        select(r.return_date.label("day"), func.sum(r.amount).label("amount"), func.sum(r.cost).label("cost"))
        .where(r.return_date.between(f.date_from, f.date_to), in_branches(r.branch_id, ctx.branches))
        .group_by(r.return_date)))}  # fmt: skip
    rows = []
    for day in sorted(set(sold) | set(back)):
        a, b = sold.get(day), back.get(day)
        revenue = (a.net if a else ZERO) - (b.amount if b else ZERO)
        cost = (a.cost if a else ZERO) - (b.cost if b else ZERO)
        rows.append({"day": day, "sales": a.net if a else ZERO, "returns": b.amount if b else ZERO,
                     "revenue": revenue, "cost": cost, "profit": revenue - cost, "margin_pct": pct(revenue - cost, revenue)})  # fmt: skip
    cols = [Col("day", "Day", "date"), Col("sales", "Sales", "money"), Col("returns", "Returns", "money"),
            Col("revenue", "Net revenue", "money"), Col("cost", "Cost", "money", "cost"),
            Col("profit", "Gross profit", "money", "cost"), Col("margin_pct", "Margin %", "pct", "cost")]  # fmt: skip
    revenue = sum((x["revenue"] for x in rows), ZERO)
    cost = sum((x["cost"] for x in rows), ZERO)
    return page(ctx, rows, cols, "Profit and margin", revenue=revenue, cost=cost, profit=revenue - cost,
                margin_pct=pct(revenue - cost, revenue))  # fmt: skip


@report("sales/by-package", "Sale Product Package", "reports.sales")
async def by_package(ctx: Ctx) -> Result:
    x = InvoiceLine
    q = (select(x.sku.label("sku"), func.max(x.name).label("name"), x.pack_unit.label("pack_unit"),
                x.is_hamper.label("is_hamper"), func.sum(x.qty).label("qty"), func.sum(x.qty_base).label("qty_base"),
                func.sum(x.net).label("net"))
         .where(_lines(ctx)).group_by(x.sku, x.pack_unit, x.is_hamper).order_by(x.sku, x.pack_unit))  # fmt: skip
    cols = [Col("sku", "SKU"), Col("name", "Medicine"), Col("pack_unit", "Pack"), Col("is_hamper", "Hamper"),
            Col("qty", "Qty", "qty"), Col("qty_base", "Qty (base)", "qty"), Col("net", "Net", "money")]  # fmt: skip
    return await run_query(ctx, q, cols, "Sale Product Package")


@report("returns/detail", "Sale Return Detail", "reports.sales")
async def returns_detail(ctx: Ctx) -> Result:
    r, f = ReturnLine, ctx.f
    cond = [r.return_date.between(f.date_from, f.date_to), in_branches(r.branch_id, ctx.branches)]
    if f.medicine_id:
        cond.append(r.medicine_id == f.medicine_id)
    q = (select(r.return_date.label("day"), r.number.label("return"), r.invoice_number.label("invoice"),
                KnownBranch.code.label("branch"), r.sku.label("sku"), r.name.label("name"), r.qty_base.label("qty_base"),
                r.amount.label("amount"), r.amount_khr.label("amount_khr"), r.cost.label("cost"),
                r.refund_method.label("refund_method"), r.to_quarantine.label("to_quarantine"), r.reason.label("reason"))
         .join(KnownBranch, KnownBranch.id == r.branch_id, isouter=True).where(*cond)
         .order_by(r.return_date, r.number))  # fmt: skip
    cols = [Col("day", "Day", "date"), Col("return", "Return"), Col("invoice", "Invoice"), Col("branch", "Branch"),
            Col("sku", "SKU"), Col("name", "Medicine"), Col("qty_base", "Qty (base)", "qty"),
            Col("amount", "Refund", "money"), Col("amount_khr", "Refund KHR", "khr"),
            Col("cost", "Cost back", "money", "cost"), Col("refund_method", "Refund as"),
            Col("to_quarantine", "Quarantine"), Col("reason", "Reason")]  # fmt: skip
    return await run_query(ctx, q, cols, "Sale Return Detail")


@report("sales/cancellations", "Cancelled invoices", "reports.sales")
async def cancellations(ctx: Ctx) -> Result:
    i, f = Invoice, ctx.f
    q = (select(i.cancel_date.label("cancel_date"), i.sale_date.label("sale_date"), i.number.label("invoice"),
                KnownBranch.code.label("branch"), Staff.name.label("staff"), i.total.label("total"),
                i.cancel_reason.label("reason"))
         .join(KnownBranch, KnownBranch.id == i.branch_id, isouter=True)
         .join(Staff, Staff.id == i.cashier_id, isouter=True)
         .where(i.status == "cancelled", i.cancel_date.between(f.date_from, f.date_to),
                in_branches(i.branch_id, ctx.branches)).order_by(i.cancel_date, i.number))  # fmt: skip
    cols = [Col("cancel_date", "Cancelled on", "date"), Col("sale_date", "Sold on", "date"), Col("invoice", "Invoice"),
            Col("branch", "Branch"), Col("staff", "Seller"), Col("total", "Total", "money"), Col("reason", "Reason")]  # fmt: skip
    return await run_query(ctx, q, cols, "Cancelled invoices")


@report("sales/discounts", "Discounts and promotions", "reports.sales")
async def discounts(ctx: Ctx) -> Result:
    x = InvoiceLine
    promo = func.coalesce(func.json_extract_path_text(x.promotion_ids, "0"), "")
    key = case((x.promo_discount > 0, promo), else_=literal("manual"))
    q = (select(key.label("promotion_id"), func.max(Lookup.name_en).label("promotion"), func.count().label("lines"),
                func.sum(x.line_total).label("gross"), func.sum(x.promo_discount).label("promo_discount"),
                func.sum(x.manual_discount).label("manual_discount"), func.sum(x.net).label("net"))
         .select_from(x).join(Lookup, cast(Lookup.id, String) == promo, isouter=True)
         .where(_lines(ctx), (x.promo_discount > 0) | (x.manual_discount > 0)).group_by(key).order_by(key))  # fmt: skip
    cols = [Col("promotion_id", "Promotion id"), Col("promotion", "Promotion"), Col("lines", "Lines", "qty"),
            Col("gross", "Gross", "money"), Col("promo_discount", "Promotion discount", "money"),
            Col("manual_discount", "Manual discount", "money"), Col("net", "Net", "money")]  # fmt: skip
    return await run_query(ctx, q, cols, "Discounts and promotions")


@report("payments", "Transaction Payment", "reports.sales")
async def payments(ctx: Ctx) -> Result:
    p, f = Payment, ctx.f
    cond = [p.day.between(f.date_from, f.date_to), in_branches(p.branch_id, ctx.branches)]
    if f.extra.get("method"):
        cond.append(p.method == f.extra["method"])
    q = (select(p.occurred_at.label("at"), KnownBranch.code.label("branch"), p.kind.label("kind"),
                p.method.label("method"), p.currency.label("currency"), p.amount.label("amount"),
                p.amount_usd.label("amount_usd"), p.reference.label("reference"), p.party.label("party"))
         .join(KnownBranch, KnownBranch.id == p.branch_id, isouter=True).where(*cond).order_by(p.occurred_at, p.id))  # fmt: skip
    cols = [Col("at", "When", "date"), Col("branch", "Branch"), Col("kind", "Kind"), Col("method", "Method"),
            Col("currency", "Currency"), Col("amount", "Amount", "money"), Col("amount_usd", "USD", "money"),
            Col("reference", "Reference"), Col("party", "Customer / supplier")]  # fmt: skip
    result = await run_query(ctx, q, cols, "Transaction Payment")
    by_method = (await ctx.session.execute(select(p.method, func.sum(p.amount_usd)).where(*cond).group_by(p.method))).all()
    result.summary = {m: str(v) for m, v in by_method}
    return result


# ---------------------------------------------------------------- stock


def _stock_cond(ctx: Ctx) -> list[Any]:
    s, f = StockRow, ctx.f
    cond = [s.qty_on_hand > 0, in_branches(s.branch_id, ctx.branches)]
    if f.medicine_id:
        cond.append(s.medicine_id == f.medicine_id)
    if f.category_id:
        cond.append(Product.category_id == f.category_id)
    return cond


def _stock_cols(extra: list[Col] | None = None) -> list[Col]:
    return [Col("branch", "Branch"), Col("sku", "SKU"), Col("name", "Medicine"), Col("lot_no", "Lot"),
            Col("expiry_date", "Expiry", "date"), *(extra or []), Col("qty_on_hand", "On hand (base)", "qty"),
            Col("cost_per_base", "Cost / base", "money", "cost"), Col("value", "Value", "money", "cost")]  # fmt: skip


def _stock_select(*extra: Any) -> Any:
    s = StockRow
    return (select(KnownBranch.code.label("branch"), Product.sku.label("sku"), Product.brand_name.label("name"),
                   s.lot_no.label("lot_no"), s.expiry_date.label("expiry_date"), *extra,
                   s.qty_on_hand.label("qty_on_hand"), s.cost_per_base.label("cost_per_base"),
                   func.round(s.qty_on_hand * s.cost_per_base, 2).label("value"))
            .join(Product, Product.id == s.medicine_id, isouter=True)
            .join(KnownBranch, KnownBranch.id == s.branch_id, isouter=True))  # fmt: skip


async def _stock_value(ctx: Ctx, cond: list[Any]) -> dict[str, Any]:
    s = StockRow
    qty, value = (await ctx.session.execute(select(
        func.coalesce(func.sum(s.qty_on_hand), 0), func.coalesce(func.sum(s.qty_on_hand * s.cost_per_base), 0))
        .join(Product, Product.id == s.medicine_id, isouter=True).where(*cond))).one()  # fmt: skip
    return {"qty_on_hand": int(qty), "value": str(Decimal(value).quantize(Decimal("0.01")))}


@report("stock", "Stock", "reports.stock")
async def stock(ctx: Ctx) -> Result:
    cond = _stock_cond(ctx)
    q = _stock_select().where(*cond).order_by(KnownBranch.code, Product.sku, StockRow.expiry_date)
    result = await run_query(ctx, q, _stock_cols(), "Stock on hand")
    result.summary = await _stock_value(ctx, cond)
    return result


@report("expiry", "Expire / Expire Alert", "reports.stock")
async def expiry(ctx: Ctx) -> Result:
    s, today = StockRow, clock.today()
    cond = _stock_cond(ctx)
    if ctx.f.extra.get("status") == "expired":
        cond.append(s.expiry_date < today)
        title = "Expired stock"
    else:
        within = int(ctx.f.extra.get("within") or 90)
        cond += [s.expiry_date >= today, s.expiry_date <= today + timedelta(days=within)]
        title = f"Expiring within {within} days"
    days_left = (s.expiry_date - today).label("days_left")
    q = _stock_select(days_left).where(*cond).order_by(s.expiry_date, Product.sku)
    result = await run_query(ctx, q, _stock_cols([Col("days_left", "Days left", "qty")]), title)
    result.summary = await _stock_value(ctx, cond)
    return result


@report("stock/slow-moving", "Slow-moving and dead stock", "reports.stock")
async def slow_moving(ctx: Ctx) -> Result:
    """On hand per branch and medicine with no sale in the last N days (dead: never sold)."""
    days = int(ctx.f.extra.get("days") or 90)
    since = clock.today() - timedelta(days=days)
    s, d = StockRow, SalesDaily
    last = (select(d.branch_id, d.medicine_id, func.max(d.day).label("last_sale"))
            .where(in_branches(d.branch_id, ctx.branches)).group_by(d.branch_id, d.medicine_id).subquery())  # fmt: skip
    q = (select(KnownBranch.code.label("branch"), Product.sku.label("sku"), Product.brand_name.label("name"),
                func.sum(s.qty_on_hand).label("qty_on_hand"),
                func.round(func.sum(s.qty_on_hand * s.cost_per_base), 2).label("value"),
                last.c.last_sale.label("last_sale"))
         .join(Product, Product.id == s.medicine_id, isouter=True)
         .join(KnownBranch, KnownBranch.id == s.branch_id, isouter=True)
         .join(last, and_(last.c.branch_id == s.branch_id, last.c.medicine_id == s.medicine_id), isouter=True)
         .where(*_stock_cond(ctx), or_(last.c.last_sale.is_(None), last.c.last_sale < since))
         .group_by(KnownBranch.code, Product.sku, Product.brand_name, last.c.last_sale)
         .order_by(last.c.last_sale.nulls_first(), Product.sku))  # fmt: skip
    cols = [Col("branch", "Branch"), Col("sku", "SKU"), Col("name", "Medicine"), Col("qty_on_hand", "On hand", "qty"),
            Col("value", "Value", "money", "cost"), Col("last_sale", "Last sale (none = dead stock)", "date")]  # fmt: skip
    return await run_query(ctx, q, cols, f"No sale in {days} days")


@report("stock/abc", "ABC analysis", "reports.stock")
async def abc(ctx: Ctx) -> Result:
    """By net sales over the period: A = the items making the first 80 %, B the next 15 %, C the rest."""
    d, f = SalesDaily, ctx.f
    rows = (await ctx.session.execute(
        select(Product.sku, Product.brand_name, func.sum(d.net).label("net"), func.sum(d.qty_base).label("qty"))
        .join(Product, Product.id == d.medicine_id, isouter=True)
        .where(d.day.between(f.date_from, f.date_to), in_branches(d.branch_id, ctx.branches))
        .group_by(Product.sku, Product.brand_name).order_by(func.sum(d.net).desc(), Product.sku))).all()  # fmt: skip
    total = sum((r.net for r in rows), ZERO)
    out, running = [], ZERO
    for r in rows:
        before = running
        running += r.net
        share = before * 100 / total if total else ZERO
        out.append({"sku": r.sku, "name": r.brand_name, "qty_base": int(r.qty), "net": r.net,
                    "share_pct": pct(r.net, total), "cumulative_pct": pct(running, total),
                    "class": "A" if share < 80 else "B" if share < 95 else "C"})  # fmt: skip
    cols = [Col("class", "Class"), Col("sku", "SKU"), Col("name", "Medicine"), Col("qty_base", "Qty (base)", "qty"),
            Col("net", "Net sales", "money"), Col("share_pct", "Share %", "pct"),
            Col("cumulative_pct", "Cumulative %", "pct")]  # fmt: skip
    counts = {c: sum(1 for x in out if x["class"] == c) for c in "ABC"}
    return page(ctx, out, cols, "ABC analysis", total=total, **counts)


@report("movements", "Movement Detail", "reports.stock")
async def movements(ctx: Ctx) -> Result:
    m, f = Movement, ctx.f
    cond = [m.day.between(f.date_from, f.date_to), in_branches(m.branch_id, ctx.branches)]
    if f.medicine_id:
        cond.append(m.medicine_id == f.medicine_id)
    if f.extra.get("batch_id"):
        cond.append(m.batch_id == f.extra["batch_id"])
    if f.extra.get("type"):
        cond.append(m.type == f.extra["type"])
    q = (select(m.occurred_at.label("at"), KnownBranch.code.label("branch"), Product.sku.label("sku"),
                m.lot_no.label("lot_no"), m.expiry_date.label("expiry_date"), m.type.label("type"),
                m.delta.label("delta"), m.qty_after.label("qty_after"), m.ref_type.label("ref_type"),
                m.reason.label("reason"), Staff.name.label("by"), m.cost_per_base.label("cost_per_base"))
         .join(Product, Product.id == m.medicine_id, isouter=True)
         .join(KnownBranch, KnownBranch.id == m.branch_id, isouter=True)
         .join(Staff, Staff.id == m.created_by, isouter=True).where(*cond).order_by(m.occurred_at, m.seq))  # fmt: skip
    cols = [Col("at", "When", "date"), Col("branch", "Branch"), Col("sku", "SKU"), Col("lot_no", "Lot"),
            Col("expiry_date", "Expiry", "date"), Col("type", "Type"), Col("delta", "Change", "qty"),
            Col("qty_after", "Batch after", "qty"), Col("ref_type", "Reference"), Col("reason", "Reason"),
            Col("by", "By"), Col("cost_per_base", "Cost / base", "money", "cost")]  # fmt: skip
    return await run_query(ctx, q, cols, "Movement Detail")


@report("shrinkage", "Shrinkage", "reports.stock")
async def shrinkage(ctx: Ctx) -> Result:
    """Posted write-offs (shrinkage movements): quantity and value by reason, branch, item."""
    m, f = Movement, ctx.f
    cond = [m.type == "shrinkage", m.day.between(f.date_from, f.date_to), in_branches(m.branch_id, ctx.branches)]
    if f.medicine_id:
        cond.append(m.medicine_id == f.medicine_id)
    q = (select(m.reason_code.label("reason"), KnownBranch.code.label("branch"), Product.sku.label("sku"),
                Product.brand_name.label("name"), func.sum(-m.delta).label("qty_base"),
                func.round(func.sum(-m.delta * m.cost_per_base), 2).label("value"))
         .join(Product, Product.id == m.medicine_id, isouter=True)
         .join(KnownBranch, KnownBranch.id == m.branch_id, isouter=True).where(*cond)
         .group_by(m.reason_code, KnownBranch.code, Product.sku, Product.brand_name)
         .order_by(m.reason_code, KnownBranch.code, Product.sku))  # fmt: skip
    cols = [Col("reason", "Reason"), Col("branch", "Branch"), Col("sku", "SKU"), Col("name", "Medicine"),
            Col("qty_base", "Qty (base)", "qty"), Col("value", "Value", "money", "cost")]  # fmt: skip
    return await run_query(ctx, q, cols, "Shrinkage")


@report("counts/variances", "Stock take variances", "reports.stock")
async def count_variances(ctx: Ctx) -> Result:
    c, x, f = Count, CountLine, ctx.f
    day = func.date(func.timezone("Asia/Phnom_Penh", c.updated_at))
    q = (select(day.label("day"), c.number.label("count"), KnownBranch.code.label("branch"), c.status.label("status"),
                x.sku.label("sku"), x.lot_no.label("lot_no"), x.expected_qty.label("expected"),
                x.counted_qty.label("counted"), x.variance.label("variance"), x.value.label("value"))
         .join(c, c.id == x.count_id).join(KnownBranch, KnownBranch.id == c.branch_id, isouter=True)
         .where(c.status.in_(("review", "approved")), day.between(f.date_from, f.date_to),
                in_branches(c.branch_id, ctx.branches)).order_by(day, c.number, x.sku))  # fmt: skip
    cols = [Col("day", "Day", "date"), Col("count", "Stock take"), Col("branch", "Branch"), Col("status", "Status"),
            Col("sku", "SKU"), Col("lot_no", "Lot"), Col("expected", "Expected", "qty"), Col("counted", "Counted", "qty"),
            Col("variance", "Variance", "qty"), Col("value", "Value", "money", "cost")]  # fmt: skip
    return await run_query(ctx, q, cols, "Stock take variances")


@report("modifications", "Modification", "reports.stock")
async def modifications(ctx: Ctx) -> Result:
    m, f = Modification, ctx.f
    q = (select(m.occurred_at, m.action, m.entity_type, m.entity_id, Staff.name.label("by"), m.changes)
         .join(Staff, Staff.id == m.actor_id, isouter=True)
         .where(m.day.between(f.date_from, f.date_to)).order_by(m.occurred_at))  # fmt: skip
    rows = []
    for r in (await ctx.session.execute(q)).all():
        for c in r.changes or [{"field": "", "old": None, "new": None}]:
            rows.append({"at": r.occurred_at, "action": r.action, "entity": r.entity_type, "entity_id": r.entity_id,
                         "by": r.by, "field": c["field"], "old": c["old"], "new": c["new"]})  # fmt: skip
    cols = [Col("at", "When", "date"), Col("action", "Action"), Col("entity", "What"), Col("entity_id", "Id"),
            Col("by", "By"), Col("field", "Field"), Col("old", "Old"), Col("new", "New")]  # fmt: skip
    return page(ctx, rows, cols, "Modification (price and product changes)")


# ---------------------------------------------------------------- purchasing, transfers


def _receipt_cond(ctx: Ctx) -> list[Any]:
    r, f = ReceiptLine, ctx.f
    cond = [r.day.between(f.date_from, f.date_to), in_branches(r.branch_id, ctx.branches)]
    if f.supplier_id:
        cond.append(r.supplier_id == f.supplier_id)
    if f.medicine_id:
        cond.append(r.medicine_id == f.medicine_id)
    return cond


@report("purchases/by-item", "Purchase By Item", "reports.purchases")
async def purchases_by_item(ctx: Ctx) -> Result:
    r = ReceiptLine
    q = (select(Product.sku.label("sku"), Product.brand_name.label("name"), Supplier.name.label("supplier"),
                func.count(func.distinct(r.receipt_id)).label("receipts"), func.sum(r.qty_base).label("qty_base"),
                func.sum(r.line_total).label("total"),
                func.round(func.sum(r.line_total) / func.nullif(func.sum(r.qty_base), 0), 4).label("avg_cost"))
         .join(Product, Product.id == r.medicine_id, isouter=True).join(Supplier, Supplier.id == r.supplier_id, isouter=True)
         .where(*_receipt_cond(ctx)).group_by(Product.sku, Product.brand_name, Supplier.name)
         .order_by(Product.sku, Supplier.name))  # fmt: skip
    cols = [Col("sku", "SKU"), Col("name", "Medicine"), Col("supplier", "Supplier"), Col("receipts", "Receipts", "qty"),
            Col("qty_base", "Qty (base)", "qty"), Col("total", "Cost", "money", "purchase"),
            Col("avg_cost", "Average cost / base", "money", "purchase")]  # fmt: skip
    return await run_query(ctx, q, cols, "Purchase By Item")


@report("purchases/by-supplier", "Purchases by supplier", "reports.purchases")
async def purchases_by_supplier(ctx: Ctx) -> Result:
    r = ReceiptLine
    q = (select(Supplier.name.label("supplier"), func.count(func.distinct(r.receipt_id)).label("receipts"),
                func.count(func.distinct(r.medicine_id)).label("items"), func.sum(r.line_total).label("total"))
         .join(Supplier, Supplier.id == r.supplier_id, isouter=True).where(*_receipt_cond(ctx))
         .group_by(Supplier.name).order_by(func.sum(r.line_total).desc()))  # fmt: skip
    cols = [Col("supplier", "Supplier"), Col("receipts", "Receipts", "qty"), Col("items", "Items", "qty"),
            Col("total", "Purchased", "money", "purchase")]  # fmt: skip
    return await run_query(ctx, q, cols, "Purchases by supplier")


@report("purchases/cost-changes", "Cost change", "reports.purchases")
async def cost_changes(ctx: Ctx) -> Result:
    """cost_per_base per medicine per receipt, with the change from the previous
    receipt of that medicine (any branch, any supplier)."""
    r = ReceiptLine
    prev = func.lag(r.cost_per_base).over(partition_by=r.medicine_id, order_by=(r.received_at, r.id))
    inner = (select(r.id, r.day, r.number, r.branch_id, r.supplier_id, r.medicine_id, r.lot_no, r.qty_base,
                    r.cost_per_base, prev.label("previous"))
             .where(in_branches(r.branch_id, ctx.branches)).subquery())  # fmt: skip
    f = ctx.f
    cond = [inner.c.day.between(f.date_from, f.date_to)]
    if f.supplier_id:
        cond.append(inner.c.supplier_id == f.supplier_id)
    if f.medicine_id:
        cond.append(inner.c.medicine_id == f.medicine_id)
    if f.extra.get("changed_only") in ("1", "true", True):
        cond.append(inner.c.previous.is_not(None) & (inner.c.previous != inner.c.cost_per_base))
    change = inner.c.cost_per_base - inner.c.previous
    q = (select(inner.c.day.label("day"), inner.c.number.label("receipt"), KnownBranch.code.label("branch"),
                Supplier.name.label("supplier"), Product.sku.label("sku"), Product.brand_name.label("name"),
                inner.c.lot_no.label("lot_no"), inner.c.qty_base.label("qty_base"),
                inner.c.cost_per_base.label("cost_per_base"), inner.c.previous.label("previous"),
                change.label("change"),
                case((inner.c.previous > 0, func.round(change * 100 / inner.c.previous, 2)), else_=None).label("change_pct"))
         .join(Product, Product.id == inner.c.medicine_id, isouter=True)
         .join(Supplier, Supplier.id == inner.c.supplier_id, isouter=True)
         .join(KnownBranch, KnownBranch.id == inner.c.branch_id, isouter=True)
         .where(*cond).order_by(Product.sku, inner.c.day, inner.c.number))  # fmt: skip
    cols = [Col("day", "Received", "date"), Col("receipt", "Receipt"), Col("branch", "Branch"),
            Col("supplier", "Supplier"), Col("sku", "SKU"), Col("name", "Medicine"), Col("lot_no", "Lot"),
            Col("qty_base", "Qty (base)", "qty"), Col("cost_per_base", "Cost / base", "money", "purchase"),
            Col("previous", "Previous cost / base", "money", "purchase"), Col("change", "Change", "money", "purchase"),
            Col("change_pct", "Change %", "pct", "purchase")]  # fmt: skip
    return await run_query(ctx, q, cols, "Cost change")


BUCKETS = (("not_due", None), ("d0_30", 30), ("d31_60", 60), ("d61_90", 90), ("d90_plus", None))


def _bucket(days_late: int) -> str:
    if days_late <= 0:
        return "not_due"
    return "d0_30" if days_late <= 30 else "d31_60" if days_late <= 60 else "d61_90" if days_late <= 90 else "d90_plus"


def _aging_cols(party: str) -> list[Col]:
    return [Col("party", party), Col("documents", "Open", "qty"), Col("not_due", "Not due", "money"),
            Col("d0_30", "1–30 days", "money"), Col("d31_60", "31–60", "money"), Col("d61_90", "61–90", "money"),
            Col("d90_plus", "90+", "money"), Col("total", "Total", "money")]  # fmt: skip


def _aging(items: list[tuple[str, int, Decimal]]) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for party, late, amount in items:
        row = by.setdefault(party, {"party": party, "documents": 0, **{b: ZERO for b, _ in BUCKETS}, "total": ZERO})
        row["documents"] += 1
        row[_bucket(late)] += amount
        row["total"] += amount
    return sorted(by.values(), key=lambda r: -r["total"])


@report("payables/aging", "Payables aging", "reports.purchases", "purchasing.pay")
async def payables_aging(ctx: Ctx) -> Result:
    """Open supplier bills by days past their due date (as of today)."""
    b, a, today = Bill, BillAllocation, clock.today()
    paid = select(a.bill_id, func.sum(a.amount).label("paid")).group_by(a.bill_id).subquery()
    cond = [in_branches(b.branch_id, ctx.branches)]
    if ctx.f.supplier_id:
        cond.append(b.supplier_id == ctx.f.supplier_id)
    rows = (await ctx.session.execute(
        select(Supplier.name, b.due_on, b.total - func.coalesce(paid.c.paid, 0))
        .join(paid, paid.c.bill_id == b.id, isouter=True).join(Supplier, Supplier.id == b.supplier_id, isouter=True)
        .where(*cond, b.total - func.coalesce(paid.c.paid, 0) > 0))).all()  # fmt: skip
    out = _aging([(name or "?", (today - due).days, open_) for name, due, open_ in rows])
    return page(ctx, out, _aging_cols("Supplier"), "Payables aging", total=sum((r["total"] for r in out), ZERO))


@report("receivables/aging", "Receivables aging", "reports.customers")
async def receivables_aging(ctx: Ctx) -> Result:
    """Open credit sales by age (days since the sale; customers have no due date)."""
    d, a, today = Debt, DebtAllocation, clock.today()
    paid = (select(Invoice.id.label("invoice_id"), func.sum(a.amount).label("paid"))
            .join(Invoice, Invoice.number == a.invoice_no).group_by(Invoice.id).subquery())  # fmt: skip
    open_ = d.amount - d.reversed - func.coalesce(paid.c.paid, 0)
    cond = [in_branches(d.branch_id, ctx.branches), open_ > 0]
    if ctx.f.customer_id:
        cond.append(d.customer_id == ctx.f.customer_id)
    rows = (await ctx.session.execute(
        select(Customer.name, d.charged_on, open_).join(paid, paid.c.invoice_id == d.invoice_id, isouter=True)
        .join(Customer, Customer.id == d.customer_id, isouter=True).where(*cond))).all()  # fmt: skip
    out = _aging([(name or "?", (today - day).days, amount) for name, day, amount in rows])
    cols = _aging_cols("Customer")
    cols[2] = Col("not_due", "Today", "money")
    return page(ctx, out, cols, "Receivables aging", total=sum((r["total"] for r in out), ZERO))


@report("customers/top", "Top customers", "reports.customers")
async def top_customers(ctx: Ctx) -> Result:
    x = InvoiceLine
    q = (select(Customer.name.label("customer"), func.count(func.distinct(x.invoice_id)).label("invoices"),
                func.sum(x.net).label("net"), func.max(x.sale_date).label("last_sale"))
         .join(Customer, Customer.id == x.customer_id).where(_lines(ctx))
         .group_by(Customer.name).order_by(func.sum(x.net).desc()))  # fmt: skip
    cols = [Col("customer", "Customer"), Col("invoices", "Invoices", "qty"), Col("net", "Net sales", "money"),
            Col("last_sale", "Last sale", "date")]  # fmt: skip
    return await run_query(ctx, q, cols, "Top customers")


def _sent(t: Transfer) -> tuple[int, int, int]:
    picks = t.data.get("picks") or []
    sent = sum(p["qty_base"] for p in picks) if t.dispatched_at else 0
    received = sum(p.get("qty_received") or 0 for p in picks)
    diffs = sum(d["qty_base"] for d in t.data.get("discrepancies") or [])
    return sent, received, diffs


def _transfer_scope(ctx: Ctx) -> Any:
    t = Transfer
    if ctx.branches is None:
        return t.id.is_not(None)
    return or_(t.from_branch_id.in_(ctx.branches), t.to_branch_id.in_(ctx.branches))


@report("transfers", "Stock Transfer", "reports.purchases")
async def transfers(ctx: Ctx) -> Result:
    t, f = Transfer, ctx.f
    day = func.date(func.timezone("Asia/Phnom_Penh", t.created_at))
    rows = []
    for x in (await ctx.session.execute(select(t).where(_transfer_scope(ctx), day.between(f.date_from, f.date_to))
                                         .order_by(t.created_at))).scalars():  # fmt: skip
        sent, received, diffs = _sent(x)
        rows.append({"number": x.number, "from": x.data["from_branch"]["code"], "to": x.data["to_branch"]["code"],
                     "status": x.status, "created_at": x.created_at, "dispatched_at": x.dispatched_at,
                     "received_at": x.received_at, "sent": sent, "received": received, "differences": diffs})  # fmt: skip
    cols = [Col("number", "Transfer"), Col("from", "From"), Col("to", "To"), Col("status", "Status"),
            Col("created_at", "Created", "date"), Col("dispatched_at", "Sent", "date"),
            Col("received_at", "Received", "date"), Col("sent", "Qty sent", "qty"),
            Col("received", "Qty received", "qty"), Col("differences", "Differences", "qty")]  # fmt: skip
    return page(ctx, rows, cols, "Stock Transfer")


@report("transfers/in-transit", "In transit", "reports.purchases")
async def in_transit(ctx: Ctx) -> Result:
    t = Transfer
    rows = []
    for x in (await ctx.session.execute(select(t).where(_transfer_scope(ctx), t.status == "dispatched")
                                         .order_by(t.dispatched_at))).scalars():  # fmt: skip
        lines = {line["line_no"]: line for line in x.data.get("lines") or []}
        for p in x.data.get("picks") or []:
            line = lines.get(p["line_no"], {})
            rows.append({"number": x.number, "from": x.data["from_branch"]["code"], "to": x.data["to_branch"]["code"],
                         "dispatched_at": x.dispatched_at, "sku": line.get("sku"), "lot_no": p["lot_no"],
                         "qty_base": p["qty_base"], "value": Decimal(p["cost_per_base"]) * p["qty_base"]})  # fmt: skip
    cols = [Col("number", "Transfer"), Col("from", "From"), Col("to", "To"), Col("dispatched_at", "Sent", "date"),
            Col("sku", "SKU"), Col("lot_no", "Lot"), Col("qty_base", "Qty (base)", "qty"),
            Col("value", "Value", "money", "cost")]  # fmt: skip
    return page(ctx, rows, cols, "In transit")


# ---------------------------------------------------------------- commission, Rx, controlled


@report("commission", "Commission", "commission.view_own|commission.manage")
async def commission(ctx: Ctx) -> Result:
    """Per staff and month (the month the line was booked in). commission.view_own: yourself only."""
    c, f = CommissionLine, ctx.f
    cond = [c.month.between(f.date_from.replace(day=1), f.date_to), in_branches(c.branch_id, ctx.branches)]
    if not (ctx.user.is_owner or ctx.user.has("commission.manage")):
        cond.append(c.staff_id == ctx.user.id)
    elif f.staff_id:
        cond.append(c.staff_id == f.staff_id)
    q = (select(c.month.label("month"), KnownBranch.code.label("branch"), Staff.name.label("staff"),
                func.count().label("lines"), func.sum(c.net_usd).label("net_usd"), func.sum(c.amount).label("commission"))
         .join(KnownBranch, KnownBranch.id == c.branch_id, isouter=True).join(Staff, Staff.id == c.staff_id, isouter=True)
         .where(*cond).group_by(c.month, KnownBranch.code, Staff.name).order_by(c.month, KnownBranch.code, Staff.name))  # fmt: skip
    cols = [Col("month", "Month", "date"), Col("branch", "Branch"), Col("staff", "Staff"), Col("lines", "Lines", "qty"),
            Col("net_usd", "Net sales", "money"), Col("commission", "Commission", "money")]  # fmt: skip
    return await run_query(ctx, q, cols, "Commission")


@report("rx/dispensing", "Rx dispensing", "reports.sales", "prescriptions.view")
async def rx_dispensing(ctx: Ctx) -> Result:
    """Rx lines sold: Rx number, medicine, qty, pharmacist, doctor. No patient data (choice F)."""
    x = InvoiceLine
    q = (select(x.sale_date.label("day"), Invoice.number.label("invoice"), KnownBranch.code.label("branch"),
                x.rx_number.label("rx_number"), x.sku.label("sku"), x.name.label("name"), x.qty_base.label("qty_base"),
                x.is_controlled.label("controlled"), Staff.name.label("pharmacist"), x.doctor_name.label("doctor"))
         .join(Invoice, Invoice.id == x.invoice_id).join(KnownBranch, KnownBranch.id == x.branch_id, isouter=True)
         .join(Staff, Staff.id == x.staff_id, isouter=True).where(_lines(ctx), x.is_rx.is_(True))
         .order_by(x.sale_date, Invoice.number, x.line_no))  # fmt: skip
    cols = [Col("day", "Day", "date"), Col("invoice", "Invoice"), Col("branch", "Branch"), Col("rx_number", "Rx"),
            Col("sku", "SKU"), Col("name", "Medicine"), Col("qty_base", "Qty (base)", "qty"),
            Col("controlled", "Controlled"), Col("pharmacist", "Pharmacist"), Col("doctor", "Doctor")]  # fmt: skip
    return await run_query(ctx, q, cols, "Rx dispensing")


@report("controlled/summary", "Controlled register summary", "controlled.view")
async def controlled_summary(ctx: Ctx) -> Result:
    """Per branch and controlled medicine: opening, received, sold, adjusted, closing
    (from the same stock movements the register is built from) and open issues."""
    m, f = Movement, ctx.f
    base = [m.is_controlled.is_(True), in_branches(m.branch_id, ctx.branches)]
    if f.medicine_id:
        base.append(m.medicine_id == f.medicine_id)
    period = m.day.between(f.date_from, f.date_to)

    def part(cond: Any) -> Any:
        return func.coalesce(func.sum(case((and_(period, cond), m.delta), else_=0)), 0)

    q = (select(m.branch_id, m.medicine_id,
                func.coalesce(func.sum(case((m.day < f.date_from, m.delta), else_=0)), 0).label("opening"),
                part(m.type.in_(("in", "opening", "transfer_in"))).label("received"),
                part(m.type.in_(("out", "sale_cancel", "return"))).label("sold"),
                part(m.type.notin_(("in", "opening", "transfer_in", "out", "sale_cancel", "return"))).label("adjusted"),
                func.coalesce(func.sum(case((m.day <= f.date_to, m.delta), else_=0)), 0).label("closing"))
         .where(*base).group_by(m.branch_id, m.medicine_id))  # fmt: skip
    rows = (await ctx.session.execute(q)).all()
    issues = dict((await ctx.session.execute(
        select(RegisterIssue.branch_id, func.count()).where(RegisterIssue.status == "open",
                                                            in_branches(RegisterIssue.branch_id, ctx.branches))
        .group_by(RegisterIssue.branch_id))).all())  # fmt: skip
    names = {p.id: p for p in (await ctx.session.execute(select(Product).where(
        Product.id.in_([r.medicine_id for r in rows])))).scalars()} if rows else {}  # fmt: skip
    branches = {b.id: b.code for b in (await ctx.session.execute(select(KnownBranch))).scalars()}
    out = [{"branch": branches.get(r.branch_id, ""), "sku": names[r.medicine_id].sku if r.medicine_id in names else "",
            "schedule": names[r.medicine_id].controlled_schedule if r.medicine_id in names else "",
            "opening": int(r.opening), "received": int(r.received), "sold": int(r.sold), "adjusted": int(r.adjusted),
            "closing": int(r.closing)} for r in rows]  # fmt: skip
    out.sort(key=lambda r: (r["branch"], r["sku"]))
    cols = [Col("branch", "Branch"), Col("sku", "SKU"), Col("schedule", "Schedule"), Col("opening", "Opening", "qty"),
            Col("received", "Received", "qty"), Col("sold", "Sold (net)", "qty"), Col("adjusted", "Adjusted", "qty"),
            Col("closing", "Closing", "qty")]  # fmt: skip
    return page(ctx, out, cols, "Controlled register summary",
                open_issues=sum(issues.values()))  # fmt: skip

