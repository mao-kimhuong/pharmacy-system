"""Daily job: open prescriptions past valid_until become expired (00:10
Asia/Phnom_Penh and once at start-up; Postgres advisory lock = one replica).
Each: prescription.expired event + User Log entry by the system. Dispensing
also refuses by date, so a missed run never lets an expired Rx through."""

import asyncio
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.db import Database

from ..models import OPEN, Prescription
from .common import audit
from .prescriptions import publish

log = logging.getLogger(__name__)
LOCK_KEY = 7_202_640


async def expire_prescriptions(session: AsyncSession, today: date) -> list[str] | None:
    if not (
        await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
    ).scalar_one():
        await session.rollback()
        return None
    rows = list((await session.execute(
        select(Prescription).where(Prescription.status.in_(OPEN), Prescription.valid_until < today)
        .with_for_update(of=Prescription, skip_locked=True))).scalars())  # fmt: skip
    for rx in rows:
        before = rx.status
        rx.status = "expired"
        rx.version += 1
        await publish(session, rx, "prescription.expired")
        audit(session, None, "prescription.expired", "prescription", rx.id, branch_id=rx.branch_id,
              before={"status": before}, after={"status": "expired", "valid_until": rx.valid_until.isoformat()})  # fmt: skip
    await session.commit()
    return [rx.number for rx in rows]


def next_run(now_local: datetime, hour: int, minute: int) -> datetime:
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now_local else target + timedelta(days=1)


async def run_scheduler(db: Database, stop: asyncio.Event, hour: int, minute: int) -> None:
    while not stop.is_set():
        try:
            async with db.sessionmaker() as session:
                done = await expire_prescriptions(session, clock.today())
            if done:
                log.info("prescriptions expired: %s", done)
        except Exception:  # noqa: BLE001
            log.exception("prescription expiry job failed")
        now_local = datetime.now(clock.TIMEZONE)
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=(next_run(now_local, hour, minute) - now_local).total_seconds()
            )
        except TimeoutError:
            pass
