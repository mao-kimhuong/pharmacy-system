"""Promotions at the till. Rules:

- The rules are a copy of the catalog's (promotion.* events; older versions
  ignored; a re-send by `make resync` refreshes an equal version).
- A promotion applies when active, inside its from / to window and days of the
  week (Asia/Phnom_Penh), for the branch, for the customer's group (when groups
  are listed), and while uses are left in total and for the customer.
- pricing.best_deal picks the best option for the customer.
- Uses: held when the sale is saved (promotion rows locked, limits counted
  again: PROMOTION_LIMIT), used when it completes, released when it fails, is
  cancelled or fully returned.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import KnownCustomer, PromotionCopy, PromotionUse
from .pricing import PriceLine, Promo, Result, best_deal

COUNTED = ("held", "used")


async def upsert(session: AsyncSession, p: dict[str, Any]) -> bool:
    promotion_id, version = UUID(p["promotion_id"]), int(p["version"])
    stored = (await session.execute(select(PromotionCopy.version).where(PromotionCopy.id == promotion_id)
                                    .with_for_update())).scalar_one_or_none()  # fmt: skip
    if stored is not None and (stored > version or (stored == version and not p.get("resync"))):
        return False
    values = {
        "id": promotion_id,
        "version": version,
        "code": p["code"],
        "is_active": bool(p["is_active"]),
        "data": p,
    }
    await session.execute(insert(PromotionCopy).values(**values).on_conflict_do_update(
        index_elements=[PromotionCopy.id], set_={k: v for k, v in values.items() if k != "id"}))  # fmt: skip
    return True


def _promo(row: PromotionCopy) -> Promo:
    d = row.data
    return Promo(
        id=row.id, code=row.code, type=d["type"], value=Decimal(d["value"]) if d.get("value") is not None else None,
        buy_qty=d.get("buy_qty"), get_qty=d.get("get_qty"),
        tiers=tuple((int(t["min_qty"]), Decimal(str(t["percent"]))) for t in d.get("tiers") or []),
        bundle_items=tuple((UUID(b["medicine_id"]), int(b["qty_base"])) for b in d.get("bundle_items") or []),
        medicine_ids=frozenset(UUID(x) for x in d.get("medicine_ids") or []),
        category_ids=frozenset(UUID(x) for x in d.get("category_ids") or []),
        brand_ids=frozenset(UUID(x) for x in d.get("brand_ids") or []),
        stackable=bool(d.get("stackable")), include_rx=bool(d.get("include_rx")),
    )  # fmt: skip


def _in_window(d: dict[str, Any], now: datetime) -> bool:
    if d.get("starts_at") and now < datetime.fromisoformat(d["starts_at"]):
        return False
    if d.get("ends_at") and now >= datetime.fromisoformat(d["ends_at"]):
        return False
    days = d.get("days_of_week") or []
    return not days or now.astimezone(clock.TIMEZONE).weekday() in days


async def _uses(session: AsyncSession, promotion_id: UUID, customer_id: UUID | None, exclude: UUID | None = None
                ) -> tuple[int, int]:  # fmt: skip
    base = select(func.count()).select_from(PromotionUse).where(
        PromotionUse.promotion_id == promotion_id, PromotionUse.status.in_(COUNTED))  # fmt: skip
    if exclude:
        base = base.where(PromotionUse.invoice_id != exclude)
    total = (await session.execute(base)).scalar_one()
    mine = (
        (await session.execute(base.where(PromotionUse.customer_id == customer_id))).scalar_one()
        if customer_id
        else 0
    )
    return int(total), int(mine)


def _limits_ok(d: dict[str, Any], total: int, mine: int, customer_id: UUID | None) -> bool:
    if d.get("max_uses_total") is not None and total >= d["max_uses_total"]:
        return False
    if d.get("max_uses_per_customer") is not None and (
        customer_id is None or mine >= d["max_uses_per_customer"]
    ):
        return False
    return True


async def applicable(session: AsyncSession, branch_id: UUID, customer: KnownCustomer | None) -> list[Promo]:
    now = clock.now()
    out = []
    for row in (
        await session.execute(select(PromotionCopy).where(PromotionCopy.is_active.is_(True)))
    ).scalars():
        d = row.data
        if not _in_window(d, now):
            continue
        if d.get("branch_ids") and str(branch_id) not in d["branch_ids"]:
            continue
        if d.get("customer_group_ids") and not (customer and customer.group_id and str(customer.group_id)
                                                in d["customer_group_ids"]):  # fmt: skip
            continue
        total, mine = await _uses(session, row.id, customer.id if customer else None)
        if _limits_ok(d, total, mine, customer.id if customer else None):
            out.append(_promo(row))
    return out


def eligible(d: dict[str, Any], branch_id: UUID, customer: KnownCustomer | None) -> bool:
    """Window, days, branch and customer group (not the use limits)."""
    if not _in_window(d, clock.now()):
        return False
    if d.get("branch_ids") and str(branch_id) not in d["branch_ids"]:
        return False
    return not (d.get("customer_group_ids") and not (customer and customer.group_id and str(customer.group_id)
                                                     in d["customer_group_ids"]))  # fmt: skip


def draft_promo(d: dict[str, Any]) -> Promo:
    """A promotion being written in the catalog (the promotion preview), never saved here."""
    return _promo(PromotionCopy(id=UUID(str(d["promotion_id"])), code=d["code"], version=0, is_active=True, data=d))


async def price(session: AsyncSession, branch_id: UUID, customer: KnownCustomer | None, lines: list[PriceLine],
                draft: dict[str, Any] | None = None) -> Result:  # fmt: skip
    """Best deal over the active promotions; a draft (promotion preview) is added to them,
    replacing the stored version of the same promotion."""
    promos = await applicable(session, branch_id, customer)
    if draft is not None:
        promos = [p for p in promos if str(p.id) != str(draft["promotion_id"])]
        if eligible(draft, branch_id, customer):
            promos.append(draft_promo(draft))
    return best_deal(promos, lines)


async def hold(
    session: AsyncSession, invoice_id: UUID, customer_id: UUID | None, promotion_ids: set[UUID]
) -> None:
    """In the transaction that saves the sale: rows locked in a fixed order, limits counted again."""
    for promotion_id in sorted(promotion_ids, key=str):
        row = (await session.execute(select(PromotionCopy).where(PromotionCopy.id == promotion_id)
                                     .with_for_update())).scalar_one()  # fmt: skip
        total, mine = await _uses(session, promotion_id, customer_id, exclude=invoice_id)
        if not row.is_active or not _limits_ok(row.data, total, mine, customer_id):
            raise AppError(ErrorCode.PROMOTION_LIMIT, f"Promotion {row.code} has just run out; price the cart again",
                           status_code=409, details={"promotion": row.code})  # fmt: skip
        await session.execute(insert(PromotionUse).values(promotion_id=promotion_id, invoice_id=invoice_id,
                                                          customer_id=customer_id, status="held")
                              .on_conflict_do_nothing())  # fmt: skip


async def set_status(session: AsyncSession, invoice_id: UUID, status: str) -> None:
    await session.execute(update(PromotionUse).where(PromotionUse.invoice_id == invoice_id, PromotionUse.status != status)
                          .values(status=status))  # fmt: skip
