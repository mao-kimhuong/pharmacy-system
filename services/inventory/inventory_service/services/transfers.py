"""Stock transfers between branches. Rules:

- Request (transfers.request, destination branch): medicines + quantities from a
  source branch. The source approves (transfers.approve → the transfer) or
  rejects (reason); the destination may cancel while it waits (reason).
- Push (transfers.dispatch, source branch): a transfer without a request.
- Pick (transfers.dispatch, source): FEFO by default (active, unexpired,
  unreserved batches); a line may name batches with a reason. Picking reserves
  the stock, so a sale cannot take it; picking again replaces the picks.
- Dispatch (transfers.dispatch, source, Idempotency-Key): a transfer_out
  movement per picked batch, at the batch's cost; the quantity is now in
  transit (visible to both branches). Controlled lines: the user's PIN and a
  witness's PIN (action transfers.dispatch); movements carry them to the register.
- Receive (transfers.receive, destination, Idempotency-Key): per picked batch the
  good and the damaged quantity, optionally the shelf location. Good quantity
  → transfer_in (same batch, same lot / expiry / supplier / cost). Short, damaged
  or extra → a discrepancy; the transfer is "received" until they are resolved,
  then "closed". Controlled: PIN + witness at the destination too.
- Resolve (transfers.resolve, either branch, reason): short / damaged →
  write_off (a shrinkage record: short on the source's books, damaged on the
  destination's; it was already out of stock) or return_to_source (transfer_in
  back into the same batch at the source); extra → accept (adjust_in at the
  destination) or reject.
- Cancel (reason) only before dispatch; the picks' reservations are released.
  After dispatch the only way is receive + discrepancies.
- No invoice, no profit: events carry quantities and cost per base unit.
- Owner: everything. Everyone else only for their own side of the transfer.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller, InternalClient
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event
from pharmacy_shared.pin import consume_pin, consume_witness

from ..models import (
    DocSequence,
    KnownBranch,
    OutboxEvent,
    Product,
    ShelfLocation,
    Shrinkage,
    Transfer,
    TransferDiscrepancy,
    TransferLine,
    TransferPick,
    TransferRequest,
    TransferRequestLine,
)
from .common import audit, clean
from .movements import already_booked, apply_movement, lock_stock
from .reservations import _fefo_rows, _override_row, available

OPEN = ("approved", "picked")


def _state(message: str, status: str) -> AppError:
    return AppError(ErrorCode.TRANSFER_STATE, message, status_code=409, details={"status": status})


def _not_found(what: str = "Transfer") -> AppError:
    return AppError(ErrorCode.NOT_FOUND, f"{what} not found", status_code=404)


def _need(actor: CurrentUser, permission: str, branch_id: UUID) -> None:
    actor.require(permission)
    actor.require_branch(branch_id)


async def _branch(session: AsyncSession, branch_id: UUID) -> KnownBranch:
    branch = await session.get(KnownBranch, branch_id)
    if branch is None or not branch.is_active:
        raise AppError(ErrorCode.UNKNOWN_BRANCH, "Unknown or inactive branch", status_code=422)
    return branch


async def _products(session: AsyncSession, ids: set[UUID]) -> dict[UUID, Product]:
    rows = (await session.execute(select(Product).where(Product.id.in_(ids)))).scalars() if ids else []
    return {p.id: p for p in rows}


# ---------------------------------------------------------------- snapshots / events


async def payload(session: AsyncSession, t: Transfer) -> dict[str, Any]:
    branches = {b.id: b for b in (await session.execute(
        select(KnownBranch).where(KnownBranch.id.in_([t.from_branch_id, t.to_branch_id])))).scalars()}  # fmt: skip
    products = await _products(session, {x.medicine_id for x in t.lines})
    request = await session.get(TransferRequest, t.request_id) if t.request_id else None

    def branch(bid: UUID) -> dict[str, Any]:
        b = branches.get(bid)
        return {"id": str(bid), "code": b.code if b else "", "name_en": b.name_en if b else "",
                "name_km": b.name_km if b else ""}  # fmt: skip

    def product(mid: UUID) -> dict[str, Any]:
        p = products.get(mid)
        return {"sku": p.sku if p else "", "name": p.display_name if p else "", "name_km": p.name_km if p else "",
                "base_unit": p.base_unit if p else ""}  # fmt: skip

    return {
        "transfer_id": str(t.id), "version": t.version, "number": t.number, "status": t.status,
        "from_branch": branch(t.from_branch_id), "to_branch": branch(t.to_branch_id),
        "request_id": str(t.request_id) if t.request_id else None, "request_number": request.number if request else None,
        "request_source_ref": request.source_ref if request else None, "note": t.note,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "dispatched_at": t.dispatched_at.isoformat() if t.dispatched_at else None,
        "received_at": t.received_at.isoformat() if t.received_at else None,
        "dispatch_witness": t.dispatch_witness, "receive_witness": t.receive_witness, "cancel_reason": t.cancel_reason,
        "lines": [{"line_no": x.line_no, "medicine_id": str(x.medicine_id), "qty_base": x.qty_base,
                   "is_controlled": x.is_controlled, "source_ref": x.source_ref, **product(x.medicine_id)}
                  for x in t.lines],
        "picks": [{"pick_id": str(p.id), "line_no": p.line_no, "batch_id": str(p.batch_id), "lot_no": p.batch.lot_no,
                   "expiry_date": p.batch.expiry_date.isoformat(), "supplier_id": str(p.batch.supplier_id)
                   if p.batch.supplier_id else None, "cost_per_base": str(p.batch.cost_per_base),
                   "qty_base": p.qty_base, "qty_received": p.qty_received, "qty_damaged": p.qty_damaged,
                   "override_reason": p.override_reason} for p in t.picks],
        "discrepancies": [{"id": str(d.id), "pick_id": str(d.pick_id), "kind": d.kind, "qty_base": d.qty_base,
                           "status": d.status, "resolution": d.resolution, "reason": d.reason} for d in t.discrepancies],
    }  # fmt: skip


async def _publish(session: AsyncSession, t: Transfer, event: str) -> None:
    t.version += 1
    await session.flush()
    await session.refresh(t, attribute_names=["lines", "picks", "discrepancies"])
    add_event(session, OutboxEvent, event, await payload(session, t))


# ---------------------------------------------------------------- reading


async def get_transfer(
    session: AsyncSession, actor: CurrentUser, transfer_id: UUID, *, lock: bool = False
) -> Transfer:
    query = select(Transfer).where(Transfer.id == transfer_id)
    if lock:
        query = query.with_for_update(of=Transfer).execution_options(populate_existing=True)
    t = (await session.execute(query)).scalar_one_or_none()
    if t is None or not (
        actor.can_access_branch(t.from_branch_id) or actor.can_access_branch(t.to_branch_id)
    ):
        raise _not_found()
    return t


async def by_number(session: AsyncSession, actor: CurrentUser, number: str) -> Transfer:
    t = (
        await session.execute(select(Transfer).where(Transfer.number == number.strip().upper()))
    ).scalar_one_or_none()
    if t is None:
        raise _not_found()
    return await get_transfer(session, actor, t.id)


@dataclass(frozen=True)
class TransferFilter:
    branch_id: UUID | None = None
    direction: str | None = None  # in | out
    status: str | None = None


async def list_transfers(session: AsyncSession, actor: CurrentUser, f: TransferFilter, page: int, size: int):  # noqa: ANN201
    query = select(Transfer)
    if f.branch_id:
        actor.require_branch(f.branch_id)
        cond = {
            "in": Transfer.to_branch_id == f.branch_id,
            "out": Transfer.from_branch_id == f.branch_id,
        }.get(
            f.direction or "",
            or_(Transfer.to_branch_id == f.branch_id, Transfer.from_branch_id == f.branch_id),
        )
        query = query.where(cond)
    elif not actor.is_owner:
        mine = list(actor.branch_ids) or [uuid4()]
        query = query.where(or_(Transfer.from_branch_id.in_(mine), Transfer.to_branch_id.in_(mine)))
    if f.status:
        query = query.where(Transfer.status == f.status)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(Transfer.created_at.desc(), Transfer.id).offset((page - 1) * size)
                                 .limit(size))  # fmt: skip
    return list(rows.scalars()), int(total)


def in_transit_of(t: Transfer) -> dict[UUID, int]:
    """pick id → quantity still in transit."""
    if t.status == "dispatched":
        return {p.id: p.qty_base for p in t.picks}
    out: dict[UUID, int] = defaultdict(int)
    for d in t.discrepancies:
        if d.status == "open" and d.kind in ("short", "damaged"):
            out[d.pick_id] += d.qty_base
    return dict(out)


async def in_transit(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID | None
) -> list[dict[str, Any]]:
    query = select(Transfer).where(Transfer.status.in_(("dispatched", "received")))
    if branch_id:
        actor.require_branch(branch_id)
        query = query.where(or_(Transfer.from_branch_id == branch_id, Transfer.to_branch_id == branch_id))
    elif not actor.is_owner:
        mine = list(actor.branch_ids) or [uuid4()]
        query = query.where(or_(Transfer.from_branch_id.in_(mine), Transfer.to_branch_id.in_(mine)))
    rows = []
    for t in (await session.execute(query.order_by(Transfer.dispatched_at))).scalars():
        for pick in t.picks:
            qty = in_transit_of(t).get(pick.id, 0)
            if qty:
                rows.append({"transfer_id": t.id, "number": t.number, "from_branch_id": t.from_branch_id,
                             "to_branch_id": t.to_branch_id, "medicine_id": pick.batch.medicine_id,
                             "batch_id": pick.batch_id, "lot_no": pick.batch.lot_no,
                             "expiry_date": pick.batch.expiry_date, "qty_base": qty,
                             "cost_per_base": pick.batch.cost_per_base, "dispatched_at": t.dispatched_at})  # fmt: skip
    return rows


# ---------------------------------------------------------------- requests


async def _lines(
    session: AsyncSession, raw: list[dict[str, Any]]
) -> list[tuple[UUID, int, Product, str | None]]:
    products = await _products(session, {UUID(str(x["medicine_id"])) for x in raw})
    out, seen = [], set()
    for i, x in enumerate(raw, start=1):
        p = products.get(UUID(str(x["medicine_id"])))
        if p is None or not p.is_active:
            raise AppError(ErrorCode.UNKNOWN_MEDICINE, f"Line {i}: unknown or inactive medicine", status_code=422,
                           details={"line": i})  # fmt: skip
        if p.id in seen:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {i}: {p.sku} is listed twice", status_code=422)
        seen.add(p.id)
        out.append((p.id, int(x["qty_base"]), p, x.get("source_ref")))
    return out


def _same_branch(from_id: UUID, to_id: UUID) -> None:
    if from_id == to_id:
        raise AppError(ErrorCode.VALIDATION_ERROR, "The source and the destination must be different branches",
                       status_code=422)  # fmt: skip


async def get_request(session: AsyncSession, actor: CurrentUser, request_id: UUID, *, lock: bool = False
                      ) -> TransferRequest:  # fmt: skip
    query = select(TransferRequest).where(TransferRequest.id == request_id)
    r = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if r is None or not (
        actor.can_access_branch(r.from_branch_id) or actor.can_access_branch(r.to_branch_id)
    ):
        raise _not_found("Transfer request")
    return r


async def list_requests(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID | None, status: str | None
):  # noqa: ANN201
    query = select(TransferRequest)
    if branch_id:
        actor.require_branch(branch_id)
        query = query.where(
            or_(TransferRequest.from_branch_id == branch_id, TransferRequest.to_branch_id == branch_id)
        )
    elif not actor.is_owner:
        mine = list(actor.branch_ids) or [uuid4()]
        query = query.where(
            or_(TransferRequest.from_branch_id.in_(mine), TransferRequest.to_branch_id.in_(mine))
        )
    if status:
        query = query.where(TransferRequest.status == status)
    return list(
        (await session.execute(query.order_by(TransferRequest.created_at.desc()).limit(500))).scalars()
    )


async def create_request(session: AsyncSession, actor: CurrentUser | None, data: dict[str, Any], *,
                         check: bool = True) -> TransferRequest:  # fmt: skip
    if check:
        _need(actor, "transfers.request", data["to_branch_id"])
    _same_branch(data["from_branch_id"], data["to_branch_id"])
    await _branch(session, data["from_branch_id"])
    to = await _branch(session, data["to_branch_id"])
    lines = await _lines(session, data["lines"])
    r = TransferRequest(from_branch_id=data["from_branch_id"], to_branch_id=to.id, status="requested",
                        reason=clean(data.get("reason")), needed_by=data.get("needed_by"),
                        source_ref=data.get("source_ref"), requested_by=actor.id if actor else None,
                        lines=[TransferRequestLine(line_no=i, medicine_id=mid, qty_base=q, source_ref=ref)
                               for i, (mid, q, _, ref) in enumerate(lines, start=1)])  # fmt: skip
    r.number = await next_number(session, DocSequence, to.id, to.code, "TQ")
    session.add(r)
    await session.flush()
    add_event(session, OutboxEvent, "transfer_request.created", _request_payload(r))
    audit(session, actor, "transfer_request.created", "transfer_request", r.id, branch_id=to.id,
          after={"number": r.number, "from": str(r.from_branch_id), "lines": len(r.lines), "reason": r.reason})  # fmt: skip
    return r


def _request_payload(r: TransferRequest) -> dict[str, Any]:
    return {"request_id": str(r.id), "number": r.number, "status": r.status, "from_branch_id": str(r.from_branch_id),
            "to_branch_id": str(r.to_branch_id), "source_ref": r.source_ref,
            "transfer_id": str(r.transfer_id) if r.transfer_id else None,
            "lines": [{"medicine_id": str(x.medicine_id), "qty_base": x.qty_base, "source_ref": x.source_ref}
                      for x in r.lines]}  # fmt: skip


async def _new_transfer(session: AsyncSession, actor_id: UUID | None, from_id: UUID, to_id: UUID,
                        lines: list[tuple[UUID, int, Product, str | None]], note: str = "",
                        request_id: UUID | None = None) -> Transfer:  # fmt: skip
    source = await _branch(session, from_id)
    t = Transfer(from_branch_id=from_id, to_branch_id=to_id, request_id=request_id, status="approved", note=note,
                 created_by=actor_id, version=0, picks=[], discrepancies=[],
                 lines=[TransferLine(line_no=i, medicine_id=mid, qty_base=q, is_controlled=bool(p.controlled_schedule),
                                     source_ref=ref) for i, (mid, q, p, ref) in enumerate(lines, start=1)])  # fmt: skip
    t.number = await next_number(session, DocSequence, source.id, source.code, "TR")
    session.add(t)
    await _publish(session, t, "transfer.created")
    return t


async def approve_request(session: AsyncSession, actor: CurrentUser, request_id: UUID) -> Transfer:
    r = await get_request(session, actor, request_id, lock=True)
    _need(actor, "transfers.approve", r.from_branch_id)
    if r.status != "requested":
        raise _state(f"This request is {r.status}", r.status)
    lines = await _lines(session, [{"medicine_id": x.medicine_id, "qty_base": x.qty_base, "source_ref": x.source_ref}
                                   for x in r.lines])  # fmt: skip
    t = await _new_transfer(session, actor.id, r.from_branch_id, r.to_branch_id, lines, r.reason, r.id)
    r.status, r.decided_by, r.decided_at, r.transfer_id = "approved", actor.id, clock.now(), t.id
    add_event(session, OutboxEvent, "transfer_request.approved", _request_payload(r))
    audit(session, actor, "transfer_request.approved", "transfer_request", r.id, branch_id=r.from_branch_id,
          after={"number": r.number, "transfer": t.number})  # fmt: skip
    await session.commit()
    return t


async def decide_request(session: AsyncSession, actor: CurrentUser, request_id: UUID, reason: str,
                         action: str) -> TransferRequest:  # fmt: skip
    """reject (source, transfers.approve) or cancel (destination, transfers.request)."""
    r = await get_request(session, actor, request_id, lock=True)
    if action == "reject":
        _need(actor, "transfers.approve", r.from_branch_id)
    else:
        _need(actor, "transfers.request", r.to_branch_id)
    if r.status != "requested":
        raise _state(f"This request is {r.status}", r.status)
    r.status = "rejected" if action == "reject" else "cancelled"
    r.decided_by, r.decided_at, r.decision_reason = actor.id, clock.now(), clean(reason)
    add_event(session, OutboxEvent, f"transfer_request.{r.status}", _request_payload(r))
    audit(session, actor, f"transfer_request.{r.status}", "transfer_request", r.id, branch_id=r.to_branch_id,
          after={"number": r.number, "reason": r.decision_reason})  # fmt: skip
    await session.commit()
    return r


async def push(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Transfer:
    _need(actor, "transfers.dispatch", data["from_branch_id"])
    _same_branch(data["from_branch_id"], data["to_branch_id"])
    await _branch(session, data["to_branch_id"])
    t = await _new_transfer(session, actor.id, data["from_branch_id"], data["to_branch_id"],
                            await _lines(session, data["lines"]), clean(data.get("note")))  # fmt: skip
    audit(session, actor, "transfer.created", "transfer", t.id, branch_id=t.from_branch_id,
          after={"number": t.number, "to": str(t.to_branch_id), "lines": len(t.lines)})  # fmt: skip
    await session.commit()
    return t


async def from_purchase_request(
    session: AsyncSession, caller: InternalCaller, data: dict[str, Any]
) -> dict[str, Any]:
    """A manager fills a purchase request from another branch's stock: an approved
    request + its transfer, once per source_ref."""
    found = (await session.execute(select(TransferRequest).where(TransferRequest.source_ref == data["source_ref"]))
             ).scalar_one_or_none()  # fmt: skip
    if found is None:
        found = await create_request(session, None, data, check=False)
        found.requested_by = caller.user_id
        lines = await _lines(session, data["lines"])
        t = await _new_transfer(session, caller.user_id, found.from_branch_id, found.to_branch_id, lines,
                                found.reason, found.id)  # fmt: skip
        found.status, found.decided_by, found.decided_at, found.transfer_id = (
            "approved",
            caller.user_id,
            clock.now(),
            t.id,
        )
        await session.commit()
    t = await session.get(Transfer, found.transfer_id)
    return {
        "request_id": found.id,
        "request_number": found.number,
        "transfer_id": t.id,
        "transfer_number": t.number,
    }


# ---------------------------------------------------------------- picking


async def _release(session: AsyncSession, t: Transfer) -> None:
    for pick in list(t.picks):
        stock = await lock_stock(session, t.from_branch_id, pick.batch_id)
        stock.qty_reserved -= pick.qty_base
        await session.delete(pick)
    await session.flush()
    await session.refresh(t, attribute_names=["picks"])


async def pick(
    session: AsyncSession, actor: CurrentUser, transfer_id: UUID, data: dict[str, Any]
) -> Transfer:
    t = await get_transfer(session, actor, transfer_id, lock=True)
    _need(actor, "transfers.dispatch", t.from_branch_id)
    if t.status not in OPEN:
        raise _state(f"Transfer {t.number} is {t.status}", t.status)
    chosen = {x["line_no"]: x.get("batches") or [] for x in data.get("lines") or []}
    await _release(session, t)  # picking again replaces the earlier picks
    missing, picks = [], []
    left: dict[UUID, int] = {}
    for line in sorted(t.lines, key=lambda x: (str(x.medicine_id), x.line_no)):  # fixed lock order
        given = chosen.get(line.line_no, [])
        if given:
            if sum(b["qty_base"] for b in given) != line.qty_base:
                raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {line.line_no}: the batches must add up to "
                               f"{line.qty_base}", status_code=422, details={"line_no": line.line_no})  # fmt: skip
            for b in given:
                if not clean(b.get("reason")):
                    raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {line.line_no}: give the reason for choosing "
                                   "this batch instead of FEFO", status_code=422,
                                   details={"line_no": line.line_no, "field": "reason"})  # fmt: skip
                stock = await _override_row(
                    session, t.from_branch_id, line.medicine_id, b["batch_id"], line.line_no
                )
                free = left.setdefault(stock.id, available(stock))
                if free < b["qty_base"]:
                    missing.append(
                        {"line_no": line.line_no, "batch_id": str(b["batch_id"]), "available": free}
                    )
                    continue
                left[stock.id] -= b["qty_base"]
                picks.append((line, stock, b["qty_base"], clean(b["reason"])))
            continue
        rows = await _fefo_rows(session, t.from_branch_id, line.medicine_id)
        if sum(left.setdefault(s.id, available(s)) for s in rows) < line.qty_base:
            missing.append({"line_no": line.line_no, "medicine_id": str(line.medicine_id), "requested": line.qty_base,
                            "available": sum(left[s.id] for s in rows)})  # fmt: skip
            continue
        need = line.qty_base
        for stock in rows:  # earliest expiry first
            take = min(need, left[stock.id])
            if take > 0:
                left[stock.id] -= take
                picks.append((line, stock, take, None))
                need -= take
            if need == 0:
                break
    if missing:
        raise AppError(ErrorCode.OUT_OF_STOCK, "Not enough stock at the source branch", status_code=409,
                       details={"lines": sorted(missing, key=lambda m: m["line_no"])})  # fmt: skip
    seq: dict[int, int] = defaultdict(int)
    for line, stock, qty, reason in picks:
        stock.qty_reserved += qty
        seq[line.line_no] += 1
        session.add(TransferPick(transfer_id=t.id, line_no=line.line_no, seq=seq[line.line_no], batch_id=stock.batch_id,
                                 qty_base=qty, override_reason=reason))  # fmt: skip
    t.status, t.picked_by, t.picked_at = "picked", actor.id, clock.now()
    await _publish(session, t, "transfer.picked")
    audit(session, actor, "transfer.picked", "transfer", t.id, branch_id=t.from_branch_id, after={
        "number": t.number, "batches": [f"{p.batch.lot_no} x {p.qty_base}" for p in t.picks],
        "overrides": [f"line {p.line_no} {p.batch.lot_no}: {p.override_reason}" for p in t.picks if p.override_reason]})  # fmt: skip
    await session.commit()
    return t


# ---------------------------------------------------------------- dispatch / receive


async def _controlled_signoff(auth: InternalClient, actor: CurrentUser, t: Transfer, data: dict[str, Any],
                              action: str, branch_id: UUID) -> dict[str, Any]:  # fmt: skip
    if not any(x.is_controlled for x in t.lines):
        return {}
    me = await consume_pin(auth, data.get("pin_token"), action, user=actor, branch_id=branch_id)
    witness = await consume_witness(auth, data.get("witness_token"), action, actor=actor, branch_id=branch_id)
    return {"actor_name": me.name, "witness_id": str(witness.user_id), "witness_name": witness.name}


async def dispatch(session: AsyncSession, actor: CurrentUser, auth: InternalClient, transfer_id: UUID,
                   data: dict[str, Any]) -> Transfer:  # fmt: skip
    t = await get_transfer(session, actor, transfer_id, lock=True)
    _need(actor, "transfers.dispatch", t.from_branch_id)
    if t.status == "approved":
        raise _state(f"Pick transfer {t.number} first", t.status)
    if t.status != "picked":
        raise _state(f"Transfer {t.number} is {t.status}", t.status)
    signoff = await _controlled_signoff(auth, actor, t, data, "transfers.dispatch", t.from_branch_id)
    controlled = {x.line_no for x in t.lines if x.is_controlled}
    for p in t.picks:
        if await already_booked(session, "transfer_out", "transfer_pick", str(p.id)):
            continue
        stock = await lock_stock(session, t.from_branch_id, p.batch_id)
        stock.qty_reserved -= p.qty_base
        await session.flush()
        meta = {"transfer_id": str(t.id), "number": t.number, "to_branch_id": str(t.to_branch_id),
                **(signoff if p.line_no in controlled else {})}  # fmt: skip
        await apply_movement(session, branch_id=t.from_branch_id, batch=p.batch, type="transfer_out",
                             qty_base=-p.qty_base, ref_type="transfer_pick", ref_id=str(p.id),
                             reason=f"Transfer {t.number}", actor_id=actor.id, meta=meta)  # fmt: skip
    t.status, t.dispatched_by, t.dispatched_at = "dispatched", actor.id, clock.now()
    t.dispatch_witness = signoff.get("witness_name", "")
    await _publish(session, t, "transfer.dispatched")
    audit(session, actor, "transfer.dispatched", "transfer", t.id, branch_id=t.from_branch_id, after={
        "number": t.number, "qty_base": sum(p.qty_base for p in t.picks), "witness": t.dispatch_witness or None})  # fmt: skip
    await session.commit()
    return t


async def receive(session: AsyncSession, actor: CurrentUser, auth: InternalClient, transfer_id: UUID,
                  data: dict[str, Any]) -> Transfer:  # fmt: skip
    t = await get_transfer(session, actor, transfer_id, lock=True)
    _need(actor, "transfers.receive", t.to_branch_id)
    if t.status != "dispatched":
        raise _state(f"Transfer {t.number} is {t.status}", t.status)
    given = {x["pick_id"]: x for x in data["lines"]}
    picks = {p.id: p for p in t.picks}
    unknown = set(given) - set(picks)
    if unknown or set(picks) - set(given):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Give the received quantity for every picked batch (pick_id)",
                       status_code=422, details={"picks": [str(p) for p in picks]})  # fmt: skip
    signoff = await _controlled_signoff(auth, actor, t, data, "transfers.receive", t.to_branch_id)
    controlled = {x.line_no for x in t.lines if x.is_controlled}
    for pick_id, x in given.items():
        p = picks[pick_id]
        good, damaged = int(x["qty_received"]), int(x.get("qty_damaged") or 0)
        p.qty_received, p.qty_damaged = good, damaged
        into_stock = min(good, p.qty_base)
        if into_stock:
            meta = {"transfer_id": str(t.id), "number": t.number, "from_branch_id": str(t.from_branch_id),
                    **(signoff if p.line_no in controlled else {})}  # fmt: skip
            await apply_movement(session, branch_id=t.to_branch_id, batch=p.batch, type="transfer_in",
                                 qty_base=into_stock, ref_type="transfer_pick", ref_id=str(p.id),
                                 reason=f"Transfer {t.number}", actor_id=actor.id, meta=meta)  # fmt: skip
        short = p.qty_base - good - damaged
        for kind, qty in (("damaged", min(damaged, max(p.qty_base - good, 0))), ("short", short),
                          ("extra", good + damaged - p.qty_base)):  # fmt: skip
            if qty > 0:
                session.add(TransferDiscrepancy(transfer_id=t.id, pick_id=p.id, kind=kind, qty_base=qty,
                                                status="open"))  # fmt: skip
        location = (x.get("location") or "").strip().upper()
        if location:
            p.location = location
            await session.execute(insert(ShelfLocation).values(
                branch_id=t.to_branch_id, medicine_id=p.batch.medicine_id, code=location, updated_by=actor.id,
            ).on_conflict_do_update(index_elements=["branch_id", "medicine_id"],
                                    set_={"code": location, "updated_by": actor.id}))  # fmt: skip
    await session.flush()
    await session.refresh(t, attribute_names=["discrepancies"])
    t.status = "received" if t.discrepancies else "closed"
    t.received_by, t.received_at, t.receive_witness = actor.id, clock.now(), signoff.get("witness_name", "")
    if t.status == "closed":
        t.closed_at = clock.now()
    await _publish(session, t, "transfer.received")
    if t.status == "closed":
        add_event(session, OutboxEvent, "transfer.closed", await payload(session, t))
    audit(session, actor, "transfer.received", "transfer", t.id, branch_id=t.to_branch_id, after={
        "number": t.number, "status": t.status, "witness": t.receive_witness or None,
        "differences": [f"{d.kind} {d.qty_base}" for d in t.discrepancies]})  # fmt: skip
    await session.commit()
    return t


# ---------------------------------------------------------------- discrepancies, cancel


async def resolve(session: AsyncSession, actor: CurrentUser, transfer_id: UUID, discrepancy_id: UUID,
                  data: dict[str, Any]) -> Transfer:  # fmt: skip
    t = await get_transfer(session, actor, transfer_id, lock=True)
    actor.require("transfers.resolve")
    d = next((x for x in t.discrepancies if x.id == discrepancy_id), None)
    if d is None:
        raise _not_found("Transfer difference")
    if d.status != "open":
        raise _state("This difference is already resolved", t.status)
    allowed = ("accept", "reject") if d.kind == "extra" else ("write_off", "return_to_source")
    if data["resolution"] not in allowed:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"A {d.kind} quantity is resolved by {' or '.join(allowed)}",
                       status_code=422, details={"allowed": list(allowed)})  # fmt: skip
    pick = next(p for p in t.picks if p.id == d.pick_id)
    reason = clean(data["reason"])
    if data["resolution"] == "write_off":
        branch_id = t.from_branch_id if d.kind == "short" else t.to_branch_id  # short: the source lost it
        branch = await _branch(session, branch_id)
        s = Shrinkage(branch_id=branch_id, batch_id=pick.batch_id, medicine_id=pick.batch.medicine_id,
                      qty_base=d.qty_base, reason="lost_theft" if d.kind == "short" else "damaged",
                      note=f"In transit, transfer {t.number}: {reason}"[:1000], status="posted",
                      value=(pick.batch.cost_per_base * d.qty_base).quantize(Decimal("0.01")),
                      is_controlled=any(x.is_controlled for x in t.lines if x.line_no == pick.line_no),
                      created_by=actor.id, decided_by=actor.id, decided_at=clock.now(),
                      meta={"in_transit": True, "transfer_id": str(t.id), "discrepancy_id": str(d.id)})  # fmt: skip
        s.number = await next_number(session, DocSequence, branch.id, branch.code, "SH")
        session.add(s)
        await session.flush()
        d.shrinkage_id = s.id
    elif data["resolution"] == "return_to_source":
        move = await apply_movement(session, branch_id=t.from_branch_id, batch=pick.batch, type="transfer_in",
                                    qty_base=d.qty_base, ref_type="transfer_return", ref_id=str(d.id),
                                    reason=f"Back from transfer {t.number}: {reason}"[:255], actor_id=actor.id,
                                    meta={"transfer_id": str(t.id), "number": t.number, "returned": True})  # fmt: skip
        d.movement_id = move.id
    elif data["resolution"] == "accept":
        move = await apply_movement(session, branch_id=t.to_branch_id, batch=pick.batch, type="adjust_in",
                                    qty_base=d.qty_base, ref_type="transfer_extra", ref_id=str(d.id),
                                    reason=f"Extra on transfer {t.number}: {reason}"[:255], actor_id=actor.id,
                                    meta={"transfer_id": str(t.id), "number": t.number})  # fmt: skip
        d.movement_id = move.id
    d.status, d.resolution, d.reason, d.resolved_by, d.resolved_at = (
        "resolved",
        data["resolution"],
        reason,
        actor.id,
        clock.now(),
    )
    if all(x.status == "resolved" for x in t.discrepancies):
        t.status, t.closed_at = "closed", clock.now()
    await _publish(session, t, "transfer.closed" if t.status == "closed" else "transfer.updated")
    audit(session, actor, "transfer.difference_resolved", "transfer", t.id, branch_id=t.to_branch_id, after={
        "number": t.number, "kind": d.kind, "qty_base": d.qty_base, "resolution": d.resolution, "reason": reason})  # fmt: skip
    await session.commit()
    return t


async def cancel(session: AsyncSession, actor: CurrentUser, transfer_id: UUID, reason: str) -> Transfer:
    t = await get_transfer(session, actor, transfer_id, lock=True)
    _need(actor, "transfers.dispatch", t.from_branch_id)
    if t.status not in OPEN:
        raise _state(
            f"Transfer {t.number} is {t.status}: after dispatch only receive + differences", t.status
        )
    await _release(session, t)
    t.status, t.cancel_reason = "cancelled", clean(reason)
    await _publish(session, t, "transfer.cancelled")
    audit(session, actor, "transfer.cancelled", "transfer", t.id, branch_id=t.from_branch_id,
          after={"number": t.number, "reason": t.cancel_reason})  # fmt: skip
    await session.commit()
    return t
