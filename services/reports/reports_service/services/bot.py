"""T2 phase 3: the figures behind the Telegram bot commands (notification asks over /internal/v1/bot/…).

Branches are the caller's (the notification service passes the user's branches; none = every branch, the owner).
Cost and profit only when `profit` is asked (the user may see cost and the chat may show it). Customer names only
when `names` is asked (a private chat). Same read models as the dashboard (built from events).
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock

from ..models import Invoice, KnownBranch, Payment, Product, ProductPackUnit, StockRow
from . import dashboard
from .common import in_branches, plain


def _time(value: datetime | None) -> str | None:
    return value.astimezone(clock.TIMEZONE).strftime("%H:%M") if value else None


async def branches_of(session: AsyncSession, ids: list[UUID] | None) -> list[dict[str, Any]]:
    rows = (await session.execute(select(KnownBranch).where(KnownBranch.is_active.is_(True),
                                                            in_branches(KnownBranch.id, ids))
                                  .order_by(KnownBranch.code))).scalars()  # fmt: skip
    return [{"id": str(b.id), "code": b.code, "name_en": b.name_en, "name_km": b.name_km} for b in rows]


async def sale_times(session: AsyncSession, branches: list[UUID] | None, day: date) -> dict[str, str | None]:
    first, last = (await session.execute(select(func.min(Invoice.completed_at), func.max(Invoice.completed_at)).where(
        Invoice.sale_date == day, Invoice.status == "completed", in_branches(Invoice.branch_id, branches)))).one()  # fmt: skip
    return {"first_sale": _time(first), "last_sale": _time(last)}


async def day(session: AsyncSession, branches: list[UUID] | None, on: date, profit: bool) -> dict[str, Any]:
    """/today, /yesterday, /branch: the day's figures, top 3, first and last sale."""
    return {"day": on.isoformat(), "branches": await branches_of(session, branches),
            "figures": await dashboard.day_figures(session, branches, on, profit),
            "top": await dashboard.top_medicines(session, branches, on, 3), **await sale_times(session, branches, on)}  # fmt: skip


async def top(session: AsyncSession, branches: list[UUID] | None, on: date, n: int = 10) -> dict[str, Any]:
    return {"day": on.isoformat(), "items": await dashboard.top_medicines(session, branches, on, n)}


async def cash(session: AsyncSession, branches: list[UUID] | None, on: date) -> dict[str, Any]:
    """/cash: the day's money in and out per method and currency (sales, change, refunds, customer payments,
    deposits, supplier payments – signed), as in the payments report."""
    rows = (await session.execute(select(Payment.method, Payment.currency, func.sum(Payment.amount),
                                         func.sum(Payment.amount_usd)).where(
        Payment.day == on, in_branches(Payment.branch_id, branches))
        .group_by(Payment.method, Payment.currency).order_by(Payment.method, Payment.currency))).all()  # fmt: skip
    items = [{"method": m, "currency": c, "amount": plain(a), "amount_usd": plain(u)} for m, c, a, u in rows]
    total = sum((u for _, _, _, u in rows), 0)
    return {"day": on.isoformat(), "items": items, "total_usd": plain(total) if rows else "0.00"}


async def debtors(session: AsyncSession, branches: list[UUID] | None, n: int, names: bool) -> dict[str, Any]:
    rows = await dashboard.top_debtors(session, branches, n)
    if not names:
        rows = [{"customer": None, "owes": r["owes"]} for r in rows]
    return {"items": rows}


async def expiring(session: AsyncSession, branches: list[UUID] | None, on: date) -> dict[str, Any]:
    return await dashboard.near_expiry(session, branches, on)


async def stock(session: AsyncSession, branches: list[UUID] | None, q: str, on: date) -> dict[str, Any]:
    """/stock <name or barcode>: up to 5 medicines (barcode exact, else SKU / names), on hand (not expired) per
    branch."""
    q = q.strip()[:60]
    if not q:
        return {"items": []}
    by_barcode = (await session.execute(select(ProductPackUnit.product_id).where(ProductPackUnit.barcode == q))).scalars().all()
    if by_barcode:
        found = (await session.execute(select(Product).where(Product.id.in_(by_barcode)))).scalars().all()
    else:
        like = f"%{q}%"
        found = (await session.execute(select(Product).where(Product.is_active.is_(True), or_(
            Product.sku.ilike(like), Product.brand_name.ilike(like), Product.generic_name.ilike(like),
            Product.name_km.ilike(like))).order_by(Product.sku).limit(5))).scalars().all()  # fmt: skip
    names = {b["id"]: b["code"] for b in await branches_of(session, branches)}
    items = []
    for p in found[:5]:
        rows = (await session.execute(select(StockRow.branch_id, func.sum(StockRow.qty_on_hand)).where(
            StockRow.medicine_id == p.id, StockRow.expiry_date >= on, in_branches(StockRow.branch_id, branches))
            .group_by(StockRow.branch_id))).all()  # fmt: skip
        per = {names.get(str(b), "?"): int(qty) for b, qty in rows if str(b) in names}
        items.append({"sku": p.sku, "name": p.display_name, "base_unit": p.base_unit, "on_hand": per,
                      "total": sum(per.values())})  # fmt: skip
    return {"items": items}
