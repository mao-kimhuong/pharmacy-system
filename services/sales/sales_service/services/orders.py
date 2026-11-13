"""Quotes and sale orders (sales.orders). Rules:

- A quote (PP1-SO-…, customer required) prices its lines now, promotions
  included; those prices are kept for the order (valid_until, 7 days by default).
- Confirm → ordered (Idempotency-Key): optionally reserve the stock (FEFO,
  inventory reservation "sale_order") until reserve_until (3 days by default, at
  most 14), and optionally take a deposit (customers; riel at the branch rate).
- Invoice all or part of the open quantity (Idempotency-Key): the normal sale
  saga – Rx, controlled PIN, pharmacist, discounts, below cost – at the order's
  prices; the order's reserved batches move to the invoice; the deposit can pay
  (payment method "deposit"). → partly_fulfilled / fulfilled. Cancelling such an
  invoice puts its quantities back on the order.
- Reservations past reserve_until are released (every 10 minutes and whenever
  the order is opened); the order stays, without reserved stock.
- Cancel (reason): quote / ordered / partly fulfilled; the reservation is
  released; what is left of the deposit follows the branch setting
  order_deposit_on_cancel – keep_as_credit (default), refund, or forfeit
  (forfeit only by a branch manager or the owner). Close: no more invoices; the
  rest of the deposit stays as credit. Never deleted.
- Every change: sale_order.* event (the document service prints the quote /
  order from it) and a User Log entry.
"""

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.db import Database
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event

from ..models import (
    BranchSettingsCopy,
    DocSequence,
    Invoice,
    InvoicePayment,
    KnownBranch,
    KnownCustomer,
    OutboxEvent,
    SaleOrder,
    SaleOrderLine,
)
from . import money, rates
from .cart import price_cart
from .clients import Clients
from .common import audit, branch_for, clean

log = logging.getLogger(__name__)
OPEN = ("ordered", "partly_fulfilled")
LOCK_KEY = 7_202_671


def _state(order: SaleOrder) -> AppError:
    return AppError(ErrorCode.ORDER_STATE, f"Order {order.number} is {order.status.replace('_', ' ')}",
                    status_code=409, details={"status": order.status})  # fmt: skip


async def remaining_usd(session: AsyncSession, o: SaleOrder) -> Decimal:
    """What the customer still pays at pickup: the open lines (at the order's net prices) minus the part of the
    deposit not used by the order's invoices yet."""
    open_value = sum(((x.line_total - x.promo_discount) * x.qty_open / x.qty for x in o.lines if x.qty),
                     Decimal("0"))  # fmt: skip
    used = (await session.execute(select(func.coalesce(func.sum(InvoicePayment.amount_usd), 0)).join(
        Invoice, Invoice.id == InvoicePayment.invoice_id).where(
        Invoice.sale_order_id == o.id, Invoice.status == "completed", InvoicePayment.method == "deposit"))).scalar_one()  # fmt: skip
    left = max(o.deposit_usd - Decimal(used), Decimal("0"))
    return max(money.usd(open_value) - left, Decimal("0.00"))


async def payload(session: AsyncSession, o: SaleOrder) -> dict[str, Any]:
    branch = await session.get(KnownBranch, o.branch_id)
    customer = await session.get(KnownCustomer, o.customer_id)
    return {
        "sale_order_id": str(o.id), "version": o.version, "number": o.number, "status": o.status,
        "branch": {"id": str(o.branch_id), "code": branch.code if branch else "", "name_en": branch.name_en if branch
                   else "", "name_km": branch.name_km if branch else ""},
        "customer": {"id": str(o.customer_id), "name": customer.name if customer else "",
                     "name_km": customer.name_km if customer else "", "phone": customer.phone if customer else ""},
        "note": o.note, "valid_until": o.valid_until.isoformat() if o.valid_until else None,
        "reserve_until": o.reserve_until.isoformat() if o.reserve_until else None,
        "deposit_usd": str(o.deposit_usd), "subtotal": str(o.subtotal), "discount": str(o.discount),
        "total": str(o.total), "created_at": o.created_at.isoformat() if o.created_at else None,
        "cancel_reason": o.cancel_reason, "ready_at": o.ready_at.isoformat() if o.ready_at else None,
        "remaining_usd": str(await remaining_usd(session, o)),
        "lines": [{"line_no": x.line_no, "medicine_id": str(x.medicine_id), "sku": x.sku, "name": x.name,
                   "name_km": x.name_km, "pack_unit": x.pack_unit, "qty": x.qty, "qty_invoiced": x.qty_invoiced,
                   "unit_price": str(x.unit_price), "line_total": str(x.line_total),
                   "promo_discount": str(x.promo_discount)} for x in o.lines],
    }  # fmt: skip


