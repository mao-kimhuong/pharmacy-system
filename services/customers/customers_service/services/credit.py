"""Credit sales, called by the sales service over /internal/v1 (the sale saga).

- charge: the customer must be active; balance + amount may not pass the credit
  limit (CREDIT_LIMIT_EXCEEDED). Adds a ledger charge and an open debt.
  Idempotent per invoice: the same invoice is charged once.
- reverse (cancel): undoes the whole charge of an invoice. If the customer had
  already paid part of it, that part becomes credit on the account.
- reverse (return): a credit note for returned goods; it lowers the invoice's
  unpaid part first, the rest is credit. Idempotent per return.
- The customer row is locked, so two tills cannot both use the last credit.
- Ledger entries are never edited: every change is a new entry.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller
from pharmacy_shared.outbox import add_event

from ..models import CustomerAllocation, CustomerDebt, LedgerEntry, OutboxEvent
from .common import acting_user, audit, balance_of, clean
from .customers import get_customer

CENT = Decimal("0.01")


async def _existing(session: AsyncSession, ref_type: str, ref_id: str) -> LedgerEntry | None:
    return (
        await session.execute(
            select(LedgerEntry).where(LedgerEntry.ref_type == ref_type, LedgerEntry.ref_id == ref_id)
        )
    ).scalar_one_or_none()


async def _result(session: AsyncSession, entry: LedgerEntry | None, customer_id: UUID) -> dict[str, Any]:
    return {"entry_id": entry.id if entry else None, "amount": entry.amount if entry else Decimal("0.00"),
            "balance_after": await balance_of(session, customer_id)}  # fmt: skip


async def charge(session: AsyncSession, caller: InternalCaller, data: dict[str, Any]) -> dict[str, Any]:
    customer = await get_customer(session, data["customer_id"], lock=True)
    ref_id = str(data["invoice_id"])
    if (entry := await _existing(session, "invoice_charge", ref_id)) is not None:
        return await _result(session, entry, customer.id)
    if not customer.is_active:
        raise AppError(ErrorCode.CUSTOMER_REQUIRED, f"{customer.name} is deactivated; no credit sales",
                       status_code=422)  # fmt: skip
    amount = Decimal(str(data["amount"])).quantize(CENT)
    balance = await balance_of(session, customer.id)
    if balance + amount > customer.credit_limit:
        available = max(customer.credit_limit - balance, Decimal("0.00"))
        raise AppError(
            ErrorCode.CREDIT_LIMIT_EXCEEDED,
            f"{customer.name} can take {available} USD more on credit (limit {customer.credit_limit})",
            status_code=422,
            details={"credit_limit": str(customer.credit_limit), "balance": str(balance),
                     "amount": str(amount), "available": str(available)},
        )  # fmt: skip
    entry = LedgerEntry(customer_id=customer.id, branch_id=data["branch_id"], kind="charge", amount=amount,
                        ref_type="invoice_charge", ref_id=ref_id, invoice_id=data["invoice_id"],
                        document_no=clean(data.get("invoice_no")), created_by=caller.user_id)  # fmt: skip
    session.add(entry)
    session.add(CustomerDebt(customer_id=customer.id, branch_id=data["branch_id"], invoice_id=data["invoice_id"],
                             invoice_no=clean(data.get("invoice_no")), amount=amount, paid=Decimal("0.00"),
                             reduced=Decimal("0.00"), status="open"))  # fmt: skip
    await session.flush()
    after = balance + amount
    add_event(session, OutboxEvent, "credit.charged", {
        "customer_id": str(customer.id), "invoice_id": ref_id, "branch_id": str(data["branch_id"]),
        "amount": str(amount), "balance_after": str(after), "occurred_at": clock.now().isoformat()})  # fmt: skip
    audit(session, acting_user(caller), "credit.charged", "customer", customer.id, branch_id=data["branch_id"],
          after={"invoice": entry.document_no or ref_id, "amount": str(amount), "balance": str(after)})  # fmt: skip
    await session.commit()
    return await _result(session, entry, customer.id)


async def reverse(session: AsyncSession, caller: InternalCaller, data: dict[str, Any]) -> dict[str, Any]:
    """data: customer_id, invoice_id, kind cancel|return, ref_id (return id), amount (return), reason."""
    customer = await get_customer(session, data["customer_id"], lock=True)
    invoice_id = str(data["invoice_id"])
    is_cancel = data["kind"] == "cancel"
    ref_type, ref_id = ("invoice_cancel", invoice_id) if is_cancel else ("return_credit", str(data["ref_id"]))
    if (entry := await _existing(session, ref_type, ref_id)) is not None:
        return await _result(session, entry, customer.id)
    debt = (
        await session.execute(
            select(CustomerDebt).where(CustomerDebt.invoice_id == data["invoice_id"]).with_for_update()
        )
    ).scalar_one_or_none()
    if is_cancel:
        if debt is None:
            return await _result(session, None, customer.id)  # nothing was charged: nothing to undo
        amount = debt.amount - (
            await _credit_notes_total(session, invoice_id)
        )  # what is still charged for this invoice
    else:
        amount = Decimal(str(data["amount"])).quantize(CENT)
    if amount <= 0:
        return await _result(session, None, customer.id)
    if debt is not None:
        debt.reduced += min(amount, debt.due)
        if debt.due == 0:
            debt.status = "cancelled" if is_cancel else ("paid" if debt.paid else "cancelled")
    entry = LedgerEntry(customer_id=customer.id, branch_id=data.get("branch_id"),
                        kind="reversal" if is_cancel else "credit_note", amount=-amount, ref_type=ref_type,
                        ref_id=ref_id, invoice_id=data["invoice_id"], document_no=clean(data.get("document_no")),
                        reason=clean(data.get("reason")), created_by=caller.user_id)  # fmt: skip
    session.add(entry)
    await session.flush()
    after = await balance_of(session, customer.id)
    add_event(session, OutboxEvent, "credit.reversed", {
        "customer_id": str(customer.id), "invoice_id": invoice_id, "kind": data["kind"], "amount": str(amount),
        "branch_id": str(data["branch_id"]) if data.get("branch_id") else None, "balance_after": str(after),
        "occurred_at": clock.now().isoformat()})  # fmt: skip
    audit(session, acting_user(caller), f"credit.{'reversed' if is_cancel else 'credit_note'}", "customer",
          customer.id, branch_id=data.get("branch_id"),
          after={"invoice": entry.document_no or invoice_id, "amount": str(-amount), "reason": entry.reason,
                 "balance": str(after)})  # fmt: skip
    await session.commit()
    return await _result(session, entry, customer.id)


async def _credit_notes_total(session: AsyncSession, invoice_id: str) -> Decimal:
    rows = (await session.execute(select(LedgerEntry.amount).where(
        LedgerEntry.invoice_id == UUID(invoice_id), LedgerEntry.kind == "credit_note"))).scalars()  # fmt: skip
    return -sum(rows, Decimal("0.00"))


async def set_invoice_number(session: AsyncSession, invoice_id: UUID, invoice_no: str) -> bool:
    """A sale gets its number only when it completes, after the charge: write it
    on the debt (and the payments already allocated to it). Ledger rows are
    never edited; the statement shows the debt's number for the charge.
    Called by sales right after the sale, and again from invoice.created."""
    debt = (
        await session.execute(
            select(CustomerDebt).where(CustomerDebt.invoice_id == invoice_id).with_for_update()
        )
    ).scalar_one_or_none()
    if debt is None or debt.invoice_no == invoice_no:
        return False
    debt.invoice_no = invoice_no
    allocations = (
        await session.execute(select(CustomerAllocation).where(CustomerAllocation.debt_id == debt.id))
    ).scalars()
    for a in allocations:
        a.invoice_no = invoice_no
    await session.commit()
    return True
