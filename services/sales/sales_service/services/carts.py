"""Suspend / resume a POS cart (sales.suspend). Rules:

- Parking a cart keeps its lines as sent (medicine, pack, quantity, Rx links,
  manual discounts), the customer and a note, with the prices and promotions as
  shown then. Number PP1-SP-2026-000001. No stock is reserved.
- Any terminal of the same branch can resume it: prices and promotions are
  worked out again and stock is checked again (nothing reserved); every change
  (price, promotion, discount, not enough stock) is listed for the cashier. The
  cashier then sells it as a normal sale.
- Carts not resumed by the end of the day (Asia/Phnom_Penh) expire at 00:01
  and are kept for audit. Never deleted. Every step is in the User Log.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.db import Database
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.numbering import next_number

from ..models import DocSequence, KnownCustomer, SuspendedCart
from .cart import price_cart
from .clients import Clients
from .common import audit, branch_for, clean

log = logging.getLogger(__name__)
LOCK_KEY = 7_202_670


async def _customer(session: AsyncSession, customer_id: UUID | None) -> KnownCustomer | None:
    return await session.get(KnownCustomer, customer_id) if customer_id else None


def _jsonable(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: (str(v) if v is not None and not isinstance(v, (int, bool, str)) else v) for k, v in x.items()}
            for x in lines]  # fmt: skip


async def suspend(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> SuspendedCart:
    branch = await branch_for(session, actor, data["branch_id"])
    customer = await _customer(session, data.get("customer_id"))
    priced = await price_cart(session, branch.id, customer, data["lines"])
    cart = SuspendedCart(branch_id=branch.id, customer_id=customer.id if customer else None,
                         note=clean(data.get("note")), lines=_jsonable(data["lines"]),
                         priced=[x.as_dict() for x in priced], total=sum((x.net for x in priced), 0),
                         status="suspended", business_date=clock.today(), created_by=actor.id)  # fmt: skip
    cart.number = await next_number(session, DocSequence, branch.id, branch.code, "SP")
    session.add(cart)
    await session.flush()
    audit(session, actor, "cart.suspended", "cart", cart.id, branch_id=branch.id,
          after={"number": cart.number, "lines": len(cart.lines), "total": str(cart.total), "note": cart.note})  # fmt: skip
    await session.commit()
    return cart


async def list_carts(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID, status: str
) -> list[SuspendedCart]:
    actor.require_branch(branch_id)
    return list((await session.execute(select(SuspendedCart).where(
        SuspendedCart.branch_id == branch_id, SuspendedCart.status == status)
        .order_by(SuspendedCart.created_at))).scalars())  # fmt: skip


def _changes(before: list[dict[str, Any]], now: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for old, new in zip(before, now, strict=True):
        for key, what in (
            ("unit_price", "price"),
            ("promo_discount", "promotion"),
            ("manual_discount", "discount"),
        ):
            if old[key] != new[key]:
                out.append({"line_no": new["line_no"], "sku": new["sku"], "change": what, "was": old[key],
                            "now": new[key]})  # fmt: skip
    return out


async def resume(
    session: AsyncSession, actor: CurrentUser, clients: Clients, cart_id: UUID
) -> dict[str, Any]:
    cart = (await session.execute(select(SuspendedCart).where(SuspendedCart.id == cart_id).with_for_update())
            ).scalar_one_or_none()  # fmt: skip
    if cart is None or not actor.can_access_branch(cart.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Suspended cart not found", status_code=404)
    if cart.status != "suspended":
        raise AppError(ErrorCode.CART_STATE, f"Cart {cart.number} is {cart.status}", status_code=409,
                       details={"status": cart.status})  # fmt: skip
    raw = [
        {**x, "medicine_id": UUID(x["medicine_id"]), "pack_unit_id": UUID(x["pack_unit_id"])}
        for x in cart.lines
    ]
    priced = await price_cart(session, cart.branch_id, await _customer(session, cart.customer_id), raw)
    now = [x.as_dict() for x in priced]
    changes = _changes(cart.priced, now)
    stock = await clients.inventory.post("/stock/available", {"branch_id": str(cart.branch_id), "items": [
        {"medicine_id": d["medicine_id"], "qty_base": x.qty_base} for d, x in zip(now, priced, strict=True)]},
        actor=actor, branch_id=cart.branch_id)  # fmt: skip
    for d, s in zip(now, stock["items"], strict=True):
        if not s["enough"]:
            changes.append({"line_no": d["line_no"], "sku": d["sku"], "change": "stock", "was": s["requested"],
                            "now": s["available"]})  # fmt: skip
    cart.status, cart.resumed_by, cart.resumed_at = "resumed", actor.id, clock.now()
    audit(session, actor, "cart.resumed", "cart", cart.id, branch_id=cart.branch_id,
          after={"number": cart.number, "changes": len(changes)})  # fmt: skip
    await session.commit()
    return {"cart_id": cart.id, "number": cart.number, "customer_id": cart.customer_id, "note": cart.note,
            "lines": [{**r, **{k: d[k] for k in ("unit_price", "line_total", "promo_discount", "promotion_ids",
                                                   "manual_discount", "net", "sku", "name", "pack_unit")}}
                      for r, d in zip(cart.lines, now, strict=True)],
            "total": str(sum((x.net for x in priced), 0)), "changes": changes}  # fmt: skip


async def expire(session: AsyncSession, today: Any) -> int | None:
    """Carts parked before today (Asia/Phnom_Penh) and never resumed → expired (kept)."""
    if not (
        await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
    ).scalar_one():
        await session.rollback()
        return None
    carts = list((await session.execute(select(SuspendedCart).where(
        SuspendedCart.status == "suspended", SuspendedCart.business_date < today).with_for_update())).scalars())  # fmt: skip
    for cart in carts:
        cart.status, cart.expired_at = "expired", clock.now()
        audit(
            session,
            None,
            "cart.expired",
            "cart",
            cart.id,
            branch_id=cart.branch_id,
            after={"number": cart.number},
        )
    await session.commit()
    return len(carts)


async def run_scheduler(db: Database, stop: asyncio.Event, hour: int = 0, minute: int = 1) -> None:
    """00:01 Asia/Phnom_Penh (and at start-up)."""
    while not stop.is_set():
        try:
            async with db.sessionmaker() as session:
                done = await expire(session, clock.today())
            if done:
                log.info("suspended carts expired: %s", done)
        except Exception:  # noqa: BLE001
            log.exception("cart expiry failed")
        now_local = datetime.now(clock.TIMEZONE)
        target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now_local:
            target += timedelta(days=1)
        try:
            await asyncio.wait_for(stop.wait(), timeout=(target - now_local).total_seconds())
        except TimeoutError:
            pass
