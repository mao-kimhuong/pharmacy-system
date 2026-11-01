"""Supplier returns (S8b). Rules:

- Draft (purchasing.return): branch, supplier, reason (damaged / expired / recalled /
  wrong_item / overstock), lines = inventory batch + qty_base (optionally the receipt
  line). A recall's "return to supplier" makes a draft too (once per recall line).
- Cancel only a draft, with a reason. Never deleted.
- Submit (purchasing.return, Idempotency-Key): stock leaves through inventory
  (/internal/v1/movements/supplier-return, once per line; the batch must be this
  supplier's); controlled lines need the user's PIN + a witness (action
  purchasing.supplier_return) and reach the controlled register. The value is the
  batches' cost. It becomes a supplier credit:
  - settle "credit" (default): applied to the branch's open bills of that supplier,
    oldest first; what is left is applied to the next bills received;
  - settle "refund" (owner or branch manager): the supplier pays the money back;
    a supplier refund receipt (PP1-SRF-…) records it (money in).
- Events supplier_return.*, supplier_credit.updated (allocations, absolute) and
  supplier_refund.created; the supplier statement shows returns (credit) and refunds.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event
from pharmacy_shared.pin import consume_pin, consume_witness

from ..models import (
    CreditAllocation,
    DocSequence,
    KnownBranch,
    OutboxEvent,
    Product,
    Receipt,
    Supplier,
    SupplierCredit,
    SupplierRefund,
    SupplierReturn,
    SupplierReturnLine,
)
from .common import audit, branch_for, clean, commit, not_found
from .suppliers import get_supplier

ZERO = Decimal("0.00")
ACTION = "purchasing.supplier_return"


def _state(message: str, status: str) -> AppError:
    return AppError(ErrorCode.SUPPLIER_RETURN_STATE, message, status_code=409, details={"status": status})


async def payload(session: AsyncSession, r: SupplierReturn) -> dict[str, Any]:
    branch = await session.get(KnownBranch, r.branch_id)
    supplier = await session.get(Supplier, r.supplier_id)
    products = {p.id: p for p in (await session.execute(select(Product).where(
        Product.id.in_([x.medicine_id for x in r.lines])))).scalars()} if r.lines else {}  # fmt: skip
    return {
        "return_id": str(r.id), "version": r.version, "number": r.number, "status": r.status, "reason": r.reason,
        "note": r.note, "total": str(r.total), "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        "branch": {"id": str(r.branch_id), "code": branch.code if branch else "", "name_en": branch.name_en if branch
                   else "", "name_km": branch.name_km if branch else ""},
        "supplier": {"id": str(r.supplier_id), "code": supplier.code if supplier else "",
                     "name": supplier.name if supplier else ""},
        "cancel_reason": r.cancel_reason,
        "lines": [{"line_no": x.line_no, "batch_id": str(x.batch_id), "medicine_id": str(x.medicine_id),
                   "sku": products[x.medicine_id].sku if x.medicine_id in products else "",
                   "name": products[x.medicine_id].display_name if x.medicine_id in products else "",
                   "qty_base": x.qty_base, "lot_no": x.lot_no,
                   "expiry_date": x.expiry_date.isoformat() if x.expiry_date else None,
                   "cost_per_base": str(x.cost_per_base) if x.cost_per_base is not None else None,
                   "line_total": str(x.line_total)} for x in r.lines],
    }  # fmt: skip


async def _publish(session: AsyncSession, r: SupplierReturn, event: str) -> None:
    r.version += 1
    await session.flush()
    add_event(session, OutboxEvent, event, await payload(session, r))


def credit_payload(c: SupplierCredit) -> dict[str, Any]:
    return {"credit_id": str(c.id), "number": c.number, "supplier_id": str(c.supplier_id),
            "branch_id": str(c.branch_id), "amount": str(c.amount), "remaining": str(c.remaining),
            "status": c.status, "allocations": [{"receipt_id": str(a.receipt_id), "amount": str(a.amount)}
                                                for a in c.allocations]}  # fmt: skip


async def _lines(session: AsyncSession, raw: list[dict[str, Any]]) -> list[SupplierReturnLine]:
    out = []
    for i, x in enumerate(raw, start=1):
        product = await session.get(Product, x["medicine_id"])
        if product is None or product.is_hamper:
            raise AppError(ErrorCode.UNKNOWN_MEDICINE, f"Line {i}: unknown medicine (hampers are returned as "
                           "their components)", status_code=422, details={"line": i})  # fmt: skip
        out.append(SupplierReturnLine(line_no=i, batch_id=x["batch_id"], medicine_id=product.id,
                                      qty_base=int(x["qty_base"]), receipt_line_id=x.get("receipt_line_id")))  # fmt: skip
    return out


async def create(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> SupplierReturn:
    if data.get("source_ref"):
        found = (await session.execute(select(SupplierReturn).where(SupplierReturn.source_ref == data["source_ref"]))
                 ).scalar_one_or_none()  # fmt: skip
        if found is not None:
            return found  # the same recall line asked again
    branch = await branch_for(session, actor, data["branch_id"])
    supplier = await get_supplier(session, data["supplier_id"])
    if not supplier.is_active:
        raise AppError(ErrorCode.UNKNOWN_SUPPLIER, f"{supplier.name} is deactivated", status_code=422)
    r = SupplierReturn(branch_id=branch.id, supplier_id=supplier.id, reason=data["reason"], note=clean(data.get("note")),
                       source_ref=data.get("source_ref"), status="draft", created_by=actor.id, version=0,
                       lines=await _lines(session, data["lines"]))  # fmt: skip
    r.number = await next_number(session, DocSequence, branch.id, branch.code, "SRN")
    session.add(r)
    await session.flush()
    await _publish(session, r, "supplier_return.created")
    audit(session, actor, "supplier_return.created", "supplier_return", r.id, branch_id=branch.id, after={
        "number": r.number, "supplier": supplier.code, "reason": r.reason, "lines": len(r.lines),
        "source": r.source_ref})  # fmt: skip
    await commit(session)
    return r


async def get(session: AsyncSession, actor: CurrentUser, return_id: UUID, *, lock: bool = False) -> SupplierReturn:
    query = select(SupplierReturn).where(SupplierReturn.id == return_id)
    r = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if r is None or not actor.can_access_branch(r.branch_id):
        raise not_found("Supplier return")
    return r


async def list_returns(session: AsyncSession, actor: CurrentUser, branch_id: UUID | None,
                       status: str | None) -> list[SupplierReturn]:  # fmt: skip
    query = select(SupplierReturn).order_by(SupplierReturn.created_at.desc()).limit(500)
    if branch_id:
        actor.require_branch(branch_id)
        query = query.where(SupplierReturn.branch_id == branch_id)
    elif not actor.is_owner:
        query = query.where(SupplierReturn.branch_id.in_(list(actor.branch_ids) or [UUID(int=0)]))
    if status:
        query = query.where(SupplierReturn.status == status)
    return list((await session.execute(query)).scalars())


async def cancel(session: AsyncSession, actor: CurrentUser, return_id: UUID, reason: str) -> SupplierReturn:
    r = await get(session, actor, return_id, lock=True)
    if r.status != "draft":
        raise _state(f"Return {r.number} is {r.status}: only a draft can be cancelled", r.status)
    r.status, r.cancel_reason = "cancelled", clean(reason)
    await _publish(session, r, "supplier_return.cancelled")
    audit(session, actor, "supplier_return.cancelled", "supplier_return", r.id, branch_id=r.branch_id,
          after={"number": r.number, "reason": r.cancel_reason})  # fmt: skip
    await commit(session)
    return r


async def _apply(session: AsyncSession, credit: SupplierCredit, receipts: list[Receipt]) -> bool:
    """Credit → open bills, oldest first. Returns whether anything was applied."""
    applied = False
    for rc in receipts:
        if credit.remaining <= 0:
            break
        part = min(credit.remaining, rc.balance)
        if part <= 0:
            continue
        rc.paid += part
        rc.status = "paid" if rc.paid >= rc.total else "open"
        credit.allocations.append(CreditAllocation(credit_id=credit.id, receipt_id=rc.id, amount=part))
        credit.remaining -= part
        applied = True
    if credit.remaining <= 0:
        credit.status = "used"
    return applied


async def _open_receipts(session: AsyncSession, supplier_id: UUID, branch_id: UUID) -> list[Receipt]:
    return list((await session.execute(select(Receipt).where(
        Receipt.supplier_id == supplier_id, Receipt.branch_id == branch_id, Receipt.status == "open")
        .order_by(Receipt.received_at, Receipt.number).with_for_update())).scalars())  # fmt: skip


async def apply_open_credits(session: AsyncSession, receipt: Receipt) -> None:
    """A new bill: the supplier's open credits at that branch pay it first (receiving)."""
    credits = list((await session.execute(select(SupplierCredit).where(
        SupplierCredit.supplier_id == receipt.supplier_id, SupplierCredit.branch_id == receipt.branch_id,
        SupplierCredit.status == "open").order_by(SupplierCredit.created_at).with_for_update())).scalars())  # fmt: skip
    for c in credits:
        if await _apply(session, c, [receipt]):
            await session.flush()
            add_event(session, OutboxEvent, "supplier_credit.updated", credit_payload(c))


