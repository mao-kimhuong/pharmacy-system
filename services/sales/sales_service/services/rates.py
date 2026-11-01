"""KHR exchange rate per branch. Rules:

- Set by owner / branch manager (sales.exchange_rate), for their branches.
- Kept as history: every change is a new row with the previous rate, who and
  when (and a User Log entry old -> new). Each invoice stores the rate it used.
"""

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.outbox import add_event

from ..models import ExchangeRate, OutboxEvent
from .common import audit, branch_for


async def current(session: AsyncSession, branch_id: UUID) -> ExchangeRate | None:
    return (
        await session.execute(
            select(ExchangeRate).where(ExchangeRate.branch_id == branch_id)
            .order_by(ExchangeRate.set_at.desc(), ExchangeRate.id).limit(1)
        )
    ).scalar_one_or_none()  # fmt: skip


async def history(session: AsyncSession, actor: CurrentUser, branch_id: UUID, limit: int = 50, offset: int = 0,
                  date_from: date | None = None, date_to: date | None = None) -> list[ExchangeRate]:  # fmt: skip
    """Newest first; days in Asia/Phnom_Penh."""
    actor.require_branch(branch_id)
    q = select(ExchangeRate).where(ExchangeRate.branch_id == branch_id)
    if date_from:
        q = q.where(ExchangeRate.set_at >= datetime.combine(date_from, time.min, clock.TIMEZONE))
    if date_to:
        q = q.where(ExchangeRate.set_at < datetime.combine(date_to + timedelta(days=1), time.min, clock.TIMEZONE))
    return list((await session.execute(q.order_by(ExchangeRate.set_at.desc()).limit(limit).offset(offset))).scalars())


async def set_rate(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID, khr_per_usd: int
) -> ExchangeRate:
    branch = await branch_for(session, actor, branch_id)
    old = await current(session, branch.id)
    row = ExchangeRate(branch_id=branch.id, khr_per_usd=khr_per_usd, previous=old.khr_per_usd if old else None,
                       set_by=actor.id)  # fmt: skip
    session.add(row)
    await session.flush()
    payload: dict[str, Any] = {
        "branch_id": str(branch.id),
        "khr_per_usd": khr_per_usd,
        "previous": row.previous,
    }
    add_event(session, OutboxEvent, "exchange_rate.changed", payload)
    audit(session, actor, "exchange_rate.changed", "branch", branch.id, branch_id=branch.id,
          before={"khr_per_usd": row.previous}, after={"khr_per_usd": khr_per_usd})  # fmt: skip
    await session.commit()
    return row
