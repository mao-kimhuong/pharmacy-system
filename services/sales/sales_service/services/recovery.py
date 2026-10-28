"""Recovery task: finishes sagas that a crash or an unreachable service left
half-way. Every minute (and `python -m sales_service.cli recover`):

- sales "pending" for longer than pending_timeout_seconds, or "needs_attention":
  compensate everything (idempotent), then "failed";
- invoices "cancelling": run the cancel steps again;
- returns "needs_attention": run the return steps again.

All of it is safe to repeat; an advisory lock keeps it to one replica.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select, text

from pharmacy_shared import clock
from pharmacy_shared.db import Database
from pharmacy_shared.errors import AppError

from ..models import Invoice, SaleReturn
from .cancel import cancel_steps
from .clients import Clients
from .common import audit
from .returns import return_steps
from .sale_saga import compensate

log = logging.getLogger(__name__)
LOCK_KEY = 7_202_610


async def recover(db: Database, clients: Clients, pending_timeout_seconds: int) -> dict[str, int]:
    done = {"failed": 0, "cancelled": 0, "returns": 0, "still_open": 0}
    async with db.sessionmaker() as session:
        if not (await session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})).scalar_one():
            return done
        try:
            cutoff = clock.now() - timedelta(seconds=pending_timeout_seconds)
            stuck = list((await session.execute(select(Invoice.id).where(or_(
                (Invoice.status == "pending") & (Invoice.created_at < cutoff),
                Invoice.status == "needs_attention",
                (Invoice.status == "cancelling") & (Invoice.updated_at < cutoff),
            )))).scalars())  # fmt: skip
            for inv_id in stuck:
                inv = await session.get(Invoice, inv_id, populate_existing=True, with_for_update=True)
                try:
                    if inv.status == "cancelling":
                        await cancel_steps(session, inv, None, clients)
                        done["cancelled"] += 1
                        continue
                    problems = await compensate(inv, None, clients)
                    if problems:
                        inv.failure_reason = ("not undone yet: " + "; ".join(problems))[:500]
                        inv.status = "needs_attention"
                        done["still_open"] += 1
                    else:
                        inv.status = "failed"
                        inv.failure_code = inv.failure_code or "TEMPORARILY_UNAVAILABLE"
                        inv.failure_reason = inv.failure_reason or "Interrupted; undone by the recovery task"
                        done["failed"] += 1
                    audit(session, None, "invoice.recovered", "invoice", inv.id, branch_id=inv.branch_id,
                          after={"status": inv.status, "reason": inv.failure_reason})  # fmt: skip
                    await session.commit()
                except AppError:
                    await session.rollback()
                    done["still_open"] += 1
            open_returns = list((await session.execute(
                select(SaleReturn.id).where(SaleReturn.status == "needs_attention"))).scalars())  # fmt: skip
            for ret_id in open_returns:
                ret = await session.get(SaleReturn, ret_id, populate_existing=True, with_for_update=True)
                inv = await session.get(Invoice, ret.invoice_id, with_for_update=True)
                try:
                    await return_steps(session, ret, inv, None, clients)
                    done["returns"] += 1
                except AppError:
                    await session.rollback()
                    done["still_open"] += 1
        finally:
            await session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            await session.commit()
    return done


async def run_recovery(db: Database, clients_factory, stop: asyncio.Event, every: int, timeout: int) -> None:  # noqa: ANN001
    while not stop.is_set():
        try:
            result = await recover(db, clients_factory(), timeout)
            if any(result.values()):
                log.info("sales recovery: %s", result)
        except Exception:  # noqa: BLE001  never stop the loop
            log.exception("sales recovery failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=every)
        except TimeoutError:
            pass
