"""Recalls and supplier returns (S8b). Rules:

Recall (inventory.recall, reason, Idempotency-Key):
- The owner recalls lots of a medicine in every branch (the batches' status becomes
  "recalled", so stock that arrives later is blocked too); a branch manager only in
  their own branches (the stock rows there are blocked, the batch elsewhere is not).
- Blocked stock is never sold, reserved, picked or counted as sellable (reservations
  → BATCH_BLOCKED for a chosen batch). batch.recalled per branch (Telegram alert) and
  a User Log entry.
- Per line (branch + batch): return to supplier (a draft supplier return in
  purchasing, from the recall) or destroy (shrinkage reason "recalled"; controlled:
  PIN + a manager/owner witness, as every destruction).
- Close when nothing is left on hand; lift (owner, reason) restores the old status.
- Numbers RC-2026-000001 from one counter (a recall spans branches).

Supplier return movement (/internal/v1/movements/supplier-return, purchasing):
- One `supplier_return` movement per line, once per line (a retried call books
  nothing twice); the batch must be the supplier's. Returns lot, expiry and cost
  (the credit is valued at the batch's cost).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller, InternalClient
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event

from ..models import (
    Batch,
    DocSequence,
    OutboxEvent,
    Product,
    Recall,
    RecallLine,
    Stock,
    Transfer,
    TransferPick,
)
from . import shrinkage
from .common import audit, clean
from .movements import already_booked, apply_movement

GLOBAL = UUID(int=0)


def _state(message: str, status: str) -> AppError:
    return AppError(ErrorCode.RECALL_STATE, message, status_code=409, details={"status": status})


def _scope(actor: CurrentUser) -> tuple[bool, list[UUID]]:
    if actor.is_owner:
        return True, []
    if actor.role != "branch_manager":
        raise AppError(ErrorCode.FORBIDDEN, "Only the owner or a branch manager starts a recall", status_code=403)
    return False, sorted(actor.branch_ids)


async def start(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Recall:
    all_branches, branches = _scope(actor)
    lots = sorted({clean(x) for x in data["lot_nos"] if clean(x)})
    product = await session.get(Product, data["medicine_id"])
    if product is None:
        raise AppError(ErrorCode.UNKNOWN_MEDICINE, "Unknown medicine", status_code=422)
    batches = list((await session.execute(select(Batch).where(
        Batch.medicine_id == product.id, Batch.lot_no.in_(lots)).with_for_update())).scalars())  # fmt: skip
    if not batches:
        raise AppError(ErrorCode.NOT_FOUND, f"No batch of {product.sku} with lot {', '.join(lots)}", status_code=404)
    number = (await next_number(session, DocSequence, GLOBAL, "HQ", "RC")).removeprefix("HQ-")
    recall = Recall(number=number, medicine_id=product.id, lot_nos=lots, all_branches=all_branches,
                    branch_ids=[str(b) for b in branches], reason=clean(data["reason"]), source=clean(data.get("source")),
                    status="open", started_by=actor.id, lines=[])  # fmt: skip
    session.add(recall)
    await session.flush()
    query = select(Stock).where(Stock.batch_id.in_([b.id for b in batches])).with_for_update()
    if not all_branches:
        query = query.where(Stock.branch_id.in_(branches))
    stocks = list((await session.execute(query)).scalars())
    by_batch = {b.id: b for b in batches}
    for st in stocks:
        st.recall_id = recall.id
        recall.lines.append(RecallLine(recall_id=recall.id, branch_id=st.branch_id, batch_id=st.batch_id,
                                       qty_at_start=st.qty_on_hand, previous_status=by_batch[st.batch_id].status,
                                       action="pending" if st.qty_on_hand > 0 else "none"))  # fmt: skip
    if all_branches:
        for b in batches:
            b.status = "recalled"
    per_branch: dict[UUID, int] = {}
    for st in stocks:
        per_branch[st.branch_id] = per_branch.get(st.branch_id, 0) + st.qty_on_hand
    for branch_id, qty in per_branch.items():
        add_event(session, OutboxEvent, "batch.recalled", {
            "recall_id": str(recall.id), "number": number, "branch_id": str(branch_id),
            "medicine_id": str(product.id), "sku": product.sku, "lots": lots, "qty_base": qty,
            "batch_ids": [str(st.batch_id) for st in stocks if st.branch_id == branch_id],
            "occurred_at": clock.now().isoformat()})  # fmt: skip
    audit(session, actor, "recall.started", "recall", recall.id, after={
        "number": number, "sku": product.sku, "lots": lots, "reason": recall.reason,
        "branches": "all" if all_branches else [str(b) for b in branches], "lines": len(recall.lines)})  # fmt: skip
    await session.commit()
    return recall


async def get(session: AsyncSession, actor: CurrentUser, recall_id: UUID, *, lock: bool = False) -> Recall:
    query = select(Recall).where(Recall.id == recall_id)
    r = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if r is None or not (actor.is_owner or any(actor.can_access_branch(x.branch_id) for x in r.lines)
                         or any(actor.can_access_branch(UUID(b)) for b in r.branch_ids)):  # fmt: skip
        raise AppError(ErrorCode.NOT_FOUND, "Recall not found", status_code=404)
    return r


async def list_recalls(session: AsyncSession, actor: CurrentUser, status: str | None) -> list[Recall]:
    query = select(Recall).order_by(Recall.created_at.desc()).limit(200)
    if status:
        query = query.where(Recall.status == status)
    rows = list((await session.execute(query)).scalars())
    return [r for r in rows if actor.is_owner or r.all_branches
            or any(actor.can_access_branch(x.branch_id) for x in r.lines)]  # fmt: skip


async def detail(session: AsyncSession, actor: CurrentUser, recall_id: UUID) -> dict[str, Any]:
    """Each line: on hand now, in transit (dispatched, not received) and on open transfers (picked)."""
    r = await get(session, actor, recall_id)
    product = await session.get(Product, r.medicine_id)
    lines = []
    for x in r.lines:
        if not (actor.is_owner or actor.can_access_branch(x.branch_id)):
            continue
        st = (await session.execute(select(Stock).where(Stock.branch_id == x.branch_id, Stock.batch_id == x.batch_id))
              ).scalar_one_or_none()  # fmt: skip
        picks = (await session.execute(select(TransferPick.qty_base, Transfer.status).join(
            Transfer, Transfer.id == TransferPick.transfer_id).where(
            TransferPick.batch_id == x.batch_id, Transfer.from_branch_id == x.branch_id,
            Transfer.status.in_(("picked", "dispatched"))))).all()  # fmt: skip
        batch = await session.get(Batch, x.batch_id)
        lines.append({
            "id": x.id, "branch_id": x.branch_id, "batch_id": x.batch_id, "lot_no": batch.lot_no,
            "expiry_date": batch.expiry_date, "qty_at_start": x.qty_at_start,
            "on_hand": st.qty_on_hand if st else 0, "in_transit": sum(q for q, s in picks if s == "dispatched"),
            "on_open_transfers": sum(q for q, s in picks if s == "picked"), "action": x.action,
            "action_ref": x.action_ref,
        })  # fmt: skip
    return {"id": r.id, "number": r.number, "medicine_id": r.medicine_id, "sku": product.sku if product else "",
            "lot_nos": r.lot_nos, "all_branches": r.all_branches, "reason": r.reason, "source": r.source,
            "status": r.status, "created_at": r.created_at, "lines": lines}  # fmt: skip


async def _line(session: AsyncSession, actor: CurrentUser, recall_id: UUID, line_id: UUID) -> tuple[Recall, RecallLine]:
    r = await get(session, actor, recall_id, lock=True)
    if r.status != "open":
        raise _state(f"Recall {r.number} is {r.status}", r.status)
    line = next((x for x in r.lines if x.id == line_id), None)
    if line is None or not actor.can_access_branch(line.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Recall line not found", status_code=404)
    if line.action not in ("pending",):
        raise _state(f"This line is already {line.action}", line.action)
    return r, line


async def return_line(session: AsyncSession, actor: CurrentUser, purchasing: InternalClient, recall_id: UUID,
                      line_id: UUID) -> dict[str, Any]:  # fmt: skip
    """A draft supplier return (purchasing) for what is on hand of this line."""
    r, line = await _line(session, actor, recall_id, line_id)
    batch = await session.get(Batch, line.batch_id)
    st = (await session.execute(select(Stock).where(Stock.branch_id == line.branch_id, Stock.batch_id == batch.id))
          ).scalar_one()  # fmt: skip
    if batch.supplier_id is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "This batch has no supplier (opening stock): destroy it instead",
                       status_code=422)  # fmt: skip
    if st.qty_on_hand <= 0:
        raise _state("Nothing left on hand for this line", "empty")
    out = await purchasing.post("/supplier-returns/from-recall", {
        "branch_id": str(line.branch_id), "supplier_id": str(batch.supplier_id), "reason": "recalled",
        "note": f"Recall {r.number}: {r.reason}"[:255], "source_ref": f"recall_line:{line.id}",
        "lines": [{"batch_id": str(batch.id), "medicine_id": str(batch.medicine_id), "qty_base": st.qty_on_hand}],
    }, actor=actor, branch_id=line.branch_id)  # fmt: skip
    line.action, line.action_ref = "returned", out["number"]
    audit(session, actor, "recall.line_returned", "recall", r.id, branch_id=line.branch_id,
          after={"number": r.number, "lot_no": batch.lot_no, "supplier_return": out["number"]})  # fmt: skip
    await session.commit()
    return out


async def destroy_line(session: AsyncSession, actor: CurrentUser, auth: InternalClient, recall_id: UUID,
                       line_id: UUID, data: dict[str, Any]) -> Any:  # fmt: skip
    """Shrinkage, reason recalled (controlled: PIN + a manager/owner witness)."""
    r, line = await _line(session, actor, recall_id, line_id)
    st = (await session.execute(select(Stock).where(Stock.branch_id == line.branch_id, Stock.batch_id == line.batch_id))
          ).scalar_one()  # fmt: skip
    qty = st.qty_on_hand - st.qty_reserved
    if qty <= 0:
        raise _state("Nothing left on hand for this line", "empty")
    line_id_value, number = line.id, r.number
    s = await shrinkage.create(session, actor, auth, {
        "branch_id": line.branch_id, "batch_id": line.batch_id, "qty_base": qty, "reason": "recalled",
        "note": f"Recall {number}", **{k: data.get(k) for k in ("destruction_method", "pin_token", "witness_token")}})  # fmt: skip
    line = await session.get(RecallLine, line_id_value)
    line.action, line.action_ref = "destroyed", s.number
    await session.commit()
    return s


async def close(session: AsyncSession, actor: CurrentUser, recall_id: UUID) -> Recall:
    r = await get(session, actor, recall_id, lock=True)
    if r.status != "open":
        raise _state(f"Recall {r.number} is {r.status}", r.status)
    if not (actor.is_owner or actor.role == "branch_manager"):
        raise AppError(ErrorCode.FORBIDDEN, "The owner or a branch manager closes a recall", status_code=403)
    left = 0
    for x in r.lines:
        st = (await session.execute(select(Stock).where(Stock.branch_id == x.branch_id, Stock.batch_id == x.batch_id))
              ).scalar_one_or_none()  # fmt: skip
        left += st.qty_on_hand if st else 0
    if left:
        raise _state(f"{left} still on hand: return or destroy it first", "open")
    r.status, r.closed_at = "closed", clock.now()
    audit(session, actor, "recall.closed", "recall", r.id, after={"number": r.number})
    await session.commit()
    return r


async def lift(session: AsyncSession, actor: CurrentUser, recall_id: UUID, reason: str) -> Recall:
    if not actor.is_owner:
        raise AppError(ErrorCode.FORBIDDEN, "Only the owner lifts a recall", status_code=403)
    r = await get(session, actor, recall_id, lock=True)
    if r.status != "open":
        raise _state(f"Recall {r.number} is {r.status}", r.status)
    for st in (await session.execute(select(Stock).where(Stock.recall_id == r.id).with_for_update())).scalars():
        st.recall_id = None
    if r.all_branches:
        previous = {x.batch_id: x.previous_status for x in r.lines}
        for b in (await session.execute(select(Batch).where(Batch.medicine_id == r.medicine_id,
                                                            Batch.lot_no.in_(r.lot_nos)).with_for_update())).scalars():  # fmt: skip
            if b.status == "recalled":
                b.status = previous.get(b.id, "active")
    r.status, r.lift_reason, r.closed_at = "lifted", clean(reason), clock.now()
    audit(session, actor, "recall.lifted", "recall", r.id, after={"number": r.number, "reason": r.lift_reason})
    await session.commit()
    return r


# ---------------------------------------------------------------- supplier returns (called by purchasing)


async def supplier_return_movement(session: AsyncSession, caller: InternalCaller, data: dict[str, Any]) -> dict[str, Any]:
    out = []
    for line in sorted(data["lines"], key=lambda x: str(x["batch_id"])):  # fixed lock order
        batch = await session.get(Batch, line["batch_id"])
        if batch is None or batch.medicine_id != line["medicine_id"]:
            raise AppError(ErrorCode.NOT_FOUND, f"Line {line['line_no']}: batch not found", status_code=404,
                           details={"line_no": line["line_no"]})  # fmt: skip
        if batch.supplier_id is not None and batch.supplier_id != data["supplier_id"]:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {line['line_no']}: lot {batch.lot_no} came from "
                           "another supplier", status_code=422, details={"line_no": line["line_no"]})  # fmt: skip
        ref = f"{data['return_id']}:{line['line_no']}"
        if not await already_booked(session, "supplier_return", "supplier_return_line", ref):
            await apply_movement(session, branch_id=data["branch_id"], batch=batch, type="supplier_return",
                                 qty_base=-int(line["qty_base"]), ref_type="supplier_return_line", ref_id=ref,
                                 reason=f"Return to supplier {data['number']}"[:255], actor_id=caller.user_id,
                                 meta=line.get("meta"))  # fmt: skip
        out.append({"line_no": line["line_no"], "batch_id": batch.id, "lot_no": batch.lot_no,
                    "expiry_date": batch.expiry_date, "cost_per_base": batch.cost_per_base,
                    "qty_base": int(line["qty_base"])})  # fmt: skip
    await session.commit()
    return {"lines": sorted(out, key=lambda x: x["line_no"])}
