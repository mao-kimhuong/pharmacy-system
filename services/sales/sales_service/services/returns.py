"""Sale returns (sales.return). Rules:

- Some lines of a completed invoice, in the line's pack unit; never more than
  sold minus already returned (RETURN_EXCEEDS_SOLD).
- Opened packs are refused (OPENED_PACK_RETURN) unless the branch allows it.
- Refund in cash, or as a credit note to the invoice's customer (credit sales
  are always refunded as a credit note). Amount = the line's net price (after
  promotions and discounts) for the quantity returned.
- Stock goes back into the batches it was sold from (the last-used batch
  first), or into quarantine until a pharmacist releases it. A hamper comes back
  whole: each component into its own batches.
- Commission is taken back for what was returned; a fully returned invoice gives
  its promotion uses back.
- Numbered PP1-RT-2026-000001 when complete; invoice.returned + User Log.
- If inventory or customers cannot be reached after part of the work, the
  return is "needs_attention" and the recovery task finishes it (idempotent).
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event

from ..models import (
    BranchSettingsCopy,
    DocSequence,
    Invoice,
    KnownBranch,
    OutboxEvent,
    SaleReturn,
    SaleReturnLine,
)
from . import commission, money, promotions
from .clients import Clients
from .common import audit, clean
from .queries import get_invoice, returns_of
from .sale_saga import controlled_meta
from .snapshot import invoice_payload


async def return_steps(session: AsyncSession, ret: SaleReturn, inv: Invoice, actor: CurrentUser | None,
                       clients: Clients) -> None:  # fmt: skip
    """Book the stock, then the credit note; then finish. Idempotent."""
    by_id = {line.id: line for line in inv.lines}
    await clients.inventory.post("/returns", {
        "branch_id": str(ret.branch_id), "to": "quarantine" if ret.to_quarantine else "stock", "reason": ret.reason,
        "items": [{"ref_id": str(x.id), "batch_id": str(x.batch_id), "qty_base": x.qty_base,
                   **({"meta": {**controlled_meta(inv, by_id[x.invoice_line_id].line_no), "reason": ret.reason}}
                      if by_id[x.invoice_line_id].is_controlled else {})} for x in ret.lines],
    }, actor=actor, branch_id=ret.branch_id)  # fmt: skip
    if ret.refund_method == "credit_note":
        await clients.customers.post("/credit/reverse", {
            "invoice_id": str(inv.id), "customer_id": str(inv.customer_id), "branch_id": str(ret.branch_id),
            "kind": "return", "ref_id": str(ret.id), "amount": str(ret.refund_usd), "document_no": inv.number or "",
            "reason": ret.reason}, actor=actor, branch_id=ret.branch_id)  # fmt: skip
    branch = await session.get(KnownBranch, ret.branch_id)
    ret.number = await next_number(session, DocSequence, ret.branch_id, branch.code if branch else "BR", "RT")
    ret.status = "completed"
    returned: dict[UUID, int] = {}
    for x in ret.lines:
        line = by_id[x.invoice_line_id]
        returned[line.id] = returned.get(line.id, 0) + (x.hamper_qty if line.is_hamper else x.qty_base)
    await commission.take_back(session, inv, f"return:{ret.id}", returned)
    if all(x.returned_qty_base >= x.qty_base for x in inv.lines):
        await promotions.set_status(session, inv.id, "released")
    ret.failure_reason = None
    inv.version += 1
    await session.flush()
    add_event(
        session,
        OutboxEvent,
        "invoice.returned",
        await invoice_payload(session, inv, await returns_of(session, inv.id)),
    )
    audit(session, actor, "invoice.returned", "invoice", inv.id, branch_id=inv.branch_id, after={
        "return": ret.number, "invoice": inv.number, "refund": f"{ret.refund_usd} USD {ret.refund_method}",
        "to": "quarantine" if ret.to_quarantine else "stock", "reason": ret.reason,
        "lines": [f"{x.qty_base} base units of line {x.invoice_line_id}" for x in ret.lines]})  # fmt: skip
    await session.commit()


def _allocate(line, qty_base: int) -> list[tuple[Any, int]]:  # noqa: ANN001
    """Back into the batches the line was sold from, last-used first. A hamper (qty in
    hampers): each component its share, back into that component's batches."""
    if line.is_hamper:
        out = []
        by_component: dict[Any, list] = {}
        for b in line.batches:
            by_component.setdefault(b.medicine_id, []).append(b)
        for batches in by_component.values():
            per_hamper = sum(b.qty_base for b in batches) // line.qty_base
            need = per_hamper * qty_base
            for b in sorted(batches, key=lambda b: -b.seq):
                take = min(need, b.qty_base - b.returned_qty_base)
                if take > 0:
                    out.append((b, take))
                    need -= take
        return out
    out, need = [], qty_base
    for b in sorted(line.batches, key=lambda b: -b.seq):
        take = min(need, b.qty_base - b.returned_qty_base)
        if take > 0:
            out.append((b, take))
            need -= take
        if need == 0:
            break
    return out


