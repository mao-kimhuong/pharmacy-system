"""Stock for sales (called by the sales service over /internal/v1, the sale saga).

Reserve (one reservation per invoice, idempotent):
- Each line (medicine + qty in base units) takes stock FEFO at the branch:
  expiry date, then received date. Only active batches whose expiry date is
  today or later count (expired by date even before the night job), minus what
  is reserved and quarantined. A line may be split over several batches.
- A pharmacist's batch override takes that batch only: blocked / recalled /
  quarantined → BATCH_BLOCKED, past expiry → BATCH_EXPIRED, too little → OUT_OF_STOCK.
- Every line is checked before anything is held; OUT_OF_STOCK lists every
  short line (requested / available).
- Stock rows are locked FOR UPDATE, medicines in a fixed order, so two tills
  wait for each other and cannot sell the same last unit (and never deadlock).
- Raises qty_reserved; on hand changes only on confirm.

Confirm → an "out" movement per batch, reserved goes down: the goods are sold.
Release → reserved goes down, nothing sold (saga compensation).
Reverse → a confirmed sale is cancelled: "sale_cancel" movements put the stock
back into the same batches.
All of them can be repeated safely.

Returns: a "return" movement back to the batch the goods were sold from; with
to=quarantine they also count as quarantined (on hand, not sellable) until a
pharmacist releases them (reason required, User Log).
"""

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller

from ..models import Batch, Product, QuarantineEntry, Reservation, ReservationLine, Stock
from .common import audit, branch_for, clean
from .movements import already_booked, apply_movement, lock_stock

FEFO = (Batch.expiry_date, Batch.received_at, Batch.id)


def state_error(message: str, status: str) -> AppError:
    return AppError(ErrorCode.INVOICE_STATE, message, status_code=409, details={"status": status})


def available(stock: Stock) -> int:
    return stock.qty_on_hand - stock.qty_reserved - stock.qty_quarantined


def to_dict(r: Reservation) -> dict[str, Any]:
    return {
        "id": r.id, "ref_type": r.ref_type, "ref_id": r.ref_id, "branch_id": r.branch_id, "status": r.status,
        "lines": [{
            "line_no": x.line_no, "medicine_id": x.medicine_id, "batch_id": x.batch_id, "lot_no": x.batch.lot_no,
            "expiry_date": x.batch.expiry_date, "qty_base": x.qty_base, "cost_per_base": x.batch.cost_per_base,
            "overridden": x.overridden, "hamper_id": (x.meta or {}).get("hamper_id"),
        } for x in r.lines],
    }  # fmt: skip


async def _get(session: AsyncSession, reservation_id: UUID) -> Reservation:
    r = (
        await session.execute(select(Reservation).where(Reservation.id == reservation_id).with_for_update())
    ).scalar_one_or_none()
    if r is None:
        raise AppError(ErrorCode.NOT_FOUND, "Reservation not found", status_code=404)
    return r


async def _fefo_rows(
    session: AsyncSession, branch_id: UUID, medicine_id: UUID, *, lock: bool = True
) -> list[Stock]:
    today = clock.today()
    query = (
        select(Stock).join(Batch, Batch.id == Stock.batch_id)
        .where(Stock.branch_id == branch_id, Batch.medicine_id == medicine_id, Batch.status == "active",
               Batch.expiry_date >= today,
               Stock.qty_on_hand - Stock.qty_reserved - Stock.qty_quarantined > 0)
        .order_by(*FEFO).execution_options(populate_existing=True)
    )  # fmt: skip
    if lock:
        query = query.with_for_update(of=Stock)
    return list((await session.execute(query)).scalars())


