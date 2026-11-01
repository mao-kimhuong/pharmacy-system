"""Cancelling a sale (sales.cancel, reason required). Rules:

- Only a completed invoice with nothing returned can be cancelled (else
  INVOICE_STATE); use a return for part of it.
- Without sales.cancel_any (owner, branch manager) only invoices of today
  (Asia/Phnom_Penh) can be cancelled: a pharmacist cannot cancel yesterday's sale.
- Credit is reversed first (if that fails, nothing has changed), then the stock
  goes back into the same batches ("sale_cancel" movements). The invoice is
  "cancelling" in between; if the stock step fails the recovery task finishes it.
- A deposit that paid it goes back on the deposit; promotion uses are given
  back; commission is taken back (negative lines in the open period); an
  invoice made from a sale order puts its quantities back on the order.
- invoice.cancelled event + User Log. Cashiers have no sales.cancel: 403.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..models import Invoice, OutboxEvent
from . import commission, promotions
from .clients import Clients
from .common import audit, clean
from .queries import get_invoice
from .sale_saga import khqr_refunds
from .snapshot import invoice_payload


async def cancel_steps(
    session: AsyncSession, inv: Invoice, actor: CurrentUser | None, clients: Clients
) -> None:
    """Reverse credit, then stock; idempotent (the recovery task repeats it)."""
    if inv.credit_amount > 0 and inv.customer_id is not None:
        await clients.customers.post("/credit/reverse", {
            "invoice_id": str(inv.id), "customer_id": str(inv.customer_id), "branch_id": str(inv.branch_id),
            "kind": "cancel", "document_no": inv.number or "", "reason": inv.cancel_reason or "",
        }, actor=actor, branch_id=inv.branch_id)  # fmt: skip
    for pay in [p for p in inv.payments if p.method == "deposit" and p.deposit_id]:
        await clients.customers.post(f"/deposits/{pay.deposit_id}/unuse", {
            "invoice_id": str(inv.id), "reason": f"{inv.number} cancelled"}, actor=actor, branch_id=inv.branch_id)  # fmt: skip
    if inv.reservation_id is not None:
        await clients.inventory.post(f"/reservations/{inv.reservation_id}/reverse",
                                     {"reason": f"{inv.number} cancelled: {inv.cancel_reason}"[:255]},
                                     actor=actor, branch_id=inv.branch_id)  # fmt: skip
    inv.status = "cancelled"
    await khqr_refunds(session, inv, f"Sale {inv.number} cancelled")  # the money went to the bank: back by hand
    inv.version += 1
    await promotions.set_status(session, inv.id, "released")
    await commission.take_back(session, inv, "cancel")
    if inv.sale_order_id:
        from .orders import after_cancel

        await after_cancel(session, actor, inv)
    add_event(session, OutboxEvent, "invoice.cancelled", await invoice_payload(session, inv))
    audit(session, actor, "invoice.cancelled", "invoice", inv.id, branch_id=inv.branch_id,
          before={"status": "completed"}, after={"status": "cancelled", "number": inv.number,
                                                 "reason": inv.cancel_reason, "total": str(inv.total)})  # fmt: skip
    await session.commit()


async def cancel_invoice(
    session: AsyncSession, actor: CurrentUser, invoice_id: UUID, reason: str, clients: Clients
) -> Invoice:
    inv = await get_invoice(session, actor, invoice_id, lock=True)
    if inv.status == "cancelled":
        return inv
    if inv.status not in ("completed", "cancelling"):
        raise AppError(ErrorCode.INVOICE_STATE, f"A {inv.status} invoice cannot be cancelled", status_code=409,
                       details={"status": inv.status})  # fmt: skip
    if inv.returned_total > 0:
        raise AppError(ErrorCode.INVOICE_STATE, "Part of this invoice was returned; return the rest instead",
                       status_code=409, details={"status": inv.status})  # fmt: skip
    sold_on = inv.completed_at.astimezone(clock.TIMEZONE).date() if inv.completed_at else None
    if sold_on != clock.today() and not actor.has("sales.cancel_any"):
        raise AppError(ErrorCode.FORBIDDEN, f"{inv.number} is from {sold_on}; only today's invoices can be "
                       "cancelled without sales.cancel_any", status_code=403,
                       details={"permission": "sales.cancel_any"})  # fmt: skip
    if inv.status == "completed":
        inv.status = "cancelling"
        inv.cancel_reason = clean(reason)
        inv.cancelled_by = actor.id
        inv.cancelled_at = clock.now()
        await session.commit()
    await cancel_steps(session, inv, actor, clients)
    return inv
