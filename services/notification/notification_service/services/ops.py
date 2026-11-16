"""T2 phase 4: operations alerts (to the branch's chat and the owner's). Rules:

- Heartbeat: every POS browser posts one a minute (POST /heartbeat). During the branch's opening hours (branch
  setting `opening_hours`, Phnom Penh), once it has been open 10 minutes: no heartbeat from any till for 10 minutes →
  "offline" (once); the next heartbeat → "back online". Branches without opening hours get no such alerts.
- Opening: 30 minutes after opening with no sale yet that day → one alert. The 20:00 summary shows the first and
  last sale (reports).
- Fridge sensors (feature switch fridge_sensors): a device posts readings with its own token (POST
  /sensors/readings, Bearer). Out of its range (default 2–8 °C) for more than 10 minutes → one alert; back in range
  → one alert; no reading for 30 minutes → one alert (cleared by the next reading). The 07:30 digest shows yesterday's
  min / max per fridge. Checked on each reading and every minute (sparse readings).
"""

import hashlib
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..config import Settings
from ..models import (
    BranchDay,
    BranchOps,
    BranchPrefs,
    FeatureCopy,
    Heartbeat,
    KnownBranch,
    OutboxEvent,
    SensorDevice,
    SensorReading,
)
from . import texts
from .telegram import queue

OFFLINE_AFTER = timedelta(minutes=10)
LATE_AFTER = timedelta(minutes=30)
OUT_AFTER = timedelta(minutes=10)
SILENT_AFTER = timedelta(minutes=30)
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
OPS_LOCK = 7_202_685
FEATURE = "fridge_sensors"
CENT = Decimal("0.01")


def _c(value: Decimal) -> str:
    """8.00 → "8", 2.50 → "2.5" (a range in a message)."""
    return f"{Decimal(value).normalize():f}"


def _hm(at: datetime | None) -> str:
    return at.astimezone(clock.TIMEZONE).strftime("%H:%M") if at else "-"


def window(prefs: BranchPrefs | None, on: date) -> tuple[datetime, datetime] | None:
    """Today's opening and closing time (Phnom Penh), or None (closed / no hours set)."""
    hours = (prefs.opening_hours or {}).get(DAYS[on.weekday()]) if prefs else None
    if not hours:
        return None
    (oh, om), (ch, cm) = (map(int, hours[0].split(":")), map(int, hours[1].split(":")))
    return (datetime(on.year, on.month, on.day, oh, om, tzinfo=clock.TIMEZONE),
            datetime(on.year, on.month, on.day, ch, cm, tzinfo=clock.TIMEZONE))  # fmt: skip


async def _branch(session: AsyncSession, branch_id: UUID) -> str:
    b = await session.get(KnownBranch, branch_id)
    return f"{b.code} {b.name_en}" if b else "Branch"


async def _alert(session: AsyncSession, settings: Settings, key: str, kind: str, branch_id: UUID, text_: str) -> None:
    for target in (str(branch_id), "owner"):
        await queue(session, settings, key=f"{key}:{target}", target=target, kind=kind, text=text_, branch_id=branch_id)


# ------------------------------------------------------------------ heartbeat + opening


async def heartbeat(session: AsyncSession, settings: Settings, user: CurrentUser, branch_id: UUID, device_id: str) -> None:
    user.require_branch(branch_id)
    now = clock.now()
    await session.execute(insert(Heartbeat).values(branch_id=branch_id, device_id=device_id[:40], user_id=user.id,
                                                   last_seen=now).on_conflict_do_update(
        index_elements=["branch_id", "device_id"], set_={"last_seen": now, "user_id": user.id}))  # fmt: skip
    ops = await session.get(BranchOps, branch_id, with_for_update=True)
    if ops is not None and ops.offline_since is not None:
        since = ops.offline_since
        ops.offline_since = None
        await _alert(session, settings, f"till_back:{branch_id}:{since.isoformat()}", "ops", branch_id,
                     texts.till_back(await _branch(session, branch_id), _hm(since), _hm(now)))  # fmt: skip
    await session.commit()


async def on_invoice(session: AsyncSession, inv: dict[str, Any]) -> None:
    """invoice.created: first and last sale of the branch's day."""
    if not inv.get("completed_at") or inv.get("status") != "completed":
        return
    at = datetime.fromisoformat(inv["completed_at"])
    branch_id, day = UUID(inv["branch"]["id"]), at.astimezone(clock.TIMEZONE).date()
    stmt = insert(BranchDay).values(branch_id=branch_id, day=day, first_sale_at=at, last_sale_at=at, late_alerted=False)
    await session.execute(stmt.on_conflict_do_update(index_elements=["branch_id", "day"], set_={
        "first_sale_at": func.least(func.coalesce(BranchDay.first_sale_at, stmt.excluded.first_sale_at),
                                    stmt.excluded.first_sale_at),
        "last_sale_at": func.greatest(func.coalesce(BranchDay.last_sale_at, stmt.excluded.last_sale_at),
                                      stmt.excluded.last_sale_at)}))  # fmt: skip


