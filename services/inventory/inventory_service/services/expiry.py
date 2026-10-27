"""Nightly expiry job. Rules:

- Runs at 00:05 Asia/Phnom_Penh (and once at start-up, to catch up after a
  stop). Active batches whose expiry date is before today become "expired",
  which blocks them from sale. Expired stock is written off only when a
  manager confirms disposal (expire_writeoff movement, later sprint).
- Each expired batch: a batch.expired event (with the quantity left per
  branch) and a User Log entry by the system (no user).
- A Postgres advisory lock makes sure only one replica runs it at a time.
- `expire_batches(session, today)` is what tests call; `dry_run` lists without
  changing anything (python -m inventory_service.cli expire-batches --dry-run).
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.db import Database
from pharmacy_shared.outbox import add_event

from ..models import Batch, OutboxEvent, Stock
from .common import audit

log = logging.getLogger(__name__)
ADVISORY_LOCK_KEY = 7_202_605  # any constant unique to this job


async def expire_batches(
    session: AsyncSession, today: date, *, dry_run: bool = False
) -> list[dict[str, Any]] | None:
    """Returns the batches expired (or that would be), or None when another
    replica holds the lock."""
    got = (
        await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
    ).scalar_one()
    if not got:
        await session.rollback()
        return None
    query = (
        select(Batch).where(Batch.status == "active", Batch.expiry_date < today)
        .order_by(Batch.expiry_date, Batch.id).with_for_update(skip_locked=True)
    )  # fmt: skip
    expired = list((await session.execute(query)).scalars())
    results = []
    for batch in expired:
        stock_rows = (
            await session.execute(
                select(Stock.branch_id, Stock.qty_on_hand).where(
                    Stock.batch_id == batch.id, Stock.qty_on_hand > 0
                )
            )
        ).all()
        payload = {
            "batch_id": str(batch.id), "medicine_id": str(batch.medicine_id), "lot_no": batch.lot_no,
            "expiry_date": batch.expiry_date.isoformat(),
            "branches": [{"branch_id": str(b), "qty_on_hand": q} for b, q in stock_rows],
        }  # fmt: skip
        results.append(payload)
        if dry_run:
            continue
        batch.status = "expired"
        batch.status_changed_at = clock.now()
        add_event(session, OutboxEvent, "batch.expired", payload)
        audit(session, None, "batch.expired", "batch", batch.id, before={"status": "active"},
              after={"status": "expired", "lot_no": batch.lot_no, "expiry_date": batch.expiry_date.isoformat(),
                     "qty_on_hand": {str(b): q for b, q in stock_rows}})  # fmt: skip
    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return results


def next_run(now_local: datetime, hour: int, minute: int) -> datetime:
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now_local else target + timedelta(days=1)


async def run_scheduler(db: Database, stop: asyncio.Event, hour: int, minute: int) -> None:
    """Background task: once now, then every day at hour:minute Phnom Penh time."""
    while not stop.is_set():
        try:
            async with db.sessionmaker() as session:
                done = await expire_batches(session, clock.today())
            if done:
                log.info("expiry job: %d batch(es) expired", len(done))
        except Exception:  # noqa: BLE001  a failed run must not stop the scheduler
            log.exception("expiry job failed")
        now_local = datetime.now(clock.TIMEZONE)
        wait = (next_run(now_local, hour, minute) - now_local).total_seconds()
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
        except TimeoutError:
            pass
