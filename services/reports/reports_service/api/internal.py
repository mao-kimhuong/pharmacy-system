"""/internal/v1 of the reports service (service token; never through Traefik)."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..models import KnownBranch
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
    return out