async def _override_row(
    session: AsyncSession, branch_id: UUID, medicine_id: UUID, batch_id: UUID, line_no: int
) -> Stock:
    stock = (
        await session.execute(
            select(Stock).where(Stock.branch_id == branch_id, Stock.batch_id == batch_id)
            .with_for_update(of=Stock).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()  # fmt: skip
    details = {"line_no": line_no, "batch_id": str(batch_id)}
    if stock is None or stock.batch.medicine_id != medicine_id:
        raise AppError(ErrorCode.OUT_OF_STOCK, f"Line {line_no}: that batch has no stock of this medicine here",
                       status_code=409, details=details)  # fmt: skip
    batch = stock.batch
    if batch.status == "expired" or batch.expiry_date < clock.today():
        raise AppError(ErrorCode.BATCH_EXPIRED, f"Line {line_no}: lot {batch.lot_no} expired on {batch.expiry_date}",
                       status_code=409, details=details)  # fmt: skip
    if batch.status != "active":
        raise AppError(ErrorCode.BATCH_BLOCKED, f"Line {line_no}: lot {batch.lot_no} is {batch.status}",
                       status_code=409, details={**details, "status": batch.status})  # fmt: skip
    return stock


async def _expand_hampers(session: AsyncSession, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A hamper line becomes one line per component (same line_no), all or nothing:
    a hamper has no stock of its own."""
    out = []
    for line in lines:
        product = await session.get(Product, line["medicine_id"])
        if product is None or product.kind != "hamper":
            out.append(line)
            continue
        if line.get("batch_id"):
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {line['line_no']}: a hamper's batches cannot be chosen",
                           status_code=422)  # fmt: skip
        for c in product.components:
            out.append({**line, "medicine_id": UUID(c["medicine_id"]), "qty_base": line["qty_base"] * c["qty_base"],
                        "meta": {**(line.get("meta") or {}), "hamper_id": str(product.id),
                                 "hamper_qty": line["qty_base"]}})  # fmt: skip
    return out


async def availability(
    session: AsyncSession, branch_id: UUID, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Sellable now (active, unexpired, not reserved / quarantined) per item; a hamper =
    the lowest of floor(component available / qty per hamper)."""
    out = []
    for item in items:
        product = await session.get(Product, item["medicine_id"])
        parts = ([(UUID(c["medicine_id"]), c["qty_base"]) for c in product.components]
                 if product and product.kind == "hamper" else [(item["medicine_id"], 1)])  # fmt: skip
        free = []
        for medicine_id, per in parts:
            rows = await _fefo_rows(session, branch_id, medicine_id, lock=False)
            free.append(sum(available(s) for s in rows) // per)
        have = min(free) if free else 0
        out.append({"medicine_id": item["medicine_id"], "available": have, "requested": item.get("qty_base", 0),
                    "enough": have >= item.get("qty_base", 0)})  # fmt: skip
    return out


async def reserve(session: AsyncSession, caller: InternalCaller, data: dict[str, Any]) -> dict[str, Any]:
    ref_type, ref_id = data["ref_type"], str(data["ref_id"])
    existing = (
        await session.execute(
            select(Reservation).where(Reservation.ref_type == ref_type, Reservation.ref_id == ref_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return to_dict(existing)  # the same invoice asked again: same answer
    branch_id = data["branch_id"]
    expanded = await _expand_hampers(session, data["lines"])
    lines = sorted(expanded, key=lambda x: (str(x["medicine_id"]), x["line_no"]))  # fixed lock order

    rows_by_medicine: dict[UUID, list[Stock]] = {}
    left: dict[UUID, int] = {}  # stock id → still free in this request
    picks: list[tuple[dict, Stock, int, bool]] = []
    missing = []
    for line in lines:
        medicine_id, qty = line["medicine_id"], line["qty_base"]
        if line.get("batch_id"):
            stock = await _override_row(session, branch_id, medicine_id, line["batch_id"], line["line_no"])
            free = left.setdefault(stock.id, available(stock))
            if free < qty:
                missing.append({"line_no": line["line_no"], "medicine_id": str(medicine_id), "requested": qty,
                                "available": free, "batch_id": str(line["batch_id"])})  # fmt: skip
                continue
            left[stock.id] -= qty
            picks.append((line, stock, qty, True))
            continue
        if medicine_id not in rows_by_medicine:
            rows_by_medicine[medicine_id] = await _fefo_rows(session, branch_id, medicine_id)
        rows = rows_by_medicine[medicine_id]
        free_total = sum(left.setdefault(s.id, available(s)) for s in rows)
        if free_total < qty:
            missing.append({"line_no": line["line_no"], "medicine_id": str(medicine_id), "requested": qty,
                            "available": free_total})  # fmt: skip
            continue
        need = qty
        for stock in rows:  # earliest expiry first
            take = min(need, left[stock.id])
            if take <= 0:
                continue
            left[stock.id] -= take
            picks.append((line, stock, take, False))
            need -= take
            if need == 0:
                break
    if missing:
        raise AppError(ErrorCode.OUT_OF_STOCK, "Not enough sellable stock at this branch", status_code=409,
                       details={"lines": sorted(missing, key=lambda m: m["line_no"])})  # fmt: skip

    reservation = Reservation(ref_type=ref_type, ref_id=ref_id, branch_id=branch_id, status="reserved",
                              created_by=caller.user_id, lines=[])  # fmt: skip
    seq: dict[int, int] = defaultdict(int)
    for line, stock, qty, overridden in picks:
        stock.qty_reserved += qty
        seq[line["line_no"]] += 1
        reservation.lines.append(ReservationLine(
            line_no=line["line_no"], seq=seq[line["line_no"]], medicine_id=line["medicine_id"],
            batch_id=stock.batch_id, qty_base=qty, overridden=overridden, batch=stock.batch, meta=line.get("meta"),
        ))  # fmt: skip
    session.add(reservation)
    await session.commit()
    return to_dict(reservation)


async def split(session: AsyncSession, caller: InternalCaller, reservation_id: UUID, data: dict[str, Any]
                ) -> dict[str, Any]:  # fmt: skip
    """Part of a sale order's reservation becomes an invoice's (same batches, nothing
    released in between, so no other sale can take it). Once per invoice.
    lines: [{from_line_no, to_line_no, qty_base}] – qty in the order line's units
    (hampers: whole hampers)."""
    existing = (await session.execute(select(Reservation).where(
        Reservation.ref_type == "invoice", Reservation.ref_id == str(data["ref_id"])))).scalar_one_or_none()  # fmt: skip
    if existing is not None:
        return to_dict(existing)
    r = await _get(session, reservation_id)
    if r.status != "reserved":
        raise state_error(f"A {r.status} reservation cannot be split", r.status)
    new = Reservation(ref_type="invoice", ref_id=str(data["ref_id"]), branch_id=r.branch_id, status="reserved",
                      created_by=caller.user_id, lines=[])  # fmt: skip
    for want in data["lines"]:
        rows = [x for x in r.lines if x.line_no == want["from_line_no"]]
        by_medicine: dict[UUID, list[ReservationLine]] = defaultdict(list)
        for x in rows:
            by_medicine[x.medicine_id].append(x)
        if not by_medicine:
            raise AppError(ErrorCode.OUT_OF_STOCK, f"Order line {want['from_line_no']} has nothing reserved",
                           status_code=409, details={"line_no": want["from_line_no"]})  # fmt: skip
        seq = 0
        for medicine_id, parts in by_medicine.items():
            meta = parts[0].meta or {}
            total = sum(x.qty_base for x in parts)
            per_unit = (
                total // int(meta["hamper_qty"]) if meta.get("hamper_id") and meta.get("hamper_qty") else 1
            )
            need = int(want["qty_base"]) * per_unit
            if need > total:
                raise AppError(ErrorCode.OUT_OF_STOCK, f"Order line {want['from_line_no']}: only {total} reserved",
                               status_code=409, details={"line_no": want["from_line_no"], "reserved": total})  # fmt: skip
            for x in sorted(parts, key=lambda x: x.seq):  # earliest expiry first
                take = min(need, x.qty_base)
                if take <= 0:
                    continue
                seq += 1
                new_meta = {**meta, "order_line_no": want["from_line_no"]}
                if meta.get("hamper_id"):
                    new_meta["hamper_qty"] = int(want["qty_base"])
                new.lines.append(ReservationLine(line_no=want["to_line_no"], seq=seq, medicine_id=medicine_id,
                                                 batch_id=x.batch_id, qty_base=take, overridden=x.overridden,
                                                 batch=x.batch, meta=new_meta))  # fmt: skip
                x.qty_base -= take
                need -= take
                if x.qty_base == 0:
                    await session.delete(x)
                if need == 0:
                    break
        hamper = next((x.meta for x in rows if (x.meta or {}).get("hamper_id")), None)
        if hamper:  # every row of the order line holds that many fewer whole hampers
            for x in rows:
                x.meta = {**(x.meta or {}), "hamper_qty": int(hamper["hamper_qty"]) - int(want["qty_base"])}
    session.add(new)
    await session.commit()  # an emptied order reservation stays open: a failed sale may give it back
    return to_dict(new)


async def merge_back(session: AsyncSession, caller: InternalCaller, reservation_id: UUID, ref_id: str
                     ) -> dict[str, Any] | None:  # fmt: skip
    """A sale from an order failed: what was split onto its invoice goes back to
    the order's reservation (same batches, still reserved, nothing free in between).
    When the order's reservation is no longer open, the invoice's is released.
    Once per invoice: a merged (or released) one is left alone."""
    inv = (await session.execute(select(Reservation).where(
        Reservation.ref_type == "invoice", Reservation.ref_id == str(ref_id)).with_for_update())).scalar_one_or_none()  # fmt: skip
    if inv is None or inv.status != "reserved":
        return to_dict(inv) if inv else None
    order = (await session.execute(select(Reservation).where(Reservation.id == reservation_id).with_for_update()
                                   )).scalar_one_or_none()  # fmt: skip
    if order is None or order.status != "reserved" or order.ref_type != "sale_order":
        return await release(session, caller, inv.id)
    seq = defaultdict(int, {})
    for x in order.lines:
        seq[x.line_no] = max(seq[x.line_no], x.seq)
    moved_hampers: dict[int, int] = {}
    for x in inv.lines:
        meta = dict(x.meta or {})
        line_no = int(meta.pop("order_line_no", x.line_no))
        if meta.get("hamper_id"):
            moved_hampers[line_no] = int(meta["hamper_qty"])
        same = next((o for o in order.lines if o.line_no == line_no and o.batch_id == x.batch_id
                     and o.medicine_id == x.medicine_id), None)  # fmt: skip
        if same is not None:
            same.qty_base += x.qty_base
        else:
            seq[line_no] += 1
            order.lines.append(ReservationLine(line_no=line_no, seq=seq[line_no], medicine_id=x.medicine_id,
                                               batch_id=x.batch_id, qty_base=x.qty_base, overridden=x.overridden,
                                               batch=x.batch, meta=meta))  # fmt: skip
        await session.delete(x)
    for line_no, qty in moved_hampers.items():  # the order holds that many more whole hampers again
        rows = [o for o in order.lines if o.line_no == line_no]
        kept = [int((o.meta or {}).get("hamper_qty", 0)) for o in rows if o.id is not None and o.qty_base > 0]
        before = min(kept, default=0)
        for o in rows:
            o.meta = {**(o.meta or {}), "hamper_qty": before + qty}
    inv.status = "merged"
    await session.commit()
    return to_dict(inv)


async def confirm(session: AsyncSession, caller: InternalCaller, reservation_id: UUID) -> dict[str, Any]:
    r = await _get(session, reservation_id)
    if r.status == "confirmed":
        return to_dict(r)
    if r.status != "reserved":
        raise state_error(f"A {r.status} reservation cannot be confirmed", r.status)
    for line in r.lines:
        stock = await lock_stock(session, r.branch_id, line.batch_id)
        stock.qty_reserved -= line.qty_base
        await session.flush()  # the movement re-reads the locked row
        await apply_movement(session, branch_id=r.branch_id, batch=line.batch, type="out", qty_base=-line.qty_base,
                             ref_type="reservation_line", ref_id=str(line.id), reason=f"Sale {r.ref_id}",
                             actor_id=caller.user_id, meta=line.meta)  # fmt: skip
    r.status = "confirmed"
    await session.commit()
    return to_dict(r)


async def release(session: AsyncSession, caller: InternalCaller, reservation_id: UUID) -> dict[str, Any]:
    r = await _get(session, reservation_id)
    if r.status in ("released", "merged"):
        return to_dict(r)
    if r.status != "reserved":
        raise state_error(f"A {r.status} reservation cannot be released", r.status)
    for line in r.lines:
        stock = await lock_stock(session, r.branch_id, line.batch_id)
        stock.qty_reserved -= line.qty_base
    r.status = "released"
    await session.commit()
    return to_dict(r)


async def release_by_ref(
    session: AsyncSession, caller: InternalCaller, ref_type: str, ref_id: str
) -> dict | None:
    """Compensation when the sales service does not know the reservation id (its
    reserve call timed out): release whatever was reserved for that invoice."""
    r = (
        await session.execute(
            select(Reservation.id).where(Reservation.ref_type == ref_type, Reservation.ref_id == ref_id)
        )
    ).scalar_one_or_none()
    if r is None:
        return None
    return await release(session, caller, r)


async def reverse(
    session: AsyncSession, caller: InternalCaller, reservation_id: UUID, reason: str
) -> dict[str, Any]:
    r = await _get(session, reservation_id)
    if r.status == "reversed":
        return to_dict(r)
    if r.status != "confirmed":
        raise state_error(f"A {r.status} reservation cannot be reversed", r.status)
    for line in r.lines:
        await apply_movement(session, branch_id=r.branch_id, batch=line.batch, type="sale_cancel",
                             qty_base=line.qty_base, ref_type="reservation_line", ref_id=str(line.id),
                             reason=clean(reason) or f"Sale {r.ref_id} cancelled", actor_id=caller.user_id,
                             meta=line.meta)  # fmt: skip
    r.status = "reversed"
    await session.commit()
    return to_dict(r)


# ---------------------------------------------------------------- returns, quarantine


async def book_returns(
    session: AsyncSession, caller: InternalCaller, data: dict[str, Any]
) -> list[dict[str, Any]]:
    """data: branch_id, reason, to (stock | quarantine), items [{ref_id, batch_id, qty_base}]."""
    out = []
    for item in data["items"]:
        ref_id = str(item["ref_id"])
        batch = await session.get(Batch, item["batch_id"])
        if batch is None:
            raise AppError(
                ErrorCode.NOT_FOUND, "Batch not found", status_code=404, details={"ref_id": ref_id}
            )
        if await already_booked(session, "return", "return_line", ref_id):
            out.append(
                {"ref_id": ref_id, "batch_id": batch.id, "qty_base": item["qty_base"], "booked": False}
            )
            continue
        await apply_movement(session, branch_id=data["branch_id"], batch=batch, type="return",
                             qty_base=item["qty_base"], ref_type="return_line", ref_id=ref_id,
                             reason=clean(data.get("reason")), actor_id=caller.user_id,
                             meta=item.get("meta"))  # fmt: skip
        if data["to"] == "quarantine":
            stock = await lock_stock(session, data["branch_id"], batch.id)
            stock.qty_quarantined += item["qty_base"]
            session.add(QuarantineEntry(branch_id=data["branch_id"], batch_id=batch.id, qty_base=item["qty_base"],
                                        ref_type="return_line", ref_id=ref_id, reason=clean(data.get("reason")),
                                        created_by=caller.user_id))  # fmt: skip
        out.append({"ref_id": ref_id, "batch_id": batch.id, "qty_base": item["qty_base"], "booked": True})
    await session.commit()
    return out


async def release_quarantine(
    session: AsyncSession, actor: CurrentUser, data: dict[str, Any]
) -> dict[str, Any]:
    """A pharmacist checks returned goods and puts them back on sale (reason required)."""
    if not actor.is_pharmacist:
        raise AppError(ErrorCode.PHARMACIST_REQUIRED, "Only a pharmacist can release quarantined stock",
                       status_code=403)  # fmt: skip
    branch = await branch_for(session, actor, data["branch_id"])
    stock = await lock_stock(session, branch.id, data["batch_id"])
    qty = data["qty_base"]
    if qty > stock.qty_quarantined:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"Only {stock.qty_quarantined} in quarantine for this batch",
                       status_code=422, details={"qty_quarantined": stock.qty_quarantined})  # fmt: skip
    stock.qty_quarantined -= qty
    session.add(QuarantineEntry(branch_id=branch.id, batch_id=stock.batch_id, qty_base=-qty, ref_type="release",
                                ref_id=str(actor.id), reason=clean(data["reason"]), created_by=actor.id))  # fmt: skip
    audit(session, actor, "quarantine.released", "batch", stock.batch_id, branch_id=branch.id,
          before={"qty_quarantined": stock.qty_quarantined + qty},
          after={"qty_quarantined": stock.qty_quarantined, "released": qty, "reason": clean(data["reason"]),
                 "lot_no": stock.batch.lot_no})  # fmt: skip
    await session.commit()
    return {"branch_id": branch.id, "batch_id": stock.batch_id, "qty_on_hand": stock.qty_on_hand,
            "qty_quarantined": stock.qty_quarantined, "released": qty}  # fmt: skip
