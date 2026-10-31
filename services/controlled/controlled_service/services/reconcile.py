"""Daily checks (00:20 Asia/Phnom_Penh and once at start-up; one replica at a
time through a Postgres advisory lock):

1. Every chain is verified; a broken one → `register.chain_broken` event + User Log.
2. Each controlled batch's register balance is compared with inventory's stock.
   A batch whose last movement has not reached the register yet (inventory's
   last seq is newer) is skipped this time. A difference opens a discrepancy
   (one open per branch + batch) → `register.discrepancy` event + User Log; an
   open one whose difference is gone is closed as `cleared`.
Resolving (controlled.resolve, PIN + witness, reason): an explanation, and
optionally a correction entry that brings the register to the stock figure.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.db import Database
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event
from pharmacy_shared.pin import consume_pin, consume_witness

from ..models import Discrepancy, OutboxEvent, RegisterEntry, Watermark
from .chain import append, verify_all
from .clients import Clients
from .common import audit, clean, not_found

log = logging.getLogger(__name__)
LOCK_KEY = 7_202_652


async def reconcile(session: AsyncSession, clients: Clients) -> dict[str, Any] | None:
    """Returns {chains_broken, opened, cleared} or None when another replica is running it."""
    if not (
        await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
    ).scalar_one():
        await session.rollback()
        return None
    broken = [c for c in await verify_all(session) if not c.valid]
    for c in broken:
        add_event(session, OutboxEvent, "register.chain_broken", {
            "branch_id": str(c.branch_id), "medicine_id": str(c.medicine_id),
            "first_bad_entry_id": str(c.first_bad_entry_id), "problem": c.problem,
            "occurred_at": clock.now().isoformat()})  # fmt: skip
        audit(session, None, "register.chain_broken", "register_entry", c.first_bad_entry_id, branch_id=c.branch_id,
              after={"medicine_id": str(c.medicine_id), "problem": c.problem})  # fmt: skip
    stock = (await clients.inventory.post("/stock/controlled", {}))["items"]
    register = {
        (r.branch_id, r.batch_id): r for r in (await session.execute(
            select(RegisterEntry.branch_id, RegisterEntry.batch_id, RegisterEntry.medicine_id,
                   func.max(RegisterEntry.lot_no).label("lot_no"), func.sum(RegisterEntry.qty_base).label("qty"),
                   func.max(RegisterEntry.movement_seq).label("last_seq"))
            .where(RegisterEntry.batch_id.is_not(None))
            .group_by(RegisterEntry.branch_id, RegisterEntry.batch_id, RegisterEntry.medicine_id))).all()
    }  # fmt: skip
    seen = (
        await session.execute(select(Watermark.last_seq).where(Watermark.id == 1))
    ).scalar_one_or_none() or 0
    rows: dict[tuple[UUID, UUID], dict[str, Any]] = {}
    for s in stock:
        key = (UUID(str(s["branch_id"])), UUID(str(s["batch_id"])))
        r = register.get(key)
        rows[key] = {"medicine_id": UUID(str(s["medicine_id"])), "lot_no": s["lot_no"], "stock": s["qty_on_hand"],
                     "register": int(r.qty) if r else 0, "behind": s["last_seq"] > seen}  # fmt: skip
    for key, r in register.items():
        rows.setdefault(key, {"medicine_id": r.medicine_id, "lot_no": r.lot_no, "stock": 0, "register": int(r.qty),
                              "behind": False})  # fmt: skip
    open_ = {(d.branch_id, d.batch_id): d for d in (await session.execute(
        select(Discrepancy).where(Discrepancy.status == "open").with_for_update())).scalars()}  # fmt: skip
    opened = cleared = 0
    for (branch_id, batch_id), row in rows.items():
        current = open_.get((branch_id, batch_id))
        if row["stock"] == row["register"]:
            if current:
                current.status, current.resolved_at = "cleared", clock.now()
                current.note = "Register and stock agree again"
                _closed(session, current)
                cleared += 1
            continue
        if row["behind"]:
            continue
        if current:
            current.register_qty, current.stock_qty = row["register"], row["stock"]
            continue
        d = Discrepancy(branch_id=branch_id, medicine_id=row["medicine_id"], batch_id=batch_id, lot_no=row["lot_no"],
                        register_qty=row["register"], stock_qty=row["stock"], status="open", found_at=clock.now())  # fmt: skip
        session.add(d)
        await session.flush()
        opened += 1
        add_event(session, OutboxEvent, "register.discrepancy", {
            "discrepancy_id": str(d.id), "branch_id": str(branch_id), "medicine_id": str(d.medicine_id),
            "batch_id": str(batch_id), "lot_no": d.lot_no, "register_qty": d.register_qty,
            "stock_qty": d.stock_qty, "occurred_at": d.found_at.isoformat()})  # fmt: skip
        audit(session, None, "register.discrepancy", "batch", batch_id, branch_id=branch_id,
              after={"lot_no": d.lot_no, "register": d.register_qty, "stock": d.stock_qty})  # fmt: skip
    await session.commit()
    return {"chains_broken": len(broken), "opened": opened, "cleared": cleared}


def _closed(session: AsyncSession, d: Discrepancy) -> None:
    """register.discrepancy_resolved: resolved by someone, or cleared (agree again)."""
    add_event(session, OutboxEvent, "register.discrepancy_resolved", {
        "discrepancy_id": str(d.id), "branch_id": str(d.branch_id), "batch_id": str(d.batch_id),
        "status": d.status, "occurred_at": (d.resolved_at or clock.now()).isoformat()})  # fmt: skip


async def resolve(session: AsyncSession, actor: CurrentUser, clients: Clients, discrepancy_id: UUID,
                  data: dict[str, Any]) -> Discrepancy:  # fmt: skip
    d = (await session.execute(select(Discrepancy).where(Discrepancy.id == discrepancy_id).with_for_update())
         ).scalar_one_or_none()  # fmt: skip
    if d is None or not actor.can_access_branch(d.branch_id):
        raise not_found("Discrepancy")
    if d.status != "open":
        raise AppError(ErrorCode.REGISTER_STATE, f"This discrepancy is {d.status}", status_code=409)
    me = await consume_pin(
        clients.auth, data.get("pin_token"), "controlled.resolve", user=actor, branch_id=d.branch_id
    )
    witness = await consume_witness(clients.auth, data.get("witness_token"), "controlled.resolve", actor=actor,
                                    branch_id=d.branch_id)  # fmt: skip
    if data.get("correct_register") and d.difference:
        last = (await session.execute(select(RegisterEntry).where(
            RegisterEntry.branch_id == d.branch_id, RegisterEntry.batch_id == d.batch_id)
            .order_by(RegisterEntry.seq.desc()).limit(1))).scalar_one_or_none()  # fmt: skip
        entry = await append(session, RegisterEntry(
            branch_id=d.branch_id, medicine_id=d.medicine_id, batch_id=d.batch_id, lot_no=d.lot_no,
            entry_type="correction", qty_base=d.difference, ref_type="discrepancy", ref_id=str(d.id),
            actor_id=actor.id, actor_name=me.name, witness_id=witness.user_id, witness_name=witness.name,
            reason=clean(data["reason"]), corrects_entry_id=last.id if last else None, occurred_at=clock.now(),
        ))  # fmt: skip
        d.correction_entry_id = entry.id
    d.status, d.resolved_at, d.resolved_by, d.witness_id = "resolved", clock.now(), actor.id, witness.user_id
    d.reason, d.note = clean(data["reason"]), clean(data.get("note"))
    _closed(session, d)
    audit(session, actor, "register.discrepancy_resolved", "batch", d.batch_id, branch_id=d.branch_id, after={
        "lot_no": d.lot_no, "register": d.register_qty, "stock": d.stock_qty, "reason": d.reason,
        "correction": bool(d.correction_entry_id), "witness": witness.name})  # fmt: skip
    await session.commit()
    return d


def next_run(now_local: datetime, hour: int, minute: int) -> datetime:
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now_local else target + timedelta(days=1)


async def run_scheduler(db: Database, get_clients, stop: asyncio.Event, hour: int, minute: int) -> None:  # noqa: ANN001
    while not stop.is_set():
        try:
            async with db.sessionmaker() as session:
                result = await reconcile(session, get_clients())
            if result:
                log.info("register check: %s", result)
        except Exception:  # noqa: BLE001
            log.exception("register check failed")
        now_local = datetime.now(clock.TIMEZONE)
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=(next_run(now_local, hour, minute) - now_local).total_seconds()
            )
        except TimeoutError:
            pass
