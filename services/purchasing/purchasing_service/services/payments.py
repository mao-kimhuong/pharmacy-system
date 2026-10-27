"""Supplier payments, balances and statements. Rules:

- A payment is for one supplier at one branch (method cash / bank / ABA /
  KHQR) and is applied to that branch's unpaid receipts, oldest first.
- More than the supplier is owed at that branch → SUPPLIER_OVERPAYMENT
  (no advance payments).
- Never deleted: cancel with a reason; its allocations are reversed and the
  receipts are open again.
- Balance = sum of open receipt balances; overdue = past their due date.
- Staff see only their branches. Idempotency-Key on the create route.
"""

from dataclasses import dataclass
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

from ..models import DocSequence, OutboxEvent, PaymentAllocation, Receipt, SupplierPayment
from .common import audit, branch_for, clean, commit, not_found
from .suppliers import get_supplier

ZERO = Decimal("0.00")


def _payload(p: SupplierPayment) -> dict[str, Any]:
    return {
        "payment_id": str(p.id), "number": p.number, "supplier_id": str(p.supplier_id),
        "branch_id": str(p.branch_id), "method": p.method, "amount": str(p.amount),
        "paid_on": p.paid_on.isoformat(), "status": p.status,
        "allocations": [{"receipt_id": str(a.receipt_id), "amount": str(a.amount), "reversed": a.reversed}
                        for a in p.allocations],
    }  # fmt: skip


def _branch_scope(query, actor: CurrentUser, model):  # noqa: ANN001, ANN202
    if not actor.is_owner:
        query = query.where(model.branch_id.in_(actor.branch_ids or [UUID(int=0)]))
    return query


async def _open_receipts(
    session: AsyncSession, supplier_id: UUID, branch_id: UUID, *, lock: bool = False
) -> list[Receipt]:
    query = (
        select(Receipt)
        .where(Receipt.supplier_id == supplier_id, Receipt.branch_id == branch_id, Receipt.status == "open")
        .order_by(Receipt.received_at, Receipt.number)
    )
    if lock:
        query = query.with_for_update()
    return list((await session.execute(query)).scalars())


