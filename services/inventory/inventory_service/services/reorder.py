"""Re-ordering: suggestions only, never automatic orders. Rules:

- Settings per branch + medicine (inventory.reorder_settings, own branch; also
  in bulk for a category): min (reorder point), max (order up to), supplier lead
  time, preferred supplier. Empty = worked out from sales.
- Average daily sales = (out − sale_cancel − return) over the branch's
  `reorder_sales_days` (30) / that many days.
- Reorder point = min, else avg × (lead + safety days); lead = the setting, else
  the branch's `reorder_lead_days` (7); safety = `reorder_safety_days` (3).
- Available = sellable on hand (minus reserved and quarantined) + coming by
  transfer + open purchase orders. Suggest when available ≤ reorder point:
  (max, else avg × (lead + safety + sales days)) − available, rounded up to
  whole packs of the biggest pack unit that adds at most 25 %.
- Each line: on hand, in transit, on order, suggested quantity, preferred
  supplier (the setting, else the newest batch's), last cost per base unit.
- Transfer suggestion: another branch with spare stock (above its max, else
  above 60 days of its own sales) or batches expiring within its
  `near_expiry_transfer_days` (90) that it will not sell in time, when this
  branch sells faster → suggested source.
- Daily job 00:30 Asia/Phnom_Penh (and at start-up; advisory lock): a list per
  branch, `stock.low` per line and `batch.expiring` per batch inside the branch's
  `expiry_alert_days`, each at most once a day. A manager may run it at any time.
- From a list, in one step: purchase requests (purchasing service) or transfer
  requests (to the suggested or a chosen source branch).
"""

import asyncio
import hashlib
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.db import Database
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient
from pharmacy_shared.outbox import add_event

from ..models import (
    AlertSent,
    Batch,
    BranchSettingsCopy,
    KnownBranch,
    Movement,
    OpenPOLine,
    OutboxEvent,
    Product,
    ReorderLine,
    ReorderList,
    ReorderSetting,
    Stock,
    Transfer,
    TransferPick,
)
from . import transfers
from .common import audit, branch_for, hamper_not_stocked

log = logging.getLogger(__name__)
LOCK_KEY = 7_202_660
SPARE_COVER_DAYS = 60
SOLD = ("out", "sale_cancel", "return")
OPEN_PO = ("sent", "partially_received")


# ---------------------------------------------------------------- settings