async def _publish(session: AsyncSession, o: SaleOrder, event: str) -> None:
    o.version += 1
    await session.flush()
    add_event(session, OutboxEvent, event, await payload(session, o))


async def get(session: AsyncSession, actor: CurrentUser, order_id: UUID, *, lock: bool = False) -> SaleOrder:
    query = select(SaleOrder).where(SaleOrder.id == order_id)
    if lock:
        query = query.with_for_update(of=SaleOrder).execution_options(populate_existing=True)
    o = (await session.execute(query)).scalar_one_or_none()
    if o is None or not actor.can_access_branch(o.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Sale order not found", status_code=404)
    return o


async def list_orders(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID, status: str | None
) -> list[SaleOrder]:
    actor.require_branch(branch_id)
    query = select(SaleOrder).where(SaleOrder.branch_id == branch_id)
    if status:
        query = query.where(SaleOrder.status == status)
    return list((await session.execute(query.order_by(SaleOrder.created_at.desc()).limit(500))).scalars())


async def create_quote(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> SaleOrder:
    branch = await branch_for(session, actor, data["branch_id"])
    customer = await session.get(KnownCustomer, data["customer_id"])
    if customer is None or not customer.is_active:
        raise AppError(ErrorCode.CUSTOMER_REQUIRED, "Choose an active customer", status_code=422)
    priced = await price_cart(
        session, branch.id, customer, [{**x, "discount_pct": None} for x in data["lines"]]
    )
    o = SaleOrder(branch_id=branch.id, customer_id=customer.id, status="quote", note=clean(data.get("note")),
                  valid_until=data.get("valid_until") or clock.today() + timedelta(days=7), created_by=actor.id,
                  subtotal=sum((x.line_total for x in priced), Decimal("0.00")),
                  discount=sum((x.promo_discount for x in priced), Decimal("0.00")), total=Decimal("0"), version=0,
                  lines=[SaleOrderLine(line_no=x.line_no, medicine_id=x.pack.product_id, pack_unit_id=x.pack.id,
                                       sku=x.pack.product.sku, name=x.pack.product.display_name,
                                       name_km=x.pack.product.name_km, pack_unit=x.pack.name, qty=x.qty,
                                       qty_in_base=x.pack.qty_in_base, unit_price=x.unit_price, line_total=x.line_total,
                                       promo_discount=x.promo_discount, promotion_ids=x.promotion_ids,
                                       is_rx_only=x.pack.product.is_rx_only, qty_invoiced=0) for x in priced])  # fmt: skip
    o.total = o.subtotal - o.discount
    o.number = await next_number(session, DocSequence, branch.id, branch.code, "SO")
    session.add(o)
    await _publish(session, o, "sale_order.created")
    audit(session, actor, "sale_order.created", "sale_order", o.id, branch_id=branch.id,
          after={"number": o.number, "customer": customer.name, "total": str(o.total), "lines": len(o.lines)})  # fmt: skip
    await session.commit()
    return o


async def confirm(session: AsyncSession, actor: CurrentUser, clients: Clients, order_id: UUID, data: dict[str, Any]
                  ) -> SaleOrder:  # fmt: skip
    o = await get(session, actor, order_id, lock=True)
    if o.status != "quote":
        raise _state(o)
    if o.valid_until and o.valid_until < clock.today():
        raise AppError(ErrorCode.ORDER_STATE, f"Quote {o.number} expired on {o.valid_until}: make a new one",
                       status_code=409, details={"status": "expired"})  # fmt: skip
    if data.get("reserve"):
        days = data.get("reserve_days") or 3
        reservation = await clients.inventory.post("/reservations", {
            "ref_type": "sale_order", "ref_id": str(o.id), "branch_id": str(o.branch_id),
            "lines": [{"line_no": x.line_no, "medicine_id": str(x.medicine_id), "qty_base": x.qty * x.qty_in_base}
                      for x in o.lines]}, actor=actor, branch_id=o.branch_id)  # fmt: skip
        o.reservation_id = UUID(str(reservation["id"]))
        o.reserve_until = clock.now() + timedelta(days=days)
    deposit = data.get("deposit")
    if deposit:
        amount = Decimal(str(deposit["amount"]))
        if deposit["currency"] == "KHR":
            rate = await rates.current(session, o.branch_id)
            if rate is None:
                raise AppError(ErrorCode.EXCHANGE_RATE_MISSING, "Set the KHR rate first", status_code=422)
            amount = money.usd(amount / rate.khr_per_usd)
        made = await clients.customers.post("/deposits", {
            "ref": str(o.id), "document_no": o.number, "customer_id": str(o.customer_id), "branch_id": str(o.branch_id),
            "method": deposit["method"], "currency": deposit["currency"], "amount": str(money.usd(amount))},
            actor=actor, branch_id=o.branch_id)  # fmt: skip
        o.deposit_id, o.deposit_usd = UUID(str(made["deposit_id"])), Decimal(made["amount"])
    o.status, o.ordered_at = "ordered", clock.now()
    await _publish(session, o, "sale_order.ordered")
    audit(session, actor, "sale_order.ordered", "sale_order", o.id, branch_id=o.branch_id, after={
        "number": o.number, "reserve_until": o.reserve_until.isoformat() if o.reserve_until else None,
        "deposit": str(o.deposit_usd) if o.deposit_id else None})  # fmt: skip
    await session.commit()
    return o


async def mark_ready(session: AsyncSession, actor: CurrentUser, order_id: UUID) -> SaleOrder:
    """The goods are packed: sale_order.ready (the customer's Telegram, with what is left to pay). Again
    later (more arrived): a new ready time and a new message."""
    o = await get(session, actor, order_id, lock=True)
    if o.status not in OPEN:
        raise _state(o)
    o.ready_at = clock.now()
    await _publish(session, o, "sale_order.ready")
    audit(session, actor, "sale_order.ready", "sale_order", o.id, branch_id=o.branch_id,
          after={"number": o.number, "remaining": str(await remaining_usd(session, o))})  # fmt: skip
    await session.commit()
    return o


async def _release(
    session: AsyncSession, clients: Clients, o: SaleOrder, actor: CurrentUser | None, why: str
) -> None:
    if o.reservation_id and o.reservation_released_at is None:
        await clients.inventory.post("/reservations/release-by-ref", {"ref_type": "sale_order", "ref_id": str(o.id)},
                                     actor=actor, branch_id=o.branch_id)  # fmt: skip
        o.reservation_released_at = clock.now()
        audit(session, actor, "sale_order.reservation_released", "sale_order", o.id, branch_id=o.branch_id,
              after={"number": o.number, "why": why})  # fmt: skip


async def release_if_expired(session: AsyncSession, clients: Clients, o: SaleOrder) -> bool:
    if o.reserve_until and o.reservation_released_at is None and o.reserve_until <= clock.now():
        await _release(session, clients, o, None, "reserved until passed")
        await _publish(session, o, "sale_order.updated")
        await session.commit()
        return True
    return False


async def invoice(session: AsyncSession, actor: CurrentUser, clients: Clients, order_id: UUID, data: dict[str, Any],
                  key: str) -> Invoice:  # fmt: skip
    from .sale_saga import create_invoice  # the saga imports this module (after_invoice)

    o = await get(session, actor, order_id, lock=True)
    if o.status not in OPEN:
        raise _state(o)
    await release_if_expired(session, clients, o)
    o = await get(session, actor, order_id)
    by_id = {x.id: x for x in o.lines}
    lines = []
    for i, x in enumerate(data["lines"], start=1):
        ol = by_id.get(x["order_line_id"])
        if ol is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {i}: not a line of this order", status_code=422)
        if x["qty"] > ol.qty_open:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {i}: only {ol.qty_open} {ol.pack_unit} still open",
                           status_code=422, details={"line": i, "open": ol.qty_open})  # fmt: skip
        lines.append({**{k: v for k, v in x.items() if k != "qty"}, "medicine_id": ol.medicine_id,
                      "pack_unit_id": ol.pack_unit_id, "qty": x["qty"]})  # fmt: skip
    sale = {**{k: v for k, v in data.items() if k != "lines"}, "branch_id": o.branch_id, "customer_id": o.customer_id,
            "lines": lines}  # fmt: skip
    await session.commit()  # release the order's row lock before the saga
    return await create_invoice(session, actor, sale, key, clients, order=o)


async def after_invoice(session: AsyncSession, actor: CurrentUser, inv: Invoice) -> None:
    """In the saga's finishing transaction: the invoiced quantities leave the order."""
    o = (await session.execute(select(SaleOrder).where(SaleOrder.id == inv.sale_order_id).with_for_update()
                               .execution_options(populate_existing=True))).scalar_one()  # fmt: skip
    by_id = {x.id: x for x in o.lines}
    for line in inv.lines:
        if line.order_line_id in by_id:
            by_id[line.order_line_id].qty_invoiced += line.qty
    o.status = "fulfilled" if all(x.qty_open == 0 for x in o.lines) else "partly_fulfilled"
    await _publish(session, o, "sale_order.updated")
    audit(session, actor, "sale_order.invoiced", "sale_order", o.id, branch_id=o.branch_id,
          after={"number": o.number, "invoice": inv.number, "status": o.status})  # fmt: skip


async def after_cancel(session: AsyncSession, actor: CurrentUser | None, inv: Invoice) -> None:
    o = (await session.execute(select(SaleOrder).where(SaleOrder.id == inv.sale_order_id).with_for_update()
                               .execution_options(populate_existing=True))).scalar_one()  # fmt: skip
    by_id = {x.id: x for x in o.lines}
    for line in inv.lines:
        if line.order_line_id in by_id:
            by_id[line.order_line_id].qty_invoiced -= line.qty
    if o.status in ("partly_fulfilled", "fulfilled"):
        o.status = "ordered" if all(x.qty_invoiced == 0 for x in o.lines) else "partly_fulfilled"
    await _publish(session, o, "sale_order.updated")


async def _settle_deposit(session: AsyncSession, actor: CurrentUser, clients: Clients, o: SaleOrder, action: str,
                          reason: str) -> None:  # fmt: skip
    if o.deposit_id is None:
        return
    await clients.customers.post(f"/deposits/{o.deposit_id}/settle", {"action": action, "reason": reason},
                                 actor=actor, branch_id=o.branch_id)  # fmt: skip


async def cancel(
    session: AsyncSession, actor: CurrentUser, clients: Clients, order_id: UUID, reason: str
) -> SaleOrder:
    o = await get(session, actor, order_id, lock=True)
    if o.status not in ("quote", *OPEN):
        raise _state(o)
    settings = await session.get(BranchSettingsCopy, o.branch_id)
    action = settings.order_deposit_on_cancel if settings else "keep_as_credit"
    if o.deposit_id and action == "forfeit" and actor.role not in ("owner", "branch_manager"):
        raise AppError(ErrorCode.FORBIDDEN, "This branch forfeits deposits on cancel: a manager or the owner cancels",
                       status_code=403)  # fmt: skip
    await _release(session, clients, o, actor, "order cancelled")
    await _settle_deposit(session, actor, clients, o, action, clean(reason))
    o.status, o.cancel_reason = "cancelled", clean(reason)
    await _publish(session, o, "sale_order.cancelled")
    audit(session, actor, "sale_order.cancelled", "sale_order", o.id, branch_id=o.branch_id, after={
        "number": o.number, "reason": o.cancel_reason, "deposit": action if o.deposit_id else None})  # fmt: skip
    await session.commit()
    return o


async def close(session: AsyncSession, actor: CurrentUser, clients: Clients, order_id: UUID) -> SaleOrder:
    o = await get(session, actor, order_id, lock=True)
    if o.status not in (*OPEN, "fulfilled"):
        raise _state(o)
    await _release(session, clients, o, actor, "order closed")
    await _settle_deposit(session, actor, clients, o, "keep_as_credit", "order closed")
    o.status, o.closed_at = "closed", clock.now()
    await _publish(session, o, "sale_order.closed")
    audit(
        session,
        actor,
        "sale_order.closed",
        "sale_order",
        o.id,
        branch_id=o.branch_id,
        after={"number": o.number},
    )
    await session.commit()
    return o


async def expire_reservations(session: AsyncSession, clients: Clients) -> int | None:
    if not (
        await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
    ).scalar_one():
        await session.rollback()
        return None
    ids = list((await session.execute(select(SaleOrder.id).where(
        SaleOrder.reserve_until <= clock.now(), SaleOrder.reservation_released_at.is_(None),
        SaleOrder.reservation_id.is_not(None)))).scalars())  # fmt: skip
    await session.commit()
    done = 0
    for order_id in ids:
        o = (
            await session.execute(select(SaleOrder).where(SaleOrder.id == order_id).with_for_update())
        ).scalar_one()
        done += await release_if_expired(session, clients, o)
    return done


async def run_scheduler(
    db: Database, get_clients: Any, stop: asyncio.Event, every_seconds: int = 600
) -> None:
    while not stop.is_set():
        try:
            async with db.sessionmaker() as session:
                done = await expire_reservations(session, get_clients())
            if done:
                log.info("sale order reservations released: %s", done)
        except Exception:  # noqa: BLE001
            log.exception("sale order reservation expiry failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=every_seconds)
        except TimeoutError:
            pass