async def submit(session: AsyncSession, actor: CurrentUser, inventory: InternalClient, auth: InternalClient,
                 return_id: UUID, data: dict[str, Any]) -> SupplierReturn:  # fmt: skip
    r = await get(session, actor, return_id, lock=True)
    if r.status != "draft":
        raise _state(f"Return {r.number} is {r.status}", r.status)
    settle = data.get("settle") or "credit"
    if settle == "refund" and not (actor.is_owner or actor.role == "branch_manager"):
        raise AppError(ErrorCode.FORBIDDEN, "Only the owner or a branch manager takes the money back instead of "
                       "a credit", status_code=403)  # fmt: skip
    if settle == "refund" and not data.get("refund_method"):
        raise AppError(ErrorCode.VALIDATION_ERROR, "How did the supplier pay it back (refund_method)?", status_code=422)
    supplier = await session.get(Supplier, r.supplier_id)
    products = {x.medicine_id: await session.get(Product, x.medicine_id) for x in r.lines}
    controlled = [x for x in r.lines if products[x.medicine_id] and products[x.medicine_id].controlled_schedule]
    meta = None
    if controlled:
        me = await consume_pin(auth, data.get("pin_token"), ACTION, user=actor, branch_id=r.branch_id)
        witness = await consume_witness(auth, data.get("witness_token"), ACTION, actor=actor, branch_id=r.branch_id)
        meta = {"entry_type": "supplier_return", "supplier": supplier.name, "return_number": r.number,
                "pharmacist_name": me.name, "witness_id": str(witness.user_id), "witness_name": witness.name,
                "pin_confirmed": True}  # fmt: skip
    moved = await inventory.post("/movements/supplier-return", {
        "return_id": str(r.id), "number": r.number, "branch_id": str(r.branch_id), "supplier_id": str(r.supplier_id),
        "lines": [{"line_no": x.line_no, "batch_id": str(x.batch_id), "medicine_id": str(x.medicine_id),
                   "qty_base": x.qty_base, **({"meta": meta} if x in controlled else {})} for x in r.lines],
    }, actor=actor, branch_id=r.branch_id)  # fmt: skip
    by_line = {m["line_no"]: m for m in moved["lines"]}
    for x in r.lines:
        m = by_line[x.line_no]
        x.lot_no, x.cost_per_base = m["lot_no"], Decimal(str(m["cost_per_base"]))
        x.expiry_date = date.fromisoformat(str(m["expiry_date"]))
        x.line_total = (x.cost_per_base * x.qty_base).quantize(Decimal("0.01"))
    r.total = sum((x.line_total for x in r.lines), ZERO)
    r.submitted_by, r.submitted_at = actor.id, clock.now()
    credit = SupplierCredit(return_id=r.id, number=r.number, branch_id=r.branch_id, supplier_id=r.supplier_id,
                            amount=r.total, remaining=r.total, status="open", allocations=[])  # fmt: skip
    session.add(credit)
    await session.flush()
    refund = None
    if settle == "refund":
        branch = await session.get(KnownBranch, r.branch_id)
        refund = SupplierRefund(return_id=r.id, branch_id=r.branch_id, supplier_id=r.supplier_id,
                                method=data["refund_method"], amount=r.total, reference=clean(data.get("refund_reference")),
                                received_on=clock.today(), created_by=actor.id)  # fmt: skip
        refund.number = await next_number(session, DocSequence, r.branch_id, branch.code if branch else "BR", "SRF")
        session.add(refund)
        credit.remaining, credit.status, r.status = ZERO, "refunded", "refunded"
    else:
        await _apply(session, credit, await _open_receipts(session, r.supplier_id, r.branch_id))
        r.status = "credited"
    await session.flush()
    await _publish(session, r, "supplier_return.submitted")
    add_event(session, OutboxEvent, "supplier_credit.updated", credit_payload(credit))
    if refund is not None:
        add_event(session, OutboxEvent, "supplier_refund.created", {
            "refund_id": str(refund.id), "number": refund.number, "return_number": r.number,
            "branch_id": str(r.branch_id), "supplier_id": str(r.supplier_id), "method": refund.method,
            "amount": str(refund.amount), "received_on": refund.received_on.isoformat()})  # fmt: skip
    audit(session, actor, "supplier_return.submitted", "supplier_return", r.id, branch_id=r.branch_id, after={
        "number": r.number, "supplier": supplier.code, "total": str(r.total), "settle": settle,
        "refund": refund.number if refund else None, "controlled_lines": len(controlled),
        "applied_to_bills": str(credit.amount - credit.remaining) if settle == "credit" else None})  # fmt: skip
    await commit(session)
    return r
