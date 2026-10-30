"""Internal reads and writes for the stock-take and controlled-drug services.

- snapshot: stock per batch at one branch (scope full / category / location /
  controlled), with cost and shelf location, plus the movement seq it is valid
  at. Taken under a short SHARE lock on movements, so no movement is half in it:
  movements after `as_of_seq` are exactly the changes since.
- movements_since: net change per batch after a seq (sales go on during a count).
- controlled_stock: on hand per batch of controlled medicines (register reconciliation).
- controlled_movement: an adjust / destroy for the controlled service (PINs were
  checked there), once per request id.
- count adjustments (`count.approved` event): one count_adjust movement per
  count line, once; it may take stock below what sales have reserved only to
  zero (the count is the truth on the shelf).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller

from ..models import Batch, Movement, Product, ShelfLocation, Stock
from .movements import already_booked, apply_movement


async def snapshot(session: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    branch_id = data["branch_id"]
    await session.execute(text("LOCK TABLE movements IN SHARE MODE"))
    as_of = (await session.execute(select(func.coalesce(func.max(Movement.seq), 0)))).scalar_one()
    query = (
        select(Stock, Batch, Product, ShelfLocation.code)
        .join(Batch, Batch.id == Stock.batch_id).join(Product, Product.id == Batch.medicine_id)
        .outerjoin(ShelfLocation, (ShelfLocation.branch_id == Stock.branch_id)
                   & (ShelfLocation.medicine_id == Batch.medicine_id))
        .where(Stock.branch_id == branch_id, Stock.qty_on_hand > 0)
    )  # fmt: skip
    scope = data.get("scope") or "full"
    if scope == "category":
        query = query.where(Product.category_id == data["category_id"])
    elif scope == "location":
        query = query.where(ShelfLocation.code == str(data["location"]).strip().upper())
    elif scope == "controlled":
        query = query.where(Product.controlled_schedule.is_not(None))
    rows = (await session.execute(query.order_by(Product.sku, Batch.expiry_date, Batch.lot_no))).all()
    await session.commit()  # ends the lock
    return {"branch_id": branch_id, "as_of_seq": as_of, "lines": [{
        "batch_id": b.id, "medicine_id": p.id, "sku": p.sku, "name": p.display_name, "name_km": p.name_km,
        "base_unit": p.base_unit, "lot_no": b.lot_no, "expiry_date": b.expiry_date, "qty_base": s.qty_on_hand,
        "cost_per_base": b.cost_per_base, "is_controlled": bool(p.controlled_schedule), "location": code or "",
        "barcodes": [u.barcode for u in p.pack_units if u.barcode],
    } for s, b, p, code in rows]}  # fmt: skip


async def movements_since(session: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    """Net change per batch after `after_seq`; with `until` per batch, only up to that
    moment (when the shelf was counted), so later sales do not count as variance."""
    query = (select(Movement.batch_id, Movement.created_at, Movement.qty_base)
             .where(Movement.branch_id == data["branch_id"], Movement.seq > data["after_seq"]))  # fmt: skip
    if data.get("batch_ids"):
        query = query.where(Movement.batch_id.in_(data["batch_ids"]))
    until = {str(x["batch_id"]): x["until"] for x in data.get("until") or []}
    changes: dict[str, int] = {}
    for batch_id, created_at, qty in await session.execute(query):
        limit = until.get(str(batch_id))
        if limit is not None and created_at > limit:
            continue
        changes[str(batch_id)] = changes.get(str(batch_id), 0) + qty
    return {"changes": changes}


async def controlled_stock(session: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    """On hand per batch of controlled medicines, with the seq of the batch's last
    movement there (the register is behind while its own last seq is lower)."""
    last = (select(Movement.branch_id, Movement.batch_id, func.max(Movement.seq).label("last_seq"))
            .group_by(Movement.branch_id, Movement.batch_id).subquery())  # fmt: skip
    query = (select(Stock.branch_id, Stock.batch_id, Batch.medicine_id, Batch.lot_no, Stock.qty_on_hand,
                    last.c.last_seq)
             .join(Batch, Batch.id == Stock.batch_id).join(Product, Product.id == Batch.medicine_id)
             .outerjoin(last, (last.c.branch_id == Stock.branch_id) & (last.c.batch_id == Stock.batch_id))
             .where(Product.controlled_schedule.is_not(None)))  # fmt: skip
    if data.get("branch_id"):
        query = query.where(Stock.branch_id == data["branch_id"])
    return {"items": [{"branch_id": r.branch_id, "batch_id": r.batch_id, "medicine_id": r.medicine_id,
                       "lot_no": r.lot_no, "qty_on_hand": r.qty_on_hand, "last_seq": r.last_seq or 0}
                      for r in await session.execute(query)]}  # fmt: skip


async def controlled_movement(
    session: AsyncSession, caller: InternalCaller, data: dict[str, Any]
) -> dict[str, Any]:
    batch = await session.get(Batch, data["batch_id"])
    product = await session.get(Product, batch.medicine_id) if batch else None
    if batch is None or product is None or not product.controlled_schedule:
        raise AppError(ErrorCode.NOT_FOUND, "Controlled batch not found", status_code=404)
    ref_id = str(data["request_id"])
    found = (await session.execute(select(Movement).where(Movement.ref_type == "controlled_request",
                                                          Movement.ref_id == ref_id))).scalar_one_or_none()  # fmt: skip
    if found is None:
        kind = data["kind"]  # adjust_in | adjust_out | destroy
        qty = data["qty_base"] if kind == "adjust_in" else -data["qty_base"]
        found = await apply_movement(
            session, branch_id=data["branch_id"], batch=batch, type="shrinkage" if kind == "destroy" else kind,
            qty_base=qty, ref_type="controlled_request", ref_id=ref_id, reason=data["reason"][:255],
            actor_id=caller.user_id, meta=data.get("meta"),
        )  # fmt: skip
        await session.commit()
    return {"movement_id": found.id, "qty_after": found.qty_after}


async def book_count(session: AsyncSession, payload: dict[str, Any]) -> int:
    """count.approved → count_adjust movements, once per count line."""
    branch_id = UUID(payload["branch_id"])
    booked = 0
    for line in payload["adjustments"]:
        ref_id = str(line["count_line_id"])
        if not line["qty_base"] or await already_booked(session, "count_adjust", "count_line", ref_id):
            continue
        batch = await session.get(Batch, UUID(line["batch_id"]))
        await apply_movement(
            session, branch_id=branch_id, batch=batch, type="count_adjust", qty_base=int(line["qty_base"]),
            ref_type="count_line", ref_id=ref_id, reason=f"Stock take {payload['number']}",
            actor_id=UUID(payload["approved_by"]) if payload.get("approved_by") else None,
            meta={"count_id": payload["count_id"], "number": payload["number"], "approved_by": payload.get("approved_by"),
                  "counted_by": line.get("counted_by") or []},
            allow_below_held=True,
        )  # fmt: skip
        booked += 1
    return booked