async def set_setting(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> ReorderSetting:
    branch = await branch_for(session, actor, data["branch_id"])
    product = await session.get(Product, data["medicine_id"])
    if product is None:
        raise AppError(ErrorCode.UNKNOWN_MEDICINE, "Unknown medicine", status_code=422)
    if product.kind == "hamper":
        raise hamper_not_stocked(product.sku)
    await _save(session, actor, branch.id, [product.id], data)
    audit(session, actor, "reorder_setting.set", "medicine", product.id, branch_id=branch.id,
          after={k: (str(v) if isinstance(v, UUID) else v) for k, v in data.items() if k not in ("branch_id", "medicine_id")})  # fmt: skip
    await session.commit()
    return await session.get(ReorderSetting, (branch.id, product.id), populate_existing=True)


def _check(data: dict[str, Any]) -> None:
    if (
        data.get("min_qty") is not None
        and data.get("max_qty") is not None
        and data["max_qty"] < data["min_qty"]
    ):
        raise AppError(ErrorCode.VALIDATION_ERROR, "max must be at least min", status_code=422)


async def _save(session: AsyncSession, actor: CurrentUser, branch_id: UUID, medicine_ids: list[UUID],
                data: dict[str, Any]) -> None:  # fmt: skip
    _check(data)
    fields = {k: data.get(k) for k in ("min_qty", "max_qty", "lead_time_days", "preferred_supplier_id")}
    for medicine_id in medicine_ids:
        await session.execute(insert(ReorderSetting).values(branch_id=branch_id, medicine_id=medicine_id,
                                                            updated_by=actor.id, **fields)
                              .on_conflict_do_update(index_elements=["branch_id", "medicine_id"],
                                                     set_={**fields, "updated_by": actor.id}))  # fmt: skip


async def set_bulk(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> int:
    branch = await branch_for(session, actor, data["branch_id"])
    ids = list((await session.execute(select(Product.id).where(Product.category_id == data["category_id"],
                                                               Product.is_active.is_(True),
                                                               Product.kind == "medicine"))).scalars())  # fmt: skip
    await _save(session, actor, branch.id, ids, data)
    audit(session, actor, "reorder_setting.bulk", "category", data["category_id"], branch_id=branch.id,
          after={"medicines": len(ids), **{k: data.get(k) for k in ("min_qty", "max_qty", "lead_time_days")}})  # fmt: skip
    await session.commit()
    return len(ids)


async def list_settings(session: AsyncSession, actor: CurrentUser, branch_id: UUID) -> list[ReorderSetting]:
    actor.require_branch(branch_id)
    return list(
        (await session.execute(select(ReorderSetting).where(ReorderSetting.branch_id == branch_id))).scalars()
    )


# ---------------------------------------------------------------- open purchase orders (events)


async def upsert_open_po(session: AsyncSession, p: dict[str, Any]) -> None:
    """purchase_order.* → open quantity per PO line (older versions ignored)."""
    version, branch_id = int(p["version"]), UUID(p["branch"]["id"])
    is_open = p["status"] in OPEN_PO
    for line in p.get("lines") or []:
        values = {"po_line_id": UUID(line["po_line_id"]), "po_id": UUID(p["purchase_order_id"]), "branch_id": branch_id,
                  "medicine_id": UUID(line["medicine_id"]), "version": version,
                  "open_qty": max(int(line["qty_base"]) - int(line.get("qty_received_base") or 0), 0) if is_open else 0}  # fmt: skip
        await session.execute(insert(OpenPOLine).values(**values).on_conflict_do_update(
            index_elements=[OpenPOLine.po_line_id], set_={k: v for k, v in values.items() if k != "po_line_id"},
            where=OpenPOLine.version < version))  # fmt: skip


# ---------------------------------------------------------------- the calculation


@dataclass
class BranchFigures:
    sellable: dict[UUID, int]
    sold: dict[UUID, int]
    near_expiry: dict[UUID, list[tuple[Batch, int]]]  # medicine → (batch, qty)


async def _settings(session: AsyncSession, branch_id: UUID) -> BranchSettingsCopy:
    return await session.get(BranchSettingsCopy, branch_id) or BranchSettingsCopy(
        branch_id=branch_id, reorder_sales_days=30, reorder_safety_days=3, reorder_lead_days=7,
        near_expiry_transfer_days=90, expiry_alert_days=[180, 90, 30])  # fmt: skip


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=clock.TIMEZONE)


async def _figures(session: AsyncSession, branch_id: UUID, today: date, sales_days: int,
                   expiry_days: int) -> BranchFigures:  # fmt: skip
    sellable = dict((await session.execute(
        select(Batch.medicine_id, func.sum(Stock.qty_on_hand - Stock.qty_reserved - Stock.qty_quarantined))
        .join(Batch, Batch.id == Stock.batch_id)
        .where(Stock.branch_id == branch_id, Batch.status == "active", Batch.expiry_date >= today,
               Stock.recall_id.is_(None))
        .group_by(Batch.medicine_id))).all())  # fmt: skip
    sold = {m: -int(q) for m, q in (await session.execute(
        select(Movement.medicine_id, func.sum(Movement.qty_base))
        .where(Movement.branch_id == branch_id, Movement.type.in_(SOLD),
               Movement.created_at >= _day_start(today - timedelta(days=sales_days)))
        .group_by(Movement.medicine_id))).all()}  # fmt: skip
    near: dict[UUID, list[tuple[Batch, int]]] = defaultdict(list)
    rows = await session.execute(
        select(Batch, Stock.qty_on_hand - Stock.qty_reserved - Stock.qty_quarantined)
        .join(Stock, Stock.batch_id == Batch.id)
        .where(Stock.branch_id == branch_id, Batch.status == "active", Batch.expiry_date >= today, Stock.recall_id.is_(None),
               Batch.expiry_date <= today + timedelta(days=expiry_days),
               Stock.qty_on_hand - Stock.qty_reserved - Stock.qty_quarantined > 0))  # fmt: skip
    for batch, qty in rows:
        near[batch.medicine_id].append((batch, int(qty)))
    return BranchFigures({m: int(q or 0) for m, q in sellable.items()}, sold, near)


def _round_to_pack(product: Product, qty: int) -> tuple[int, Any]:
    """Up to whole packs: the biggest pack unit that adds at most 25 % to the need
    (105 tablets: not 2 boxes of 100, but 11 strips of 10)."""
    packs = sorted((p for p in product.pack_units if p.is_active), key=lambda p: p.qty_in_base, reverse=True)
    for pack in packs:
        rounded = math.ceil(qty / pack.qty_in_base) * pack.qty_in_base
        if rounded <= qty * 1.25:
            return rounded, pack
    return qty, packs[-1] if packs else None


async def build_list(session: AsyncSession, branch_id: UUID, today: date, actor: CurrentUser | None = None
                     ) -> ReorderList:  # fmt: skip
    """The re-order list of one branch (the caller commits)."""
    s = await _settings(session, branch_id)
    n = s.reorder_sales_days
    mine = await _figures(session, branch_id, today, n, s.near_expiry_transfer_days)
    settings = {r.medicine_id: r for r in (await session.execute(
        select(ReorderSetting).where(ReorderSetting.branch_id == branch_id))).scalars()}  # fmt: skip
    candidates = set(settings) | {m for m, q in mine.sold.items() if q > 0}
    products = {p.id: p for p in (await session.execute(
        select(Product).where(Product.id.in_(candidates), Product.is_active.is_(True)))).scalars()} if candidates else {}  # fmt: skip
    in_transit = dict((await session.execute(
        select(Batch.medicine_id, func.sum(TransferPick.qty_base))
        .join(TransferPick, TransferPick.batch_id == Batch.id).join(Transfer, Transfer.id == TransferPick.transfer_id)
        .where(Transfer.to_branch_id == branch_id, Transfer.status == "dispatched").group_by(Batch.medicine_id))).all())  # fmt: skip
    on_order = dict((await session.execute(
        select(OpenPOLine.medicine_id, func.sum(OpenPOLine.open_qty))
        .where(OpenPOLine.branch_id == branch_id).group_by(OpenPOLine.medicine_id))).all())  # fmt: skip
    others = [b.id for b in (await session.execute(select(KnownBranch).where(
        KnownBranch.is_active.is_(True), KnownBranch.id != branch_id))).scalars()]  # fmt: skip
    other_figures: dict[UUID, tuple[BranchFigures, BranchSettingsCopy, dict[UUID, ReorderSetting]]] = {}
    for other in others:
        os_ = await _settings(session, other)
        other_settings = {r.medicine_id: r for r in (await session.execute(
            select(ReorderSetting).where(ReorderSetting.branch_id == other))).scalars()}  # fmt: skip
        other_figures[other] = (await _figures(session, other, today, os_.reorder_sales_days,
                                               os_.near_expiry_transfer_days), os_, other_settings)  # fmt: skip

    rl = ReorderList(
        branch_id=branch_id, run_date=today, sales_days=n, created_by=actor.id if actor else None, lines=[]
    )
    for medicine_id, product in sorted(products.items(), key=lambda kv: kv[1].sku):
        setting = settings.get(medicine_id)
        avg = Decimal(max(mine.sold.get(medicine_id, 0), 0)) / Decimal(n)
        lead = (
            setting.lead_time_days if setting and setting.lead_time_days is not None else s.reorder_lead_days
        )
        point = (
            setting.min_qty
            if setting and setting.min_qty is not None
            else math.ceil(avg * (lead + s.reorder_safety_days))
        )
        target = setting.max_qty if setting and setting.max_qty is not None else math.ceil(
            avg * (lead + s.reorder_safety_days + n))  # fmt: skip
        on_hand = mine.sellable.get(medicine_id, 0)
        transit, ordered = int(in_transit.get(medicine_id) or 0), int(on_order.get(medicine_id) or 0)
        available = on_hand + transit + ordered
        if point <= 0 or available > point or target - available <= 0:
            continue
        suggested, pack = _round_to_pack(product, target - available)
        newest = (await session.execute(select(Batch).where(Batch.medicine_id == medicine_id)
                                        .order_by(Batch.received_at.desc()).limit(1))).scalar_one_or_none()  # fmt: skip
        line = ReorderLine(
            medicine_id=medicine_id, sku=product.sku, name=product.display_name, on_hand=on_hand, in_transit=transit,
            on_order=ordered, avg_daily=avg.quantize(Decimal("0.001")), reorder_point=point, target=target,
            suggested_qty=suggested, pack_unit_id=pack.id if pack else None, pack_unit=pack.name if pack else "",
            pack_qty=suggested // pack.qty_in_base if pack else suggested,
            preferred_supplier_id=(setting.preferred_supplier_id if setting and setting.preferred_supplier_id
                                   else newest.supplier_id if newest else None),
            last_cost_per_base=newest.cost_per_base if newest else None, status="open",
        )  # fmt: skip
        _suggest_source(line, avg, today, other_figures)
        rl.lines.append(line)
    session.add(rl)
    await session.flush()
    return rl


def _suggest_source(line: ReorderLine, my_avg: Decimal, today: date,
                    others: dict[UUID, tuple[BranchFigures, BranchSettingsCopy, dict[UUID, ReorderSetting]]]) -> None:  # fmt: skip
    best: tuple[int, int, UUID, str] | None = None  # (priority, qty, branch, reason)
    for branch_id, (fig, s, settings) in others.items():
        their_avg = Decimal(max(fig.sold.get(line.medicine_id, 0), 0)) / Decimal(s.reorder_sales_days)
        # near expiry: what they will not sell before it expires, if we sell faster
        if my_avg > their_avg:
            excess = sum(
                max(qty - math.floor(their_avg * (batch.expiry_date - today).days), 0)
                for batch, qty in fig.near_expiry.get(line.medicine_id, [])
            )
            if excess > 0:
                cand = (2, min(excess, line.suggested_qty), branch_id, "near_expiry")
                best = max(best, cand) if best else cand
        setting = settings.get(line.medicine_id)
        keep = (
            setting.max_qty
            if setting and setting.max_qty is not None
            else math.ceil(their_avg * SPARE_COVER_DAYS)
        )
        spare = fig.sellable.get(line.medicine_id, 0) - keep
        if spare > 0:
            cand = (1, min(spare, line.suggested_qty), branch_id, "spare")
            best = max(best, cand) if best else cand
    if best:
        _, line.source_qty, line.source_branch_id, line.source_reason = best


# ---------------------------------------------------------------- alerts, job


async def _once(session: AsyncSession, kind: str, ref: str, day: date) -> bool:
    result = await session.execute(
        insert(AlertSent).values(kind=kind, ref=ref, day=day).on_conflict_do_nothing()
    )
    return bool(result.rowcount)


async def alerts(session: AsyncSession, rl: ReorderList, today: date) -> int:
    sent = 0
    for line in rl.lines:
        if await _once(session, "stock.low", f"{rl.branch_id}:{line.medicine_id}", today):
            add_event(session, OutboxEvent, "stock.low", {
                "branch_id": str(rl.branch_id), "medicine_id": str(line.medicine_id), "sku": line.sku, "name": line.name,
                "available": line.on_hand + line.in_transit + line.on_order, "reorder_point": line.reorder_point,
                "suggested_qty": line.suggested_qty, "day": today.isoformat()})  # fmt: skip
            sent += 1
    s = await _settings(session, rl.branch_id)
    thresholds = sorted(int(d) for d in (s.expiry_alert_days or [180, 90, 30]))
    if not thresholds:
        return sent
    rows = await session.execute(
        select(Batch, Stock.qty_on_hand).join(Stock, Stock.batch_id == Batch.id)
        .where(Stock.branch_id == rl.branch_id, Stock.qty_on_hand > 0, Batch.status == "active",
               Batch.expiry_date >= today, Batch.expiry_date <= today + timedelta(days=thresholds[-1])))  # fmt: skip
    products = {p.id: p for p in (await session.execute(select(Product))).scalars()}
    for batch, qty in rows:
        days_left = (batch.expiry_date - today).days
        if await _once(session, "batch.expiring", f"{rl.branch_id}:{batch.id}", today):
            p = products.get(batch.medicine_id)
            add_event(session, OutboxEvent, "batch.expiring", {
                "branch_id": str(rl.branch_id), "batch_id": str(batch.id), "medicine_id": str(batch.medicine_id),
                "sku": p.sku if p else "", "name": p.display_name if p else "", "lot_no": batch.lot_no,
                "expiry_date": batch.expiry_date.isoformat(), "days_left": days_left, "qty_base": int(qty),
                "threshold_days": next(t for t in thresholds if days_left <= t), "day": today.isoformat()})  # fmt: skip
            sent += 1
    return sent


async def run_all(session: AsyncSession, today: date) -> dict[str, int] | None:
    """The daily job for every active branch; None when another replica runs it."""
    if not (
        await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
    ).scalar_one():
        await session.rollback()
        return None
    branches = list(
        (await session.execute(select(KnownBranch.id).where(KnownBranch.is_active.is_(True)))).scalars()
    )
    lines = events = 0
    for branch_id in branches:
        rl = await build_list(session, branch_id, today)
        lines += len(rl.lines)
        events += await alerts(session, rl, today)
    await session.commit()
    return {"branches": len(branches), "lines": lines, "alerts": events}


async def run_branch(session: AsyncSession, actor: CurrentUser, branch_id: UUID) -> ReorderList:
    branch = await branch_for(session, actor, branch_id)
    rl = await build_list(session, branch.id, clock.today(), actor)
    await alerts(session, rl, clock.today())
    audit(
        session,
        actor,
        "reorder_list.run",
        "branch",
        branch.id,
        branch_id=branch.id,
        after={"lines": len(rl.lines)},
    )
    await session.commit()
    return rl


def next_run(now_local: datetime, hour: int, minute: int) -> datetime:
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now_local else target + timedelta(days=1)


async def run_scheduler(db: Database, stop: asyncio.Event, hour: int, minute: int) -> None:
    """Asia/Phnom_Penh time (clock.TIMEZONE), not UTC."""
    while not stop.is_set():
        try:
            async with db.sessionmaker() as session:
                result = await run_all(session, clock.today())
            if result:
                log.info("re-order lists: %s", result)
        except Exception:  # noqa: BLE001
            log.exception("re-order job failed")
        now_local = datetime.now(clock.TIMEZONE)
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=(next_run(now_local, hour, minute) - now_local).total_seconds()
            )
        except TimeoutError:
            pass