async def check_branches(session: AsyncSession, settings: Settings, now: datetime) -> int:
    """The minute job's branch part: offline tills and late opening."""
    made = 0
    today = now.astimezone(clock.TIMEZONE).date()
    for prefs in (await session.execute(select(BranchPrefs))).scalars().all():
        w = window(prefs, today)
        b = await session.get(KnownBranch, prefs.branch_id)
        if w is None or b is None or not b.is_active:
            continue
        opens, closes = w
        if not opens <= now < closes:
            continue
        name = f"{b.code} {b.name_en}"
        last = (await session.execute(select(func.max(Heartbeat.last_seen)).where(
            Heartbeat.branch_id == b.id))).scalar_one()  # fmt: skip
        ops = await session.get(BranchOps, b.id, with_for_update=True)
        if ops is None:
            ops = BranchOps(branch_id=b.id)
            session.add(ops)
        if (now - opens >= OFFLINE_AFTER and ops.offline_since is None
                and (last is None or now - last >= OFFLINE_AFTER)):  # fmt: skip
            ops.offline_since = max(last, opens) if last else opens
            await _alert(session, settings, f"till_offline:{b.id}:{ops.offline_since.isoformat()}", "ops", b.id,
                         texts.till_offline(name, _hm(last) if last else None))  # fmt: skip
            made += 1
        if now - opens >= LATE_AFTER:
            day = await session.get(BranchDay, (b.id, today), with_for_update=True)
            if day is None:
                day = BranchDay(branch_id=b.id, day=today, late_alerted=False)
                session.add(day)
            if day.first_sale_at is None and not day.late_alerted:
                day.late_alerted = True
                await _alert(session, settings, f"late_opening:{b.id}:{today}", "ops", b.id,
                             texts.late_opening(name, _hm(opens), int(LATE_AFTER.total_seconds() // 60)))  # fmt: skip
                made += 1
    return made


# ------------------------------------------------------------------ fridge sensors


async def sensors_on(session: AsyncSession) -> bool:
    row = await session.get(FeatureCopy, FEATURE)
    return bool(row and row.enabled)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _check(user: CurrentUser, branch_id: UUID) -> None:
    user.require("notifications.manage")
    user.require_branch(branch_id)


def _audit(session: AsyncSession, user: CurrentUser, action: str, d: SensorDevice, after: dict[str, Any]) -> None:
    record_audit(session, OutboxEvent, service="notification", action=action, entity_type="sensor_device",
                 entity_id=d.id, actor=user, branch_id=d.branch_id, after=after)  # fmt: skip


async def list_devices(session: AsyncSession, user: CurrentUser) -> list[SensorDevice]:
    user.require("notifications.manage")
    rows = (await session.execute(select(SensorDevice).order_by(SensorDevice.created_at))).scalars().all()
    return [d for d in rows if user.can_access_branch(d.branch_id)]


async def create_device(session: AsyncSession, user: CurrentUser, data: dict[str, Any]) -> tuple[SensorDevice, str]:
    _check(user, data["branch_id"])
    if data["min_c"] >= data["max_c"]:
        raise AppError(ErrorCode.VALIDATION_ERROR, "The minimum must be below the maximum", status_code=422,
                       details={"field": "min_c", "reason": "min_above_max"})  # fmt: skip
    token = f"fs_{secrets.token_urlsafe(24)}"
    d = SensorDevice(branch_id=data["branch_id"], name=data["name"].strip(), min_c=Decimal(data["min_c"]).quantize(CENT),
                     max_c=Decimal(data["max_c"]).quantize(CENT),
                     token_hash=_hash(token), is_active=True, state="ok", out_alerted=False, silent_alerted=False,
                     created_by=user.id, created_at=clock.now())  # fmt: skip
    session.add(d)
    await session.flush()
    _audit(session, user, "sensor_device.created", d, {"name": d.name, "min_c": str(d.min_c), "max_c": str(d.max_c)})
    await session.commit()
    return d, token


async def update_device(session: AsyncSession, user: CurrentUser, device_id: UUID, data: dict[str, Any],
                        new_token: bool = False) -> tuple[SensorDevice, str | None]:  # fmt: skip
    d = await session.get(SensorDevice, device_id, with_for_update=True)
    if d is None or not user.can_access_branch(d.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Sensor not found", status_code=404)
    _check(user, d.branch_id)
    for k in ("name", "min_c", "max_c", "is_active"):
        if data.get(k) is not None:
            value = data[k].strip() if k == "name" else data[k]
            setattr(d, k, Decimal(value).quantize(CENT) if k in ("min_c", "max_c") else value)
    if d.min_c >= d.max_c:
        raise AppError(ErrorCode.VALIDATION_ERROR, "The minimum must be below the maximum", status_code=422,
                       details={"field": "min_c", "reason": "min_above_max"})  # fmt: skip
    token = None
    if new_token:  # the old token stops working at once
        token = f"fs_{secrets.token_urlsafe(24)}"
        d.token_hash = _hash(token)
    _audit(session, user, "sensor_device.updated", d, {"name": d.name, "min_c": str(d.min_c), "max_c": str(d.max_c),
                                                        "is_active": d.is_active, "new_token": new_token})  # fmt: skip
    await session.commit()
    return d, token


async def reading(session: AsyncSession, settings: Settings, token: str | None, temp_c: Decimal) -> SensorDevice:
    if not await sensors_on(session):
        raise AppError(ErrorCode.NOT_FOUND, "Fridge sensors are switched off", status_code=404)
    d = (await session.execute(select(SensorDevice).where(SensorDevice.token_hash == _hash(token or ""))
                               .with_for_update())).scalar_one_or_none() if token else None  # fmt: skip
    if d is None or not d.is_active:
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Unknown sensor token", status_code=401)
    now = clock.now()
    ok = d.min_c <= temp_c <= d.max_c
    session.add(SensorReading(device_id=d.id, at=now, temp_c=temp_c, in_range=ok))
    d.last_reading_at, d.last_temp_c = now, temp_c
    branch = await _branch(session, d.branch_id)
    if d.silent_alerted:
        d.silent_alerted = False
    if ok:
        if d.out_since is not None and d.out_alerted:
            await _alert(session, settings, f"fridge_back:{d.id}:{d.out_since.isoformat()}", "sensor", d.branch_id,
                         texts.fridge_back(branch, d.name, f"{temp_c:.1f}", _hm(d.out_since), _hm(now)))  # fmt: skip
        d.state, d.out_since, d.out_alerted = "ok", None, False
    else:
        if d.out_since is None:
            d.state, d.out_since = "out", now
        await _out_alert(session, settings, d, branch, now)
    await session.commit()
    return d


async def _out_alert(session: AsyncSession, settings: Settings, d: SensorDevice, branch: str, now: datetime) -> bool:
    if d.out_since is None or d.out_alerted or now - d.out_since <= OUT_AFTER:
        return False
    d.out_alerted = True
    minutes = int((now - d.out_since).total_seconds() // 60)
    await _alert(session, settings, f"fridge_out:{d.id}:{d.out_since.isoformat()}", "sensor", d.branch_id,
                 texts.fridge_out(branch, d.name, f"{d.last_temp_c:.1f}", minutes, _c(d.min_c), _c(d.max_c)))  # fmt: skip
    return True


async def check_sensors(session: AsyncSession, settings: Settings, now: datetime) -> int:
    if not await sensors_on(session):
        return 0
    made = 0
    for d in (await session.execute(select(SensorDevice).where(SensorDevice.is_active.is_(True))
                                    .with_for_update())).scalars().all():  # fmt: skip
        branch = await _branch(session, d.branch_id)
        made += await _out_alert(session, settings, d, branch, now)
        since = d.last_reading_at or d.created_at
        if since and now - since >= SILENT_AFTER and not d.silent_alerted:
            d.silent_alerted = True
            await _alert(session, settings, f"fridge_silent:{d.id}:{since.isoformat()}", "sensor", d.branch_id,
                         texts.fridge_silent(branch, d.name, _hm(d.last_reading_at) if d.last_reading_at else None))  # fmt: skip
            made += 1
    return made


async def fridge_day(session: AsyncSession, branch_id: UUID, day: date) -> list[dict[str, Any]]:
    """Yesterday's min / max per fridge of a branch (the 07:30 digest)."""
    start = datetime(day.year, day.month, day.day, tzinfo=clock.TIMEZONE)
    rows = (await session.execute(select(SensorDevice.name, func.min(SensorReading.temp_c), func.max(SensorReading.temp_c),
                                         func.count(), func.count().filter(SensorReading.in_range.is_(False)))
        .join(SensorReading, SensorReading.device_id == SensorDevice.id)
        .where(SensorDevice.branch_id == branch_id, SensorReading.at >= start, SensorReading.at < start + timedelta(days=1))
        .group_by(SensorDevice.name).order_by(SensorDevice.name))).all()  # fmt: skip
    return [{"name": n, "min": f"{lo:.1f}", "max": f"{hi:.1f}", "n": int(c), "out": int(bad)} for n, lo, hi, c, bad in rows]


async def fridge_branches(session: AsyncSession, day: date) -> set[UUID]:
    start = datetime(day.year, day.month, day.day, tzinfo=clock.TIMEZONE)
    rows = await session.execute(select(SensorDevice.branch_id).join(SensorReading, SensorReading.device_id == SensorDevice.id)
                                 .where(SensorReading.at >= start, SensorReading.at < start + timedelta(days=1)).distinct())  # fmt: skip
    return set(rows.scalars())


async def minute_job(session: AsyncSession, settings: Settings, now: datetime | None = None) -> int | None:
    if not (await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": OPS_LOCK})).scalar_one():
        return None
    now = now or clock.now()
    made = await check_branches(session, settings, now) + await check_sensors(session, settings, now)
    await session.commit()
    return made
