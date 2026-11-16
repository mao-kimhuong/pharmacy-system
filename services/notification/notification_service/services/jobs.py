"""Scheduled work (Asia/Phnom_Penh), one replica at a time (advisory lock):

- 20:00 daily summary: each active branch with a chat gets its own figures
  (no profit); the owner's chat gets all branches with gross profit. Figures come
  from the reports service. Dedupe key daily:<chat>:<date>: a second run (or the
  catch-up at start-up) queues nothing, and a summary already sent is never
  changed, even if the figures move later (late returns, cancels).
- 07:30 stock digest: the night job's low stock and near-expiry alerts of that
  day, one message per branch (to the owner's chat when the branch has none).
- The sender: due messages every few seconds (telegram.Sender).
"""

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.db import Database
from pharmacy_shared.internal import InternalClient

from ..config import Settings
from ..models import KnownBranch, StockAlert
from . import customers, ops, texts
from .telegram import Sender, chat_for, queue

log = logging.getLogger(__name__)
SUMMARY_LOCK, DIGEST_LOCK = 7_202_681, 7_202_682


async def _lock(session: AsyncSession, key: int) -> bool:
    return bool((await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key})).scalar_one())


async def daily_summary(session: AsyncSession, settings: Settings, reports: InternalClient, day: date) -> int | None:
    """Queues the day's summaries; returns how many are new (None: another replica runs it)."""
    if not await _lock(session, SUMMARY_LOCK):
        return None
    made = 0
    branches = (await session.execute(select(KnownBranch).where(KnownBranch.is_active.is_(True))
                                      .order_by(KnownBranch.code))).scalars().all()  # fmt: skip
    for b in branches:
        target = str(b.id)
        if await chat_for(session, target) is None:
            continue
        figures = await reports.get("/daily-summary", {"day": day.isoformat(), "branch_id": target})
        made += bool(await queue(session, settings, key=f"daily:{target}:{day}", target=target, kind="daily_summary",
                                 text=texts.daily_summary(f"{b.code} {b.name_en}", figures, profit=False),
                                 branch_id=b.id))  # fmt: skip
    if branches:  # the owner's summary is always made (kept as "skipped" without a chat or token)
        figures = await reports.get("/daily-summary", {"day": day.isoformat(), "profit": "true"})
        made += bool(await queue(session, settings, key=f"daily:owner:{day}", target="owner", kind="daily_summary",
                                 text=texts.daily_summary("All branches", figures, profit=True)))  # fmt: skip
    await session.commit()
    return made


async def stock_digest(session: AsyncSession, settings: Settings, day: date) -> int | None:
    if not await _lock(session, DIGEST_LOCK):
        return None
    found: dict[Any, dict[str, list]] = defaultdict(lambda: {"low": [], "expiring": []})
    for a in (await session.execute(select(StockAlert).where(StockAlert.day == day))).scalars():
        found[a.branch_id][a.kind].append(a.data)
    yesterday = day - timedelta(days=1)
    for branch_id in await ops.fridge_branches(session, yesterday):  # T2: fridges also make a digest
        found[branch_id]  # noqa: B018 – creates the branch's entry
    made = 0
    for branch_id, kinds in found.items():
        b = await session.get(KnownBranch, branch_id)
        target = str(branch_id) if await chat_for(session, str(branch_id)) else "owner"
        fridges = await ops.fridge_day(session, branch_id, yesterday)
        made += bool(await queue(session, settings, key=f"digest:{branch_id}:{day}", target=target, kind="stock_digest",
                                 text=texts.stock_digest(f"{b.code} {b.name_en}" if b else "Branch", kinds["low"],
                                                         kinds["expiring"], fridges), branch_id=branch_id))  # fmt: skip
    await session.commit()
    return made


def last_due(now_local: datetime, hour: int, minute: int = 0) -> date:
    """The latest day whose hour:minute has passed (start-up catch-up)."""
    passed = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0) <= now_local
    return now_local.date() if passed else now_local.date() - timedelta(days=1)