# ---------------------------------------------------------------- reading, requests from a list


async def get_list(session: AsyncSession, actor: CurrentUser, list_id: UUID) -> ReorderList:
    rl = await session.get(ReorderList, list_id)
    if rl is None or not actor.can_access_branch(rl.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Re-order list not found", status_code=404)
    return rl


async def latest(session: AsyncSession, actor: CurrentUser, branch_id: UUID) -> ReorderList:
    actor.require_branch(branch_id)
    rl = (await session.execute(select(ReorderList).where(ReorderList.branch_id == branch_id)
                                .order_by(ReorderList.created_at.desc()).limit(1))).scalar_one_or_none()  # fmt: skip
    if rl is None:
        raise AppError(ErrorCode.NOT_FOUND, "No re-order list yet for this branch: run it", status_code=404)
    return rl


def _chosen(rl: ReorderList, line_ids: list[UUID]) -> list[ReorderLine]:
    lines = [x for x in rl.lines if x.id in set(line_ids)]
    if len(lines) != len(set(line_ids)):
        raise AppError(ErrorCode.NOT_FOUND, "Line not found on this re-order list", status_code=404)
    taken = [x.sku for x in lines if x.status != "open"]
    if taken:
        raise AppError(ErrorCode.REQUEST_STATE, f"Already requested: {', '.join(taken)}", status_code=409)
    return lines


async def to_purchase_request(session: AsyncSession, actor: CurrentUser, purchasing: InternalClient, list_id: UUID,
                              line_ids: list[UUID]) -> ReorderList:  # fmt: skip
    rl = await get_list(session, actor, list_id)
    actor.require("purchasing.request")
    lines = _chosen(rl, line_ids)
    ref = "reorder:" + hashlib.sha256(",".join(sorted(str(x.id) for x in lines)).encode()).hexdigest()[:40]
    made = await purchasing.post("/purchase-requests", {
        "branch_id": str(rl.branch_id), "source_ref": ref, "note": f"Re-order list {rl.run_date}",
        "lines": [{"medicine_id": str(x.medicine_id), "qty_base": x.suggested_qty,
                   "reason": f"Below reorder point ({x.on_hand + x.in_transit + x.on_order} ≤ {x.reorder_point})"}
                  for x in lines]}, actor=actor, branch_id=rl.branch_id)  # fmt: skip
    for x in lines:
        x.status, x.request_number = "purchase_requested", made["number"]
    audit(session, actor, "reorder_list.purchase_request", "branch", rl.branch_id, branch_id=rl.branch_id,
          after={"request": made["number"], "lines": [x.sku for x in lines]})  # fmt: skip
    await session.commit()
    return rl


async def to_transfer_requests(session: AsyncSession, actor: CurrentUser, list_id: UUID, line_ids: list[UUID],
                               source_branch_id: UUID | None) -> ReorderList:  # fmt: skip
    rl = await get_list(session, actor, list_id)
    lines = _chosen(rl, line_ids)
    by_source: dict[UUID, list[ReorderLine]] = defaultdict(list)
    for x in lines:
        source = source_branch_id or x.source_branch_id
        if source is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"{x.sku}: no branch suggested; choose the source branch",
                           status_code=422)  # fmt: skip
        by_source[source].append(x)
    for source, group in by_source.items():
        r = await transfers.create_request(session, actor, {
            "from_branch_id": source, "to_branch_id": rl.branch_id, "reason": f"Re-order list {rl.run_date}",
            "lines": [{"medicine_id": x.medicine_id,
                       "qty_base": x.source_qty if x.source_qty and source == x.source_branch_id else x.suggested_qty}
                      for x in group]})  # fmt: skip
        for x in group:
            x.status, x.request_number = "transfer_requested", r.number
    await session.commit()
    return rl
