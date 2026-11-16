"""Stock takes. Rules:

- Start (stockcount.count, own branch): inventory takes a snapshot of the scope
  (full / category / location / controlled) at movement seq N; one open count
  per branch. Sales go on during the count.
- Blind counting: counters see medicine, lot, expiry and location, never the
  expected quantity nor other people's counts. Lookup by barcode (phone scanner).
- A line is agreed after one count, or – controlled lines and lines whose
  snapshot value is above the branch's `double_count_above_usd` (50) – after two
  different people counted the same number; different numbers → recount until
  two people agree. Counting again replaces your own earlier count.
- Submit (all lines agreed) → review: expected = snapshot + movements after N
  up to the moment the line was counted; variance = counted − expected.
- Approve (stockcount.approve, Idempotency-Key): the approver's PIN when a
  controlled line has a variance; total |variance value| above the branch's
  `owner_approval_above_usd` (200) → owner only. Emits count.approved; inventory
  books one count_adjust movement per line with a variance (once). Lines can be
  sent back for a recount; cancel (reason) before approval. Never deleted.
- Cost and values only with finance.cost_profit.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event
from pharmacy_shared.pin import consume_pin

from ..models import BranchSettingsCopy, Count, CountEntry, CountLine, DocSequence, KnownBranch, OutboxEvent
from .clients import Clients

DOUBLE_ABOVE = Decimal("50.00")
OWNER_ABOVE = Decimal("200.00")
OPEN = ("counting", "review")


def _state(message: str, status: str, **details: Any) -> AppError:
    return AppError(ErrorCode.COUNT_STATE, message, status_code=409, details={"status": status, **details})


def _audit(session: AsyncSession, actor: CurrentUser | None, action: str, count: Count, **after: Any) -> None:
    record_audit(session, OutboxEvent, service="stockcount", action=action, entity_type="stock_count",
                 entity_id=count.id, actor=actor, branch_id=count.branch_id,
                 after={"number": count.number, **after})  # fmt: skip


def _event(session: AsyncSession, name: str, count: Count, **extra: Any) -> None:
    add_event(session, OutboxEvent, name, {
        "count_id": str(count.id), "number": count.number, "branch_id": str(count.branch_id), "status": count.status,
        "scope": count.scope, "version": count.version, **extra})  # fmt: skip


def _variance_lines(count: Count) -> list[dict[str, Any]]:
    """Lines with a variance (reports: stock take variances)."""
    return [{"count_line_id": str(x.id), "batch_id": str(x.batch_id), "medicine_id": str(x.medicine_id),
             "sku": x.sku, "lot_no": x.lot_no, "expected_qty": x.expected_qty, "counted_qty": x.counted_qty,
             "variance": x.variance, "cost_per_base": str(x.cost_per_base), "value": str(x.variance_value),
             "is_controlled": x.is_controlled} for x in count.lines if x.variance]  # fmt: skip


async def get_count(
    session: AsyncSession, actor: CurrentUser, count_id: UUID, *, lock: bool = False
) -> Count:
    query = select(Count).where(Count.id == count_id)
    count = (await session.execute(query.with_for_update(of=Count) if lock else query)).scalar_one_or_none()
    if count is None or not actor.can_access_branch(count.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Stock take not found", status_code=404)
    return count


async def list_counts(session: AsyncSession, actor: CurrentUser, branch_id: UUID | None, status: str | None):  # noqa: ANN201
    query = select(Count)
    if branch_id:
        actor.require_branch(branch_id)
        query = query.where(Count.branch_id == branch_id)
    elif not actor.is_owner:
        query = query.where(Count.branch_id.in_(list(actor.branch_ids)))
    if status:
        query = query.where(Count.status == status)
    return list((await session.execute(query.order_by(Count.started_at.desc()).limit(200))).scalars())


async def start(session: AsyncSession, actor: CurrentUser, clients: Clients, data: dict[str, Any]) -> Count:
    actor.require_branch(data["branch_id"])
    branch = await session.get(KnownBranch, data["branch_id"])
    if branch is None or not branch.is_active:
        raise AppError(ErrorCode.UNKNOWN_BRANCH, "Unknown or inactive branch", status_code=422)
    running = (await session.execute(select(Count.number).where(
        Count.branch_id == branch.id, Count.status.in_(OPEN)))).scalar_one_or_none()  # fmt: skip
    if running:
        raise _state(f"Stock take {running} is still open at this branch", "counting", open=running)
    if data["scope"] == "category" and not data.get("category_id"):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Choose the category", status_code=422)
    if data["scope"] == "location" and not (data.get("location") or "").strip():
        raise AppError(ErrorCode.VALIDATION_ERROR, "Give the shelf location", status_code=422)
    snap = await clients.inventory.post("/stock/snapshot", {
        "branch_id": str(branch.id), "scope": data["scope"],
        "category_id": str(data["category_id"]) if data.get("category_id") else None,
        "location": data.get("location")}, actor=actor, branch_id=branch.id)  # fmt: skip
    if not snap["lines"]:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Nothing in stock in this scope", status_code=422)
    settings = await session.get(BranchSettingsCopy, branch.id)
    double_above = settings.double_count_above_usd if settings else DOUBLE_ABOVE
    count = Count(branch_id=branch.id, scope=data["scope"], category_id=data.get("category_id"),
                  location=(data.get("location") or "").strip().upper(), status="counting", as_of_seq=snap["as_of_seq"],
                  note=(data.get("note") or "").strip(), started_by=actor.id, started_at=clock.now(), lines=[])  # fmt: skip
    for x in snap["lines"]:
        cost = Decimal(str(x["cost_per_base"]))
        count.lines.append(CountLine(
            batch_id=UUID(str(x["batch_id"])), medicine_id=UUID(str(x["medicine_id"])), sku=x["sku"], name=x["name"],
            name_km=x.get("name_km") or "", base_unit=x["base_unit"], lot_no=x["lot_no"],
            expiry_date=datetime.fromisoformat(str(x["expiry_date"])).date(), location=x.get("location") or "",
            barcodes=x.get("barcodes") or [], is_controlled=bool(x["is_controlled"]), cost_per_base=cost,
            snapshot_qty=int(x["qty_base"]), status="pending", entries=[],
            needs_double=bool(x["is_controlled"]) or cost * int(x["qty_base"]) > double_above,
        ))  # fmt: skip
    count.number = await next_number(session, DocSequence, branch.id, branch.code, "SC")
    session.add(count)
    await session.flush()
    _event(session, "count.started", count)
    _audit(session, actor, "stock_count.started", count, scope=count.scope, lines=len(count.lines))
    await session.commit()
    return count


def _settle(line: CountLine) -> None:
    """Line status from the latest count of each person."""
    latest: dict[UUID, CountEntry] = {}
    for e in line.entries:
        if e.round == line.round:
            latest[e.user_id] = e
    counts = list(latest.values())
    if not counts:
        line.status, line.counted_qty, line.counted_at = "pending", None, None
        return
    if not line.needs_double:
        last = max(counts, key=lambda e: e.counted_at)
        line.status, line.counted_qty, line.counted_at = "agreed", last.qty, last.counted_at
        return
    by_qty: dict[int, list[CountEntry]] = {}
    for e in counts:
        by_qty.setdefault(e.qty, []).append(e)
    agreed = [es for es in by_qty.values() if len(es) >= 2]
    if agreed:
        es = max(agreed, key=lambda es: max(e.counted_at for e in es))
        line.status, line.counted_qty = "agreed", es[0].qty
        line.counted_at = max(e.counted_at for e in es)
    else:
        line.status = "needs_second" if len(counts) == 1 else "recount"
        line.counted_qty = line.counted_at = None


async def add_entry(
    session: AsyncSession, actor: CurrentUser, count_id: UUID, data: dict[str, Any]
) -> CountLine:
    count = await get_count(session, actor, count_id, lock=True)
    if count.status != "counting":
        raise _state(f"Stock take {count.number} is {count.status}", count.status)
    line = next((x for x in count.lines if x.id == data["line_id"]), None)
    if line is None:
        raise AppError(ErrorCode.NOT_FOUND, "Line not found on this stock take", status_code=404)
    line.entries.append(CountEntry(user_id=actor.id, qty=data["qty"], round=line.round))
    await session.flush()  # counted_at: the database's clock, like inventory's movements
    _settle(line)
    await session.commit()
    return line


async def submit(session: AsyncSession, actor: CurrentUser, clients: Clients, count_id: UUID) -> Count:
    count = await get_count(session, actor, count_id, lock=True)
    if count.status != "counting":
        raise _state(f"Stock take {count.number} is {count.status}", count.status)
    open_lines = [x for x in count.lines if x.status != "agreed"]
    if open_lines:
        raise _state(f"{len(open_lines)} line(s) still need counting", count.status,
                     lines=[{"line_id": str(x.id), "sku": x.sku, "lot_no": x.lot_no, "status": x.status}
                            for x in open_lines[:50]])  # fmt: skip
    since = await clients.inventory.post("/movements/since", {
        "branch_id": str(count.branch_id), "after_seq": count.as_of_seq,
        "batch_ids": [str(x.batch_id) for x in count.lines],
        "until": [{"batch_id": str(x.batch_id), "until": x.counted_at.isoformat()} for x in count.lines],
    }, actor=actor, branch_id=count.branch_id)  # fmt: skip
    total = Decimal("0")
    for line in count.lines:
        line.expected_qty = line.snapshot_qty + int(since["changes"].get(str(line.batch_id), 0))
        line.variance = line.counted_qty - line.expected_qty
        total += abs(line.variance_value)
    count.status, count.submitted_by, count.submitted_at = "review", actor.id, clock.now()
    count.variance_value = total
    count.version += 1
    settings = await session.get(BranchSettingsCopy, count.branch_id)
    owner_above = settings.owner_approval_above_usd if settings else OWNER_ABOVE
    _event(session, "count.submitted", count, submitted_by=str(actor.id), occurred_at=clock.now().isoformat(),
           variance_value=str(total), lines=_variance_lines(count), needs_owner=total > owner_above,
           needs_pin=any(x.is_controlled and x.variance for x in count.lines))  # fmt: skip
    _audit(session, actor, "stock_count.submitted", count, variance_value=str(total),
           lines_with_variance=sum(1 for x in count.lines if x.variance))  # fmt: skip
    await session.commit()
    return count


async def send_back(session: AsyncSession, actor: CurrentUser, count_id: UUID, line_ids: list[UUID],
                    reason: str) -> Count:  # fmt: skip
    """The reviewer asks for lines to be counted again (their counts are kept, the line is reopened)."""
    count = await get_count(session, actor, count_id, lock=True)
    if count.status != "review":
        raise _state(f"Stock take {count.number} is {count.status}", count.status)
    chosen = [x for x in count.lines if x.id in set(line_ids)]
    if not chosen:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Choose lines of this stock take", status_code=422)
    for line in chosen:
        line.status, line.counted_qty, line.counted_at = "recount", None, None
        line.expected_qty = line.variance = None
        line.round += 1
    count.status = "counting"
    count.version += 1
    _audit(
        session,
        actor,
        "stock_count.recount",
        count,
        lines=[f"{x.sku} {x.lot_no}" for x in chosen],
        reason=reason,
    )
    await session.commit()
    return count


async def approve(session: AsyncSession, actor: CurrentUser, clients: Clients, count_id: UUID,
                  pin_token: str | None, via: str | None = None) -> Count:  # fmt: skip
    count = await get_count(session, actor, count_id, lock=True)
    if count.status != "review":
        raise _state(f"Stock take {count.number} is {count.status}", count.status)
    settings = await session.get(BranchSettingsCopy, count.branch_id)
    owner_above = settings.owner_approval_above_usd if settings else OWNER_ABOVE
    if count.variance_value > owner_above and not actor.is_owner:
        raise AppError(ErrorCode.OWNER_APPROVAL_REQUIRED, f"The variance is above {owner_above} USD: the owner approves",
                       status_code=403, details={"limit": str(owner_above)})  # fmt: skip
    controlled = any(x.is_controlled and x.variance for x in count.lines)
    if via and controlled:  # T2: a PIN cannot be typed on Telegram
        raise AppError(ErrorCode.FORBIDDEN, "A controlled variance needs the PIN: approve in the app", status_code=403)
    if controlled:
        await consume_pin(
            clients.auth, pin_token, "stockcount.approve", user=actor, branch_id=count.branch_id
        )
    count.status, count.approved_by, count.approved_at = "approved", actor.id, clock.now()
    count.version += 1
    adjustments = [{
        "count_line_id": str(x.id), "batch_id": str(x.batch_id), "medicine_id": str(x.medicine_id),
        "qty_base": x.variance, "is_controlled": x.is_controlled, "cost_per_base": str(x.cost_per_base),
        "counted_by": sorted({str(e.user_id) for e in x.entries if e.round == x.round and e.qty == x.counted_qty}),
    } for x in count.lines if x.variance]  # fmt: skip
    _event(session, "count.approved", count, approved_by=str(actor.id), adjustments=adjustments,
           occurred_at=clock.now().isoformat(), variance_value=str(count.variance_value), lines=_variance_lines(count),
           via=via or "app")  # fmt: skip
    _audit(session, actor, "stock_count.approved", count, variance_value=str(count.variance_value),
           adjustments=len(adjustments), **({"via": via} if via else {}))  # fmt: skip
    await session.commit()
    return count


async def cancel(session: AsyncSession, actor: CurrentUser, count_id: UUID, reason: str) -> Count:
    count = await get_count(session, actor, count_id, lock=True)
    if count.status not in OPEN:
        raise _state(f"Stock take {count.number} is {count.status}", count.status)
    count.status, count.cancel_reason = "cancelled", reason.strip()
    count.version += 1
    _event(session, "count.cancelled", count)
    _audit(session, actor, "stock_count.cancelled", count, reason=count.cancel_reason)
    await session.commit()
    return count


async def lookup(session: AsyncSession, actor: CurrentUser, count_id: UUID, barcode: str) -> list[CountLine]:
    count = await get_count(session, actor, count_id)
    code = barcode.strip()
    return [x for x in count.lines if code in (x.barcodes or []) or code.upper() == x.sku.upper()]


async def progress(session: AsyncSession, count: Count) -> dict[str, int]:
    rows = await session.execute(select(CountLine.status, func.count()).where(CountLine.count_id == count.id)
                                 .group_by(CountLine.status))  # fmt: skip
    return {status: n for status, n in rows}
