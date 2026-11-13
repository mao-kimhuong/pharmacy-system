"""/internal/v1 of the reports service (service token; never through Traefik)."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..models import KnownBranch
from ..services import bot
from ..services.dashboard import dashboard

router = APIRouter()


@router.get("/daily-summary")
async def daily_summary(
    day: date | None = None,
    branch_id: UUID | None = None,
    profit: bool = False,
    caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:
    """The 20:00 Telegram summary (notification service): one branch, or every
    active branch (no branch_id). Profit only when asked (the owner's chat)."""
    branches = [branch_id] if branch_id else None
    out = await dashboard(session, branches, profit, day or clock.today())
    names = {b.id: b for b in (await session.execute(select(KnownBranch))).scalars()}
    out["branches"] = [{"id": str(b.id), "code": b.code, "name_en": b.name_en, "name_km": b.name_km}
                       for b in names.values() if b.is_active and (branch_id is None or b.id == branch_id)]  # fmt: skip
    out.pop("top_debtors", None)  # customer names stay out of chat messages
    out.update(await bot.sale_times(session, branches, day or clock.today()))  # T2: first / last sale of the day
    return out


# ---------------------------------------------------------------- T2 bot commands (notification checks the user)


def _branches(branch_ids: str | None) -> list[UUID] | None:
    """Comma separated; left out = every branch (the owner)."""
    if branch_ids is None:
        return None
    return [UUID(x) for x in branch_ids.split(",") if x.strip()]


@router.get("/bot/{command}")
async def bot_command(
    command: str, day: date | None = None, branch_ids: str | None = None, profit: bool = False,
    names: bool = False, q: str = Query(default="", max_length=60), n: int = Query(default=10, ge=1, le=20),
    caller: InternalCaller = Depends(internal_caller), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """day | top | cash | debtors | expiring | stock (see services/bot.py)."""
    branches, on = _branches(branch_ids), day or clock.today()
    if command == "day":
        return await bot.day(session, branches, on, profit)
    if command == "top":
        return await bot.top(session, branches, on, n)
    if command == "cash":
        return await bot.cash(session, branches, on)
    if command == "debtors":
        return await bot.debtors(session, branches, n, names)
    if command == "expiring":
        return await bot.expiring(session, branches, on)
    if command == "stock":
        return await bot.stock(session, branches, q, on)
    raise AppError(ErrorCode.NOT_FOUND, "Unknown bot command", status_code=404)
