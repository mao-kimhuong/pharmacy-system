"""Reading the register (controlled.view, own branches), and opening balances.

- list: entries of a branch (+ medicine, date range in Asia/Phnom_Penh), oldest
  first, with each chain's `chain_valid` flag.
- open_balances (CLI, once after S5 is installed): controlled stock that existed
  before the register gets an `opening` entry per batch, so register = stock.
"""

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock

from ..models import ControlledProduct, KnownBranch, RegisterEntry
from .chain import append, verify_chain
from .clients import Clients


def _local_day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=clock.TIMEZONE)


async def entries(
    session: AsyncSession, branch_id: UUID, medicine_id: UUID | None, date_from: date | None, date_to: date | None,
    limit: int = 5000,
) -> dict[str, Any]:  # fmt: skip
    query = select(RegisterEntry).where(RegisterEntry.branch_id == branch_id)
    if medicine_id:
        query = query.where(RegisterEntry.medicine_id == medicine_id)
    if date_from:
        query = query.where(RegisterEntry.occurred_at >= _local_day_start(date_from))
    if date_to:
        query = query.where(RegisterEntry.occurred_at < _local_day_start(date_to + timedelta(days=1)))
    rows = list((await session.execute(query.order_by(RegisterEntry.seq).limit(limit))).scalars())
    medicines = sorted({e.medicine_id for e in rows} | ({medicine_id} if medicine_id else set()), key=str)
    chains = {m: await verify_chain(session, branch_id, m) for m in medicines}
    products = {p.id: p for p in (await session.execute(
        select(ControlledProduct).where(ControlledProduct.id.in_(medicines)))).scalars()}  # fmt: skip
    branch = await session.get(KnownBranch, branch_id)
    return {
        "branch_id": branch_id, "branch_name_en": branch.name_en if branch else "",
        "branch_name_km": branch.name_km if branch else "",
        "chain_valid": all(c.valid for c in chains.values()),
        "chains": [{"medicine_id": m, "valid": c.valid, "entries": c.entries, "first_bad_entry_id": c.first_bad_entry_id,
                    "problem": c.problem} for m, c in chains.items()],
        "medicines": [{"id": p.id, "sku": p.sku, "name": p.name, "name_km": p.name_km, "strength": p.strength,
                       "base_unit": p.base_unit, "schedule": p.controlled_schedule} for p in products.values()],
        "entries": rows,
    }  # fmt: skip


async def open_balances(session: AsyncSession, clients: Clients) -> int:
    stock = (await clients.inventory.post("/stock/controlled", {}))["items"]
    done = 0
    for s in stock:
        branch_id, batch_id = UUID(str(s["branch_id"])), UUID(str(s["batch_id"]))
        exists = (await session.execute(select(RegisterEntry.id).where(
            RegisterEntry.branch_id == branch_id, RegisterEntry.batch_id == batch_id).limit(1))).first()  # fmt: skip
        if exists or not s["qty_on_hand"]:
            continue
        await append(session, RegisterEntry(
            branch_id=branch_id, medicine_id=UUID(str(s["medicine_id"])), batch_id=batch_id, lot_no=s["lot_no"],
            entry_type="opening", qty_base=int(s["qty_on_hand"]), ref_type="opening", ref_id=str(batch_id),
            reason="Opening balance: stock before the register started", occurred_at=clock.now(),
            movement_seq=s.get("last_seq"),
        ))  # fmt: skip
        done += 1
    await session.commit()
    return done