async def create_return(
    session: AsyncSession, actor: CurrentUser, invoice_id: UUID, data: dict[str, Any], clients: Clients
) -> SaleReturn:
    inv = await get_invoice(session, actor, invoice_id, lock=True)
    if inv.status != "completed":
        raise AppError(ErrorCode.INVOICE_STATE, f"A {inv.status} invoice cannot take returns", status_code=409,
                       details={"status": inv.status})  # fmt: skip
    refund = data["refund_method"]
    if refund == "credit_note" and inv.customer_id is None:
        raise AppError(
            ErrorCode.CUSTOMER_REQUIRED, "A credit note needs the invoice's customer", status_code=422
        )
    if inv.credit_amount > 0 and refund == "cash":
        raise AppError(ErrorCode.VALIDATION_ERROR, "A credit sale is refunded as a credit note", status_code=422,
                       details={"field": "refund_method"})  # fmt: skip
    settings = await session.get(BranchSettingsCopy, inv.branch_id)
    lines = {x.id: x for x in inv.lines}
    ret = SaleReturn(invoice_id=inv.id, branch_id=inv.branch_id, refund_method=refund, refund_usd=Decimal("0.00"),
                     to_quarantine=data["to"] == "quarantine", reason=clean(data["reason"]), status="pending",
                     created_by=actor.id, lines=[])  # fmt: skip
    seq = 0
    for i, item in enumerate(data["lines"], start=1):
        line = lines.get(item["invoice_line_id"])
        if line is None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, f"Line {i}: not a line of this invoice", status_code=422
            )
        if item.get("opened") and not (settings and settings.allow_opened_pack_returns):
            raise AppError(ErrorCode.OPENED_PACK_RETURN, f"Line {i}: opened packs are not taken back at this branch",
                           status_code=422, details={"line": i})  # fmt: skip
        qty_base = item["qty"] * line.qty_in_base
        left = line.qty_base - line.returned_qty_base
        if qty_base > left:
            raise AppError(ErrorCode.RETURN_EXCEEDS_SOLD, f"Line {i}: only {left // line.qty_in_base} {line.pack_unit} "
                           "can still be returned", status_code=422,
                           details={"line": i, "returnable_base": left})  # fmt: skip
        amount = money.usd(line.net * qty_base / line.qty_base)
        ret.refund_usd += amount
        line.returned_qty_base += qty_base
        allocations = _allocate(line, qty_base)
        given = Decimal("0.00")
        for n, (batch, qty) in enumerate(allocations):
            batch.returned_qty_base += qty
            seq += 1
            # each batch its share of the refund; the last one the rest, so cents add up
            parts = sum(q for _, q in allocations)
            share = amount - given if n == len(allocations) - 1 else money.usd(amount * qty / parts)
            given += share
            ret.lines.append(SaleReturnLine(seq=seq, invoice_line_id=line.id, batch_id=batch.batch_id, qty_base=qty,
                                            amount=share, opened=bool(item.get("opened")),
                                            hamper_qty=qty_base if line.is_hamper and n == 0 else 0))  # fmt: skip
    inv.returned_total += ret.refund_usd
    session.add(ret)
    await session.commit()  # holds the returned quantities: a second return cannot take them again

    try:
        await return_steps(session, ret, inv, actor, clients)
    except AppError as err:
        await session.rollback()
        ret = await session.get(SaleReturn, ret.id, populate_existing=True)
        ret.status = "needs_attention"
        ret.failure_reason = f"{err.code}: {err.message}"[:500]
        audit(session, actor, "invoice.return_failed", "invoice", inv.id, branch_id=inv.branch_id,
              after={"return_id": str(ret.id), "reason": ret.failure_reason})  # fmt: skip
        await session.commit()
        raise
    return ret
