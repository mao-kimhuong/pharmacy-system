"""The only way stock changes. Rules:

- Every change of qty_on_hand is a movement row (signed, base units) written
  by `apply_movement` in the caller's transaction, after locking the stock row:
  two changes of the same branch + batch wait for each other.
- On hand never goes below zero (OUT_OF_STOCK) nor below what is reserved + quarantined.
- A batch is identified by medicine + lot + expiry + supplier + cost per base
  unit: the same lot at another cost is another batch.
- Each movement emits stock.changed (branch, batch, medicine, delta, reason,
  ref, controlled flag, lot, expiry, cost for reports).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..models import Batch, Movement, OutboxEvent, Product, Stock


async def get_or_create_batch(
    session: AsyncSession,
    *,
    medicine_id: UUID,
    lot_no: str,
    expiry_date: date,
    supplier_id: UUID | None,
    cost_per_base: Decimal,
    received_at: datetime | None = None,
) -> Batch:
    identity = {
        "medicine_id": medicine_id, "lot_no": lot_no, "expiry_date": expiry_date,
        "supplier_id": supplier_id, "cost_per_base": cost_per_base,
    }  # fmt: skip
    values = {**identity, **({"received_at": received_at} if received_at else {})}
    await session.execute(
        insert(Batch)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["medicine_id", "lot_no", "expiry_date", "supplier_id", "cost_per_base"]
        )
    )
    query = select(Batch).where(*(getattr(Batch, k) == v for k, v in identity.items() if v is not None))
    if supplier_id is None:
        query = query.where(Batch.supplier_id.is_(None))
    return (await session.execute(query)).scalar_one()


async def lock_stock(session: AsyncSession, branch_id: UUID, batch_id: UUID) -> Stock:
    await session.execute(
        insert(Stock)
        .values(branch_id=branch_id, batch_id=batch_id, qty_on_hand=0, qty_reserved=0)
        .on_conflict_do_nothing(constraint="uq_stock_branch_batch")
    )
    return (
        await session.execute(
            select(Stock)
            .where(Stock.branch_id == branch_id, Stock.batch_id == batch_id)
            .with_for_update(of=Stock)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def apply_movement(
    session: AsyncSession,
    *,
    branch_id: UUID,
    batch: Batch,
    type: str,
    qty_base: int,
    ref_type: str,
    ref_id: str,
    reason: str = "",
    actor_id: UUID | None = None,
) -> Movement:
    if qty_base == 0:
        raise AppError(ErrorCode.VALIDATION_ERROR, "A movement needs a quantity", status_code=422)
    stock = await lock_stock(session, branch_id, batch.id)
    after = stock.qty_on_hand + qty_base
    held = stock.qty_reserved + stock.qty_quarantined  # reserved for sales or quarantined: not movable
    if after < held:
        free = stock.qty_on_hand - held
        raise AppError(
            ErrorCode.OUT_OF_STOCK, f"Only {free} available in lot {batch.lot_no}",
            status_code=409, details={"batch_id": str(batch.id), "available": free},
        )  # fmt: skip
    stock.qty_on_hand = after
    movement = Movement(
        branch_id=branch_id, batch_id=batch.id, medicine_id=batch.medicine_id, type=type, qty_base=qty_base,
        qty_after=after, ref_type=ref_type, ref_id=str(ref_id), reason=reason, created_by=actor_id,
    )  # fmt: skip
    session.add(movement)
    await session.flush()
    product = await session.get(Product, batch.medicine_id)
    add_event(session, OutboxEvent, "stock.changed", stock_changed_payload(movement, batch, product))
    return movement


def stock_changed_payload(m: Movement, batch: Batch, product: Product | None) -> dict[str, Any]:
    return {
        "movement_id": str(m.id), "branch_id": str(m.branch_id), "batch_id": str(batch.id),
        "medicine_id": str(batch.medicine_id), "type": m.type, "delta": m.qty_base, "qty_after": m.qty_after,
        "reason": m.reason, "ref_type": m.ref_type, "ref_id": m.ref_id, "lot_no": batch.lot_no,
        "expiry_date": batch.expiry_date.isoformat(), "cost_per_base": str(batch.cost_per_base),
        "controlled_schedule": product.controlled_schedule if product else None,
        "is_controlled": bool(product and product.controlled_schedule),
        "created_by": str(m.created_by) if m.created_by else None,
    }  # fmt: skip


async def already_booked(session: AsyncSession, type: str, ref_type: str, ref_id: str) -> bool:
    found = await session.execute(
        select(Movement.id).where(
            Movement.type == type, Movement.ref_type == ref_type, Movement.ref_id == ref_id
        )
    )
    return found.first() is not None