async def create_payment(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> SupplierPayment:
    branch = await branch_for(session, actor, data["branch_id"])
    supplier = await get_supplier(session, data["supplier_id"])
    amount = Decimal(str(data["amount"])).quantize(Decimal("0.01"))
    receipts = await _open_receipts(session, supplier.id, branch.id, lock=True)
    owed = sum((r.balance for r in receipts), ZERO)
    if amount > owed:
        raise AppError(
            ErrorCode.SUPPLIER_OVERPAYMENT,
            f"{supplier.name} is owed {owed} USD at {branch.code}; advance payments are not allowed",
            status_code=422, details={"owed": str(owed), "amount": str(amount)},
        )  # fmt: skip
    payment = SupplierPayment(
        supplier=supplier, branch_id=branch.id, method=data["method"], amount=amount,
        reference=clean(data.get("reference")), paid_on=data.get("paid_on") or clock.today(),
        status="posted", created_by=actor.id, allocations=[],
    )  # fmt: skip
    left = amount
    for r in receipts:  # oldest first
        if left <= 0:
            break
        part = min(left, r.balance)
        r.paid += part
        r.status = "paid" if r.paid >= r.total else "open"
        payment.allocations.append(PaymentAllocation(receipt_id=r.id, amount=part, reversed=False))
        left -= part
    payment.number = await next_number(session, DocSequence, branch.id, branch.code, "SP")
    session.add(payment)
    await session.flush()
    add_event(session, OutboxEvent, "supplier_payment.created", _payload(payment))
    numbers = {r.id: r.number for r in receipts}
    audit(session, actor, "supplier_payment.created", "supplier_payment", payment.id, branch_id=branch.id, after={
        "number": payment.number, "supplier": supplier.code, "method": payment.method,
        "amount": str(amount), "allocations": {numbers[a.receipt_id]: str(a.amount) for a in payment.allocations},
    })  # fmt: skip
    await commit(session)
    return payment


async def get_payment(
    session: AsyncSession, actor: CurrentUser, payment_id: UUID, *, lock: bool = False
) -> SupplierPayment:
    query = select(SupplierPayment).where(SupplierPayment.id == payment_id)
    p = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if p is None or not actor.can_access_branch(p.branch_id):
        raise not_found("Supplier payment")
    return p


async def cancel_payment(
    session: AsyncSession, actor: CurrentUser, payment_id: UUID, reason: str
) -> SupplierPayment:
    p = await get_payment(session, actor, payment_id, lock=True)
    if p.status != "posted":
        raise AppError(ErrorCode.PAYMENT_STATE, "This payment is already cancelled", status_code=409)
    receipt_ids = [a.receipt_id for a in p.allocations if not a.reversed]
    receipts = {
        r.id: r
        for r in (
            await session.execute(select(Receipt).where(Receipt.id.in_(receipt_ids)).with_for_update())
        ).scalars()
    }
    for a in p.allocations:
        if a.reversed:
            continue
        r = receipts[a.receipt_id]
        r.paid -= a.amount
        r.status = "open"
        a.reversed = True
    p.status = "cancelled"
    p.cancel_reason = clean(reason)
    p.cancelled_at = clock.now()
    add_event(session, OutboxEvent, "supplier_payment.cancelled", _payload(p))
    audit(session, actor, "supplier_payment.cancelled", "supplier_payment", p.id, branch_id=p.branch_id,
          before={"status": "posted"}, after={"status": "cancelled", "reason": p.cancel_reason,
                                              "amount": str(p.amount)})  # fmt: skip
    await commit(session)
    return p


async def list_payments(
    session: AsyncSession,
    actor: CurrentUser,
    supplier_id: UUID | None,
    branch_id: UUID | None,
    page: int,
    size: int,
) -> tuple[list[SupplierPayment], int]:
    query = _branch_scope(select(SupplierPayment), actor, SupplierPayment)
    if supplier_id:
        query = query.where(SupplierPayment.supplier_id == supplier_id)
    if branch_id:
        query = query.where(SupplierPayment.branch_id == branch_id)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(
        query.order_by(SupplierPayment.created_at.desc(), SupplierPayment.id)
        .offset((page - 1) * size)
        .limit(size)
    )
    return list(rows.scalars()), int(total)


async def list_receipts(
    session: AsyncSession, actor: CurrentUser, supplier_id: UUID | None, branch_id: UUID | None,
    status: str | None, page: int, size: int,
) -> tuple[list[Receipt], int]:  # fmt: skip
    query = _branch_scope(select(Receipt), actor, Receipt)
    if supplier_id:
        query = query.where(Receipt.supplier_id == supplier_id)
    if branch_id:
        query = query.where(Receipt.branch_id == branch_id)
    if status:
        query = query.where(Receipt.status == status)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(
        query.order_by(Receipt.received_at.desc(), Receipt.id).offset((page - 1) * size).limit(size)
    )
    return list(rows.scalars()), int(total)


# ---------------------------------------------------------------- balance, statement


async def balance(session: AsyncSession, actor: CurrentUser, supplier_id: UUID) -> dict[str, Any]:
    supplier = await get_supplier(session, supplier_id)
    query = _branch_scope(
        select(Receipt).where(Receipt.supplier_id == supplier.id, Receipt.status == "open"), actor, Receipt
    )
    today = clock.today()
    by_branch: dict[UUID, dict[str, Decimal]] = {}
    for r in (await session.execute(query)).scalars():
        b = by_branch.setdefault(r.branch_id, {"owed": ZERO, "overdue": ZERO})
        b["owed"] += r.balance
        if r.due_on < today:
            b["overdue"] += r.balance
    return {
        "supplier_id": supplier.id,
        "owed": sum((b["owed"] for b in by_branch.values()), ZERO),
        "overdue": sum((b["overdue"] for b in by_branch.values()), ZERO),
        "branches": [{"branch_id": k, **v} for k, v in sorted(by_branch.items(), key=lambda kv: str(kv[0]))],
    }


@dataclass
class Entry:
    on: date
    kind: str  # receipt / payment
    number: str
    branch_id: UUID
    debit: Decimal
    credit: Decimal
    due_on: date | None = None
    balance: Decimal = ZERO


async def statement(
    session: AsyncSession, actor: CurrentUser, supplier_id: UUID, branch_id: UUID | None,
    date_from: date | None, date_to: date | None,
) -> dict[str, Any]:  # fmt: skip
    """Bills (debit) and posted payments (credit) in date order with a running
    balance; entries before `date_from` make the opening balance."""
    supplier = await get_supplier(session, supplier_id)
    rq = _branch_scope(select(Receipt).where(Receipt.supplier_id == supplier.id), actor, Receipt)
    pq = _branch_scope(
        select(SupplierPayment).where(SupplierPayment.supplier_id == supplier.id, SupplierPayment.status == "posted"),
        actor, SupplierPayment,
    )  # fmt: skip
    if branch_id:
        actor.require_branch(branch_id)
        rq = rq.where(Receipt.branch_id == branch_id)
        pq = pq.where(SupplierPayment.branch_id == branch_id)
    entries = [
        Entry(r.received_at.astimezone(clock.TIMEZONE).date(), "receipt", r.number, r.branch_id,
              r.total, ZERO, r.due_on)
        for r in (await session.execute(rq)).scalars()
    ] + [
        Entry(p.paid_on, "payment", p.number, p.branch_id, ZERO, p.amount)
        for p in (await session.execute(pq)).scalars()
    ]  # fmt: skip
    entries.sort(key=lambda e: (e.on, 0 if e.kind == "receipt" else 1, e.number))
    opening = sum((e.debit - e.credit for e in entries if date_from and e.on < date_from), ZERO)
    running = opening
    shown = []
    for e in entries:
        if (date_from and e.on < date_from) or (date_to and e.on > date_to):
            continue
        running += e.debit - e.credit
        e.balance = running
        shown.append(e)
    return {
        "supplier_id": supplier.id, "supplier": supplier.name, "from": date_from, "to": date_to,
        "opening_balance": opening, "closing_balance": running,
        "entries": [e.__dict__ for e in shown],
    }  # fmt: skip
