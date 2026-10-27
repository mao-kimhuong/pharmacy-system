"""Initialize: opening stock of a branch at go-live. Rules:

- Lines (JSON: medicine_id + pack_unit_id; Excel: sku + pack unit name) with
  lot, expiry, qty in that pack unit and unit cost in USD per pack unit.
- First validated line by line and stored with the errors; nothing reaches
  stock. GET shows the errors. Commit (Idempotency-Key) books everything as
  "opening" movements in ONE transaction, then locks the branch for initialize.
- While a branch is locked nothing can be validated or committed for it
  (INITIALIZE_LOCKED). Only the owner unlocks, with a reason (User Log).
- Expiry before today → line error; within 180 days → flagged short_expiry.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.xlsx import read_sheet, write_workbook

from ..models import InitializeLock, OpeningBalance, OpeningLine, Product, ProductPackUnit
from .common import audit, branch_for, clean, expiry_problem, find_pack_unit, is_short_expiry
from .movements import apply_movement, get_or_create_batch

COST = Decimal("0.0001")
XLSX_KEYS = ("sku", "pack_unit", "lot_no", "expiry_date", "qty", "unit_cost_usd")
XLSX_ALIASES = {
    "unit_cost": "unit_cost_usd",
    "cost": "unit_cost_usd",
    "lot": "lot_no",
    "expiry": "expiry_date",
}
_DMY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")


def _locked(branch_code: str) -> AppError:
    return AppError(ErrorCode.INITIALIZE_LOCKED, f"Opening stock of {branch_code} was already committed; "
                    "the owner can unlock it with a reason", status_code=409)  # fmt: skip


async def _lock_row(
    session: AsyncSession, branch_id: UUID, *, for_update: bool = False
) -> InitializeLock | None:
    query = select(InitializeLock).where(InitializeLock.branch_id == branch_id)
    return (await session.execute(query.with_for_update() if for_update else query)).scalar_one_or_none()


def _parse_date(text: str) -> date:
    text = text.strip()[:10] if "T" not in text else text.split("T")[0]
    if m := _DMY.match(text):
        return date(int(m[3]), int(m[2]), int(m[1]))
    return date.fromisoformat(text)


async def _validate(session: AsyncSession, line: OpeningLine, *, by_sku: bool) -> None:
    """Fills the parsed fields and errors of one line from line.data (text)."""
    d = line.data
    errors: list[dict[str, str]] = []

    def err(field: str, message: str, code: ErrorCode = ErrorCode.VALIDATION_ERROR) -> None:
        errors.append({"field": field, "code": code.value, "message": message})

    pack: ProductPackUnit | None = None
    if by_sku:
        product = (
            await session.execute(select(Product).where(Product.sku == clean(d.get("sku")).upper()))
        ).scalar_one_or_none()
        if product is None:
            err("sku", f"unknown sku {d.get('sku')!r}", ErrorCode.UNKNOWN_MEDICINE)
        else:
            name = clean(d.get("pack_unit")).casefold()
            pack = next((p for p in product.pack_units if p.name.casefold() == name), None)
            if pack is None:
                err("pack_unit", f"{product.sku} has no pack unit {d.get('pack_unit')!r}")
    else:
        try:
            pack = await find_pack_unit(session, UUID(d["medicine_id"]), UUID(d["pack_unit_id"]))
        except (KeyError, ValueError):
            pack = None
        if pack is None:
            err("pack_unit_id", "unknown medicine or pack unit", ErrorCode.UNKNOWN_MEDICINE)
    if pack is not None and not (pack.is_active and pack.product.is_active):
        err("pack_unit", f"{pack.product.sku} ({pack.name}) is deactivated", ErrorCode.UNKNOWN_MEDICINE)

    lot = clean(d.get("lot_no"))
    if not lot or len(lot) > 40:
        err("lot_no", "lot_no is required (at most 40 characters)")
    expiry = None
    try:
        expiry = _parse_date(clean(d.get("expiry_date")))
    except ValueError:
        err("expiry_date", "expiry_date must be a date, e.g. 2028-03-31")
    if expiry and (problem := expiry_problem(expiry)):
        err("expiry_date", f"lot {lot} {problem}", ErrorCode.BATCH_EXPIRED)
    qty = None
    try:
        qty = int(Decimal(clean(d.get("qty"))))
        if qty < 1 or Decimal(clean(d.get("qty"))) != qty:
            raise ValueError
    except (InvalidOperation, ValueError):
        err("qty", "qty must be a whole number from 1")
        qty = None
    unit_cost = None
    try:
        unit_cost = Decimal(clean(d.get("unit_cost")).replace("$", "")).quantize(COST)
        if unit_cost < 0 or not unit_cost.is_finite():
            raise InvalidOperation
    except InvalidOperation:
        err("unit_cost", "unit_cost must be a price from 0 in USD per pack unit")
        unit_cost = None

    line.medicine_id = pack.product_id if pack else None
    line.pack_unit_id = pack.id if pack else None
    line.lot_no = lot[:40]
    line.expiry_date = expiry
    line.qty = qty
    line.qty_base = qty * pack.qty_in_base if (qty and pack) else None
    line.unit_cost = unit_cost
    line.cost_per_base = (
        (unit_cost / pack.qty_in_base).quantize(COST) if (unit_cost is not None and pack) else None
    )
    line.short_expiry = bool(expiry and not errors and is_short_expiry(expiry))
    line.errors = errors


def _check_duplicates(lines: list[OpeningLine]) -> None:
    seen: dict[tuple, int] = {}
    for line in lines:
        if line.errors or line.medicine_id is None:
            continue
        key = (line.medicine_id, line.lot_no.casefold(), line.expiry_date, line.cost_per_base)
        if key in seen:
            line.errors = [*line.errors, {"field": "lot_no", "code": "VALIDATION_ERROR",
                                          "message": f"same medicine, lot, expiry and cost as line {seen[key]}"}]  # fmt: skip
        else:
            seen[key] = line.line_no


async def _revalidate(session: AsyncSession, ob: OpeningBalance) -> None:
    for line in ob.lines:
        await _validate(session, line, by_sku=ob.source == "xlsx")
    _check_duplicates(ob.lines)
    ob.error_lines = sum(1 for line in ob.lines if line.errors)
    ob.total_lines = len(ob.lines)
    ob.status = "has_errors" if ob.error_lines else "validated"


async def _create(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID, rows: list[tuple[int, dict[str, Any]]],
    source: str, file_name: str = "",
) -> OpeningBalance:  # fmt: skip
    branch = await branch_for(session, actor, branch_id)
    lock = await _lock_row(session, branch.id)
    if lock is not None and lock.locked:
        raise _locked(branch.code)
    ob = OpeningBalance(branch_id=branch.id, status="validated", source=source, file_name=file_name,
                        created_by=actor.id, lines=[])  # fmt: skip
    for line_no, data in rows:
        ob.lines.append(OpeningLine(line_no=line_no, data={k: "" if v is None else str(v) for k, v in data.items()},
                                    errors=[]))  # fmt: skip
    session.add(ob)
    await _revalidate(session, ob)
    await session.flush()
    audit(session, actor, "opening.validated", "opening_balance", ob.id, branch_id=branch.id,
          after={"source": source, "file_name": file_name, "lines": ob.total_lines, "error_lines": ob.error_lines})  # fmt: skip
    await session.commit()
    return ob


async def create_from_lines(
    session: AsyncSession, actor: CurrentUser, data: dict[str, Any]
) -> OpeningBalance:
    rows = [(i, {**line, "medicine_id": str(line["medicine_id"]), "pack_unit_id": str(line["pack_unit_id"]),
                 "expiry_date": line["expiry_date"].isoformat()})
            for i, line in enumerate(data["lines"], start=1)]  # fmt: skip
    return await _create(session, actor, data["branch_id"], rows, "api")


async def create_from_xlsx(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID, file_name: str, content: bytes
) -> OpeningBalance:
    rows = read_sheet(
        content, keys=XLSX_KEYS, required=XLSX_KEYS, sheet="Opening stock", aliases=XLSX_ALIASES
    )
    rows = [(n, {**r, "unit_cost": r.pop("unit_cost_usd")}) for n, r in rows]
    return await _create(session, actor, branch_id, rows, "xlsx", clean(file_name)[:255])


def template() -> bytes:
    return write_workbook([
        ("Opening stock", list(XLSX_KEYS), [
            ["PARA500", "box", "A2391", "2028-03-31", 12, "4.25"],
            ["PARA500", "strip", "A2391", "2028-03-31", 7, "0.45"],
            ["AMOX500", "box", "K774", "2027-11-30", 3, "9.80"],
        ]),
        ("Instructions", ["column", "what to enter"], [
            ["sku", "Product SKU as in Settings → Product"],
            ["pack_unit", "tablet / strip / box ... (a pack unit of that product)"],
            ["lot_no", "Lot / batch number printed on the pack"],
            ["expiry_date", "2028-03-31 or 31/03/2028; expired lots are refused"],
            ["qty", "How many of that pack unit you have"],
            ["unit_cost_usd", "What one pack unit cost you, in USD"],
        ]),
    ])  # fmt: skip


async def get_opening(
    session: AsyncSession, actor: CurrentUser, opening_id: UUID, *, lock: bool = False
) -> OpeningBalance:
    query = select(OpeningBalance).where(OpeningBalance.id == opening_id)
    ob = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if ob is None or not actor.can_access_branch(ob.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Opening balance not found", status_code=404)
    return ob


async def commit_opening(session: AsyncSession, actor: CurrentUser, opening_id: UUID) -> OpeningBalance:
    ob = await get_opening(session, actor, opening_id, lock=True)
    branch = await branch_for(session, actor, ob.branch_id)
    if ob.status == "committed":
        raise AppError(ErrorCode.IMPORT_STATE, "This opening balance was already committed", status_code=409)
    lock = await _lock_row(session, branch.id, for_update=True)
    if lock is not None and lock.locked:
        raise _locked(branch.code)
    await _revalidate(session, ob)
    if ob.error_lines:
        await session.commit()  # keep the fresh errors for GET
        raise AppError(ErrorCode.OPENING_HAS_ERRORS, f"{ob.error_lines} line(s) have errors; fix them and "
                       "validate again", status_code=422, details={"error_lines": ob.error_lines})  # fmt: skip
    for line in ob.lines:
        batch = await get_or_create_batch(
            session, medicine_id=line.medicine_id, lot_no=line.lot_no, expiry_date=line.expiry_date,
            supplier_id=None, cost_per_base=line.cost_per_base,
        )  # fmt: skip
        await apply_movement(
            session, branch_id=branch.id, batch=batch, type="opening", qty_base=line.qty_base,
            ref_type="opening_line", ref_id=str(line.id), reason="Opening stock", actor_id=actor.id,
        )  # fmt: skip
    now = clock.now()
    ob.status, ob.committed_by, ob.committed_at = "committed", actor.id, now
    if lock is None:
        lock = InitializeLock(branch_id=branch.id)
        session.add(lock)
    lock.locked, lock.opening_id, lock.locked_at, lock.locked_by = True, ob.id, now, actor.id
    audit(session, actor, "opening.committed", "opening_balance", ob.id, branch_id=branch.id,
          after={"lines": ob.total_lines, "qty_base": sum(x.qty_base for x in ob.lines), "branch_locked": True})  # fmt: skip
    await session.commit()
    return ob


async def unlock(session: AsyncSession, actor: CurrentUser, branch_id: UUID, reason: str) -> InitializeLock:
    if not actor.is_owner:
        raise AppError(ErrorCode.FORBIDDEN, "Only the owner can unlock opening stock", status_code=403)
    branch = await branch_for(session, actor, branch_id)
    lock = await _lock_row(session, branch.id, for_update=True)
    if lock is None or not lock.locked:
        raise AppError(ErrorCode.IMPORT_STATE, f"{branch.code} is not locked", status_code=409)
    lock.locked, lock.unlocked_at, lock.unlocked_by, lock.unlock_reason = (
        False,
        clock.now(),
        actor.id,
        clean(reason),
    )
    audit(session, actor, "initialize.unlocked", "branch", branch.id, branch_id=branch.id,
          before={"locked": True}, after={"locked": False, "reason": lock.unlock_reason})  # fmt: skip
    await session.commit()
    return lock


async def locks(session: AsyncSession, actor: CurrentUser) -> list[InitializeLock]:
    query = select(InitializeLock).order_by(InitializeLock.branch_id)
    if not actor.is_owner:
        query = query.where(InitializeLock.branch_id.in_(actor.branch_ids or [UUID(int=0)]))
    return list((await session.execute(query)).scalars())


async def list_openings(
    session: AsyncSession, actor: CurrentUser, page: int, size: int
) -> tuple[list[OpeningBalance], int]:
    query = select(OpeningBalance)
    if not actor.is_owner:
        query = query.where(OpeningBalance.branch_id.in_(actor.branch_ids or [UUID(int=0)]))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(
        query.order_by(OpeningBalance.created_at.desc(), OpeningBalance.id)
        .offset((page - 1) * size)
        .limit(size)
    )
    return list(rows.scalars()), int(total)