def next_run(now_local: datetime, hour: int, minute: int) -> datetime:
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now_local else target + timedelta(days=1)


async def _daily(db: Database, stop: asyncio.Event, hour: int, minute: int, job: Any, name: str) -> None:
    while not stop.is_set():
        now_local = datetime.now(clock.TIMEZONE)
        try:
            async with db.sessionmaker() as session:
                done = await job(session, last_due(now_local, hour, minute))
            if done:
                log.info("%s: %d message(s) queued", name, done)
        except Exception:  # noqa: BLE001 – a failed run must not stop the scheduler
            log.exception("%s failed", name)
        wait = (next_run(datetime.now(clock.TIMEZONE), hour, minute) - datetime.now(clock.TIMEZONE)).total_seconds()
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
        except TimeoutError:
            pass


def schedulers(db: Database, settings: Settings) -> list:
    reports = InternalClient(settings.reports_url, settings.service_name, settings.service_token, read_timeout=30)
    sender = Sender(settings)

    async def summary(stop: asyncio.Event) -> None:
        await _daily(db, stop, settings.daily_summary_hour, 0,
                     lambda s, d: daily_summary(s, settings, reports, d), "daily summary")  # fmt: skip

    async def digest(stop: asyncio.Event) -> None:
        await _daily(db, stop, settings.digest_hour, settings.digest_minute,
                     lambda s, d: stock_digest(s, settings, d), "stock digest")  # fmt: skip

    async def send(stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                async with db.sessionmaker() as session:
                    await sender.send_due(session)
            except Exception:  # noqa: BLE001
                log.exception("telegram sender failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.send_every_seconds)
            except TimeoutError:
                pass

    customers_client = InternalClient(settings.customers_url, settings.service_name, settings.service_token)

    async def refills(stop: asyncio.Event) -> None:
        await _daily(db, stop, settings.refill_hour, 0, lambda s, d: customers.refill_job(s, settings, d),
                     "refill reminders")  # fmt: skip

    async def balances(stop: asyncio.Event) -> None:
        await _daily(db, stop, settings.refill_hour, 5,
                     lambda s, d: customers.balance_job(s, settings, customers_client, d), "balance reminders")  # fmt: skip

    async def every_minute(stop: asyncio.Event) -> None:
        """T2 operations: offline tills, late opening, fridges."""
        while not stop.is_set():
            try:
                async with db.sessionmaker() as session:
                    await ops.minute_job(session, settings)
            except Exception:  # noqa: BLE001
                log.exception("operations check failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=60)
            except TimeoutError:
                pass

    tasks = [summary, digest, send, refills, balances, every_minute]
    if settings.telegram_mode == "polling" and settings.telegram_bot_token:
        tasks.append(lambda stop: poll_updates(db, settings, sender, stop))
    return tasks


async def poll_updates(db: Database, settings: Settings, sender: Sender, stop: asyncio.Event) -> None:
    """Development without a public URL: getUpdates (long poll) instead of the webhook. Same handler."""
    from . import bot

    await sender.call("deleteWebhook", {"drop_pending_updates": False})
    offset = 0
    while not stop.is_set():
        try:
            status, body = await sender.call("getUpdates", {"offset": offset, "timeout": 25,
                                                            "allowed_updates": ["message", "callback_query"]})  # fmt: skip
            for update in body.get("result") or [] if status == 200 else []:
                offset = max(offset, int(update["update_id"]) + 1)
                async with db.sessionmaker() as session:
                    made = await bot.handle_update(session, settings, sender, update, bot.HOOKS)
                    await session.commit()
                    await bot.send_now(session, sender, made)
            if status != 200:
                await asyncio.wait_for(stop.wait(), timeout=10)
        except TimeoutError:
            pass
        except Exception:  # noqa: BLE001 – keep polling
            log.exception("telegram polling failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
            except TimeoutError:
                pass
