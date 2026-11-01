"""Price history: list it, and fill it once from the catalog's own outbox.

The backfill replays the medicine.* events (each carries every pack unit's price;
outbox rows are never deleted) and records each price a pack unit had, up to the
first change recorded live for that pack unit. Running it again changes nothing."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import Medicine, OutboxEvent, PriceHistory

MEDICINE_EVENTS = ("medicine.created", "medicine.updated", "medicine.activated", "medicine.deactivated")


async def history(session: AsyncSession, medicine_id: UUID, pack_unit_id: UUID | None, date_from: date | None,
                  date_to: date | None) -> list[PriceHistory]:  # fmt: skip
    if await session.get(Medicine, medicine_id) is None:
        raise AppError(ErrorCode.NOT_FOUND, "Medicine not found", status_code=404)
    q = select(PriceHistory).where(PriceHistory.medicine_id == medicine_id)
    if pack_unit_id:
        q = q.where(PriceHistory.pack_unit_id == pack_unit_id)
    if date_from:
        q = q.where(PriceHistory.changed_at >= datetime.combine(date_from, time.min, clock.TIMEZONE))
    if date_to:
        q = q.where(PriceHistory.changed_at < datetime.combine(date_to, time.max, clock.TIMEZONE))
    return list((await session.execute(q.order_by(PriceHistory.changed_at, PriceHistory.pack_unit))).scalars())


async def backfill(session: AsyncSession) -> int:
    await session.execute(delete(PriceHistory).where(PriceHistory.source == "backfill"))
    first_live = dict((await session.execute(select(PriceHistory.pack_unit_id, func.min(PriceHistory.changed_at))
                                             .where(PriceHistory.source == "change")
                                             .group_by(PriceHistory.pack_unit_id))).all())  # fmt: skip
    last: dict[str, Decimal] = {}
    added = 0
    rows = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type.in_(MEDICINE_EVENTS))
                                  .order_by(OutboxEvent.seq))).scalars()  # fmt: skip
    for row in rows:
        p: dict[str, Any] = row.payload
        for pu in p.get("pack_units") or []:
            pid, price = pu["id"], Decimal(str(pu["sell_price"]))
            stop = first_live.get(UUID(pid))
            if stop is not None and row.created_at >= stop:
                continue
            if last.get(pid) == price:
                continue
            session.add(PriceHistory(medicine_id=UUID(p["medicine_id"]), pack_unit_id=UUID(pid), pack_unit=pu["name"],
                                     old_price=last.get(pid), new_price=price, changed_at=row.created_at,
                                     changed_by=None, source="backfill"))  # fmt: skip
            last[pid] = price
            added += 1
    await session.commit()
    return added
