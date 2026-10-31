"""Customer payments and statements. Rules:

- A payment (cash / card / ABA / KHQR) goes to the customer's oldest unpaid
  credit invoices first. More than owed → CUSTOMER_OVERPAYMENT.
- Never deleted: cancel with a reason; the invoices it paid are open again
  (and a ledger entry adds the amount back).
- Numbered per branch: PP1-CP-2026-000001. Idempotency-Key on the route.
- Statement: every ledger entry with a running balance; entries before `from`
  make the opening balance.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event

from ..models import CustomerAllocation, CustomerDebt, CustomerPayment, DocSequence, LedgerEntry, OutboxEvent
from .common import ZERO, audit, balance_of, branch_for, clean, not_found
from .customers import get_customer


def _payload(p: CustomerPayment) -> dict[str, Any]:
    return {"payment_id": str(p.id), "number": p.number, "customer_id": str(p.customer_id),
            "branch_id": str(p.branch_id), "method": p.method, "amount": str(p.amount), "status": p.status,
            "paid_on": p.paid_on.isoformat(), "occurred_at": (p.cancelled_at or clock.now()).isoformat(),
            "allocations": [{"invoice_no": a.invoice_no, "amount": str(a.amount), "reversed": a.reversed}
                            for a in p.allocations]}  # fmt: skip


async def create_payment(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> CustomerPayment:
    branch = await branch_for(session, actor, data["branch_id"])
    customer = await get_customer(session, data["customer_id"], lock=True)
    amount = Decimal(str(data["amount"])).quantize(Decimal("0.01"))
    debts = list((await session.execute(
        select(CustomerDebt).where(CustomerDebt.customer_id == customer.id, CustomerDebt.status == "open")
        .order_by(CustomerDebt.created_at, CustomerDebt.invoice_no).with_for_update())).scalars())  # fmt: skip
    owed = sum((d.due for d in debts), ZERO)
    if amount > owed:
        raise AppError(ErrorCode.CUSTOMER_OVERPAYMENT, f"{customer.name} owes {owed} USD on unpaid invoices",
                       status_code=422, details={"owed": str(owed), "amount": str(amount)})  # fmt: skip
    payment = CustomerPayment(customer_id=customer.id, branch_id=branch.id, method=data["method"], amount=amount,
                              reference=clean(data.get("reference")), paid_on=data.get("paid_on") or clock.today(),
                              status="posted", created_by=actor.id, allocations=[])  # fmt: skip
    left = amount
    for d in debts:  # oldest first
        if left <= 0:
            break
        part = min(left, d.due)
        if part <= 0:
            continue
        d.paid += part
        if d.due == 0:
            d.status = "paid"
        payment.allocations.append(CustomerAllocation(debt_id=d.id, invoice_no=d.invoice_no, amount=part))
        left -= part
    payment.number = await next_number(session, DocSequence, branch.id, branch.code, "CP")
    session.add(payment)
    await session.flush()
    session.add(LedgerEntry(customer_id=customer.id, branch_id=branch.id, kind="payment", amount=-amount,
                            ref_type="payment", ref_id=str(payment.id), document_no=payment.number,
                            created_by=actor.id))  # fmt: skip
    add_event(session, OutboxEvent, "customer_payment.created", _payload(payment))
    audit(session, actor, "customer_payment.created", "customer_payment", payment.id, branch_id=branch.id, after={
        "number": payment.number, "customer": customer.phone, "method": payment.method, "amount": str(amount),
        "allocations": {a.invoice_no: str(a.amount) for a in payment.allocations}})  # fmt: skip
    await session.commit()
    return payment


async def get_payment(
    session: AsyncSession, actor: CurrentUser, payment_id: UUID, *, lock: bool = False
) -> CustomerPayment:
    query = select(CustomerPayment).where(CustomerPayment.id == payment_id)
    p = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if p is None or not actor.can_access_branch(p.branch_id):
        raise not_found("Customer payment")
    return p


async def cancel_payment(
    session: AsyncSession, actor: CurrentUser, payment_id: UUID, reason: str
) -> CustomerPayment:
    p = await get_payment(session, actor, payment_id, lock=True)
    if p.status != "posted":
        raise AppError(ErrorCode.PAYMENT_STATE, "This payment is already cancelled", status_code=409)
    await get_customer(session, p.customer_id, lock=True)
    debts = {d.id: d for d in (await session.execute(select(CustomerDebt).where(
        CustomerDebt.id.in_([a.debt_id for a in p.allocations])).with_for_update())).scalars()}  # fmt: skip
    for a in p.allocations:
        if a.reversed:
            continue
        d = debts[a.debt_id]
        d.paid -= a.amount
        if d.status == "paid" and d.due > 0:
            d.status = "open"
        a.reversed = True
    p.status, p.cancel_reason, p.cancelled_at = "cancelled", clean(reason), clock.now()
    session.add(LedgerEntry(customer_id=p.customer_id, branch_id=p.branch_id, kind="payment_cancel", amount=p.amount,
                            ref_type="payment_cancel", ref_id=str(p.id), document_no=p.number,
                            reason=p.cancel_reason, created_by=actor.id))  # fmt: skip
    add_event(session, OutboxEvent, "customer_payment.cancelled", _payload(p))
    audit(session, actor, "customer_payment.cancelled", "customer_payment", p.id, branch_id=p.branch_id,
          before={"status": "posted"}, after={"status": "cancelled", "reason": p.cancel_reason,
                                              "amount": str(p.amount)})  # fmt: skip
    await session.commit()
    return p


async def list_payments(
    session: AsyncSession, actor: CurrentUser, customer_id: UUID | None, page: int, size: int
) -> tuple[list[CustomerPayment], int]:
    query = select(CustomerPayment)
    if not actor.is_owner:
        query = query.where(CustomerPayment.branch_id.in_(actor.branch_ids or [UUID(int=0)]))
    if customer_id:
        query = query.where(CustomerPayment.customer_id == customer_id)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(CustomerPayment.created_at.desc(), CustomerPayment.id)
                                 .offset((page - 1) * size).limit(size))  # fmt: skip
    return list(rows.scalars()), int(total)


async def open_debts(session: AsyncSession, customer_id: UUID) -> list[CustomerDebt]:
    return list((await session.execute(select(CustomerDebt).where(
        CustomerDebt.customer_id == customer_id, CustomerDebt.status == "open")
        .order_by(CustomerDebt.created_at))).scalars())  # fmt: skip


async def statement(
    session: AsyncSession, customer_id: UUID, date_from: date | None, date_to: date | None
) -> dict[str, Any]:
    customer = await get_customer(session, customer_id)
    entries = list((await session.execute(select(LedgerEntry).where(LedgerEntry.customer_id == customer.id)
                                          .order_by(LedgerEntry.seq))).scalars())  # fmt: skip

    def local_day(e: LedgerEntry) -> date:
        return e.created_at.astimezone(clock.TIMEZONE).date()

    numbers = {d.invoice_id: d.invoice_no for d in (await session.execute(
        select(CustomerDebt).where(CustomerDebt.customer_id == customer.id))).scalars()}  # fmt: skip
    opening = sum((e.amount for e in entries if date_from and local_day(e) < date_from), ZERO)
    running, rows = opening, []
    for e in entries:
        day = local_day(e)
        if (date_from and day < date_from) or (date_to and day > date_to):
            continue
        running += e.amount
        document_no = e.document_no or (numbers.get(e.invoice_id, "") if e.invoice_id else "")
        rows.append({"on": day, "kind": e.kind, "document_no": document_no, "branch_id": e.branch_id,
                     "debit": e.amount if e.amount > 0 else ZERO, "credit": -e.amount if e.amount < 0 else ZERO,
                     "reason": e.reason, "balance": running})  # fmt: skip
    return {"customer_id": customer.id, "customer": customer.name, "from": date_from, "to": date_to,
            "opening_balance": opening, "closing_balance": running, "entries": rows,
            "balance": await balance_of(session, customer.id)}  # fmt: skip
