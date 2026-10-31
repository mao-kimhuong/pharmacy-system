"""Deposits on sale orders, called by the sales service over /internal/v1.

- take: once per order (ref); the customer must be active. Amount in USD (the
  sales service converted riel at its rate).
- use: an invoice of the order (or, for a deposit kept as credit, any later
  invoice of the customer) takes up to what is left (DEPOSIT_EXCEEDED); once
  per invoice. unuse: the invoice was undone or cancelled; once per invoice.
- settle: what is left when the order ends – keep_as_credit (stays usable by
  the customer's later sales), refund (paid back), forfeit (kept by the shop).
- The deposit row is locked: two tills cannot use the same money.
Every step: deposit.* event + User Log entry.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller
from pharmacy_shared.outbox import add_event

from ..models import Deposit, DepositMovement, OutboxEvent
from .common import acting_user, audit, clean
from .customers import get_customer

CENT = Decimal("0.01")


def out(d: Deposit) -> dict[str, Any]:
    return {"deposit_id": str(d.id), "customer_id": str(d.customer_id), "branch_id": str(d.branch_id), "ref": d.ref,
            "document_no": d.document_no, "amount": str(d.amount), "used": str(d.used), "remaining": str(d.remaining),
            "status": d.status, "method": d.method, "currency": d.currency}  # fmt: skip


async def _lock(session: AsyncSession, deposit_id: UUID) -> Deposit:
    d = (await session.execute(select(Deposit).where(Deposit.id == deposit_id).with_for_update()
                               .execution_options(populate_existing=True))).scalar_one_or_none()  # fmt: skip
    if d is None:
        raise AppError(ErrorCode.NOT_FOUND, "Deposit not found", status_code=404)
    return d


async def _done(session: AsyncSession, d: Deposit, event: str) -> dict[str, Any]:
    await session.flush()
    await session.refresh(d, attribute_names=["movements"])
    add_event(session, OutboxEvent, event, out(d))
    await session.commit()
    return out(d)


async def take(session: AsyncSession, caller: InternalCaller, data: dict[str, Any]) -> dict[str, Any]:
    found = (await session.execute(select(Deposit).where(Deposit.ref == data["ref"]))).scalar_one_or_none()
    if found:
        return out(found)
    customer = await get_customer(session, data["customer_id"])
    if not customer.is_active:
        raise AppError(ErrorCode.CUSTOMER_REQUIRED, "This customer is deactivated", status_code=422)
    d = Deposit(customer_id=customer.id, branch_id=data["branch_id"], ref=data["ref"],
                document_no=clean(data.get("document_no")), method=data["method"], currency=data["currency"],
                amount=Decimal(str(data["amount"])).quantize(CENT), status="held", created_by=caller.user_id,
                movements=[])  # fmt: skip
    session.add(d)
    await session.flush()
    audit(session, acting_user(caller), "deposit.taken", "customer", customer.id, branch_id=d.branch_id,
          after={"order": d.document_no, "amount": str(d.amount), "method": d.method})  # fmt: skip
    return await _done(session, d, "deposit.taken")


async def use(
    session: AsyncSession, caller: InternalCaller, deposit_id: UUID, data: dict[str, Any]
) -> dict[str, Any]:
    d = await _lock(session, deposit_id)
    ref = str(data["invoice_id"])
    if any(m.kind == "use" and m.ref == ref for m in d.movements):
        return out(d)
    if d.status not in ("held", "credit"):
        raise AppError(ErrorCode.DEPOSIT_EXCEEDED, f"This deposit is {d.status}", status_code=409)
    if str(data.get("customer_id") or d.customer_id) != str(d.customer_id):
        raise AppError(ErrorCode.VALIDATION_ERROR, "The deposit belongs to another customer", status_code=422)
    amount = Decimal(str(data["amount"])).quantize(CENT)
    if amount <= 0 or amount > d.remaining:
        raise AppError(ErrorCode.DEPOSIT_EXCEEDED, f"Only {d.remaining} USD is left on the deposit",
                       status_code=409, details={"remaining": str(d.remaining)})  # fmt: skip
    session.add(
        DepositMovement(deposit_id=d.id, kind="use", amount=amount, ref=ref, created_by=caller.user_id)
    )
    audit(session, acting_user(caller), "deposit.used", "customer", d.customer_id, branch_id=d.branch_id,
          after={"order": d.document_no, "invoice": clean(data.get("invoice_no")) or ref, "amount": str(amount)})  # fmt: skip
    return await _done(session, d, "deposit.used")


async def unuse(
    session: AsyncSession, caller: InternalCaller, deposit_id: UUID, data: dict[str, Any]
) -> dict[str, Any]:
    d = await _lock(session, deposit_id)
    ref = str(data["invoice_id"])
    used = sum((m.amount for m in d.movements if m.ref == ref and m.kind in ("use", "unuse")), Decimal("0"))
    if used <= 0:
        return out(d)  # nothing (more) to give back
    session.add(DepositMovement(deposit_id=d.id, kind="unuse", amount=-used, ref=ref, created_by=caller.user_id,
                                reason=clean(data.get("reason"))))  # fmt: skip
    audit(session, acting_user(caller), "deposit.given_back", "customer", d.customer_id, branch_id=d.branch_id,
          after={"order": d.document_no, "invoice": ref, "amount": str(used)})  # fmt: skip
    return await _done(session, d, "deposit.updated")


async def settle(
    session: AsyncSession, caller: InternalCaller, deposit_id: UUID, data: dict[str, Any]
) -> dict[str, Any]:
    d = await _lock(session, deposit_id)
    if d.status != "held":
        return out(d)
    action, left = data["action"], d.remaining
    if action in ("refund", "forfeit") and left > 0:
        session.add(DepositMovement(deposit_id=d.id, kind=action, amount=left, ref=f"settle:{d.ref}",
                                    reason=clean(data.get("reason")), created_by=caller.user_id))  # fmt: skip
    d.status = (
        {"keep_as_credit": "credit", "refund": "refunded", "forfeit": "forfeited"}[action]
        if left > 0
        else "used"
    )
    audit(session, acting_user(caller), f"deposit.{d.status}", "customer", d.customer_id, branch_id=d.branch_id,
          after={"order": d.document_no, "amount": str(left), "reason": clean(data.get("reason"))})  # fmt: skip
    return await _done(session, d, "deposit.settled")


async def of_customer(session: AsyncSession, customer_id: UUID) -> list[Deposit]:
    return list((await session.execute(select(Deposit).where(Deposit.customer_id == customer_id)
                                       .order_by(Deposit.created_at))).scalars())  # fmt: skip
